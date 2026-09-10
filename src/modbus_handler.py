#!/usr/bin/env python3
"""
Modbus Protocol Handler
Supports Modbus RTU and ASCII protocols
Handles register mapping for different inverter types
Includes hardware simulator for testing without physical devices
"""
import struct
import time
import random
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

class ModbusFunctionCode(Enum):
    READ_HOLDING_REGISTERS = 0x03
    READ_INPUT_REGISTERS = 0x04
    WRITE_SINGLE_REGISTER = 0x06
    WRITE_MULTIPLE_REGISTERS = 0x10

@dataclass
class ModbusRegister:
    """Single Modbus register definition."""
    address: int
    name: str
    unit: str
    scale: float = 1.0
    offset: float = 0.0
    size: int = 1
    signed: bool = False
    writable: bool = False
    category: str = "general"
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    description: str = ""

@dataclass
class InverterProfile:
    """Profile for a specific inverter model."""
    name: str
    manufacturer: str
    protocol: str
    baudrate: int
    slave_id: int
    registers: List[ModbusRegister]
    
    def get_register_map(self) -> Dict[int, ModbusRegister]:
        """Get register map indexed by address."""
        return {r.address: r for r in self.registers}
    
    def get_registers_by_category(self, category: str) -> List[ModbusRegister]:
        """Get registers filtered by category."""
        return [r for r in self.registers if r.category == category]

class ModbusRTU:
    """Modbus RTU protocol implementation."""
    
    @staticmethod
    def calculate_crc(data: bytes) -> bytes:
        """Calculate Modbus CRC16."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return struct.pack("<H", crc)
    
    @staticmethod
    def build_read_holding_registers(slave_id: int, start_addr: int, count: int) -> bytes:
        """Build Modbus RTU read holding registers request."""
        pdu = struct.pack(">BHH", 0x03, start_addr, count)
        frame = struct.pack("B", slave_id) + pdu
        crc = ModbusRTU.calculate_crc(frame)
        return frame + crc
    
    @staticmethod
    def build_read_input_registers(slave_id: int, start_addr: int, count: int) -> bytes:
        """Build Modbus RTU read input registers request."""
        pdu = struct.pack(">BHH", 0x04, start_addr, count)
        frame = struct.pack("B", slave_id) + pdu
        crc = ModbusRTU.calculate_crc(frame)
        return frame + crc
    
    @staticmethod
    def build_write_single_register(slave_id: int, addr: int, value: int) -> bytes:
        """Build Modbus RTU write single register request."""
        # FIX: was ">BHHH" (expects 4 values), now ">BHH" (3 values: func_code, addr, value)
        pdu = struct.pack(">BHH", 0x06, addr, value)
        frame = struct.pack("B", slave_id) + pdu
        crc = ModbusRTU.calculate_crc(frame)
        return frame + crc
    
    @staticmethod
    def parse_response(frame: bytes) -> Optional[Dict]:
        """Parse Modbus RTU response with strict validation."""
        if len(frame) < 5:
            return None
        
        # Verify CRC
        data = frame[:-2]
        received_crc = struct.unpack("<H", frame[-2:])[0]
        calculated_crc = struct.unpack("<H", ModbusRTU.calculate_crc(data))[0]
        
        if received_crc != calculated_crc:
            return None
        
        slave_id = frame[0]
        function_code = frame[1]
        
        # Check for exception
        if function_code & 0x80:
            exception_code = frame[2]
            return {
                "slave_id": slave_id,
                "error": True,
                "exception_code": exception_code
            }
        
        # Parse holding/input registers response
        if function_code in (0x03, 0x04):
            byte_count = frame[2]
            # Validate: frame size must match byte_count
            expected_len = 3 + byte_count + 2  # slave + func + count + data + crc
            if len(frame) != expected_len:
                return None
            # byte_count must be even (registers are 2 bytes each)
            if byte_count % 2 != 0:
                return None
            registers = []
            for i in range(byte_count // 2):
                value = struct.unpack(">H", frame[3 + i*2:5 + i*2])[0]
                registers.append(value)
            return {
                "slave_id": slave_id,
                "function_code": function_code,
                "registers": registers,
                "error": False
            }
        
        # Parse write response
        if function_code == 0x06:
            # Write response is 8 bytes: slave(1) + func(1) + addr(2) + value(2) + crc(2)
            if len(frame) != 8:
                return None
            addr = struct.unpack(">H", frame[2:4])[0]
            value = struct.unpack(">H", frame[4:6])[0]
            return {
                "slave_id": slave_id,
                "function_code": function_code,
                "address": addr,
                "value": value,
                "error": False
            }
        
        return None
    
    @staticmethod
    def decode_registers(registers: List[int], register_map: Dict[int, ModbusRegister], 
                        start_addr: int) -> Dict[str, float]:
        """Decode raw register values using register map."""
        result = {}
        i = 0
        while i < len(registers):
            addr = start_addr + i
            if addr in register_map:
                reg = register_map[addr]
                # Handle 32-bit values (2 registers)
                if reg.size == 2 and i + 1 < len(registers):
                    combined = (registers[i] << 16) | registers[i + 1]
                    if reg.signed and combined >= 0x80000000:
                        combined -= 0x100000000
                    decoded = combined * reg.scale + reg.offset
                    i += 1  # Skip next register
                else:
                    value = registers[i]
                    if reg.signed and value >= 0x8000:
                        value -= 0x10000
                    decoded = value * reg.scale + reg.offset
                
                # Apply min/max limits
                if reg.min_value is not None:
                    decoded = max(decoded, reg.min_value)
                if reg.max_value is not None:
                    decoded = min(decoded, reg.max_value)
                
                result[reg.name] = round(decoded, 3)
            i += 1
        return result

class InverterSimulator:
    """Simulates inverter responses for testing without hardware."""
    
    def __init__(self, profile: InverterProfile, slave_id: int = 1):
        self.profile = profile
        self.slave_id = slave_id
        self.registers: Dict[int, int] = {}
        self._init_registers()
    
    def _init_registers(self):
        """Initialize register values with realistic defaults."""
        for reg in self.profile.registers:
            if reg.category == "pv":
                self.registers[reg.address] = random.randint(0, 5000)
            elif reg.category == "battery":
                if "soc" in reg.name:
                    self.registers[reg.address] = random.randint(20, 100)
                elif "voltage" in reg.name:
                    self.registers[reg.address] = random.randint(400, 520)
                elif "current" in reg.name:
                    self.registers[reg.address] = random.randint(0, 100)
                elif "power" in reg.name:
                    self.registers[reg.address] = random.randint(0, 5000)
                elif "temperature" in reg.name:
                    self.registers[reg.address] = random.randint(200, 450)
                else:
                    self.registers[reg.address] = random.randint(0, 1000)
            elif reg.category == "grid":
                if "voltage" in reg.name:
                    self.registers[reg.address] = random.randint(2200, 2500)
                elif "power" in reg.name:
                    self.registers[reg.address] = random.randint(-5000, 5000)
                elif "frequency" in reg.name:
                    self.registers[reg.address] = random.randint(4950, 5050)
                else:
                    self.registers[reg.address] = random.randint(0, 1000)
            elif reg.category == "load":
                if "power" in reg.name:
                    self.registers[reg.address] = random.randint(0, 8000)
                elif "voltage" in reg.name:
                    self.registers[reg.address] = random.randint(2200, 2500)
                else:
                    self.registers[reg.address] = random.randint(0, 1000)
            else:
                self.registers[reg.address] = random.randint(0, 1000)
    
    def update(self):
        """Update simulated values with realistic drift."""
        for addr in self.registers:
            reg = next((r for r in self.profile.registers if r.address == addr), None)
            if reg:
                # Add small random drift
                drift = random.randint(-10, 10)
                self.registers[addr] = max(0, self.registers[addr] + drift)
                
                # Keep within realistic bounds
                if reg.category == "battery" and "soc" in reg.name:
                    self.registers[addr] = min(100, max(0, self.registers[addr]))
                elif reg.category == "grid" and "voltage" in reg.name:
                    self.registers[addr] = min(2600, max(2000, self.registers[addr]))
    
    def handle_request(self, request: bytes) -> bytes:
        """Handle a Modbus request and return response."""
        if len(request) < 8:
            return b""
        
        # Verify CRC
        data = request[:-2]
        received_crc = struct.unpack("<H", request[-2:])[0]
        calculated_crc = struct.unpack("<H", ModbusRTU.calculate_crc(data))[0]
        
        if received_crc != calculated_crc:
            return b""
        
        slave_id = request[0]
        if slave_id != self.slave_id and slave_id != 0:  # 0 = broadcast
            return b""
        
        function_code = request[1]
        
        # Read holding registers
        if function_code == 0x03:
            start_addr = struct.unpack(">H", request[2:4])[0]
            count = struct.unpack(">H", request[4:6])[0]
            
            values = []
            for i in range(count):
                addr = start_addr + i
                values.append(self.registers.get(addr, 0))
            
            # Build response
            byte_count = len(values) * 2
            response = struct.pack(">BBB", slave_id, function_code, byte_count)
            for v in values:
                response += struct.pack(">H", v)
            response += ModbusRTU.calculate_crc(response)
            return response
        
        # Read input registers
        if function_code == 0x04:
            start_addr = struct.unpack(">H", request[2:4])[0]
            count = struct.unpack(">H", request[4:6])[0]
            
            values = []
            for i in range(count):
                addr = start_addr + i
                values.append(self.registers.get(addr, 0))
            
            byte_count = len(values) * 2
            response = struct.pack(">BBB", slave_id, function_code, byte_count)
            for v in values:
                response += struct.pack(">H", v)
            response += ModbusRTU.calculate_crc(response)
            return response
        
        # Write single register
        if function_code == 0x06:
            addr = struct.unpack(">H", request[2:4])[0]
            value = struct.unpack(">H", request[4:6])[0]
            self.registers[addr] = value
            return request  # Echo request as acknowledgment
        
        return b""

# Common inverter profiles
INVERTER_PROFILES = {
    "deye_sg03lp1": InverterProfile(
        name="Deye Sun-5K-SG03LP1",
        manufacturer="Deye",
        protocol="modbus_rtu",
        baudrate=9600,
        slave_id=1,
        registers=[
            ModbusRegister(0, "pv_power", "W", scale=1, category="pv", description="PV array power"),
            ModbusRegister(1, "pv_voltage", "V", scale=0.1, category="pv", description="PV array voltage"),
            ModbusRegister(2, "pv_current", "A", scale=0.1, category="pv", description="PV array current"),
            ModbusRegister(3, "battery_voltage", "V", scale=0.1, category="battery", description="Battery voltage"),
            ModbusRegister(4, "battery_current", "A", scale=0.1, category="battery", description="Battery current"),
            ModbusRegister(5, "battery_soc", "%", scale=1, category="battery", min_value=0, max_value=100, description="Battery state of charge"),
            ModbusRegister(6, "battery_soh", "%", scale=1, category="battery", min_value=0, max_value=100, description="Battery state of health"),
            ModbusRegister(7, "battery_temperature", "°C", scale=0.1, category="battery", description="Battery temperature"),
            ModbusRegister(8, "grid_power", "W", scale=1, category="grid", description="Grid power (positive=import, negative=export)"),
            ModbusRegister(9, "grid_voltage", "V", scale=0.1, category="grid", description="Grid voltage"),
            ModbusRegister(10, "grid_frequency", "Hz", scale=0.01, category="grid", description="Grid frequency"),
            ModbusRegister(11, "load_power", "W", scale=1, category="load", description="House load power"),
            ModbusRegister(12, "load_voltage", "V", scale=0.1, category="load", description="Load voltage"),
            ModbusRegister(13, "inverter_temp", "°C", scale=0.1, category="temperature", description="Inverter temperature"),
            ModbusRegister(14, "inverter_status", "", scale=1, category="general", description="Inverter operating status"),
        ]
    ),
    "growatt_spf3000": InverterProfile(
        name="Growatt SPF3000",
        manufacturer="Growatt",
        protocol="modbus_rtu",
        baudrate=9600,
        slave_id=1,
        registers=[
            ModbusRegister(0, "pv_power", "W", scale=1, category="pv"),
            ModbusRegister(1, "battery_voltage", "V", scale=0.1, category="battery"),
            ModbusRegister(2, "battery_soc", "%", scale=1, category="battery", min_value=0, max_value=100),
            ModbusRegister(3, "grid_voltage", "V", scale=0.1, category="grid"),
            ModbusRegister(4, "grid_power", "W", scale=1, category="grid"),
            ModbusRegister(5, "load_power", "W", scale=1, category="load"),
        ]
    ),
    "generic": InverterProfile(
        name="Generic Inverter",
        manufacturer="Generic",
        protocol="modbus_rtu",
        baudrate=9600,
        slave_id=1,
        registers=[
            ModbusRegister(0, "voltage", "V", scale=0.1),
            ModbusRegister(1, "current", "A", scale=0.1),
            ModbusRegister(2, "power", "W", scale=1),
            ModbusRegister(3, "frequency", "Hz", scale=0.01),
        ]
    )
}

def get_profile(name: str) -> InverterProfile:
    """Get inverter profile by name."""
    return INVERTER_PROFILES.get(name, INVERTER_PROFILES["generic"])
