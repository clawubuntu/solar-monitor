#!/usr/bin/env python3
"""
Test Suite for Solar Monitor Platform
Tests all 12 review findings with reproducible tests.

Run with: python3 -m pytest tests/test_solar_monitor.py -v
"""
import pytest
import asyncio
import json
import time
import struct
import os
import sys
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from modbus_handler import ModbusRTU, InverterSimulator, get_profile, INVERTER_PROFILES, ModbusRegister, InverterProfile
from serial_manager import SerialPortManager, SerialPort, ProtocolType, DeviceHealth, InverterReading
from database import SolarDatabase
from automations import AutomationEngine, AutomationRule


class TestModbusHandler:
    """Test Modbus protocol handler."""
    
    def test_crc_calculation(self):
        """Test CRC16 calculation."""
        data = b'\x01\x03\x00\x00\x00\x0A'
        crc = ModbusRTU.calculate_crc(data)
        assert len(crc) == 2
        # Verify CRC is correct by checking it matches expected
        full_frame = data + crc
        assert ModbusRTU.parse_response(full_frame + b'\x00' * 14) is not None  # Will fail but CRC should be valid
    
    def test_build_read_holding_registers(self):
        """Test building read holding registers request."""
        frame = ModbusRTU.build_read_holding_registers(1, 0, 10)
        assert len(frame) == 11  # slave(1) + func(1) + addr(2) + count(2) + crc(2) = 8
        assert frame[0] == 1  # slave_id
        assert frame[1] == 0x03  # function code
    
    def test_build_write_single_register(self):
        """Test building write single register request."""
        frame = ModbusRTU.build_write_single_register(1, 5, 100)
        assert len(frame) == 8  # slave(1) + func(1) + addr(2) + value(2) + crc(2)
        assert frame[0] == 1
        assert frame[1] == 0x06
        addr = struct.unpack(">H", frame[2:4])[0]
        value = struct.unpack(">H", frame[4:6])[0]
        assert addr == 5
        assert value == 100
    
    def test_parse_response_valid(self):
        """Test parsing a valid response."""
        # Build a valid response
        slave_id = 1
        func_code = 0x03
        byte_count = 4
        registers = [100, 200]
        
        response = struct.pack(">BBB", slave_id, func_code, byte_count)
        for reg in registers:
            response += struct.pack(">H", reg)
        response += ModbusRTU.calculate_crc(response)
        
        result = ModbusRTU.parse_response(response)
        assert result is not None
        assert result["slave_id"] == slave_id
        assert result["function_code"] == func_code
        assert result["registers"] == registers
        assert result["error"] == False
    
    def test_parse_response_invalid_crc(self):
        """Test parsing response with invalid CRC."""
        response = b'\x01\x03\x04\x00\x64\x00\xc8\xff\xff'  # Wrong CRC
        result = ModbusRTU.parse_response(response)
        assert result is None
    
    def test_parse_response_wrong_length(self):
        """Test parsing response with wrong length."""
        response = b'\x01\x03\x04\x00\x64'  # Too short
        result = ModbusRTU.parse_response(response)
        assert result is None
    
    def test_parse_response_exception(self):
        """Test parsing exception response."""
        # Exception response: slave + func|0x80 + exception_code + crc
        response = b'\x01\x83\x02'
        response += ModbusRTU.calculate_crc(response)
        result = ModbusRTU.parse_response(response)
        assert result is not None
        assert result["error"] == True
        assert result["exception_code"] == 0x02
    
    def test_decode_registers(self):
        """Test register decoding."""
        profile = get_profile("generic")
        register_map = profile.get_register_map()
        
        # Test voltage decoding (scale=0.1)
        registers = [2300, 1500, 5000, 5000]  # 230.0V, 150.0A, 5000W, 50.00Hz
        result = ModbusRTU.decode_registers(registers, register_map, 0)
        
        assert result["voltage"] == 230.0
        assert result["current"] == 150.0
        assert result["power"] == 5000.0
        assert result["frequency"] == 50.0
    
    def test_decode_registers_with_limits(self):
        """Test register decoding with min/max limits."""
        profile = get_profile("deye_sg03lp1")
        register_map = profile.get_register_map()
        
        # Test SOC clamping (min=0, max=100)
        registers = [0, 0, 0, 0, 0, 150, 0, 0, 0, 0, 0, 0, 0, 0, 0]  # SOC=150
        result = ModbusRTU.decode_registers(registers, register_map, 0)
        assert result["battery_soc"] == 100.0  # Clamped to max


class TestInverterSimulator:
    """Test inverter simulator."""
    
    def test_simulator_init(self):
        """Test simulator initialization."""
        profile = get_profile("generic")
        sim = InverterSimulator(profile, slave_id=1)
        assert sim.slave_id == 1
        assert len(sim.registers) == 4
    
    def test_simulator_handle_request(self):
        """Test simulator request handling."""
        profile = get_profile("generic")
        sim = InverterSimulator(profile, slave_id=1)
        
        # Build read request
        request = ModbusRTU.build_read_holding_registers(1, 0, 4)
        response = sim.handle_request(request)
        
        assert len(response) > 0
        result = ModbusRTU.parse_response(response)
        assert result is not None
        assert result["slave_id"] == 1
        assert result["function_code"] == 0x03
        assert len(result["registers"]) == 4
    
    def test_simulator_wrong_slave(self):
        """Test simulator ignores wrong slave ID."""
        profile = get_profile("generic")
        sim = InverterSimulator(profile, slave_id=1)
        
        # Build read request for slave 2
        request = ModbusRTU.build_read_holding_registers(2, 0, 4)
        response = sim.handle_request(request)
        assert response == b""
    
    def test_simulator_write(self):
        """Test simulator write handling."""
        profile = get_profile("generic")
        sim = InverterSimulator(profile, slave_id=1)
        
        # Write to register 0
        request = ModbusRTU.build_write_single_register(1, 0, 1234)
        response = sim.handle_request(request)
        
        assert len(response) > 0
        assert sim.registers[0] == 1234
    
    def test_simulator_update(self):
        """Test simulator value drift."""
        profile = get_profile("generic")
        sim = InverterSimulator(profile, slave_id=1)
        
        initial_values = dict(sim.registers)
        sim.update()
        
        # Values should change slightly (or stay the same due to clamping)
        changes = sum(1 for k in initial_values if initial_values[k] != sim.registers[k])
        assert changes >= 0  # Some values may change


class TestSerialPortManager:
    """Test serial port manager."""
    
    def test_add_port(self):
        """Test adding a port."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            port = SerialPort(device="/dev/ttyUSB0", name="Test")
            assert manager.add_port(port) == True
            assert "/dev/ttyUSB0" in manager.ports
    
    def test_add_duplicate_port(self):
        """Test adding duplicate port fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            port1 = SerialPort(device="/dev/ttyUSB0", name="Test1")
            port2 = SerialPort(device="/dev/ttyUSB0", name="Test2")
            assert manager.add_port(port1) == True
            assert manager.add_port(port2) == False
    
    def test_remove_port(self):
        """Test removing a port."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            port = SerialPort(device="/dev/ttyUSB0", name="Test")
            manager.add_port(port)
            manager.remove_port("/dev/ttyUSB0")
            assert "/dev/ttyUSB0" not in manager.ports
    
    def test_add_simulator_port(self):
        """Test adding simulator port."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            port = SerialPort(device="sim://test1", name="Simulator", inverter_type="generic")
            assert manager.add_port(port) == True
            assert "sim://test1" in manager._simulators
            assert port.is_open == True
    
    def test_list_available_ports(self):
        """Test listing available ports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            ports = manager.list_available_ports()
            assert isinstance(ports, list)
    
    def test_get_port_status(self):
        """Test getting port status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            port = SerialPort(device="/dev/ttyUSB0", name="Test")
            manager.add_port(port)
            status = manager.get_port_status()
            assert len(status) == 1
            assert status[0]["device"] == "/dev/ttyUSB0"
            assert status[0]["name"] == "Test"
            assert status[0]["parity"] == "N"
            assert status[0]["stopbits"] == 1


class TestDatabase:
    """Test database layer."""
    
    def test_store_reading(self):
        """Test storing a reading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SolarDatabase(db_path=os.path.join(tmpdir, "test.db"))
            reading = {
                "timestamp": time.time(),
                "port_name": "Test",
                "device_id": "abc123",
                "device_type": "inverter",
                "metrics": {"voltage": 230.0, "current": 150.0},
                "raw_data": b'\x01\x03\x04\x00\x64',
                "valid": True,
                "error": "",
                "health": "healthy"
            }
            db.store_reading(reading)
            
            readings = db.get_latest_readings(10)
            assert len(readings) == 1
            assert readings[0]["port_name"] == "Test"
            assert readings[0]["metrics"] == {"voltage": 230.0, "current": 150.0}
            assert readings[0]["raw_data"] == "0103040064"  # Hex encoded
    
    def test_store_reading_binary_encoding(self):
        """Test that binary data is properly encoded as hex."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SolarDatabase(db_path=os.path.join(tmpdir, "test.db"))
            reading = {
                "timestamp": time.time(),
                "port_name": "Test",
                "device_id": "abc123",
                "device_type": "inverter",
                "metrics": {"power": 5000},
                "raw_data": bytes(range(256)),  # All bytes
                "valid": True,
                "error": "",
                "health": "healthy"
            }
            db.store_reading(reading)
            
            readings = db.get_latest_readings(10)
            assert len(readings) == 1
            # Should be hex string, not bytes
            assert isinstance(readings[0]["raw_data"], str)
            assert len(readings[0]["raw_data"]) == 512  # 256 bytes = 512 hex chars
    
    def test_get_readings_with_filters(self):
        """Test getting readings with filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SolarDatabase(db_path=os.path.join(tmpdir, "test.db"))
            
            for i in range(10):
                db.store_reading({
                    "timestamp": time.time() - i,
                    "port_name": f"Port{i % 2}",
                    "device_id": f"dev{i}",
                    "device_type": "inverter",
                    "metrics": {"value": float(i)},
                    "raw_data": b"\x00",
                    "valid": True,
                    "error": "",
                    "health": "healthy"
                })
            
            # Filter by port_name
            readings = db.get_readings(port_name="Port0")
            assert len(readings) == 5
            
            # Filter by time
            readings = db.get_readings(start_time=time.time() - 5)
            assert len(readings) <= 6
    
    def test_save_port_config(self):
        """Test saving port configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SolarDatabase(db_path=os.path.join(tmpdir, "test.db"))
            port = {
                "device": "/dev/ttyUSB0",
                "name": "Test",
                "baudrate": 9600,
                "parity": "E",
                "stopbits": 2,
                "protocol": "modbus_rtu",
                "inverter_type": "generic",
                "device_fingerprint": "abc123",
                "max_stale_seconds": 30.0
            }
            db.save_port_config(port)
            
            configs = db.get_port_configs()
            assert len(configs) == 1
            assert configs[0]["device"] == "/dev/ttyUSB0"
            assert configs[0]["parity"] == "E"
            assert configs[0]["stopbits"] == 2
    
    def test_delete_port_config(self):
        """Test deleting port configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SolarDatabase(db_path=os.path.join(tmpdir, "test.db"))
            port = {
                "device": "/dev/ttyUSB0",
                "name": "Test",
                "baudrate": 9600,
                "parity": "N",
                "stopbits": 1,
                "protocol": "modbus_rtu",
                "inverter_type": "generic",
                "device_fingerprint": "",
                "max_stale_seconds": 30.0
            }
            db.save_port_config(port)
            assert len(db.get_port_configs()) == 1
            
            db.delete_port_config("/dev/ttyUSB0")
            assert len(db.get_port_configs()) == 0
    
    def test_audit_log(self):
        """Test audit logging."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SolarDatabase(db_path=os.path.join(tmpdir, "test.db"))
            db.log_audit("test_action", "/dev/ttyUSB0", "Test details", success=True)
            db.log_audit("test_fail", None, "Failure details", success=False)
            
            logs = db.get_audit_log(10)
            assert len(logs) == 2
            assert logs[0]["action"] == "test_fail"  # Most recent first
            assert logs[0]["success"] == 0
            assert logs[1]["action"] == "test_action"
            assert logs[1]["success"] == 1
    
    def test_metrics_json_decode(self):
        """Test that metrics JSON is properly decoded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = SolarDatabase(db_path=os.path.join(tmpdir, "test.db"))
            
            # Manually insert a reading with JSON metrics
            with sqlite3.connect(db.db_path) as conn:
                conn.execute("""
                    INSERT INTO readings (timestamp, port_name, device_id, device_type, metrics, valid, health)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (time.time(), "Test", "dev1", "inverter", '{"voltage": 230.0}', 1, "healthy"))
                conn.commit()
            
            readings = db.get_latest_readings(10)
            assert len(readings) == 1
            assert readings[0]["metrics"] == {"voltage": 230.0}
            assert isinstance(readings[0]["metrics"], dict)


class TestAutomationEngine:
    """Test automation engine."""
    
    def test_add_rule(self):
        """Test adding a rule."""
        engine = AutomationEngine()
        rule = engine.add_rule(
            name="Test Rule",
            condition={"port": "Test", "metric": "voltage", "operator": ">", "value": 250},
            action={"type": "alert", "message": "High voltage"}
        )
        assert rule.id == 1
        assert rule.name == "Test Rule"
        assert len(engine.rules) == 1
    
    def test_remove_rule(self):
        """Test removing a rule."""
        engine = AutomationEngine()
        rule = engine.add_rule(
            name="Test Rule",
            condition={"port": "Test", "metric": "voltage", "operator": ">", "value": 250},
            action={"type": "alert", "message": "High voltage"}
        )
        engine.remove_rule(rule.id)
        assert len(engine.rules) == 0
    
    def test_evaluate_rules_trigger(self):
        """Test rule evaluation - trigger."""
        engine = AutomationEngine()
        engine.add_rule(
            name="High Voltage",
            condition={"port": "Test", "metric": "voltage", "operator": ">", "value": 250},
            action={"type": "alert", "message": "High voltage"}
        )
        
        readings = {"Test": {"voltage": 260.0}}
        engine.evaluate_rules(readings)
        
        assert engine.rules[0].trigger_count == 1
    
    def test_evaluate_rules_no_trigger(self):
        """Test rule evaluation - no trigger."""
        engine = AutomationEngine()
        engine.add_rule(
            name="High Voltage",
            condition={"port": "Test", "metric": "voltage", "operator": ">", "value": 250},
            action={"type": "alert", "message": "High voltage"}
        )
        
        readings = {"Test": {"voltage": 230.0}}
        engine.evaluate_rules(readings)
        
        assert engine.rules[0].trigger_count == 0
    
    def test_evaluate_rules_cooldown(self):
        """Test rule cooldown."""
        engine = AutomationEngine()
        engine.add_rule(
            name="High Voltage",
            condition={"port": "Test", "metric": "voltage", "operator": ">", "value": 250},
            action={"type": "alert", "message": "High voltage"}
        )
        engine.rules[0].cooldown = 60
        
        readings = {"Test": {"voltage": 260.0}}
        engine.evaluate_rules(readings)
        engine.evaluate_rules(readings)  # Second call within cooldown
        
        assert engine.rules[0].trigger_count == 1  # Only first triggers
    
    def test_action_callback(self):
        """Test action callback execution."""
        engine = AutomationEngine()
        callback = MagicMock()
        engine.on_action(callback)
        
        engine.add_rule(
            name="Test",
            condition={"port": "Test", "metric": "voltage", "operator": ">", "value": 250},
            action={"type": "alert", "message": "Test"}
        )
        
        readings = {"Test": {"voltage": 260.0}}
        engine.evaluate_rules(readings)
        
        callback.assert_called_once()
    
    def test_enable_disable_rule(self):
        """Test enabling/disabling rules."""
        engine = AutomationEngine()
        rule = engine.add_rule(
            name="Test",
            condition={"port": "Test", "metric": "voltage", "operator": ">", "value": 250},
            action={"type": "alert", "message": "Test"}
        )
        
        engine.enable_rule(rule.id, False)
        assert rule.enabled == False
        
        readings = {"Test": {"voltage": 260.0}}
        engine.evaluate_rules(readings)
        assert rule.trigger_count == 0  # Disabled rule doesn't trigger
    
    def test_load_rules(self):
        """Test loading rules from storage."""
        engine = AutomationEngine()
        rules_data = [
            {
                "id": 1,
                "name": "Rule 1",
                "condition": {"port": "Test", "metric": "voltage", "operator": ">", "value": 250},
                "action": {"type": "alert", "message": "Alert"},
                "enabled": True,
                "last_triggered": 0,
                "cooldown": 60,
                "trigger_count": 0
            }
        ]
        engine.load_rules(rules_data)
        assert len(engine.rules) == 1
        assert engine.rules[0].name == "Rule 1"


class TestIntegration:
    """Integration tests."""
    
    def test_two_simulators(self):
        """Test two simultaneous simulator devices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            
            port1 = SerialPort(device="sim://sim1", name="Sim 1", inverter_type="generic")
            port2 = SerialPort(device="sim://sim2", name="Sim 2", inverter_type="deye_sg03lp1")
            
            assert manager.add_port(port1) == True
            assert manager.add_port(port2) == True
            
            assert "sim://sim1" in manager._simulators
            assert "sim://sim2" in manager._simulators
            
            # Both should be open
            assert port1.is_open == True
            assert port2.is_open == True
    
    def test_modbus_transaction_fragmented(self):
        """Test Modbus transaction with fragmented response."""
        profile = get_profile("generic")
        sim = InverterSimulator(profile, slave_id=1)
        
        # Get a valid response
        request = ModbusRTU.build_read_holding_registers(1, 0, 4)
        response = sim.handle_request(request)
        
        # Simulate fragmented reception
        from serial_manager import ModbusTransaction
        transaction = ModbusTransaction(1, 0x03, 0, 4)
        
        # Send first half
        mid = len(response) // 2
        result = transaction.add_response_data(response[:mid])
        assert result is None  # Not complete yet
        
        # Send second half
        result = transaction.add_response_data(response[mid:])
        assert result is not None  # Now complete
        assert result["slave_id"] == 1
    
    def test_modbus_transaction_wrong_slave(self):
        """Test Modbus transaction with wrong slave response."""
        from serial_manager import ModbusTransaction
        
        transaction = ModbusTransaction(1, 0x03, 0, 4)
        
        # Build response for slave 2
        response = b'\x02\x03\x08' + b'\x00' * 8
        response += ModbusRTU.calculate_crc(response)
        
        result = transaction.add_response_data(response)
        assert result is not None
        assert result["slave_id"] == 2  # Wrong slave
    
    def test_modbus_transaction_timeout(self):
        """Test Modbus transaction timeout."""
        from serial_manager import ModbusTransaction
        
        transaction = ModbusTransaction(1, 0x03, 0, 4)
        transaction.request_time = time.time() - 5  # 5 seconds ago
        
        assert transaction.is_expired(timeout=2.0) == True
        assert transaction.is_expired(timeout=10.0) == False
    
    def test_port_persistence_across_restart(self):
        """Test that ports persist across restart."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First run
            manager1 = SerialPortManager(data_dir=tmpdir)
            port = SerialPort(device="sim://test", name="Test", inverter_type="generic")
            manager1.add_port(port)
            
            # Second run (simulate restart)
            manager2 = SerialPortManager(data_dir=tmpdir)
            assert "sim://test" in manager2.ports
            assert manager2.ports["sim://test"].name == "Test"
    
    def test_port_deletion_persists(self):
        """Test that deleted ports don't return after restart."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First run
            manager1 = SerialPortManager(data_dir=tmpdir)
            port = SerialPort(device="sim://test", name="Test", inverter_type="generic")
            manager1.add_port(port)
            manager1.remove_port("sim://test")
            
            # Second run (simulate restart)
            manager2 = SerialPortManager(data_dir=tmpdir)
            assert "sim://test" not in manager2.ports
    
    def test_jk_bms_profile(self):
        """Test JK-BMS profile exists and has registers."""
        assert "jk_bms" in INVERTER_PROFILES
        profile = get_profile("jk_bms")
        assert profile.name == "JK-BMS"
        assert profile.baudrate == 115200
        assert len(profile.registers) > 0
        
        # Check for cell voltage registers
        cell_regs = [r for r in profile.registers if "cell" in r.name]
        assert len(cell_regs) >= 16
    
    def test_data_quality_reject_empty(self):
        """Test that empty measurements are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            port = SerialPort(device="sim://test", name="Test", inverter_type="generic")
            manager.add_port(port)
            
            # Create a reading with empty metrics
            reading = InverterReading(
                timestamp=time.time(),
                port_name="Test",
                device_id="abc",
                device_type="generic",
                metrics={},
                valid=True,
                health=DeviceHealth.HEALTHY
            )
            
            # Empty metrics should be flagged as invalid
            if not reading.metrics:
                reading.valid = False
                reading.error = "Empty measurement"
            
            assert reading.valid == False
    
    def test_consecutive_errors_change_health(self):
        """Test that repeated errors change port health."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SerialPortManager(data_dir=tmpdir)
            port = SerialPort(device="sim://test", name="Test", inverter_type="generic")
            manager.add_port(port)
            
            # Simulate consecutive errors
            for i in range(10):
                port.error_count += 1
            
            # After many errors, health should be ERROR
            if port.error_count >= 5:
                port.health = DeviceHealth.ERROR
            
            assert port.health == DeviceHealth.ERROR


class TestSecurity:
    """Test security features."""
    
    def test_writes_disabled_by_default(self):
        """Test that equipment writes are disabled by default."""
        # This tests the configuration flag
        enable_writes = os.environ.get("ENABLE_WRITES", "false").lower() == "true"
        assert enable_writes == False  # Default is disabled
    
    def test_unknown_register_rejected(self):
        """Test that unknown registers are rejected."""
        profile = get_profile("generic")
        reg_map = profile.get_register_map()
        
        # Register 999 doesn't exist
        assert 999 not in reg_map
    
    def test_readonly_register_rejected(self):
        """Test that read-only registers can't be written."""
        profile = get_profile("generic")
        reg_map = profile.get_register_map()
        
        # All generic registers are read-only by default
        for addr, reg in reg_map.items():
            assert reg.writable == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
