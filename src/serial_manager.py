#!/usr/bin/env python3
"""
Solar Monitor - Multi-Serial Ingestion Engine
Manages multiple RS-232/RS-485/CAN adapters simultaneously.
Each adapter connects to a different inverter or BMS.
Devices retain identity across reconnects; stale/invalid data is flagged.
"""
import serial
import serial.tools.list_ports
import asyncio
import time
import json
import os
import hashlib
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

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
    device_fingerprint: str = ""  # Persistent identity
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
    device_type: str  # "inverter", "bms", "meter"
    metrics: Dict[str, float]
    raw_data: bytes = b""
    valid: bool = True
    error: str = ""
    health: DeviceHealth = DeviceHealth.HEALTHY


class SerialPortManager:
    """Manages multiple serial ports and their data streams."""

    def __init__(self, data_dir: str = "database"):
        self.ports: Dict[str, SerialPort] = {}
        self.readings: List[InverterReading] = []
        self.max_history = 100000
        self._callbacks: List[Callable] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
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
        return True

    def remove_port(self, device: str):
        """Remove a serial port."""
        if device in self.ports:
            port = self.ports[device]
            if port.is_open:
                self.close_port(device)
            del self.ports[device]
            self._save_state()

    def open_port(self, device: str) -> bool:
        """Open a serial port."""
        if device not in self.ports:
            return False
        port = self.ports[device]
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
            port.health = DeviceHealth.HEALTHY
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
        """Continuously read from a single port with health monitoring."""
        port = self.ports[device]
        while self._running and port.is_open:
            try:
                if port.serial_conn and port.serial_conn.in_waiting > 0:
                    data = port.serial_conn.read(port.serial_conn.in_waiting)
                    port.last_read = time.time()
                    port.total_reads += 1

                    reading = InverterReading(
                        timestamp=time.time(),
                        port_name=port.name,
                        device_id=port.device_fingerprint,
                        device_type=port.inverter_type,
                        metrics={},
                        raw_data=data,
                        valid=True,
                        health=DeviceHealth.HEALTHY,
                    )
                    self._add_reading(reading)
                    if callback:
                        await callback(reading)
                else:
                    # Check staleness
                    if port.last_valid_read > 0 and (time.time() - port.last_valid_read) > port.max_stale_seconds:
                        port.health = DeviceHealth.STALE
                    await asyncio.sleep(0.01)
            except Exception as e:
                port.error_count += 1
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
                await asyncio.sleep(1)

    def _add_reading(self, reading: InverterReading):
        """Add a reading to history."""
        self.readings.append(reading)
        if len(self.readings) > self.max_history:
            self.readings = self.readings[-self.max_history:]

    async def start(self, callback: Optional[Callable] = None):
        """Start reading from all open ports."""
        self._running = True
        self._tasks = []
        for device in self.ports:
            if self.ports[device].is_open:
                task = asyncio.create_task(self.read_port(device, callback))
                self._tasks.append(task)
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self):
        """Stop all reading tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self.close_all()

    def get_port_status(self) -> List[Dict]:
        """Get status of all ports."""
        return [
            {
                "device": p.device,
                "name": p.name,
                "baudrate": p.baudrate,
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
