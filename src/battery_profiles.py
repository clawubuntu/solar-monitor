#!/usr/bin/env python3
"""
Battery Communication Protocols
Comprehensive register maps and protocol handlers for common BMS/inverter batteries.

Supported protocols:
1. JK-BMS (Jikong) - Custom 300-byte frame protocol
2. JK-PB Series - Modbus RTU RS485
3. Pylontech - Modbus RTU RS485 (CAN-to-Modbus adaptation)
4. Growatt BMS - Modbus RTU RS485
5. Deye BMS - Modbus RTU RS485
6. SolaX BMS - Modbus RTU RS485 (page-based addressing)
7. GoodWe BMS - Modbus RTU RS485
8. EG4 BMS - Modbus RTU RS485
9. Ruixu BMS - Modbus RTU RS485
10. Seplos BMS - Modbus RTU RS485
11. PACE BMS - Modbus RTU RS485
12. Must BMS - Modbus RTU RS485
13. SRNE BMS - Modbus RTU RS485
14. Victron BMS - VE.Direct / VE.Can
15. LUXpower BMS - CAN bus
16. Megarevo BMS - CAN bus
17. Voltronic BMS - Modbus RTU RS485
"""

from modbus_handler import ModbusRegister, InverterProfile

# ============================================================================
# JK-BMS (Jikong) - Custom 300-byte frame protocol
# Used by: JK-BD, JK-B2A series (non-PB)
# Physical: TTL UART (3.3V) on "RS485" port
# ============================================================================
# Handled by jk_bms_handler.py - not Modbus

# ============================================================================
# JK-PB Series - Modbus RTU RS485
# Used by: JK-PB2A16S20P, JK-PB2A8S-10P, etc.
# Physical: Genuine RS-485 differential
# Baud: 9600 default
# ============================================================================
JK_PB_PROFILE = InverterProfile(
    name="JK-PB2A16S20P",
    manufacturer="JK",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Cell voltages (0x1200-0x120F) - 16 registers
        ModbusRegister(0x1200, "cell_01_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1201, "cell_02_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1202, "cell_03_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1203, "cell_04_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1204, "cell_05_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1205, "cell_06_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1206, "cell_07_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1207, "cell_08_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1208, "cell_09_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x1209, "cell_10_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x120A, "cell_11_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x120B, "cell_12_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x120C, "cell_13_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x120D, "cell_14_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x120E, "cell_15_v", "V", scale=0.001, category="battery"),
        ModbusRegister(0x120F, "cell_16_v", "V", scale=0.001, category="battery"),
        # Battery voltage (0x1290)
        ModbusRegister(0x1290, "voltage", "V", scale=0.001, category="battery"),
        # Battery current (0x1294)
        ModbusRegister(0x1294, "current", "A", scale=0.001, category="battery"),
        # SOC (0x12A6)
        ModbusRegister(0x12A6, "soc", "%", scale=1, category="battery"),
        # Temperature (0x12A0)
        ModbusRegister(0x12A0, "temp1", "°C", scale=0.1, category="temperature"),
        ModbusRegister(0x12A1, "temp2", "°C", scale=0.1, category="temperature"),
    ]
)

# ============================================================================
# Pylontech - Modbus RTU RS485
# Used by: US2000, US3000, US5000, Force H2, etc.
# Physical: RS-485
# Baud: 9600 default
# Protocol: CAN-to-Modbus adaptation
# ============================================================================
PYLONTECH_PROFILE = InverterProfile(
    name="Pylontech US3000C",
    manufacturer="Pylontech",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Charge voltage limit (0x0100)
        ModbusRegister(0x0100, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Charge current limit (0x0101)
        ModbusRegister(0x0101, "charge_current_limit", "A", scale=0.1, category="battery"),
        # Discharge current limit (0x0102)
        ModbusRegister(0x0102, "discharge_current_limit", "A", scale=0.1, category="battery"),
        # SOC (0x0110)
        ModbusRegister(0x0110, "soc", "%", scale=1, category="battery"),
        # SOH (0x0111)
        ModbusRegister(0x0111, "soh", "%", scale=1, category="battery"),
        # Module voltage (0x0120)
        ModbusRegister(0x0120, "voltage", "V", scale=0.01, category="battery"),
        # Total current (0x0121)
        ModbusRegister(0x0121, "current", "A", scale=0.1, category="battery"),
        # Average temperature (0x0122)
        ModbusRegister(0x0122, "temp", "°C", scale=0.1, category="temperature"),
        # Protection flags (0x0130)
        ModbusRegister(0x0130, "protection_flags", "", scale=1, category="status"),
        # Alarm flags (0x0131)
        ModbusRegister(0x0131, "alarm_flags", "", scale=1, category="status"),
        # Module count (0x0132)
        ModbusRegister(0x0132, "module_count", "", scale=1, category="status"),
        # Request/control flags (0x0140)
        ModbusRegister(0x0140, "control_flags", "", scale=1, category="status"),
        # Manufacturer (0x0150)
        ModbusRegister(0x0150, "manufacturer", "", scale=1, category="info"),
    ]
)

# ============================================================================
# Growatt BMS - Modbus RTU RS485
# Used by: Growatt ARK, AXE series batteries
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
GROWATT_BMS_PROFILE = InverterProfile(
    name="Growatt ARK 10.2kWh",
    manufacturer="Growatt",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x107)
        ModbusRegister(0x107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x108)
        ModbusRegister(0x108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x109)
        ModbusRegister(0x109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x10A)
        ModbusRegister(0x10A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x10B)
        ModbusRegister(0x10B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x10C)
        ModbusRegister(0x10C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x10D)
        ModbusRegister(0x10D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x10E)
        ModbusRegister(0x10E, "status", "", scale=1, category="status"),
        # Alarm (0x10F)
        ModbusRegister(0x10F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# Deye BMS - Modbus RTU RS485
# Used by: Deye RW, SEA series batteries
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
DEYE_BMS_PROFILE = InverterProfile(
    name="Deye RW 10.2kWh",
    manufacturer="Deye",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# SolaX BMS - Modbus RTU RS485
# Used by: SolaX X1-Hybrid, X3-Hybrid, X1-Boost, X3-AC
# Physical: RS-485
# Baud: 19200 default
# Note: Uses page-based addressing (page << 8 | register)
# ============================================================================
SOLAX_BMS_PROFILE = InverterProfile(
    name="SolaX X3-Hybrid",
    manufacturer="SolaX",
    protocol="modbus_rtu",
    baudrate=19200,
    slave_id=1,
    registers=[
        # Battery voltage (0x0400)
        ModbusRegister(0x0400, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0401)
        ModbusRegister(0x0401, "current", "A", scale=0.1, category="battery"),
        # Battery power (0x0402)
        ModbusRegister(0x0402, "power", "W", scale=1, category="battery"),
        # SOC (0x0403)
        ModbusRegister(0x0403, "soc", "%", scale=1, category="battery"),
        # SOH (0x0404)
        ModbusRegister(0x0404, "soh", "%", scale=1, category="battery"),
        # Battery temperature (0x0405)
        ModbusRegister(0x0405, "temp", "°C", scale=0.1, category="temperature"),
        # Charge voltage limit (0x0406)
        ModbusRegister(0x0406, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0407)
        ModbusRegister(0x0407, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0408)
        ModbusRegister(0x0408, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0409)
        ModbusRegister(0x0409, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Cell max voltage (0x040A)
        ModbusRegister(0x040A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x040B)
        ModbusRegister(0x040B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x040C)
        ModbusRegister(0x040C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x040D)
        ModbusRegister(0x040D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x040E)
        ModbusRegister(0x040E, "status", "", scale=1, category="status"),
        # Alarm (0x040F)
        ModbusRegister(0x040F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# GoodWe BMS - Modbus RTU RS485
# Used by: GoodWe SBP, ARS series batteries
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
GOODWE_BMS_PROFILE = InverterProfile(
    name="GoodWe SBP 10.1kWh",
    manufacturer="GoodWe",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# EG4 BMS - Modbus RTU RS485
# Used by: EG4 LL, PowerPro series batteries
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
EG4_BMS_PROFILE = InverterProfile(
    name="EG4 LL 10.2kWh",
    manufacturer="EG4",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# Ruixu BMS - Modbus RTU RS485
# Used by: Ruixu Iron, Iron-X series batteries
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
RUIXU_BMS_PROFILE = InverterProfile(
    name="Ruixu Iron 10kWh",
    manufacturer="Ruixu",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# Seplos BMS - Modbus RTU RS485
# Used by: Seplos V3, V4 series batteries
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
SEPLOS_BMS_PROFILE = InverterProfile(
    name="Seplos V3 10kWh",
    manufacturer="Seplos",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# PACE BMS - Modbus RTU RS485
# Used by: PACE PACE2000, PACE3000 series
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
PACE_BMS_PROFILE = InverterProfile(
    name="PACE PACE2000",
    manufacturer="PACE",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# Must BMS - Modbus RTU RS485
# Used by: Must PH1800, PV1800 series
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
MUST_BMS_PROFILE = InverterProfile(
    name="Must PH1800",
    manufacturer="Must",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# SRNE BMS - Modbus RTU RS485
# Used by: SRNE ML, MC series
# Physical: RS-485
# Baud: 9600 default
# ============================================================================
SRNE_BMS_PROFILE = InverterProfile(
    name="SRNE ML2440",
    manufacturer="SRNE",
    protocol="modbus_rtu",
    baudrate=9600,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# Voltronic BMS - Modbus RTU RS485
# Used by: Voltronic Axpert, MPP Solar series
# Physical: RS-485
# Baud: 2400 default
# ============================================================================
VOLTRONIC_BMS_PROFILE = InverterProfile(
    name="Voltronic Axpert 5K",
    manufacturer="Voltronic",
    protocol="modbus_rtu",
    baudrate=2400,
    slave_id=1,
    registers=[
        # Battery voltage (0x0100)
        ModbusRegister(0x0100, "voltage", "V", scale=0.1, category="battery"),
        # Battery current (0x0101)
        ModbusRegister(0x0101, "current", "A", scale=0.1, category="battery"),
        # SOC (0x0102)
        ModbusRegister(0x0102, "soc", "%", scale=1, category="battery"),
        # SOH (0x0103)
        ModbusRegister(0x0103, "soh", "%", scale=1, category="battery"),
        # Battery power (0x0104)
        ModbusRegister(0x0104, "power", "W", scale=1, category="battery"),
        # Charge voltage limit (0x0105)
        ModbusRegister(0x0105, "charge_voltage_limit", "V", scale=0.1, category="battery"),
        # Discharge voltage limit (0x0106)
        ModbusRegister(0x0106, "discharge_voltage_limit", "V", scale=0.1, category="battery"),
        # Max charge current (0x0107)
        ModbusRegister(0x0107, "max_charge_current", "A", scale=0.1, category="battery"),
        # Max discharge current (0x0108)
        ModbusRegister(0x0108, "max_discharge_current", "A", scale=0.1, category="battery"),
        # Battery temperature (0x0109)
        ModbusRegister(0x0109, "temp", "°C", scale=0.1, category="temperature"),
        # Cell max voltage (0x010A)
        ModbusRegister(0x010A, "cell_max_v", "V", scale=0.001, category="battery"),
        # Cell min voltage (0x010B)
        ModbusRegister(0x010B, "cell_min_v", "V", scale=0.001, category="battery"),
        # Cell count (0x010C)
        ModbusRegister(0x010C, "cell_count", "", scale=1, category="battery"),
        # Cycle count (0x010D)
        ModbusRegister(0x010D, "cycle_count", "", scale=1, category="battery"),
        # Status (0x010E)
        ModbusRegister(0x010E, "status", "", scale=1, category="status"),
        # Alarm (0x010F)
        ModbusRegister(0x010F, "alarm", "", scale=1, category="status"),
    ]
)

# ============================================================================
# Register all profiles
# ============================================================================
ALL_BATTERY_PROFILES = {
    "jk_pb": JK_PB_PROFILE,
    "pylontech": PYLONTECH_PROFILE,
    "growatt_bms": GROWATT_BMS_PROFILE,
    "deye_bms": DEYE_BMS_PROFILE,
    "solax_bms": SOLAX_BMS_PROFILE,
    "goodwe_bms": GOODWE_BMS_PROFILE,
    "eg4_bms": EG4_BMS_PROFILE,
    "ruixu_bms": RUIXU_BMS_PROFILE,
    "seplos_bms": SEPLOS_BMS_PROFILE,
    "pace_bms": PACE_BMS_PROFILE,
    "must_bms": MUST_BMS_PROFILE,
    "srne_bms": SRNE_BMS_PROFILE,
    "voltronic_bms": VOLTRONIC_BMS_PROFILE,
}

def get_battery_profile(name: str) -> InverterProfile:
    """Get battery profile by name."""
    return ALL_BATTERY_PROFILES.get(name, ALL_BATTERY_PROFILES["jk_pb"])
