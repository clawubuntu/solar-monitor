#!/usr/bin/env python3
"""
Unknown Protocol Decoder
A systematic framework for reverse engineering unknown serial protocols.

Based on methodology from:
- Berkner Tech: "Reverse Engineering an Unknown Binary Protocol"
- /dev/ttyS0: "Reverse Engineering Serial Ports"
- Hackaday: Protocol reverse engineering techniques
- Solvetronix: Industrial protocol reconstruction

Usage:
    python3 unknown_protocol_decoder.py --port /dev/ttyUSB0
    python3 unknown_protocol_decoder.py --port /dev/ttyUSB0 --baud 115200
    python3 unknown_protocol_decoder.py --capture-file data.bin --analyze
"""

import serial
import time
import struct
import sys
import os
import argparse
from collections import Counter, defaultdict
from typing import List, Dict, Tuple, Optional
import json


class SerialCapture:
    """Capture raw serial data."""
    
    def __init__(self, port: str, baud: int = 115200, timeout: float = 0.5):
        self.port = port
        self.baud = baud
        self.timeout = timeout
    
    def capture(self, duration: float = 5.0) -> bytes:
        """Capture raw data for a specified duration."""
        try:
            ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            start = time.time()
            data = b""
            while time.time() - start < duration:
                if ser.in_waiting > 0:
                    data += ser.read(ser.in_waiting)
                time.sleep(0.01)
            ser.close()
            return data
        except Exception as e:
            print(f"Error capturing from {self.port}: {e}")
            return b""
    
    def capture_with_trigger(self, trigger: bytes, duration: float = 5.0) -> bytes:
        """Capture data after a trigger is received."""
        try:
            ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            start = time.time()
            data = b""
            triggered = False
            while time.time() - start < duration:
                if ser.in_waiting > 0:
                    byte = ser.read(1)
                    if not triggered:
                        if byte == trigger[:1]:
                            triggered = True
                            data = byte
                    else:
                        data += byte
                time.sleep(0.01)
            ser.close()
            return data
        except Exception as e:
            print(f"Error capturing from {self.port}: {e}")
            return b""
    
    def capture_at_bauds(self, baud_rates: List[int], duration: float = 2.0) -> Dict[int, bytes]:
        """Capture data at multiple baud rates."""
        results = {}
        for baud in baud_rates:
            print(f"  Capturing at {baud} baud...")
            self.baud = baud
            data = self.capture(duration)
            if data and len(data) > 0:
                results[baud] = data
                print(f"    Got {len(data)} bytes")
        return results


class PatternAnalyzer:
    """Analyze captured data for patterns."""
    
    def __init__(self, data: bytes):
        self.data = data
    
    def find_repeated_patterns(self, min_len: int = 2, max_len: int = 4) -> List[Tuple[bytes, int]]:
        """Find repeated byte patterns that could be frame delimiters."""
        patterns = Counter()
        
        for length in range(min_len, max_len + 1):
            for i in range(len(self.data) - length):
                pattern = self.data[i:i+length]
                patterns[pattern] += 1
        
        # Filter to patterns that appear multiple times
        repeated = [(p, c) for p, c in patterns.items() if c >= 3]
        repeated.sort(key=lambda x: x[1], reverse=True)
        return repeated
    
    def find_frame_candidates(self, delimiter: bytes) -> List[bytes]:
        """Split data by a candidate delimiter and return frames."""
        frames = self.data.split(delimiter)
        return [f for f in frames if len(f) > 0]
    
    def byte_frequency(self) -> Counter:
        """Count frequency of each byte value."""
        return Counter(self.data)
    
    def byte_positions(self, byte_val: int) -> List[int]:
        """Find all positions of a specific byte value."""
        return [i for i, b in enumerate(self.data) if b == byte_val]
    
    def entropy(self, data: Optional[bytes] = None) -> float:
        """Calculate Shannon entropy of data."""
        if data is None:
            data = self.data
        
        if len(data) == 0:
            return 0.0
        
        import math
        freq = Counter(data)
        entropy = 0.0
        for count in freq.values():
            p = count / len(data)
            if p > 0:
                entropy -= p * math.log2(p)
        
        return entropy
    
    def find_fixed_positions(self, frames: List[bytes]) -> List[Tuple[int, int]]:
        """
        Find positions where the byte value is constant across all frames.
        Returns list of (position, value) tuples.
        """
        if not frames:
            return []
        
        fixed = []
        max_len = max(len(f) for f in frames)
        
        for pos in range(max_len):
            values = set()
            for frame in frames:
                if pos < len(frame):
                    values.add(frame[pos])
            if len(values) == 1:
                fixed.append((pos, values.pop()))
        
        return fixed
    
    def find_changing_positions(self, frames: List[bytes]) -> List[int]:
        """Find positions where the byte value varies across frames."""
        if not frames:
            return []
        
        changing = []
        max_len = max(len(f) for f in frames)
        
        for pos in range(max_len):
            values = set()
            for frame in frames:
                if pos < len(frame):
                    values.add(frame[pos])
            if len(values) > 1:
                changing.append(pos)
        
        return changing
    
    def guess_field_type(self, frames: List[bytes], position: int) -> str:
        """Guess the type of field at a given position."""
        values = []
        for frame in frames:
            if position < len(frame):
                values.append(frame[position])
        
        if len(values) < 2:
            return "unknown"
        
        # Check if sequential (counter)
        diffs = [values[i+1] - values[i] for i in range(len(values)-1)]
        if all(d == 1 for d in diffs):
            return "counter"
        
        # Check if constant
        if len(set(values)) == 1:
            return "constant"
        
        # Check if could be checksum (last byte)
        if position == max(len(f) for f in frames) - 1:
            return "checksum"
        
        return "data"
    
    def guess_checksum_type(self, frames: List[bytes]) -> str:
        """Guess the checksum algorithm used."""
        if not frames:
            return "unknown"
        
        # Check for simple sum8
        for frame in frames:
            if len(frame) < 2:
                continue
            payload = frame[:-1]
            checksum = frame[-1]
            
            # Sum8
            calc_sum = sum(payload) & 0xFF
            if calc_sum == checksum:
                return "sum8"
            
            # XOR
            calc_xor = 0
            for b in payload:
                calc_xor ^= b
            if calc_xor == checksum:
                return "xor8"
        
        return "unknown"


class ProtocolDecoder:
    """Main protocol decoder class."""
    
    def __init__(self):
        self.data = b""
        self.frames = []
        self.delimiter = None
        self.fields = {}
        self.checksum_type = "unknown"
    
    def load_data(self, data: bytes):
        """Load raw captured data."""
        self.data = data
        self.frames = []
        self.delimiter = None
        self.fields = {}
        self.checksum_type = "unknown"
    
    def load_file(self, filename: str):
        """Load data from a binary file."""
        with open(filename, "rb") as f:
            self.load_data(f.read())
    
    def analyze(self) -> Dict:
        """Perform full analysis of the data."""
        if not self.data:
            return {"error": "No data loaded"}
        
        print("=" * 70)
        print("UNKNOWN PROTOCOL DECODER")
        print("=" * 70)
        
        analyzer = PatternAnalyzer(self.data)
        
        results = {
            "total_bytes": len(self.data),
            "unique_bytes": len(set(self.data)),
            "byte_frequency": analyzer.byte_frequency().most_common(10),
            "repeated_patterns": analyzer.find_repeated_patterns()[:10],
            "frames": [],
        }
        
        # Print byte frequency
        print(f"\nTotal bytes: {results['total_bytes']}")
        print(f"Unique byte values: {results['unique_bytes']}")
        print(f"\nMost common bytes:")
        for byte, count in results["byte_frequency"]:
            print(f"  0x{byte:02X}: {count} ({count/len(self.data)*100:.1f}%)")
        
        # Print repeated patterns
        print(f"\nRepeated patterns (potential frame delimiters):")
        for pattern, count in results["repeated_patterns"]:
            print(f"  {pattern.hex()}: {count} occurrences")
        
        # Try to find frames
        if results["repeated_patterns"]:
            best_delimiter = results["repeated_patterns"][0][0]
            self.delimiter = best_delimiter
            print(f"\nUsing delimiter: {best_delimiter.hex()}")
            
            frames = analyzer.find_frame_candidates(best_delimiter)
            self.frames = frames
            results["frames"] = [{"length": len(f), "data": f.hex()} for f in frames[:20]]
            
            print(f"\nFound {len(frames)} frames")
            
            # Analyze frame structure
            if len(frames) >= 2:
                fixed = analyzer.find_fixed_positions(frames)
                changing = analyzer.find_changing_positions(frames)
                self.checksum_type = analyzer.guess_checksum_type(frames)
                
                print(f"\nFixed positions (header/constants):")
                for pos, val in fixed:
                    print(f"  Position {pos}: 0x{val:02X}")
                
                print(f"\nChanging positions (data fields):")
                for pos in changing[:20]:
                    field_type = analyzer.guess_field_type(frames, pos)
                    print(f"  Position {pos}: {field_type}")
                
                print(f"\nChecksum type: {self.checksum_type}")
                
                results["fixed_positions"] = fixed
                results["changing_positions"] = changing
                results["checksum_type"] = self.checksum_type
        
        return results
    
    def decode_frames(self) -> List[Dict]:
        """Attempt to decode all loaded frames."""
        if not self.frames:
            return []
        
        decoded = []
        for frame in self.frames:
            if len(frame) < 2:
                continue
            
            result = {
                "raw": frame.hex(),
                "length": len(frame),
            }
            
            # Try to identify fields
            if self.delimiter:
                result["delimiter"] = self.delimiter.hex()
            
            # Try to parse as different field types
            if len(frame) >= 4:
                result["big_endian_u16"] = struct.unpack(">H", frame[:2])[0]
                result["little_endian_u16"] = struct.unpack("<H", frame[:2])[0]
            
            if len(frame) >= 6:
                result["big_endian_u32"] = struct.unpack(">I", frame[:4])[0]
                result["little_endian_u32"] = struct.unpack("<I", frame[:4])[0]
            
            # Try to verify checksum
            if self.checksum_type == "sum8":
                payload = frame[:-1]
                calc = sum(payload) & 0xFF
                result["checksum_valid"] = calc == frame[-1]
            
            decoded.append(result)
        
        return decoded
    
    def generate_parser_code(self) -> str:
        """Generate Python parser code based on analysis."""
        if not self.frames:
            return "# No frames to parse"
        
        code = '''#!/usr/bin/env python3
"""
Auto-generated parser for unknown protocol.
Generated by Unknown Protocol Decoder.
"""

import struct
from typing import Dict, List, Optional

DELIMITER = bytes([%s])

def decode_frame(frame: bytes) -> Optional[Dict]:
    """Decode a single frame."""
    if len(frame) < %d:
        return None
    
    result = {
        "raw": frame.hex(),
        "length": len(frame),
    }
    
    # TODO: Add field parsing based on your analysis
    
    return result

def decode_all(data: bytes) -> List[Dict]:
    """Decode all frames from raw data."""
    frames = data.split(DELIMITER)
    results = []
    for frame in frames:
        if len(frame) > 0:
            decoded = decode_frame(frame)
            if decoded:
                results.append(decoded)
    return results
''' % (
            ", ".join(f"0x{b:02X}" for b in self.delimiter) if self.delimiter else "0x00",
            min(len(f) for f in self.frames) if self.frames else 0,
        )
        
        return code
    
    def interactive_mode(self):
        """Run interactive analysis mode."""
        while True:
            print("\n" + "=" * 70)
            print("INTERACTIVE MODE")
            print("=" * 70)
            print("1. Analyze data")
            print("2. Set delimiter")
            print("3. Decode frames")
            print("4. Generate parser code")
            print("5. Save analysis")
            print("6. Load new data")
            print("7. Exit")
            
            choice = input("\nChoice: ").strip()
            
            if choice == "1":
                self.analyze()
            elif choice == "2":
                delim = input("Enter delimiter (hex, e.g., 5aa5): ").strip()
                try:
                    self.delimiter = bytes.fromhex(delim)
                    print(f"Delimiter set to: {self.delimiter.hex()}")
                except Exception:
                    print("Invalid hex")
            elif choice == "3":
                decoded = self.decode_frames()
                for i, d in enumerate(decoded[:10]):
                    print(f"\nFrame {i}:")
                    for k, v in d.items():
                        print(f"  {k}: {v}")
            elif choice == "4":
                code = self.generate_parser_code()
                print(code)
            elif choice == "5":
                filename = input("Filename: ").strip()
                with open(filename, "w") as f:
                    json.dump({
                        "delimiter": self.delimiter.hex() if self.delimiter else None,
                        "frame_count": len(self.frames),
                        "data_sample": self.data[:100].hex(),
                    }, f, indent=2)
                print(f"Saved to {filename}")
            elif choice == "6":
                filename = input("Filename: ").strip()
                if os.path.exists(filename):
                    self.load_file(filename)
                    print(f"Loaded {len(self.data)} bytes from {filename}")
                else:
                    print("File not found")
            elif choice == "7":
                break
            else:
                print("Invalid choice")


class BaudRateDetector:
    """Auto-detect baud rate from serial data."""
    
    COMMON_BAUD_RATES = [
        1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400,
        56000, 57600, 115200, 128000, 230400, 256000, 460800, 921600
    ]
    
    def __init__(self, port: str):
        self.port = port
    
    def detect(self, duration: float = 2.0) -> List[int]:
        """Try common baud rates and return those that produce data."""
        valid_bauds = []
        
        for baud in self.COMMON_BAUD_RATES:
            try:
                ser = serial.Serial(self.port, baud, timeout=0.5)
                time.sleep(0.1)
                
                # Send a query (generic Modbus read)
                ser.write(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0a, 0xc5, 0xcd]))
                time.sleep(duration)
                
                data = ser.read(2000)
                ser.close()
                
                if data and len(data) > 5:
                    valid_bauds.append((baud, len(data)))
                    print(f"  {baud} baud: {len(data)} bytes received")
            except:
                pass
        
        return valid_bauds


def main():
    parser = argparse.ArgumentParser(description="Unknown Protocol Decoder")
    parser.add_argument("--port", help="Serial port (e.g., /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--capture-duration", type=float, default=5.0, help="Capture duration in seconds")
    parser.add_argument("--capture-file", help="Load captured data from file")
    parser.add_argument("--analyze", action="store_true", help="Analyze captured data")
    parser.add_argument("--interactive", action="store_true", help="Run interactive mode")
    parser.add_argument("--detect-baud", action="store_true", help="Auto-detect baud rate")
    parser.add_argument("--output", help="Output file for parser code")
    
    args = parser.parse_args()
    
    decoder = ProtocolDecoder()
    
    # Load data from file if specified
    if args.capture_file:
        print(f"Loading data from {args.capture_file}...")
        decoder.load_file(args.capture_file)
        print(f"Loaded {len(decoder.data)} bytes")
    
    # Capture from serial port
    elif args.port:
        if args.detect_baud:
            print("Detecting baud rate...")
            detector = BaudRateDetector(args.port)
            valid_bauds = detector.detect()
            if valid_bauds:
                print(f"\nValid baud rates: {[b for b, _ in valid_bauds]}")
                baud = valid_bauds[0][0]
                print(f"Using {baud} baud")
            else:
                print("No valid baud rate detected")
                return
        else:
            baud = args.baud
        
        print(f"Capturing from {args.port} at {baud} baud...")
        capture = SerialCapture(args.port, baud)
        data = capture.capture(args.capture_duration)
        decoder.load_data(data)
        print(f"Captured {len(data)} bytes")
    
    # Analyze
    if args.analyze or decoder.data:
        results = decoder.analyze()
        
        # Save parser code if requested
        if args.output:
            code = decoder.generate_parser_code()
            with open(args.output, "w") as f:
                f.write(code)
            print(f"\nParser code saved to {args.output}")
    
    # Interactive mode
    if args.interactive:
        decoder.interactive_mode()


if __name__ == "__main__":
    main()
