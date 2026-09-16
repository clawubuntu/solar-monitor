#!/usr/bin/env python3
"""
Solar Monitor - Multi-Serial Ingestion Engine
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
from bms_handler import (
    build_query as jk_build_query,
    parse_frame as jk_parse_frame,
    parse_runtime_data as jk_parse_runtime_data,
    parse_config_data as jk_parse_config_data,
    parse_device_info as jk_parse_device_info,
    parse_fault_info as jk_parse_fault_info,
    build_modbus_trigger as jk_build_modbus_trigger,
    FRAME_RUNTIME_DATA,
    FRAME_CONFIG_READ,
    FRAME_DEVICE_INFO,
    FRAME_FAULT_INFO,
)

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
    timestamp: float
    port_name: str
    device_id: str
    device_type: str
    metrics: Dict[str, float]
    raw_data: bytes = b""
    valid: bool = True
    error: str = ""
    health: DeviceHealth = DeviceHealth.HEALTHY


class SerialPortManager:
    def __init__(self, data_dir: Optional[str] = None):
        self.ports: Dict[str, SerialPort] = {}
        self.readings: List[InverterReading] = []
        self.max_history = 100000
        self._callbacks: List[Callable] = []
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}
        
        # Use absolute path based on project root
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path(__file__).resolve().parent.parent / "database"
        
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._simulators: Dict[str, InverterSimulator] = {}
        self._load_state()

    def _load_state(self):
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

    def _add_reading(self, reading: InverterReading):
        """Add a reading to history."""
        self.readings.append(reading)
        if len(self.readings) > self.max_history:
            self.readings = self.readings[-self.max_history:]

    def list_available_ports(self) -> List[Dict]:
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
        if port.device in self.ports:
            return False
        port.device_fingerprint = port.fingerprint()
        self.ports[port.device] = port
        self._save_state()
        if port.device.startswith("sim://"):
            profile = get_profile(port.inverter_type)
            self._simulators[port.device] = InverterSimulator(profile)
            port.is_open = True
            port.health = DeviceHealth.HEALTHY
        return True

    def remove_port(self, device: str):
        if device in self.ports:
            port = self.ports[device]
            if port.is_open:
                self.close_port(device)
            del self.ports[device]
            if device in self._simulators:
                del self._simulators[device]
            self._save_state()

    def open_port(self, device: str) -> bool:
        if device not in self.ports:
            return False
        port = self.ports[device]
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
            port.health = DeviceHealth.DISCONNECTED
            return True
        except Exception as e:
            port.error_count += 1
            port.health = DeviceHealth.ERROR
            logger.error(f"Failed to open {device}: {e}")
            return False

    def close_port(self, device: str):
        if device in self.ports:
            port = self.ports[device]
            if port.serial_conn and port.serial_conn.is_open:
                port.serial_conn.close()
            port.is_open = False
            port.health = DeviceHealth.DISCONNECTED
            if device in self._tasks:
                self._tasks[device].cancel()
                del self._tasks[device]

    async def read_port(self, device: str, callback: Optional[Callable] = None):
        port = self.ports[device]
        
        if port.inverter_type == "jk_bms":
            await self._read_jk_bms(device, callback)
            return
        
        # Standard Modbus path
        profile = get_profile(port.inverter_type)
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        while self._running and port.is_open:
            try:
                if not port.serial_conn or not port.serial_conn.is_open:
                    if not self.open_port(device):
                        await asyncio.sleep(5)
                        continue
                
                if device.startswith("sim://") and device in self._simulators:
                    simulator = self._simulators[device]
                    simulator.update()
                    await asyncio.sleep(1)
                    continue
                
                # Standard modbus read would go here
                await asyncio.sleep(0.5)
                
            except Exception as e:
                port.error_count += 1
                consecutive_errors += 1
                logger.error(f"Error reading {device}: {e}")
                await asyncio.sleep(5)

    async def _read_jk_bms(self, device: str, callback: Optional[Callable] = None):
        """Read from JK-BMS device(s) using 300-byte 5AA5 frames.
        
        For parallel battery setups, the master BMS broadcasts its own data,
        then queries all slave devices. We collect all frames after a trigger
        and combine them into a single reading with 32 cells.
        """
        port = self.ports[device]
        counter = 0
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        poll_sequence = [
            FRAME_RUNTIME_DATA,
            FRAME_CONFIG_READ,
            FRAME_DEVICE_INFO,
            FRAME_FAULT_INFO,
        ]
        poll_index = 0
        
        while self._running and port.is_open:
            try:
                if not port.serial_conn or not port.serial_conn.is_open:
                    if not self.open_port(device):
                        await asyncio.sleep(5)
                        continue
                
                frame_code = poll_sequence[poll_index % len(poll_sequence)]
                poll_index += 1
                
                # Build and send trigger to master (addr 0x00)
                # This causes master to broadcast and query slaves
                trigger = jk_build_modbus_trigger()
                port.serial_conn.write(trigger)
                
                # Wait briefly for master to process
                await asyncio.sleep(0.05)
                
                # Send 5AA5 query to trigger slave responses
                query = jk_build_query(frame_code, counter)
                port.serial_conn.write(query)
                
                # Wait for ALL frames (master + slaves) over 2 seconds
                all_frames = []  # List of (raw_bytes, timestamp)
                deadline = time.time() + 2.0
                current_frame = b""
                
                while self._running and port.is_open and time.time() < deadline:
                    if port.serial_conn.in_waiting > 0:
                        current_frame += port.serial_conn.read(port.serial_conn.in_waiting)
                        
                        # Check for complete 300-byte frames
                        while len(current_frame) >= 300:
                            # Find frame start (55 AA EB 90)
                            idx = current_frame.find(b'\x55\xAA\xEB\x90')
                            if idx == -1:
                                current_frame = b""
                                break
                            if idx > 0:
                                current_frame = current_frame[idx:]
                            if len(current_frame) < 300:
                                break
                            
                            frame = current_frame[:300]
                            current_frame = current_frame[300:]
                            
                            parsed = jk_parse_frame(frame)
                            if parsed:
                                all_frames.append((frame, time.time()))
                    
                    await asyncio.sleep(0.005)
                
                if not all_frames:
                    port.error_count += 1
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        port.health = DeviceHealth.ERROR
                    await asyncio.sleep(0.1)
                    continue
                
                # Parse frames and combine cells from master + slaves
                metrics = {}
                all_cells = []
                avg_cell_v = 0
                volt_delta = 0
                total_current = 0
                total_power = 0
                soc_values = []
                temp1_values = []
                temp2_values = []
                valid_frame_count = 0
                
                for frame, ts in all_frames:
                    parsed = jk_parse_frame(frame)
                    if not parsed:
                        continue
                    
                    data = parsed["data"]
                    
                    if parsed["frame_code"] == FRAME_RUNTIME_DATA:
                        runtime = jk_parse_runtime_data(data)
                        cells = runtime.get("cell_voltages", [])
                        valid_cells = [c for c in cells if c > 0.1]
                        
                        if valid_cells:
                            all_cells.extend(valid_cells)
                            avg_cell_v = runtime.get("avg_cell_v", avg_cell_v)
                            volt_delta = max(volt_delta, runtime.get("volt_delta", 0))
                            total_current += runtime.get("current", 0)
                            total_power += runtime.get("power", 0)
                            soc_values.append(runtime.get("soc", 0))
                            temp1_values.append(runtime.get("temp1", 0))
                            temp2_values.append(runtime.get("temp2", 0))
                            valid_frame_count += 1
                
                if not all_cells:
                    port.error_count += 1
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        port.health = DeviceHealth.ERROR
                    await asyncio.sleep(0.1)
                    continue
                
                # Build combined metrics for all 32 cells
                metrics = {
                    "voltage": round(sum(all_cells), 2),
                    "current": round(total_current, 3),
                    "power": round(sum(all_cells) * total_current, 2),
                    "soc": round(sum(soc_values) / len(soc_values)) if soc_values else 0,
                    "temp1": round(max(temp1_values) if temp1_values else 0, 1),
                    "temp2": round(max(temp2_values) if temp2_values else 0, 1),
                    "avg_cell_v": round(avg_cell_v, 3) if avg_cell_v > 0 else round(sum(all_cells) / len(all_cells), 3),
                    "volt_delta": round((max(all_cells) - min(all_cells)) * 1000, 1) if all_cells else 0,
                    "cell_count": len(all_cells),
                    "bank_count": valid_frame_count,
                }
                
                for i, v in enumerate(all_cells):
                    metrics[f"cell_{i+1:02d}_v"] = round(v, 3)
                
                # Validate
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
                    raw_data=all_frames[0][0] if all_frames else b"",
                    valid=valid,
                    error=error_msg,
                    health=port.health,
                )
                self._add_reading(reading)
                if callback:
                    await callback(reading)
                
                counter = (counter + 1) % 256
                await asyncio.sleep(0.02)
                    
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
                self.close_port(device)
                await asyncio.sleep(5)

    async def start(self, callback: Optional[Callable] = None):
        self._running = True
        for device in self.ports:
            self.open_port(device)
        for device in self.ports:
            if self.ports[device].is_open and device not in self._tasks:
                task = asyncio.create_task(self.read_port(device, callback))
                self._tasks[device] = task
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def stop(self):
        self._running = False
        for device, task in self._tasks.items():
            task.cancel()
        self._tasks.clear()
        self.close_all()

    def close_all(self):
        for device in list(self.ports.keys()):
            self.close_port(device)

    def open_all(self) -> Dict[str, bool]:
        return {device: self.open_port(device) for device in self.ports}

    def get_port_status(self) -> List[Dict]:
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
