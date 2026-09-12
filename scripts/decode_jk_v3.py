#!/usr/bin/env python3
"""
Decode JK-BMS data with 5AA5 frame delimiter - v3.
"""
import serial
import time
import struct

def parse_jk_frame(data, idx):
    """Parse a single JK-BMS frame starting at idx."""
    if idx + 4 >= len(data):
        return None, idx
    
    # Verify delimiter
    if data[idx] != 0x5A or data[idx+1] != 0xA5:
        return None, idx
    
    # Frame type (2 bytes)
    frame_type = (data[idx+2] << 8) | data[idx+3]
    
    # Length
    length = data[idx+4]
    
    if idx + 5 + length + 1 > len(data):
        return None, idx
    
    # Data
    frame_data = data[idx+5:idx+5+length]
    
    # Checksum (last byte)
    checksum = data[idx+5+length]
    
    return {
        "type": frame_type,
        "length": length,
        "data": frame_data,
        "checksum": checksum,
    }, idx + 5 + length + 1

def decode_all_frames(data):
    """Decode all JK-BMS frames in data."""
    frames = []
    idx = 0
    
    while idx < len(data) - 4:
        frame, new_idx = parse_jk_frame(data, idx)
        if frame:
            frames.append(frame)
            idx = new_idx
        else:
            idx += 1
    
    return frames

def parse_cell_voltages(data):
    """Parse cell voltages from frame data."""
    # Each cell voltage is 3 bytes: [cell_number (1 byte)] [voltage (2 bytes, 0.001V)]
    cells = []
    for i in range(0, len(data), 3):
        if i + 2 < len(data):
            cell_num = data[i]
            voltage = (data[i+1] << 8) | data[i+2]
            cells.append({
                "cell": cell_num,
                "voltage": voltage * 0.001
            })
    return cells

def parse_runtime_data(data):
    """Parse runtime data from frame data."""
    if len(data) < 10:
        return None
    
    result = {}
    
    # Parse based on observed structure
    # Bytes 0-1: Pack voltage (0.01V)
    # Bytes 2-3: Current (0.01A, signed)
    # Byte 4: SOC
    # Byte 5-6: Temperatures
    # etc.
    
    try:
        pack_v = (data[0] << 8) | data[1]
        result['pack_voltage'] = pack_v * 0.01
        
        current = (data[2] << 8) | data[3]
        if current >= 0x8000:
            current -= 0x10000
        result['current'] = current * 0.01
        
        result['soc'] = data[4]
        
        if len(data) > 6:
            result['temp1'] = data[5] * 0.1
            result['temp2'] = data[6] * 0.1
        
        if len(data) > 7:
            result['capacity'] = data[7]
        
    except Exception as e:
        result['error'] = str(e)
    
    return result

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
    print(f"Hex: {data.hex()}")
    
    # Decode frames
    frames = decode_all_frames(data)
    print(f"\nFound {len(frames)} frames")
    
    for i, frame in enumerate(frames):
        print(f"\nFrame {i}:")
        print(f"  Type: 0x{frame['type']:04X}")
        print(f"  Length: {frame['length']}")
        print(f"  Data: {frame['data'].hex()}")
        
        # Parse cell voltage frames
        if frame['type'] == 0x3982:
            cells = parse_cell_voltages(frame['data'])
            if cells:
                print(f"  Cell voltages ({len(cells)} cells):")
                for cell in cells:
                    print(f"    Cell {cell['cell']}: {cell['voltage']:.3f}V")
        
        # Parse runtime data
        if frame['type'] == 0x0582:
            parsed = parse_runtime_data(frame['data'])
            if parsed:
                print(f"  Runtime data: {parsed}")

if __name__ == "__main__":
    main()
