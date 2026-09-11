#!/usr/bin/env python3
"""
Solar Monitor - Multi-Serial Ingestion Engine
Manages multiple RS-232/RS-485/CAN adapters simultaneously.
Each adapter connects to a different inverter or BMS.
Devices retain identity across reconnects; stale/invalid data is flagged.

Features:
- Proper Modbus transactions with buffering and timeouts
- Exactly one worker per port (no duplicate readers)
- Automatic reconnection after USB disconnection
- Simulator integration through same polling path
"""
import serial
import serial.tools.list_ports
import asyncio
import time
import json
import os
import hashlib
import logging
import struct
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from modbus_handler import ModbusRTU, get_profile, InverterProfile, InverterSimulator

logger = logging.getLogger(__name__)


class ProtocolType(Enum):
    MODBUS_RTU = "modbus_rtu"
    MODBUS_ASCII = "modbus_ascii"
    CUSTOM = "custom"


class DeviceHealth(Enum):
    HEALTHY = "healthy"
    STALE = "stale"
    ERROR = "error"
    DISCONNECTED = "disconnected"


@dataclass
class SerialPort:
    """Represents a physical serial port with persistent identity."""
    device: str
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    timeout: float = 1.0
    protocol: ProtocolType = ProtocolType.MODBUS_RTU
    inverter_type: str = "generic"
    name: str = ""
    is_open: bool = False
    last_read: float = 0
    last_valid_read: float = 0
    error_count: int = 0
    total_reads: int = 0
    serial_conn: Optional[serial.Serial] = None
    device_fingerprint: str = ""
    health: DeviceHealth = DeviceHealth.DISCONNECTED
    max_stale_seconds: float = 30.0

    def __post_init__(self):
        if not self.name:
            self.name = os.path.basename(self.device)

    def fingerprint(self) -> str:
        """Generate persistent device fingerprint from hardware info."""
        try:
            for port in serial.tools.list_ports.comports():
                if port.device == self.device:
                    hw_str = f"{port.vid or ''}:{port.pid or ''}:{port.serial_number or ''}:{port.manufacturer or ''}"
                    return hashlib.sha256(hw_str.encode()).hexdigest()[:16]
        except Exception:
            pass
        return hashlib.sha256(self.device.encode()).hexdigest()[:16]


@dataclass
class InverterReading:
    """Single reading from an inverter with health metadata."""
    timestamp: float
    port_name: str
    device_id: str
    device_type: str
    metrics: Dict[str, float]
    raw_data: bytes = b""
    valid: bool = True
    error: str = ""
    health: DeviceHealth = DeviceHealth.HEALTHY


class ModbusTransaction:
    """
    Manages a single Modbus transaction with proper frame assembly,
    response timeouts, and validation.
    """
    
    def __init__(self, slave_id: int, function_code: int, start_addr: int, count: int):
        self.slave_id = slave_id
        self.function_code = function_code
        self.start_addr = start_addr
        self.count = count
        self.request_time = 0.0
        self.response_buffer = b""
        self.expected_length = 0
        
        # Calculate expected response length
        if function_code in (0x03, 0x04):
            self.expected_length = 5 + (count * 2)  # slave + func + count + data + crc
        elif function_code == 0x06:
            self.expected_length = 8
    
    def build_request(self) -> bytes:
        """Build the Modbus request frame."""
        if self.function_code == 0x03:
            return ModbusRTU.build_read_holding_registers(
                self.slave_id, self.start_addr, self.count
            )
        elif self.function_code == 0x04:
            return ModbusRTU.build_read_input_registers(
                self.slave_id, self.start_addr, self.count
            )
        elif self.function_code == 0x06:
            return ModbusRTU.build_write_single_register(
                self.slave_id, self.start_addr, self.count
            )
        return b""
    
    def add_response_data(self, data: bytes) -> Optional[Dict]:
        """
        Add received data to buffer and attempt to parse complete response.
        Returns parsed response if complete, None if more data needed.
        """
        self.response_buffer += data
        
        # Check if we have enough data
        if len(self.response_buffer) < 5:
            return None
        
        # Check for complete response based on function code
        func_code = self.response_buffer[1]
        
        if func_code in (0x03, 0x04):
            # Read response: byte_count at position[2], total = 5 + byte_count
            byte_count = self.response_buffer[2]
            expected_len = 5 + byte_count
            if len(self.response_buffer) < expected_len:
                return None
            # Extract complete frame
            frame = self.response_buffer[:expected_len]
            self.response_buffer = self.response_buffer[expected_len:]
            return ModbusRTU.parse_response(frame)
        
        elif func_code == 0x06:
            # Write response: always 8 bytes
            if len(self.response_buffer) < 8:
                return None
            frame = self.response_buffer[:8]
            self.response_buffer = self.response_buffer[8:]
            return ModbusRTU.parse_response(frame)
        
        elif func_code & 0x80:
            # Exception: 5 bytes
            if len(self.response_buffer) < 5:
                return None
            frame = self.response_buffer[:5]
            self.response_buffer = self.response_buffer[5:]
            return ModbusRTU.parse_response(frame)
        
        return None
    
    def is_expired(self, timeout: float = 2.0) -> bool:
        """Check if transaction has expired (no response received)."""
        return (time.time() - self.request_time) > timeout and self.request_time > 0


class SerialPortManager:
    """Manages multiple serial ports and their data streams."""

    def __init__(self, data_dir: str = "database"):
        self.ports: Dict[str, SerialPort] = {}
        self.readings: List[InverterReading] = []
        self.max_history = 100000
        self._callbacks: List[Callable] = []
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}  # One task per port
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._simulators: Dict[str, InverterSimulator] = {}
        self._load_state()

    def _load_state(self):
        """Load persisted port configurations."""
        state_file = self._data_dir / "ports.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                for p in data.get("ports", []):
                    port = SerialPort(
                        device=p["device"],
                        baudrate=p.get("baudrate", 9600),
                        parity=p.get("parity", "N"),
                        stopbits=p.get("stopbits", 1),
                        protocol=ProtocolType(p.get("protocol", "modbus_rtu")),
                        inverter_type=p.get("inverter_type", "generic"),
                        name=p.get("name", ""),
                        device_fingerprint=p.get("device_fingerprint", ""),
                        max_stale_seconds=p.get("max_stale_seconds", 30.0),
                    )
                    self.ports[port.device] = port
                logger.info(f"Loaded {len(self.ports)} port configs")
            except Exception as e:
                logger.error(f"Failed to load state: {e}")

    def _save_state(self):
        """Persist port configurations."""
        state_file = self._data_dir / "ports.json"
        data = {
            "ports": [
                {
                    "device": p.device,
                    "name": p.name,
                    "baudrate": p.baudrate,
                    "parity": p.parity,
                    "stopbits": p.stopbits,
                    "protocol": p.protocol.value,
                    "inverter_type": p.inverter_type,
                    "device_fingerprint": p.device_fingerprint,
                    "max_stale_seconds": p.max_stale_seconds,
                }
                for p in self.ports.values()
            ]
        }
        state_file.write_text(json.dumps(data, indent=2))

    def list_available_ports(self) -> List[Dict]:
        """List all available serial ports on the system."""
        ports = []
        for port in serial.tools.list_ports.comports():
            ports.append({
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid,
                "vid": port.vid,
                "pid": port.pid,
                "serial_number": port.serial_number,
                "manufacturer": port.manufacturer,
                "product": port.product,
                "is_rs485": any(x in str(port.description).upper() for x in ["RS485", "485", "CH340", "UART", "FTDI", "PL2303", "CP210"]),
            })
        return ports

    def add_port(self, port: SerialPort) -> bool:
        """Add a serial port to the manager."""
        if port.device in self.ports:
            return False
        port.device_fingerprint = port.fingerprint()
        self.ports[port.device] = port
        self._save_state()
        
        # Create simulator for sim:// devices
        if port.device.startswith("sim://"):
            profile = get_profile(port.inverter_type)
            self._simulators[port.device] = InverterSimulator(profile)
            port.is_open = True
            port.health = DeviceHealth.HEALTHY
        
        return True

    def remove_port(self, device: str):
        """Remove a serial port."""
        if device in self.ports:
            port = self.ports[device]
            if port.is_open:
                self.close_port(device)
            del self.ports[device]
            if device in self._simulators:
                del self._simulators[device]
            self._save_state()

    def open_port(self, device: str) -> bool:
        """Open a serial port."""
        if device not in self.ports:
            return False
        port = self.ports[device]
        
        # Simulator ports are always "open"
        if device.startswith("sim://"):
            port.is_open = True
            port.health = DeviceHealth.HEALTHY
            return True
        
        try:
            port.serial_conn = serial.Serial(
                port=port.device,
                baudrate=port.baudrate,
                bytesize=port.bytesize,
                parity=port.parity,
                stopbits=port.stopbits,
                timeout=port.timeout,
            )
            port.is_open = True
            port.error_count = 0
            # Don't mark as HEALTHY until we receive valid data
            port.health = DeviceHealth.DISCONNECTED
            return True
        except Exception as e:
            port.error_count += 1
            port.health = DeviceHealth.ERROR
            logger.error(f"Failed to open {device}: {e}")
            return False

    def close_port(self, device: str):
        """Close a serial port."""
        if device in self.ports:
            port = self.ports[device]
            if port.serial_conn and port.serial_conn.is_open:
                port.serial_conn.close()
            port.is_open = False
            port.health = DeviceHealth.DISCONNECTED
            # Cancel any running task for this device
            if device in self._tasks:
                self._tasks[device].cancel()
                del self._tasks[device]

    def open_all(self) -> Dict[str, bool]:
        """Open all registered ports."""
        results = {}
        for device in self.ports:
            results[device] = self.open_port(device)
        return results

    def close_all(self):
        """Close all open ports."""
        for device in list(self.ports.keys()):
            self.close_port(device)

    async def read_port(self, device: str, callback: Optional[Callable] = None):
        """
        Continuously read from a single port with health monitoring.
        Sends Modbus requests, assembles responses with proper buffering,
        validates CRC, decodes registers, and publishes readings.
        
        Handles:
        - Partial response buffering
        - Response timeouts
        - Slave ID and function code verification
        - Automatic reconnection on disconnection
        """
        port = self.ports[device]
        profile = get_profile(port.inverter_type)
        
        # Determine register range
        if profile.registers:
            start_addr = min(r.address for r in profile.registers)
            count = max(r.address for r in profile.registers) - start_addr + 1
        else:
            start_addr = 0
            count = 10
        
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        while self._running and port.is_open:
            try:
                # Handle simulator
                if device.startswith("sim://") and device in self._simulators:
                    simulator = self._simulators[device]
                    simulator.update()
                    
                    # Build and handle request through simulator
                    request = ModbusRTU.build_read_holding_registers(
                        profile.slave_id, start_addr, count
                    )
                    response = simulator.handle_request(request)
                    
                    if response:
                        parsed = ModbusRTU.parse_response(response)
                        if parsed and not parsed.get("error"):
                            register_map = profile.get_register_map()
                            metrics = ModbusRTU.decode_registers(
                                parsed.get("registers", []),
                                register_map,
                                start_addr
                            )
                            
                            # Validate decoded values
                            valid = True
                            error_msg = ""
                            for key, value in metrics.items():
                                if isinstance(value, float) and (value != value or value == float('inf') or value == float('-inf')):
                                    valid = False
                                    error_msg = f"Invalid value for {key}"
                                    break
                            
                            if valid and metrics:
                                port.last_valid_read = time.time()
                                port.health = DeviceHealth.HEALTHY
                                port.last_read = time.time()
                                port.total_reads += 1
                            
                            reading = InverterReading(
                                timestamp=time.time(),
                                port_name=port.name,
                                device_id=port.device_fingerprint,
                                device_type=port.inverter_type,
                                metrics=metrics,
                                raw_data=response,
                                valid=valid,
                                error=error_msg,
                                health=port.health,
                            )
                            self._add_reading(reading)
                            if callback:
                                await callback(reading)
                    
                    await asyncio.sleep(1)  # Simulator update rate
                    continue
                
                # Real hardware path
                if not port.serial_conn or not port.serial_conn.is_open:
                    # Attempt reconnection
                    if not self.open_port(device):
                        await asyncio.sleep(5)
                        continue
                
                # Create Modbus transaction
                transaction = ModbusTransaction(
                    slave_id=profile.slave_id,
                    function_code=0x03,
                    start_addr=start_addr,
                    count=count
                )
                
                # Send request
                request = transaction.build_request()
                port.serial_conn.write(request)
                transaction.request_time = time.time()
                
                # Wait for response with timeout
                response_received = False
                while self._running and port.is_open:
                    # Check for timeout
                    if transaction.is_expired(timeout=2.0):
                        break
                    
                    # Read available data
                    if port.serial_conn.in_waiting > 0:
                        data = port.serial_conn.read(port.serial_conn.in_waiting)
                        result = transaction.add_response_data(data)
                        
                        if result is not None:
                            # Validate response
                            if result.get("slave_id") != profile.slave_id:
                                # Wrong slave - discard
                                break
                            
                            if result.get("function_code") != 0x03:
                                # Unexpected function code - discard
                                break
                            
                            if result.get("error"):
                                # Modbus exception
                                port.error_count += 1
                                consecutive_errors += 1
                                reading = InverterReading(
                                    timestamp=time.time(),
                                    port_name=port.name,
                                    device_id=port.device_fingerprint,
                                    device_type=port.inverter_type,
                                    metrics={},
                                    raw_data=data,
                                    valid=False,
                                    error=f"Modbus exception: {result.get('exception_code')}",
                                    health=DeviceHealth.ERROR,
                                )
                                self._add_reading(reading)
                                if callback:
                                    await callback(reading)
                                response_received = True
                                break
                            
                            # Decode registers
                            register_map = profile.get_register_map()
                            metrics = ModbusRTU.decode_registers(
                                result.get("registers", []),
                                register_map,
                                start_addr
                            )
                            
                            # Validate decoded values
                            valid = True
                            error_msg = ""
                            for key, value in metrics.items():
                                if isinstance(value, float) and (value != value or value == float('inf') or value == float('-inf')):
                                    valid = False
                                    error_msg = f"Invalid value for {key}"
                                    break
                            
                            if valid and metrics:
                                port.last_valid_read = time.time()
                                port.health = DeviceHealth.HEALTHY
                                consecutive_errors = 0
                            
                            port.last_read = time.time()
                            port.total_reads += 1
                            
                            reading = InverterReading(
                                timestamp=time.time(),
                                port_name=port.name,
                                device_id=port.device_fingerprint,
                                device_type=port.inverter_type,
                                metrics=metrics,
                                raw_data=data,
                                valid=valid,
                                error=error_msg,
                                health=port.health,
                            )
                            self._add_reading(reading)
                            if callback:
                                await callback(reading)
                            response_received = True
                            break
                    
                    await asyncio.sleep(0.01)
                
                if not response_received:
                    # Timeout or error
                    port.error_count += 1
                    consecutive_errors += 1
                    
                    if consecutive_errors >= max_consecutive_errors:
                        port.health = DeviceHealth.ERROR
                        # Try to reconnect
                        self.close_port(device)
                        await asyncio.sleep(5)
                        continue
                
                # Check staleness
                if port.last_valid_read > 0 and (time.time() - port.last_valid_read) > port.max_stale_seconds:
                    port.health = DeviceHealth.STALE
                
                # Polling interval
                await asyncio.sleep(0.5)
                    
            except Exception as e:
                port.error_count += 1
                consecutive_errors += 1
                port.health = DeviceHealth.ERROR
                reading = InverterReading(
                    timestamp=time.time(),
                    port_name=port.name,
                    device_id=port.device_fingerprint,
                    device_type=port.inverter_type,
                    metrics={},
                    valid=False,
                    error=str(e),
                    health=DeviceHealth.ERROR,
                )
                self._add_reading(reading)
                if callback:
                    await callback(reading)
                
                # Attempt reconnection
                self.close_port(device)
                await asyncio.sleep(5)

    def _add_reading(self, reading: InverterReading):
        """Add a reading to history."""
        self.readings.append(reading)
        if len(self.readings) > self.max_history:
            self.readings = self.readings[-self.max_history:]

    async def start(self, callback: Optional[Callable] = None):
        """
        Start reading from all ports.
        Opens all registered ports first, then creates exactly one reader task per port.
        """
        self._running = True
        
        # Open all ports first
        for device in self.ports:
            self.open_port(device)
        
        # Create exactly one reader task per open port
        for device in self.ports:
            if self.ports[device].is_open and device not in self._tasks:
                task = asyncio.create_task(self.read_port(device, callback))
                self._tasks[device] = task
        
        # Wait for all tasks
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self):
        """Stop all reading tasks."""
        self._running = False
        for device, task in self._tasks.items():
            task.cancel()
        self._tasks.clear()
        self.close_all()

    def get_port_status(self) -> List[Dict]:
        """Get status of all ports."""
        return [
            {
                "device": p.device,
                "name": p.name,
                "baudrate": p.baudrate,
                "parity": p.parity,
                "stopbits": p.stopbits,
                "protocol": p.protocol.value,
                "inverter_type": p.inverter_type,
                "is_open": p.is_open,
                "last_read": p.last_read,
                "last_valid_read": p.last_valid_read,
                "error_count": p.error_count,
                "total_reads": p.total_reads,
                "device_fingerprint": p.device_fingerprint,
                "health": p.health.value,
            }
            for p in self.ports.values()
        ]

    def get_latest_readings(self, count: int = 100) -> List[Dict]:
        """Get latest readings."""
        readings = self.readings[-count:]
        return [
            {
                "timestamp": r.timestamp,
                "port_name": r.port_name,
                "device_id": r.device_id,
                "device_type": r.device_type,
                "metrics": r.metrics,
                "valid": r.valid,
                "error": r.error,
                "health": r.health.value,
            }
            for r in readings
        ]

    def send_data(self, device: str, data: bytes) -> bool:
        """Send data to a specific port."""
        if device not in self.ports:
            return False
        port = self.ports[device]
        if not port.is_open or not port.serial_conn:
            return False
        try:
            port.serial_conn.write(data)
            return True
        except Exception:
            return False
