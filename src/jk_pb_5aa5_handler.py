#!/usr/bin/env python3
"""
JK-PB 5AA5 Frame Protocol Handler
Custom protocol for JK-PB series BMS via RS-485 at 115200 baud.

Frame format:
  [0:2]   Delimiter: 5A A5
  [2:4]   Frame type (big-endian u16)
  [4]     Length (number of data bytes)
  [5:5+N] Data payload
  [5+N]   Checksum (sum of all preceding bytes INCLUDING delimiter, truncated to u8)

This is NOT standard Modbus RTU. The BMS continuously outputs frames
or responds to a trigger write (Modbus RTU query 01 03 00 00 00 0A C5 CD).
"""
import struct
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Frame delimiter
DELIMITER = bytes([0x5A, 0xA5])

# Frame types
FRAME_RUNTIME_DATA = 0x2182   # Pack voltage, current, SOC, temps, etc.
FRAME_CELL_VOLTAGES = 0x3982  # Cell voltage data
FRAME_STATUS = 0x0582         # Status/control frame

FRAME_NAMES = {
    0x2182: "Runtime Data",
    0x3982: "Cell Voltages",
    0x0582: "Status/Control",
}


def calculate_checksum(data: bytes) -> int:
    """Calculate checksum: sum of all bytes truncated to u8."""
    return sum(data) & 0xFF


def decode_frames(raw_data: bytes) -> List[Dict]:
    """
    Decode all 5AA5 frames from raw serial data.
    Returns a list of parsed frame dicts.
    """
    frames = []
    
    # Find all delimiter positions
    start = 0
    while start < len(raw_data):
        # Find next delimiter
        idx = raw_data.find(DELIMITER, start)
        if idx == -1:
            break
        
        # Need at least delimiter (2) + type (2) + length (1) = 5 bytes for header
        if idx + 5 > len(raw_data):
            break
        
        # Parse header (after delimiter)
        frame_type = (raw_data[idx + 2] << 8) | raw_data[idx + 3]
        length = raw_data[idx + 4]
        
        # Check if we have enough data: header(3 after delim) + length + checksum(1)
        frame_end = idx + 2 + 3 + length + 1
        if frame_end > len(raw_data):
            break
        
        # Extract frame data and checksum
        frame_bytes = raw_data[idx:idx + 2 + 3 + length]  # delimiter + type + length + data
        checksum = raw_data[idx + 2 + 3 + length]
        frame_data = raw_data[idx + 5:idx + 5 + length]
        
        # Verify checksum (includes delimiter)
        expected_checksum = calculate_checksum(frame_bytes)
        if checksum != expected_checksum:
            logger.debug(f"Checksum mismatch for frame 0x{frame_type:04X}: "
                        f"got 0x{checksum:02X}, expected 0x{expected_checksum:02X}")
            # Still add frame but mark as invalid
            # (in production, we might want to skip instead)
        
        frames.append({
            "type": frame_type,
            "name": FRAME_NAMES.get(frame_type, f"Unknown 0x{frame_type:04X}"),
            "length": length,
            "data": frame_data,
            "checksum": checksum,
            "valid": checksum == expected_checksum,
        })
        
        start = frame_end
    
    return frames


def parse_runtime_data(data: bytes) -> Dict:
    """
    Parse 0x2182 runtime data frame.
    
    Field offsets (from protocol analysis):
      0-3:   Pack voltage (LE u32, 0.01V scale)
      4-5:   Current (LE u16 signed, 0.1A scale)
      6:     SOC (u8, 1% scale)
      7:     Temp 1 (i8, 1°C scale)
      8:     Temp 2 (i8, 1°C scale)
      9:     Cell count (u8)
      10-11: Remaining capacity (LE u16, 0.01Ah scale)
      12-13: Full capacity (LE u16, 0.01Ah scale)
      14-15: Cycle count (LE u16)
    """
    result = {}
    
    if len(data) < 16:
        return result
    
    # Pack voltage: bytes 0-3, LE u32, 0.01V scale
    pack_v = struct.unpack_from('<I', data, 0)[0]
    if 1000 < pack_v < 60000:  # 10V - 600V range
        result['voltage'] = round(pack_v * 0.01, 2)
    
    # Current: bytes 4-5, LE u16 signed, 0.1A scale
    current = struct.unpack_from('<H', data, 4)[0]
    if current >= 0x8000:
        current -= 0x10000
    result['current'] = round(current * 0.1, 1)
    
    # SOC: byte 6, u8
    soc = data[6]
    if 0 <= soc <= 100:
        result['soc'] = soc
    
    # Temperature 1: byte 7, i8
    temp1 = struct.unpack_from('<b', data, 7)[0]
    result['temp1'] = temp1
    
    # Temperature 2: byte 8, i8
    temp2 = struct.unpack_from('<b', data, 8)[0]
    result['temp2'] = temp2
    
    # Cell count: byte 9
    if 0 < data[9] <= 32:
        result['cell_count'] = data[9]
    
    # Remaining capacity: bytes 10-11, LE u16, 0.01Ah scale
    remaining = struct.unpack_from('<H', data, 10)[0]
    result['remaining_capacity'] = round(remaining * 0.01, 2)
    
    # Full capacity: bytes 12-13, LE u16, 0.01Ah scale
    full = struct.unpack_from('<H', data, 12)[0]
    result['full_capacity'] = round(full * 0.01, 2)
    
    # Cycle count: bytes 14-15, LE u16
    result['cycle_count'] = struct.unpack_from('<H', data, 14)[0]
    
    # Power (calculated)
    if 'voltage' in result and 'current' in result:
        result['power'] = round(result['voltage'] * result['current'], 1)
    
    return result


def parse_cell_voltages(data: bytes) -> Tuple[int, List[float]]:
    """
    Parse 0x3982 cell voltage frame.
    
    Field layout:
      0:     Starting cell index (u8)
      1-2:   Cell voltage 1 (BE u16, 0.001V scale)
      3-4:   Cell voltage 2 (BE u16, 0.001V scale)
      ...    (up to 8 cells per frame)
    
    Returns (start_index, [voltages]).
    """
    if len(data) < 3:
        return (0, [])
    
    start_index = data[0]
    cells = []
    
    # Cell voltages: 2 bytes each, big-endian, 0.001V scale
    for i in range(1, len(data) - 1, 2):
        val = (data[i] << 8) | data[i + 1]
        if 1000 < val < 5000:  # 1.0V - 5.0V valid range
            cells.append(round(val * 0.001, 3))
    
    return (start_index, cells)


def parse_status_frame(data: bytes) -> Dict:
    """
    Parse 0x0582 status/control frame.
    Content varies; extract known fields if present.
    """
    result = {}
    
    if len(data) >= 2:
        # First 2 bytes often contain status flags
        status_flags = (data[0] << 8) | data[1]
        result['charge_enabled'] = bool(status_flags & 0x01)
        result['discharge_enabled'] = bool(status_flags & 0x02)
        result['balance_active'] = bool(status_flags & 0x04)
    
    return result


def build_trigger_query() -> bytes:
    """
    Build a trigger query to wake up the BMS.
    This is a standard Modbus RTU read holding registers command.
    The BMS appears to respond to this by outputting 5AA5 frames.
    """
    # Modbus RTU: slave=1, func=0x03, addr=0x0000, count=0x000A
    # CRC16: 0xC5CD (pre-calculated)
    return bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A, 0xC5, 0xCD])


def process_frames(raw_data: bytes) -> Dict:
    """
    Process all frames from raw serial data.
    Returns a combined metrics dict.
    """
    frames = decode_frames(raw_data)
    
    metrics = {}
    cell_voltages = {}
    status = {}
    
    for frame in frames:
        if not frame.get('valid', False):
            continue
        
        frame_type = frame['type']
        data = frame['data']
        
        if frame_type == FRAME_RUNTIME_DATA:
            runtime = parse_runtime_data(data)
            metrics.update(runtime)
        
        elif frame_type == FRAME_CELL_VOLTAGES:
            start_idx, cells = parse_cell_voltages(data)
            for i, v in enumerate(cells):
                cell_voltages[start_idx + i] = v
        
        elif frame_type == FRAME_STATUS:
            status = parse_status_frame(data)
    
    # Add cell voltages to metrics with cell_NN_v naming
    for idx in sorted(cell_voltages.keys()):
        metrics[f'cell_{idx + 1:02d}_v'] = cell_voltages[idx]
    
    # Add status flags
    metrics.update(status)
    
    # Calculate aggregate cell statistics
    if cell_voltages:
        voltages = list(cell_voltages.values())
        metrics['avg_cell_v'] = round(sum(voltages) / len(voltages), 4)
        metrics['min_cell_v'] = min(voltages)
        metrics['max_cell_v'] = max(voltages)
        metrics['volt_delta'] = round(max(voltages) - min(voltages), 4)
        metrics['cell_count_actual'] = len(voltages)
    
    return metrics
