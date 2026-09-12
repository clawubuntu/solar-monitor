#!/usr/bin/env python3
"""
Decode JK-BMS data with 5AA5 frame delimiter.
"""
import serial
import time
import struct

def decode_jk_data(data):
    """Decode JK-BMS data with 5AA5 frame delimiter."""
    frames = []
    delimiter = bytes([0x5A, 0xA5])
    
    # Split by delimiter
    parts = data.split(delimiter)
    
    for part in parts:
        if len(part) < 4:
            continue
        
        # Try to parse frame
        # Format: [5A A5] [frame_type] [length] [data...] [checksum]
        frame_type = part[0:2]
        length = part[2]
        
        if len(part) < 3 + length:
            continue
        
        frame_data = part[3:3+length]
        checksum = part[3+length] if len(part) > 3+length else 0
        
        frames.append({
            "type": frame_type.hex(),
            "length": length,
            "data": frame_data,
            "checksum": checksum,
        })
    
    return frames

def parse_runtime_data(data):
    """Parse runtime data from JK-BMS frame."""
    if len(data) < 40:
        return None
    
    # Parse based on observed data structure
    # This is a guess based on the hex patterns
    result = {}
    
    # Try to extract values
    # Bytes 0-1: Frame type
    # Bytes 2-3: Status
    # Bytes 4-5: Pack voltage (0.01V)
    # Bytes 6-7: Current (0.01A, signed)
    # Byte 8: SOC
    # etc.
    
    try:
        # Pack voltage at offset 4 (0.01V scale)
        pack_v = struct.unpack_from('>H', data, 4)[0] * 0.01
        result['voltage'] = pack_v
        
        # Current at offset 6 (0.01A scale, signed)
        current = struct.unpack_from('>h', data, 6)[0] * 0.01
        result['current'] = current
        
        # SOC at offset 8
        result['soc'] = data[8]
        
        # Temperatures at offset 9-10 (0.1C scale)
        temp1 = struct.unpack_from('>b', data, 9)[0] * 0.1
        temp2 = struct.unpack_from('>b', data, 10)[0] * 0.1
        result['temp1'] = temp1
        result['temp2'] = temp2
        
        # Cell voltages start at offset 20 (0.001V scale)
        cell_voltages = []
        for i in range(16):
            if len(data) > 20 + i*2:
                cv = struct.unpack_from('>H', data, 20 + i*2)[0] * 0.001
                cell_voltages.append(cv)
        result['cell_voltages'] = cell_voltages
        
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
    print(f"Hex: {data[:200].hex()}")
    
    # Decode frames
    frames = decode_jk_data(data)
    print(f"\nFound {len(frames)} frames")
    
    for i, frame in enumerate(frames[:5]):
        print(f"\nFrame {i}:")
        print(f"  Type: {frame['type']}")
        print(f"  Length: {frame['length']}")
        print(f"  Data: {frame['data'].hex()[:100]}")
        
        # Try to parse runtime data
        parsed = parse_runtime_data(frame['data'])
        if parsed:
            print(f"  Parsed: {parsed}")

if __name__ == "__main__":
    main()
