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
    r['cell_voltages']=[round(struct.unpack_from('<H',data,i*2)[0]*0.001,3)for i in range(16)]
    r['cell_voltages_17_32']=[round(struct.unpack_from('<H',data,i*2)[0]*0.001,3)for i in range(16,32)]
    r['avg_cell_v']=struct.unpack_from('<H',data,68)[0]*0.001
    r['soc']=struct.unpack_from('<H',data,70)[0]
    r['current']=struct.unpack_from('<h',data,72)[0]*0.01
    r['pack_v']=struct.unpack_from('<H',data,74)[0]*0.01
    r['temp1']=struct.unpack_from('<h',data,76)[0]*0.1
    r['temp2']=struct.unpack_from('<h',data,78)[0]*0.1
    r['power']=r['pack_v']*r['current']
    return r

def parse_config_data(data:bytes)->Dict:
    r={};r['raw']=data[:50].hex();return r

def parse_device_info(data:bytes)->Dict:
    r={};r['raw']=data[:50].hex();return r

def parse_fault_info(data:bytes)->Dict:
    r={};r['raw']=data[:50].hex();return r

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
