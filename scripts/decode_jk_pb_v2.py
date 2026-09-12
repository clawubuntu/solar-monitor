#!/usr/bin/env python3
"""
Decode JK-PB BMS data - tries multiple parsing strategies.
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
    print(f"Hex: {data[:300].hex()}")
    
    # Parse as 5AA5 frames
    delimiter = bytes([0x5A, 0xA5])
    parts = data.split(delimiter)
    
    for i, part in enumerate(parts):
        if len(part) < 10:
            continue
        
        frame_type = (part[0] << 8) | part[1]
        length = part[2]
        
        if len(part) < 3 + length:
            continue
        
        frame_data = part[3:3+length]
        
        print(f"\nFrame {i}: type=0x{frame_type:04X}, len={length}")
        print(f"  Data: {frame_data.hex()}")
        
        # Try to find cell voltages (values between 2500-4000 = 2.5V-4.0V)
        if len(frame_data) >= 4:
            # Try 2-byte big-endian at different offsets
            for offset in range(0, 4):
                voltages = []
                for j in range(offset, len(frame_data)-1, 2):
                    val = (frame_data[j] << 8) | frame_data[j+1]
                    if 2000 < val < 5000:
                        voltages.append(val * 0.001)
                if len(voltages) >= 8:
                    print(f"  Offset {offset}: {len(voltages)} voltages: {[f'{v:.3f}' for v in voltages[:16]]}")
            
            # Try 3-byte format: [cell_num, hi, lo]
            voltages = []
            for j in range(0, len(frame_data)-2, 3):
                cell_num = frame_data[j]
                voltage = (frame_data[j+1] << 8) | frame_data[j+2]
                if 2000 < voltage < 5000:
                    voltages.append((cell_num, voltage * 0.001))
            if voltages:
                print(f"  3-byte format: {voltages[:16]}")

if __name__ == "__main__":
    main()
