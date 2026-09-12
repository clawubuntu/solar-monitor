#!/usr/bin/env python3
"""
Comprehensive Battery Protocol Decoder
Tests all profiles against live serial data and reports readable values.
"""
import serial
import time
import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

SERIAL_PORTS = ["/dev/ttyUSB0", "/dev/ttyUSB2"]

def read_serial_data(port, baud, timeout=1):
    """Read raw data from serial port."""
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
        # Send a generic query
        ser.write(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0a, 0xc5, 0xcd]))
        time.sleep(0.5)
        data = ser.read(2000)
        ser.close()
        return data
    except:
        return None

def try_parse_modbus(data, profile):
    """Try to parse data as Modbus RTU."""
    if not data or len(data) < 5:
        return None
    
    results = []
    
    # Check for valid Modbus response
    if data[0] == profile.slave_id and data[1] == 0x03:
        byte_count = data[2]
        if len(data) >= 3 + byte_count + 2:
            # Extract register values
            registers = []
            for i in range(byte_count // 2):
                val = struct.unpack('>H', data[3 + i*2:5 + i*2])[0]
                registers.append(val)
            
            # Map to profile registers
            if registers and profile.registers:
                start_addr = profile.registers[0].address
                metrics = {}
                for i, reg in enumerate(registers):
                    addr = start_addr + i
                    # Find matching profile register
                    for prof_reg in profile.registers:
                        if prof_reg.address == addr:
                            value = reg * prof_reg.scale
                            metrics[prof_reg.name] = value
                            break
                
                if metrics:
                    results.append({
                        "protocol": "Modbus RTU",
                        "metrics": metrics
                    })
    
    return results

def try_parse_jk_custom(data):
    """Try to parse data as JK-BMS custom protocol (55 AA EB 90 header)."""
    if not data:
        return None
    
    header = bytes([0x55, 0xAA, 0xEB, 0x90])
    if header not in data:
        return None
    
    idx = data.index(header)
    if len(data) < idx + 300:
        return None
    
    frame = data[idx:idx+300]
    
    # Verify checksum
    checksum = sum(frame[0:299]) & 0xFF
    if frame[299] != checksum:
        return None
    
    frame_code = frame[4]
    data_section = frame[6:299]
    
    results = []
    
    if frame_code == 0x02:
        # Runtime data
        cell_voltages = []
        for i in range(32):
            raw = struct.unpack_from('<H', data_section, i * 2)[0]
            cell_voltages.append(raw * 0.001)
        
        avg_cell_v = struct.unpack_from('<H', data_section, 68)[0] * 0.001
        volt_delta = struct.unpack_from('<H', data_section, 70)[0] * 0.001
        mos_temp = struct.unpack_from('<h', data_section, 138)[0] * 0.1
        bat_voltage = struct.unpack_from('<i', data_section, 144)[0] * 0.001
        bat_current = struct.unpack_from('<i', data_section, 152)[0] * 0.001
        bat_temp1 = struct.unpack_from('<h', data_section, 156)[0] * 0.1
        bat_temp2 = struct.unpack_from('<h', data_section, 158)[0] * 0.1
        soc = data_section[167]
        
        results.append({
            "protocol": "JK-BMS Custom (300-byte)",
            "metrics": {
                "voltage": bat_voltage,
                "current": bat_current,
                "soc": soc,
                "temp1": bat_temp1,
                "temp2": bat_temp2,
                "mos_temp": mos_temp,
                "avg_cell_v": avg_cell_v,
                "volt_delta": volt_delta,
                "cell_voltages": cell_voltages[:16]
            }
        })
    
    return results

def try_parse_jk_5aa5(data):
    """Try to parse data as JK-BMS with 5AA5 frame delimiter."""
    if not data:
        return None
    
    delimiter = bytes([0x5A, 0xA5])
    if delimiter not in data:
        return None
    
    # Split by delimiter
    parts = data.split(delimiter)
    results = []
    
    for part in parts:
        if len(part) < 10:
            continue
        
        frame_type = (part[0] << 8) | part[1]
        length = part[2]
        
        if len(part) < 3 + length:
            continue
        
        frame_data = part[3:3+length]
        
        # Parse based on frame type
        if frame_type == 0x3982 and length > 0:
            # Cell voltages
            cells = []
            for i in range(0, len(frame_data), 3):
                if i + 2 < len(frame_data):
                    cell_num = frame_data[i]
                    voltage = (frame_data[i+1] << 8) | frame_data[i+2]
                    cells.append(voltage * 0.001)
            
            if cells:
                results.append({
                    "protocol": "JK-BMS 5AA5 (cell voltages)",
                    "metrics": {
                        "cell_voltages": cells
                    }
                })
        
        elif frame_type == 0x0582 and length > 0:
            # Runtime data
            metrics = {}
            if len(frame_data) >= 4:
                pack_v = (frame_data[0] << 8) | frame_data[1]
                metrics['pack_voltage'] = pack_v * 0.01
                
                current = (frame_data[2] << 8) | frame_data[3]
                if current >= 0x8000:
                    current -= 0x10000
                metrics['current'] = current * 0.01
            
            if len(frame_data) >= 5:
                metrics['soc'] = frame_data[4]
            
            if len(frame_data) >= 7:
                metrics['temp1'] = frame_data[5] * 0.1
                metrics['temp2'] = frame_data[6] * 0.1
            
            if metrics:
                results.append({
                    "protocol": "JK-BMS 5AA5 (runtime)",
                    "metrics": metrics
                })
    
    return results

def main():
    print("=" * 80)
    print("COMPREHENSIVE BATTERY PROTOCOL DECODER")
    print("=" * 80)
    
    all_results = []
    
    for port in SERIAL_PORTS:
        print(f"\n{'='*80}")
        print(f"Port: {port}")
        print(f"{'='*80}")
        
        for baud in [9600, 19200, 115200]:
            print(f"\n--- {baud} baud ---")
            
            data = read_serial_data(port, baud)
            if not data or len(data) == 0:
                print(f"  No data")
                continue
            
            print(f"  Received {len(data)} bytes")
            
            # Try JK custom protocol (300-byte)
            results = try_parse_jk_custom(data)
            if results:
                for r in results:
                    print(f"  ✓ {r['protocol']}: {r['metrics']}")
                    all_results.append({**r, "port": port, "baud": baud})
            
            # Try JK 5AA5 protocol
            results = try_parse_jk_5aa5(data)
            if results:
                for r in results:
                    print(f"  ✓ {r['protocol']}: {r['metrics']}")
                    all_results.append({**r, "port": port, "baud": baud})
            
            # Try Modbus profiles
            from battery_profiles import ALL_BATTERY_PROFILES
            for name, profile in ALL_BATTERY_PROFILES.items():
                if profile.baudrate == baud:
                    results = try_parse_modbus(data, profile)
                    if results:
                        for r in results:
                            print(f"  ✓ {name}: {r['metrics']}")
                            all_results.append({**r, "port": port, "baud": baud, "profile": name})
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total valid readings: {len(all_results)}")
    for r in all_results:
        print(f"  {r['port']} baud={r['baud']}: {r['protocol']} -> {r['metrics']}")

if __name__ == "__main__":
    main()
