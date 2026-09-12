#!/usr/bin/env python3
"""
Aggressive Serial Scanner
Listens for ANY data on serial ports and tries all possible configurations.
"""
import serial
import time
import struct
import sys

SERIAL_PORTS = ["/dev/ttyUSB0", "/dev/ttyUSB2"]
BAUD_RATES = [1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400, 56000, 57600, 115200, 128000, 230400, 256000]
ADDRESSES = list(range(1, 20))
PARITIES = ["N", "E", "O"]
STOPBITS = [1, 2]

def listen_passive(port, baud, parity="N", stopbits=1, duration=3):
    """Listen for any data without sending anything."""
    try:
        ser = serial.Serial(port, baud, timeout=0.1, parity=parity, stopbits=stopbits)
        start = time.time()
        data = b""
        while time.time() - start < duration:
            if ser.in_waiting > 0:
                data += ser.read(ser.in_waiting)
            time.sleep(0.01)
        ser.close()
        if data:
            return data
    except:
        pass
    return None

def send_modbus_query(port, baud, addr, parity="N", stopbits=1, register=0, count=10):
    """Send a Modbus query and return response."""
    try:
        ser = serial.Serial(port, baud, timeout=0.3, parity=parity, stopbits=stopbits)
        
        # Build Modbus query
        query = struct.pack(">BBHH", addr, 0x03, register, count)
        
        # Calculate CRC
        crc = 0xFFFF
        for b in query:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        query += struct.pack("<H", crc)
        
        ser.write(query)
        time.sleep(0.2)
        response = ser.read(100)
        ser.close()
        return response
    except:
        return None

def main():
    print("=" * 80)
    print("AGGRESSIVE SERIAL SCANNER")
    print("=" * 80)
    
    found_any = False
    
    for port in SERIAL_PORTS:
        print(f"\n{'='*80}")
        print(f"Port: {port}")
        print(f"{'='*80}")
        
        # Passive listen at each baud rate
        print("\n--- Passive Listen (3 seconds each) ---")
        for baud in BAUD_RATES:
            data = listen_passive(port, baud, duration=1)
            if data and len(data) > 0:
                print(f"  baud={baud}: {len(data)} bytes: {data[:50].hex()}")
                found_any = True
        
        # Active Modbus scan
        print("\n--- Active Modbus Scan ---")
        for baud in BAUD_RATES:
            for addr in ADDRESSES:
                for register in [0, 0x1000, 0x1200, 0x1290]:
                    for parity in PARITIES:
                        for stopbits in STOPBITS:
                            response = send_modbus_query(port, baud, addr, parity, stopbits, register, 10)
                            if response and len(response) >= 5:
                                # Check if it looks like a valid response
                                if response[0] == addr or (response[1] in [0x03, 0x04, 0x83]):
                                    print(f"  RESPONSE: baud={baud} addr={addr} reg=0x{register:04X} parity={parity} stop={stopbits}: {len(response)} bytes: {response.hex()[:100]}")
                                    found_any = True
        
        # Try function code 0x04 (read input registers)
        print("\n--- Function Code 0x04 (Read Input Registers) ---")
        for baud in BAUD_RATES:
            for addr in ADDRESSES[:5]:
                try:
                    ser = serial.Serial(port, baud, timeout=0.3)
                    query = struct.pack(">BBHH", addr, 0x04, 0, 10)
                    crc = 0xFFFF
                    for b in query:
                        crc ^= b
                        for _ in range(8):
                            if crc & 1:
                                crc = (crc >> 1) ^ 0xA001
                            else:
                                crc >>= 1
                    query += struct.pack("<H", crc)
                    ser.write(query)
                    time.sleep(0.2)
                    response = ser.read(100)
                    ser.close()
                    if response and len(response) > 0:
                        print(f"  RESPONSE: baud={baud} addr={addr}: {len(response)} bytes: {response.hex()[:100]}")
                        found_any = True
                except:
                    pass
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    if not found_any:
        print("No data detected on any port at any baud rate.")
        print("Possible issues:")
        print("  1. Wrong wiring (check A/B polarity)")
        print("  2. BMS not powered on")
        print("  3. Wrong protocol selected on BMS")
        print("  4. Adapter not properly connected")
        print("  5. Baud rate mismatch")
    else:
        print("Found data! Check output above for details.")

if __name__ == "__main__":
    main()
