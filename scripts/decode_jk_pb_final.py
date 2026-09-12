#!/usr/bin/env python3
"""
Complete JK-PB BMS Decoder
"""
import serial
import time
import struct

def main():
    port = "/dev/ttyUSB2"
    baud = 115200
    
    ser = serial.Serial(port, baud, timeout=1)
    ser.write(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0a, 0xc5, 0xcd]))
    time.sleep(0.5)
    data = ser.read(2000)
    ser.close()
    
    print(f"Received {len(data)} bytes")
    
    # Parse as 5AA5 frames
    delimiter = bytes([0x5A, 0xA5])
    parts = data.split(delimiter)
    
    results = {
        "cell_voltages": [],
        "pack_voltage": 0,
        "current": 0,
        "soc": 0,
        "temperatures": [],
        "cell_count": 0,
    }
    
    for i, part in enumerate(parts):
        if len(part) < 4:
            continue
        
        frame_type = (part[0] << 8) | part[1]
        length = part[2]
        
        if len(part) < 3 + length:
            continue
        
        frame_data = part[3:3+length]
        
        # Cell voltage frame (0x3982)
        if frame_type == 0x3982 and len(frame_data) > 2:
            # Cell voltages start at offset 1 (skip first byte which is cell count or index)
            for j in range(1, len(frame_data)-1, 2):
                val = (frame_data[j] << 8) | frame_data[j+1]
                if 2000 < val < 5000:
                    results["cell_voltages"].append(val * 0.001)
        
        # Runtime data frame (0x2182)
        elif frame_type == 0x2182 and len(frame_data) >= 16:
            # Parse based on observed structure
            # Bytes 0-1: Pack voltage (0.01V scale)
            pack_v = (frame_data[0] << 8) | frame_data[1]
            if 1000 < pack_v < 6000:
                results["pack_voltage"] = pack_v * 0.01
            
            # Bytes 2-3: Current (0.01A scale)
            current = (frame_data[2] << 8) | frame_data[3]
            if current >= 0x8000:
                current -= 0x10000
            results["current"] = current * 0.01
            
            # Bytes 4-5: SOC
            results["soc"] = (frame_data[4] << 8) | frame_data[5]
            
            # Bytes 6-7: Temperatures
            temp1 = (frame_data[6] << 8) | frame_data[7]
            if temp1 >= 0x8000:
                temp1 -= 0x10000
            results["temperatures"].append(temp1 * 0.1)
            
            temp2 = (frame_data[8] << 8) | frame_data[9]
            if temp2 >= 0x8000:
                temp2 -= 0x10000
            results["temperatures"].append(temp2 * 0.1)
            
            # Byte 10: Cell count
            results["cell_count"] = frame_data[10]
    
    # Print results
    print(f"\n{'='*60}")
    print(f"JK-PB BMS Data")
    print(f"{'='*60}")
    
    if results["cell_voltages"]:
        print(f"\nCell Voltages ({len(results['cell_voltages'])} cells):")
        for i, v in enumerate(results["cell_voltages"]):
            print(f"  Cell {i+1:2d}: {v:.3f}V")
        print(f"  Min: {min(results['cell_voltages']):.3f}V")
        print(f"  Max: {max(results['cell_voltages']):.3f}V")
        print(f"  Delta: {max(results['cell_voltages']) - min(results['cell_voltages']):.3f}V")
    
    print(f"\nPack Voltage: {results['pack_voltage']}V")
    print(f"Current: {results['current']}A")
    print(f"SOC: {results['soc']}%")
    
    if results["temperatures"]:
        print(f"Temperatures: {results['temperatures']}°C")
    
    print(f"Cell Count: {results['cell_count']}")

if __name__ == "__main__":
    main()
