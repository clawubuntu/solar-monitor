#!/usr/bin/env python3
"""
Decode JK-BMS data from serial port.
"""
import serial
import time
import struct

def decode_jk_frame(frame):
    """Decode a JK-BMS 300-byte frame."""
    if len(frame) < 300:
        return None
    
    # Verify header
    if frame[0:4] != bytes([0x55, 0xAA, 0xEB, 0x90]):
        return None
    
    # Verify checksum
    checksum = sum(frame[0:299]) & 0xFF
    if frame[299] != checksum:
        return None
    
    frame_code = frame[4]
    counter = frame[5]
    data = frame[6:299]
    
    result = {
        "frame_code": frame_code,
        "counter": counter,
        "data": data,
    }
    
    # Parse runtime data (frame code 0x02)
    if frame_code == 0x02:
        # Cell voltages (32 x u16)
        cell_voltages = []
        for i in range(32):
            raw = struct.unpack_from('<H', data, i * 2)[0]
            cell_voltages.append(raw * 0.001)
        
        avg_cell_v = struct.unpack_from('<H', data, 68)[0] * 0.001
        volt_delta = struct.unpack_from('<H', data, 70)[0] * 0.001
        max_cell_no = data[72]
        min_cell_no = data[73]
        mos_temp = struct.unpack_from('<h', data, 138)[0] * 0.1
        bat_voltage = struct.unpack_from('<i', data, 144)[0] * 0.001
        bat_power = struct.unpack_from('<I', data, 148)[0] * 0.001
        bat_current = struct.unpack_from('<i', data, 152)[0] * 0.001
        bat_temp1 = struct.unpack_from('<h', data, 156)[0] * 0.1
        bat_temp2 = struct.unpack_from('<h', data, 158)[0] * 0.1
        soc = data[167]
        remaining_capacity = struct.unpack_from('<I', data, 168)[0] * 0.001
        full_capacity = struct.unpack_from('<I', data, 172)[0] * 0.001
        cycle_count = struct.unpack_from('<I', data, 176)[0]
        
        result["metrics"] = {
            "cell_voltages": cell_voltages[:16],  # First 16 cells
            "avg_cell_v": avg_cell_v,
            "volt_delta": volt_delta,
            "max_cell_no": max_cell_no,
            "min_cell_no": min_cell_no,
            "mos_temp": mos_temp,
            "voltage": bat_voltage,
            "power": bat_power,
            "current": bat_current,
            "temp1": bat_temp1,
            "temp2": bat_temp2,
            "soc": soc,
            "remaining_capacity": remaining_capacity,
            "full_capacity": full_capacity,
            "cycle_count": cycle_count,
        }
    
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
    data = ser.read(1000)
    ser.close()
    
    print(f"Received {len(data)} bytes")
    print(f"Hex: {data.hex()}")
    
    # Try to decode
    decoded = decode_jk_frame(data)
    if decoded:
        print(f"\nDecoded JK-BMS frame:")
        print(f"  Frame code: 0x{decoded['frame_code']:02X}")
        print(f"  Counter: {decoded['counter']}")
        if "metrics" in decoded:
            m = decoded["metrics"]
            print(f"  Voltage: {m['voltage']}V")
            print(f"  Current: {m['current']}A")
            print(f"  SOC: {m['soc']}%")
            print(f"  Cell voltages: {m['cell_voltages']}")
            print(f"  Temperatures: {m['temp1']}°C, {m['temp2']}°C")
            print(f"  Cycle count: {m['cycle_count']}")
    else:
        print("\nCould not decode as JK-BMS frame")
        print("First 10 bytes:", data[:10].hex() if len(data) >= 10 else "N/A")

if __name__ == "__main__":
    main()
