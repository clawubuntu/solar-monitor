#!/usr/bin/env python3
"""
JK-PB BMS Continuous Reader
Reads data continuously and tries to decode all frames.
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
        
        calc_checksum = sum(part[0:3+length]) & 0xFF
        
        frames.append({
            "type": frame_type,
            "length": length,
            "data": frame_data,
            "checksum": checksum,
            "valid": checksum == calc_checksum,
        })
    
    return frames

def parse_v2182(data):
    """Parse 0x2182 runtime data frame."""
    if len(data) < 16:
        return None
    
    result = {}
    
    # Try different interpretations
    # Bytes 0-1: Pack voltage (0.01V)
    pack_v = (data[0] << 8) | data[1]
    if 1000 < pack_v < 6000:
        result['pack_voltage'] = pack_v * 0.01
    
    # Bytes 2-3: Current (0.01A, signed)
    current = (data[2] << 8) | data[3]
    if current >= 0x8000:
        current -= 0x10000
    result['current'] = current * 0.01
    
    # Bytes 4-5: SOC
    soc = (data[4] << 8) | data[5]
    if 0 <= soc <= 100:
        result['soc'] = soc
    
    # Bytes 6-7: Temperature 1
    temp1 = (data[6] << 8) | data[7]
    if temp1 >= 0x8000:
        temp1 -= 0x10000
    result['temp1'] = temp1 * 0.1
    
    # Bytes 8-9: Temperature 2
    temp2 = (data[8] << 8) | data[9]
    if temp2 >= 0x8000:
        temp2 -= 0x10000
    result['temp2'] = temp2 * 0.1
    
    # Byte 10: Cell count
    if data[10] > 0 and data[10] <= 32:
        result['cell_count'] = data[10]
    
    # Bytes 11-12: Remaining capacity (0.01Ah)
    remaining = (data[11] << 8) | data[12]
    result['remaining_capacity'] = remaining * 0.01
    
    # Bytes 13-14: Full capacity (0.01Ah)
    full = (data[13] << 8) | data[14]
    result['full_capacity'] = full * 0.01
    
    # Byte 15: Cycle count
    result['cycle_count'] = data[15]
    
    return result

def parse_v3982(data):
    """Parse 0x3982 cell voltage frame."""
    cells = []
    
    # First byte might be cell count or starting index
    start = data[0]
    
    # Parse cell voltages (2 bytes each, 0.001V scale)
    for i in range(1, len(data)-1, 2):
        val = (data[i] << 8) | data[i+1]
        if 2000 < val < 5000:
            cells.append(val * 0.001)
    
    return cells

def main():
    port = "/dev/ttyUSB2"
    baud = 115200
    
    print(f"Reading from {port} at {baud} baud...")
    
    ser = serial.Serial(port, baud, timeout=1)
    
    # Send query
    ser.write(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0a, 0xc5, 0xcd]))
    
    # Read data
    time.sleep(0.5)
    data = ser.read(2000)
    ser.close()
    
    print(f"Received {len(data)} bytes")
    print(f"Hex: {data[:300].hex()}")
    
    frames = decode_frames(data)
    print(f"\nFound {len(frames)} frames")
    
    cell_voltages = []
    runtime_data = {}
    
    for i, frame in enumerate(frames):
        frame_type = frame['type']
        frame_data = frame['data']
        
        if frame_type == 0x2182:
            result = parse_v2182(frame_data)
            if result:
                runtime_data.update(result)
                print(f"\nFrame 0x{frame_type:04X}: Runtime Data")
                for k, v in result.items():
                    print(f"  {k}: {v}")
        
        elif frame_type == 0x3982:
            cells = parse_v3982(frame_data)
            if cells:
                cell_voltages.extend(cells)
                print(f"\nFrame 0x{frame_type:04X}: Cell Voltages ({len(cells)} cells)")
                print(f"  {cells}")
        
        elif frame_type == 0x0582:
            print(f"\nFrame 0x{frame_type:04X}: Status ({frame['length']} bytes)")
            print(f"  Data: {frame_data.hex()}")
    
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    
    if cell_voltages:
        print(f"Cell Voltages ({len(cell_voltages)} cells):")
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
