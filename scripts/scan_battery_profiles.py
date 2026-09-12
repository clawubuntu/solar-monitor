#!/usr/bin/env python3
"""
Battery Profile Scanner
Iterates through all battery profiles to find readable data.
"""
import serial
import time
import struct
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from battery_profiles import ALL_BATTERY_PROFILES
from modbus_handler import get_profile, ModbusRTU

SERIAL_PORTS = ["/dev/ttyUSB0", "/dev/ttyUSB2"]
TIMEOUT = 0.3
ADDRESSES = [1, 2, 3, 4, 5, 6, 7, 8]

def test_modbus_profile(port, profile):
    """Test a Modbus RTU profile."""
    results = []
    baud = profile.baudrate
    slave_id = profile.slave_id
    
    # Get register addresses to test
    registers = profile.registers
    if not registers:
        return results
    
    # Test first few register addresses
    test_addrs = [r.address for r in registers[:3]]
    
    for addr in test_addrs:
        try:
            ser = serial.Serial(port, baud, timeout=TIMEOUT)
            # Build Modbus read holding registers request
            query = struct.pack(">BBHH", slave_id, 0x03, addr, 10)
            query += ModbusRTU.calculate_crc(query)
            ser.write(query)
            time.sleep(TIMEOUT)
            response = ser.read(100)
            ser.close()
            
            if len(response) > 0:
                # Check for valid Modbus response
                if len(response) >= 5 and response[0] == slave_id:
                    if response[1] == 0x03:
                        # Valid read response
                        byte_count = response[2]
                        if byte_count > 0 and len(response) >= 3 + byte_count + 2:
                            results.append({
                                "port": port,
                                "baud": baud,
                                "address": slave_id,
                                "register": addr,
                                "bytes": len(response),
                                "data": response.hex(),
                                "type": "Modbus RTU"
                            })
                    elif response[1] & 0x80:
                        # Exception response - still means device is there
                        results.append({
                            "port": port,
                            "baud": baud,
                            "address": slave_id,
                            "register": addr,
                            "bytes": len(response),
                            "data": response.hex(),
                            "type": "Modbus Exception"
                        })
        except Exception as e:
            pass
    
    return results

def test_jk_custom_protocol(port, baud=115200):
    """Test JK-BMS custom 300-byte frame protocol."""
    results = []
    
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
        
        # Build JK-BMS runtime data query
        frame = bytearray(300)
        frame[0:4] = bytes([0x55, 0xAA, 0xEB, 0x90])
        frame[4] = 0x02  # Runtime data
        frame[5] = 0     # Counter
        checksum = sum(frame[0:299]) & 0xFF
        frame[299] = checksum
        
        ser.write(bytes(frame))
        time.sleep(0.5)
        response = ser.read(300)
        ser.close()
        
        if len(response) >= 4:
            if response[0:4] == bytes([0x55, 0xAA, 0xEB, 0x90]):
                results.append({
                    "port": port,
                    "baud": baud,
                    "address": 1,
                    "register": 0,
                    "bytes": len(response),
                    "data": response.hex()[:100] + "...",
                    "type": "JK-BMS Custom"
                })
    except Exception as e:
        pass
    
    return results

def main():
    print("=" * 80)
    print("BATTERY PROFILE SCANNER")
    print("=" * 80)
    
    all_results = []
    
    for port in SERIAL_PORTS:
        print(f"\n{'='*80}")
        print(f"Testing port: {port}")
        print(f"{'='*80}")
        
        # Test JK-BMS custom protocol first
        print(f"\n--- JK-BMS Custom Protocol (115200 baud) ---")
        results = test_jk_custom_protocol(port, 115200)
        if results:
            print(f"  FOUND: {results[0]}")
            all_results.extend(results)
        else:
            print(f"  No response at 115200")
        
        # Also try 9600
        print(f"\n--- JK-BMS Custom Protocol (9600 baud) ---")
        results = test_jk_custom_protocol(port, 9600)
        if results:
            print(f"  FOUND: {results[0]}")
            all_results.extend(results)
        else:
            print(f"  No response at 9600")
        
        # Test each Modbus profile
        for name, profile in ALL_BATTERY_PROFILES.items():
            print(f"\n--- {name} ({profile.baudrate} baud) ---")
            results = test_modbus_profile(port, profile)
            if results:
                for r in results:
                    print(f"  FOUND: addr={r['address']} reg=0x{r['register']:04X}: {r['data']}")
                all_results.extend(results)
            else:
                print(f"  No response")
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total findings: {len(all_results)}")
    for r in all_results:
        print(f"  {r['port']} baud={r['baud']} addr={r['address']} reg=0x{r['register']:04X}: {r['type']} ({r['bytes']} bytes)")

if __name__ == "__main__":
    main()
