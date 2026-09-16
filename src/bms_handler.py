#!/usr/bin/env python3
"""JK-BMS Protocol Handler - 5AA5 proprietary framing for JK-PB series"""
import struct, time, logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FRAME_CONFIG_READ=0x01; FRAME_RUNTIME_DATA=0x02; FRAME_DEVICE_INFO=0x03
FRAME_CONFIG_WRITE=0x04; FRAME_SYSTEM_LOG=0x05; FRAME_FAULT_INFO=0x06

FRAME_NAMES={0x01:"Config",0x02:"Runtime",0x03:"DeviceInfo",0x04:"ConfigWrite",0x05:"SystemLog",0x06:"Fault"}

HEADER=bytes([0x55,0xAA,0xEB,0x90])

def calculate_checksum(frame:bytes)->int:return sum(frame[0:299])&0xFF

def build_query(frame_code:int,counter:int=0)->bytes:
    frame=bytearray(300);frame[0:4]=HEADER;frame[4]=frame_code;frame[5]=counter
    frame[299]=calculate_checksum(frame);return bytes(frame)

def calc_crc16(data:bytes)->int:
    crc=0xFFFF
    for b in data:
        crc^=b
        for _ in range(8):
            if crc&1:crc=(crc>>1)^0xA001
            else:crc>>=1
    return crc

def build_modbus_trigger()->bytes:
    q=bytes([0x01,0x06,0x00,0x20,0x00,0x05]);c=calc_crc16(q);return q+bytes([c&0xFF,c>>8])

def parse_frame(frame:bytes)->Optional[Dict]:
    if len(frame)!=300 or frame[0:4]!=HEADER:return None
    if frame[299]!=calculate_checksum(frame):return None
    return{"frame_code":frame[4],"frame_name":FRAME_NAMES.get(frame[4],"Unknown"),"counter":frame[5],"data":frame[6:299]}

def parse_runtime_data(data: bytes) -> Dict:
    """Parse runtime frame 0x02 for JK-PB V19 (firmware V19.09).
    
    The master BMS frame contains cell data for all connected slaves.
    Layout:
      [0:32]   Cell voltages 1-16 (master): u16 LE, ×0.001V
      [32:64]  Cell voltages 17-32 (slave): u16 LE, ×0.001V
      [64:66]  Delimiter: 0xFFFF
      [68:70]  Avg cell voltage: u16 LE, ×0.001V
      [70:72]  Cell delta: u16 LE, ×0.001V
      [72:74]  Current: i16 LE, ×0.001A (+ = charging)
      [74:76]  SOC: u16 LE, %
      [86:88]  Temp1: i16 LE, ×0.1°C
      [88:90]  Temp2: i16 LE, ×0.1°C
    """
    r = {}
    
    # Cell voltages 1-16 (master battery)
    cells = []
    for i in range(16):
        raw = struct.unpack_from('<H', data, i * 2)[0]
        cells.append(round(raw * 0.001, 3))
    r['cell_voltages'] = cells
    
    # Cell voltages 17-32 (slave batteries, if present in same frame)
    cells_17_32 = []
    for i in range(16, 32):
        raw = struct.unpack_from('<H', data, i * 2)[0]
        cells_17_32.append(round(raw * 0.001, 3))
    r['cell_voltages_17_32'] = cells_17_32
    
    # Average cell voltage
    r['avg_cell_v'] = struct.unpack_from('<H', data, 68)[0] * 0.001
    
    # Cell delta (mV)
    r['volt_delta'] = struct.unpack_from('<H', data, 70)[0] * 0.001
    
    # Current (signed, ×0.001A)
    r['current'] = struct.unpack_from('<h', data, 72)[0] * 0.001
    
    # SOC (%)
    r['soc'] = struct.unpack_from('<H', data, 74)[0]
    
    # Temperatures (×0.1°C)
    r['temp1'] = struct.unpack_from('<h', data, 86)[0] * 0.1
    r['temp2'] = struct.unpack_from('<h', data, 88)[0] * 0.1
    
    # Pack voltage = sum of valid cell voltages
    valid_cells = [c for c in cells if c > 0.1]
    r['pack_v'] = round(sum(valid_cells), 2)
    
    # Power
    r['power'] = round(r['pack_v'] * r['current'], 2)
    
    # Total cell count = master + slave cells
    total_cells = valid_cells + [c for c in cells_17_32 if c > 0.1]
    r['cell_count'] = len(total_cells)
    
    # Alias for API compatibility
    r['voltage'] = r['pack_v']
    
    return r

def parse_config_data(data:bytes)->Dict:
    r={}
    # Config offsets based on Foroxon protocol research
    r['cell_uv']=struct.unpack_from('<I',data,0)[0]*0.001  # Cell undervoltage protection (mV→V)
    r['cell_uvpr']=struct.unpack_from('<I',data,4)[0]*0.001  # Recovery voltage
    r['cell_ov']=struct.unpack_from('<I',data,8)[0]*0.001  # Overcharge protection
    r['cell_ovpr']=struct.unpack_from('<I',data,12)[0]*0.001  # Recovery
    r['balance_trig']=struct.unpack_from('<I',data,16)[0]*0.001  # Balance trigger delta
    r['soc_100_v']=struct.unpack_from('<I',data,20)[0]*0.001  # SOC 100% voltage
    r['soc_0_v']=struct.unpack_from('<I',data,24)[0]*0.001  # SOC 0% voltage
    r['charge_current']=struct.unpack_from('<I',data,40)[0]*0.001  # Continuous charge current (mA→A)
    r['discharge_current']=struct.unpack_from('<I',data,56)[0]*0.001  # Continuous discharge current
    r['charge_otp']=struct.unpack_from('<i',data,76)[0]*0.1  # Charge over-temp
    r['charge_otpr']=struct.unpack_from('<i',data,80)[0]*0.1  # Recovery
    r['discharge_otp']=struct.unpack_from('<i',data,84)[0]*0.1  # Discharge over-temp
    r['cell_count_str']=struct.unpack_from('<I',data,108)[0]  # Cell count
    return r

def parse_device_info(data:bytes)->Dict:
    r={}
    # Device info frame contains model, firmware version, serial number
    # Extract as strings from various offsets
    try:
        r['model']=data[0:16].decode('ascii',errors='ignore').strip('\x00')
        r['firmware']=data[16:32].decode('ascii',errors='ignore').strip('\x00')
        r['serial']=data[32:48].decode('ascii',errors='ignore').strip('\x00')
    except:
        pass
    r['raw']=data[:50].hex()
    return r

def parse_fault_info(data:bytes)->Dict:
    r={}
    # Fault bitmap - each bit represents a fault condition
    faults=[]
    fault_names=[
        "Cell UV","Cell OV","Pack UV","Pack OV","Charge OC","Discharge OC",
        "Charge OT","Discharge OT","Charge UT","Discharge UT","MOS OT","MOS UT",
        "Short Circuit","Balance Wire","Software Lock","Hardware Fault"
    ]
    fault_bits=struct.unpack_from('<I',data,0)[0]
    for i,name in enumerate(fault_names):
        if fault_bits&(1<<i):
            faults.append(name)
    r['faults']=faults
    r['fault_count']=len(faults)
    r['raw']=data[:20].hex()
    return r

def decode_from_raw(raw_data:bytes)->List[Dict]:
    frames=[];pos=0
    while pos<len(raw_data)-4:
        if raw_data[pos:pos+4]==HEADER:
            frame=raw_data[pos:pos+300]
            if len(frame)==300:
                parsed=parse_frame(frame)
                if parsed:frames.append(parsed)
                pos+=300
            else:pos+=1
        else:pos+=1
    return frames
