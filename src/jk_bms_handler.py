#!/usr/bin/env python3
"""
JK-BMS Protocol Handler
Custom protocol for JK-BMS batteries via RS-485

Frame format (300 bytes):
  [0:4]   Header: 55 AA EB 90
  [4]     Frame code (0x01-0x06)
  [5]     Counter
  [6:299] Data (293 bytes)
  [299]   Checksum (sum8 of bytes 0-298)
"""
import struct
import time
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Frame codes
FRAME_CONFIG_READ = 0x01      # BMS → Host: Configuration
FRAME_RUNTIME_DATA = 0x02     # BMS → Host: Runtime data
FRAME_DEVICE_INFO = 0x03      # BMS → Host: Device info
FRAME_CONFIG_WRITE = 0x04     # Host → BMS: Write config
FRAME_SYSTEM_LOG = 0x05       # BMS → Host: System log
FRAME_FAULT_INFO = 0x06       # BMS → Host: Fault info

FRAME_NAMES = {
    0x01: "Config Read",
    0x02: "Runtime Data",
    0x03: "Device Info",
    0x04: "Config Write",
    0x05: "System Log",
    0x06: "Fault Info",
}

# Magic header
HEADER = bytes([0x55, 0xAA, 0xEB, 0x90])


def calculate_checksum(frame: bytes) -> int:
    """Calculate sum8 checksum of bytes 0-298."""
    return sum(frame[0:299]) & 0xFF


def build_query(frame_code: int, counter: int = 0) -> bytes:
    """Build a 300-byte query frame."""
    frame = bytearray(300)
    frame[0:4] = HEADER
    frame[4] = frame_code
    frame[5] = counter
    # Data section is already zeros
    frame[299] = calculate_checksum(frame)
    return bytes(frame)


def parse_frame(frame: bytes) -> Optional[Dict]:
    """Parse a 300-byte JK-BMS frame."""
    if len(frame) != 300:
        return None
    
    # Verify header
    if frame[0:4] != HEADER:
        return None
    
    # Verify checksum
    expected_checksum = calculate_checksum(frame)
    if frame[299] != expected_checksum:
        return None
    
    frame_code = frame[4]
    counter = frame[5]
    data = frame[6:299]
    
    return {
        "frame_code": frame_code,
        "frame_name": FRAME_NAMES.get(frame_code, f"Unknown 0x{frame_code:02X}"),
        "counter": counter,
        "data": data,
    }


def parse_runtime_data(data: bytes) -> Dict:
    """Parse runtime data (frame 0x02) from BMS."""
    result = {}
    
    # Cell voltages: 32 x u16 (little-endian), scale 0.001
    cell_voltages = []
    for i in range(32):
        raw = struct.unpack_from('<H', data, i * 2)[0]
        cell_voltages.append(round(raw * 0.001, 3))
    result['cell_voltages'] = cell_voltages
    
    # Cell status bitmap (offset 64, 4 bytes) - skip
    
    # Average cell voltage (offset 68)
    result['avg_cell_v'] = struct.unpack_from('<H', data, 68)[0] * 0.001
    
    # Voltage delta (offset 70)
    result['volt_delta'] = struct.unpack_from('<H', data, 70)[0] * 0.001
    
    # Max/min cell number (offset 72-73)
    result['max_cell_no'] = data[72]
    result['min_cell_no'] = data[73]
    
    # Cell wire resistance (offset 74, 64 bytes) - skip
    
    # MOS temperature (offset 138, i16, scale 0.1)
    result['mos_temp'] = struct.unpack_from('<h', data, 138)[0] * 0.1
    
    # Battery voltage (offset 144, i32, scale 0.001)
    result['voltage'] = struct.unpack_from('<i', data, 144)[0] * 0.001
    
    # Battery power (offset 148, u32, scale 0.001)
    result['power'] = struct.unpack_from('<I', data, 148)[0] * 0.001
    
    # Battery current (offset 152, i32, scale 0.001)
    result['current'] = struct.unpack_from('<i', data, 152)[0] * 0.001
    
    # Battery temp1 (offset 156, i16, scale 0.1)
    result['temp1'] = struct.unpack_from('<h', data, 156)[0] * 0.1
    
    # Battery temp2 (offset 158, i16, scale 0.1)
    result['temp2'] = struct.unpack_from('<h', data, 158)[0] * 0.1
    
    # SOC (offset 167, u8)
    result['soc'] = data[167]
    
    # Remaining capacity (offset 168, u32, scale 0.001)
    result['remaining_capacity'] = struct.unpack_from('<I', data, 168)[0] * 0.001
    
    # Full capacity (offset 172, u32, scale 0.001)
    result['full_capacity'] = struct.unpack_from('<I', data, 172)[0] * 0.001
    
    # Cycle count (offset 176, u32)
    result['cycle_count'] = struct.unpack_from('<I', data, 176)[0]
    
    return result


def parse_config_data(data: bytes) -> Dict:
    """Parse configuration data (frame 0x01) from BMS."""
    result = {}
    
    # Cell UV voltage (offset 0, u32, scale 0.001)
    result['cell_uv'] = struct.unpack_from('<I', data, 0)[0] * 0.001
    
    # Cell OVP voltage (offset 12, u32, scale 0.001)
    result['cell_ov'] = struct.unpack_from('<I', data, 12)[0] * 0.001
    
    # Balance trigger voltage (offset 20, u32, scale 0.001)
    result['balance_trig'] = struct.unpack_from('<I', data, 20)[0] * 0.001
    
    # Charge OTP (offset 76, i32, scale 0.1)
    result['charge_otp'] = struct.unpack_from('<i', data, 76)[0] * 0.1
    
    # Discharge OTP (offset 84, i32, scale 0.1)
    result['discharge_otp'] = struct.unpack_from('<i', data, 84)[0] * 0.1
    
    # Cell count (offset 108, u32)
    result['cell_count'] = struct.unpack_from('<I', data, 108)[0]
    
    # Charge enabled (offset 112, u32)
    result['charge_enabled'] = data[112]
    
    return result


def parse_device_info(data: bytes) -> Dict:
    """Parse device info (frame 0x03) from BMS."""
    result = {}
    
    # Device name (offset 0, 32 bytes, null-terminated string)
    name_bytes = data[0:32]
    result['device_name'] = name_bytes.split(b'\x00')[0].decode('utf-8', errors='ignore')
    
    # Manufacturer (offset 32, 32 bytes)
    mfr_bytes = data[32:64]
    result['manufacturer'] = mfr_bytes.split(b'\x00')[0].decode('utf-8', errors='ignore')
    
    # Protocol version (offset 64, u32)
    result['protocol_version'] = struct.unpack_from('<I', data, 64)[0]
    
    # Battery chemistry (offset 68, u32)
    chemistry_map = {0: "LiFePO4", 1: "Li-ion", 2: "LTO", 3: "Lead Acid"}
    chem_val = struct.unpack_from('<I', data, 68)[0]
    result['chemistry'] = chemistry_map.get(chem_val, f"Unknown ({chem_val})")
    
    # Nominal voltage (offset 72, u32, scale 0.001)
    result['nominal_voltage'] = struct.unpack_from('<I', data, 72)[0] * 0.001
    
    # Nominal capacity (offset 76, u32, scale 0.001)
    result['nominal_capacity'] = struct.unpack_from('<I', data, 76)[0] * 0.001
    
    return result


def parse_fault_info(data: bytes) -> Dict:
    """Parse fault info (frame 0x06) from BMS."""
    result = {}
    
    # Fault code (offset 0, u32)
    result['fault_code'] = struct.unpack_from('<I', data, 0)[0]
    
    # Fault flags (offset 4, u32)
    fault_flags = struct.unpack_from('<I', data, 4)[0]
    result['cell_ov'] = bool(fault_flags & 0x01)
    result['cell_uv'] = bool(fault_flags & 0x02)
    result['pack_ov'] = bool(fault_flags & 0x04)
    result['pack_uv'] = bool(fault_flags & 0x08)
    result['charge_oc'] = bool(fault_flags & 0x10)
    result['discharge_oc'] = bool(fault_flags & 0x20)
    result['charge_ot'] = bool(fault_flags & 0x40)
    result['charge_ut'] = bool(fault_flags & 0x80)
    result['discharge_ot'] = bool(fault_flags & 0x100)
    result['discharge_ut'] = bool(fault_flags & 0x200)
    result['mos_ot'] = bool(fault_flags & 0x400)
    
    return result
