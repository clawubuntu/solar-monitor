#!/usr/bin/env python3
"""
JK-PB BMS Decoder - Final Version
Parses cell voltages and runtime data from JK-PB series BMS.
"""
import serial
import time
import struct

def decode_frames(data):
    """Decode all 5AA5 frames from data."""
    delimiter = bytes([0x5A, 0xA5])
    parts = data.split(delimiter)
    frames = []
    
    for part in parts:
        if len(part) < 4:
            continue
        
        frame_type = (part[0] << 8) | part[1]
        length = part[2]
        
        if len(part) < 3 + length + 1:
            continue
        
        frame_data = part[3:3+length]
        checksum = part[3+length]
        
        frames.append({
            "type": frame_type,
            "length": length,
            "data": frame_data,
            "checksum": checksum,
        })
    
    return frames

def parse_runtime_data(data):
    """Parse 0x2182 runtime data frame."""
    if len(data) < 16:
        return None
    
    result = {}
    
    # Pack voltage: bytes 0-3, little-endian u32, 0.01V scale
    pack_v = struct.unpack_from('<I', data, 0)[0]
    if 10000 < pack_v < 60000:  # 100V - 600V range
        result['pack_voltage'] = pack_v * 0.01
    
    # Current: bytes 4-5, little-endian u16, 0.1A scale
    current = struct.unpack_from('<H', data, 4)[0]
    if current >= 0x8000:
        current -= 0x10000
    result['current'] = current * 0.1
    
    # SOC: byte 6, u8
    soc = data[6]
    if 0 <= soc <= 100:
        result['soc'] = soc
    
    # Temperature 1: byte 7, i8, 1°C scale
    temp1 = struct.unpack_from('<b', data, 7)[0]
    result['temp1'] = temp1
    
    # Temperature 2: byte 8, i8, 1°C scale
    temp2 = struct.unpack_from('<b', data, 8)[0]
    result['temp2'] = temp2
    
    # Cell count: byte 9
    if 0 < data[9] <= 32:
        result['cell_count'] = data[9]
    
    # Remaining capacity: bytes 10-11, little-endian u16, 0.01Ah scale
    remaining = struct.unpack_from('<H', data, 10)[0]
    result['remaining_capacity'] = remaining * 0.01
    
    # Full capacity: bytes 12-13, little-endian u16, 0.01Ah scale
    full = struct.unpack_from('<H', data, 12)[0]
    result['full_capacity'] = full * 0.01
    
    # Cycle count: bytes 14-15, little-endian u16
    result['cycle_count'] = struct.unpack_from('<H', data, 14)[0]
    
    return result

def parse_cell_voltages(data):
    """Parse 0x3982 cell voltage frame."""
    cells = []
    
    # First byte is cell count or starting index
    # Cell voltages: 2 bytes each, big-endian, 0.001V scale
    for i in range(1, len(data)-1, 2):
        val = (data[i] << 8) | data[i+1]
        if 2000 < val < 5000:  # 2.0V - 5.0V range
            cells.append(val * 0.001)
    
    return cells

def main():
    port = "/dev/ttyUSB2"
    baud = 115200
    
    ser = serial.Serial(port, baud, timeout=1)
    ser.write(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0a, 0xc5, 0xcd]))
    time.sleep(0.5)
    data = ser.read(2000)
    ser.close()
    
    frames = decode_frames(data)
    
    cell_voltages = []
    runtime_data = {}
    
    for frame in frames:
        frame_type = frame['type']
        frame_data = frame['data']
        
        if frame_type == 0x2182:
            result = parse_runtime_data(frame_data)
            if result:
                runtime_data.update(result)
        
        elif frame_type == 0x3982:
            cells = parse_cell_voltages(frame_data)
            if cells:
                cell_voltages.extend(cells)
    
    # Print results
    print(f"{'='*60}")
    print(f"JK-PB BMS Data")
    print(f"{'='*60}")
    
    if cell_voltages:
        print(f"\nCell Voltages ({len(cell_voltages)} cells):")
        for i, v in enumerate(cell_voltages):
            print(f"  Cell {i+1:2d}: {v:.3f}V")
        print(f"  Min: {min(cell_voltages):.3f}V")
        print(f"  Max: {max(cell_voltages):.3f}V")
        print(f"  Delta: {max(cell_voltages) - min(cell_voltages):.3f}V")
    
    if runtime_data:
        print(f"\nRuntime Data:")
        for k, v in runtime_data.items():
            print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
