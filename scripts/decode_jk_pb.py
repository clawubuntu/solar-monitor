#!/usr/bin/env python3
"""
Decode JK-PB BMS data at 115200 baud with 5AA5 frame delimiter.
"""
import serial
import time
import struct

def decode_jk_pb_data(data):
    """Decode JK-PB BMS data with 5AA5 frame delimiter."""
    frames = []
    delimiter = bytes([0x5A, 0xA5])
    
    parts = data.split(delimiter)
    
    for part in parts:
        if len(part) < 4:
            continue
        
        # Frame type (2 bytes, big-endian)
        frame_type = (part[0] << 8) | part[1]
        
        # Length (1 byte)
        length = part[2]
        
        if len(part) < 3 + length + 1:
            continue
        
        # Data
        frame_data = part[3:3+length]
        
        # Checksum (last byte)
        checksum = part[3+length]
        
        frames.append({
            "type": frame_type,
            "length": length,
            "data": frame_data,
            "checksum": checksum,
        })
    
    return frames

def parse_cell_voltages(data):
    """Parse cell voltages from frame data (2 bytes each, big-endian, 0.001V scale)."""
    cells = []
    for i in range(0, len(data)-1, 2):
        voltage = (data[i] << 8) | data[i+1]
        if 2000 < voltage < 5000:  # Filter realistic cell voltages (2.0V - 5.0V)
            cells.append(voltage * 0.001)
    return cells

def parse_runtime_data(data):
    """Parse runtime data from frame data."""
    metrics = {}
    
    # Based on observed data patterns
    # Bytes 0-1: Pack voltage (0.01V scale)
    # Bytes 2-3: Current (0.01A scale, signed)
    # Byte 4: SOC
    # Bytes 5-6: Temperatures (0.1C scale)
    
    if len(data) >= 4:
        pack_v = (data[0] << 8) | data[1]
        metrics['pack_voltage'] = pack_v * 0.01
        
        current = (data[2] << 8) | data[3]
        if current >= 0x8000:
            current -= 0x10000
        metrics['current'] = current * 0.01
    
    if len(data) >= 5:
        metrics['soc'] = data[4]
    
    if len(data) >= 7:
        metrics['temp1'] = data[5] * 0.1
        metrics['temp2'] = data[6] * 0.1
    
    return metrics

def main():
    port = "/dev/ttyUSB2"
    baud = 115200
    
    print(f"Reading from {port} at {baud} baud...")
    
    ser = serial.Serial(port, baud, timeout=1)
    ser.write(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0a, 0xc5, 0xcd]))
    time.sleep(0.5)
    data = ser.read(2000)
    ser.close()
    
    print(f"Received {len(data)} bytes")
    
    frames = decode_jk_pb_data(data)
    print(f"Found {len(frames)} frames")
    
    all_cell_voltages = []
    runtime_metrics = {}
    
    for i, frame in enumerate(frames):
        frame_type = frame['type']
        frame_data = frame['data']
        
        # Cell voltage frames (type 0x3982)
        if frame_type == 0x3982:
            cells = parse_cell_voltages(frame_data)
            if cells:
                all_cell_voltages.extend(cells)
        
        # Runtime data frames (type 0x2182)
        elif frame_type == 0x2182:
            metrics = parse_runtime_data(frame_data)
            runtime_metrics.update(metrics)
        
        # Alternative runtime data (type 0x0582)
        elif frame_type == 0x0582:
            # Parse based on observed structure
            if len(frame_data) >= 10:
                pack_v = (frame_data[0] << 8) | frame_data[1]
                if 1000 < pack_v < 6000:  # 10V - 60V range
                    runtime_metrics['pack_voltage'] = pack_v * 0.01
                
                soc = frame_data[4]
                if 0 <= soc <= 100:
                    runtime_metrics['soc'] = soc
    
    print(f"\n=== RESULTS ===")
    if all_cell_voltages:
        print(f"Cell voltages ({len(all_cell_voltages)} cells):")
        for i, v in enumerate(all_cell_voltages):
            print(f"  Cell {i+1}: {v:.3f}V")
        print(f"  Min: {min(all_cell_voltages):.3f}V")
        print(f"  Max: {max(all_cell_voltages):.3f}V")
        print(f"  Delta: {max(all_cell_voltages) - min(all_cell_voltages):.3f}V")
    
    if runtime_metrics:
        print(f"\nRuntime metrics:")
        for k, v in runtime_metrics.items():
            print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
