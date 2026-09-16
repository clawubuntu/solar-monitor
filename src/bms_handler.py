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

def parse_runtime_data(data:bytes)->Dict:
    r={}
    # Cell voltages 1-16 at offsets 0-31 (frame 6-37)
    r['cell_voltages']=[round(struct.unpack_from('<H',data,i*2)[0]*0.001,3)for i in range(16)]
    # Cell voltages 17-32 at offsets 32-63 (frame 38-69)
    r['cell_voltages_17_32']=[round(struct.unpack_from('<H',data,i*2)[0]*0.001,3)for i in range(16,32)]
    # Average cell voltage at offset 68 (frame 74)
    r['avg_cell_v']=struct.unpack_from('<H',data,68)[0]*0.001
    # Voltage delta at offset 70 (frame 76)
    r['volt_delta']=struct.unpack_from('<H',data,70)[0]*0.001
    # SOC at offset 72 (frame 78)
    r['soc']=struct.unpack_from('<H',data,72)[0]
    # Current at offset 74 (frame 80) - signed, scale 0.01A
    r['current']=struct.unpack_from('<h',data,74)[0]*0.01
    # Pack voltage at offset 76 (frame 82) - scale 0.01V
    r['voltage']=struct.unpack_from('<H',data,76)[0]*0.01
    # Power
    r['power']=r['voltage']*r['current']
    # Temperature 1 at offset 78 (frame 84) - signed, scale 0.1°C
    r['temp1']=struct.unpack_from('<h',data,78)[0]*0.1
    # Temperature 2 at offset 80 (frame 86) - signed, scale 0.1°C
    r['temp2']=struct.unpack_from('<h',data,80)[0]*0.1
    # MOS temp at offset 82 (frame 88)
    r['mos_temp']=struct.unpack_from('<h',data,82)[0]*0.1
    # Remaining capacity at offset 84 (frame 90) - scale 0.01Ah
    r['remaining_capacity']=struct.unpack_from('<H',data,84)[0]*0.01
    # Full capacity at offset 86 (frame 92) - scale 0.01Ah
    r['full_capacity']=struct.unpack_from('<H',data,86)[0]*0.01
    # Cycle count at offset 88 (frame 94)
    r['cycle_count']=struct.unpack_from('<H',data,88)[0]
    # Cell count from number of non-zero cell voltages
    r['cell_count']=sum(1 for v in r['cell_voltages'] if v > 0.1)
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
