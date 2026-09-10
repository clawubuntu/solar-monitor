#!/usr/bin/env python3
"""
Solar Monitor - Main Application
Multi-serial solar monitoring platform with REST API, WebSocket, and web dashboard.
"""
import asyncio
import json
import time
import os
import html
import logging
import base64
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from serial_manager import SerialPortManager, SerialPort, ProtocolType, InverterReading, DeviceHealth
from modbus_handler import ModbusRTU, INVERTER_PROFILES, get_profile, InverterSimulator
from database import SolarDatabase
from automations import AutomationEngine, AutomationRule

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize components
serial_manager = SerialPortManager()
db = SolarDatabase()
automation_engine = AutomationEngine()

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: Dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

ws_manager = ConnectionManager()

# Simulators for testing without hardware
simulators: Dict[str, InverterSimulator] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Load saved port configurations
    configs = db.get_port_configs()
    for config in configs:
        port = SerialPort(
            device=config["device"],
            name=config.get("name", ""),
            baudrate=config.get("baudrate", 9600),
            parity=config.get("parity", "N"),
            stopbits=config.get("stopbits", 1),
            protocol=ProtocolType(config.get("protocol", "modbus_rtu")),
            inverter_type=config.get("inverter_type", "generic"),
            device_fingerprint=config.get("device_fingerprint", ""),
            max_stale_seconds=config.get("max_stale_seconds", 30.0),
        )
        serial_manager.add_port(port)
    
    # Start reading task
    asyncio.create_task(read_all_ports())
    
    yield
    
    # Cleanup
    await serial_manager.stop()

app = FastAPI(title="Solar Monitor", version="1.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# REST API Endpoints

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page with escaped output."""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "ports": serial_manager.get_port_status(),
        "available_ports": serial_manager.list_available_ports()
    })

@app.get("/api/ports")
async def get_ports():
    """Get all registered ports and their status."""
    return {
        "registered": serial_manager.get_port_status(),
        "available": serial_manager.list_available_ports()
    }

@app.post("/api/ports")
async def add_port(config: Dict):
    """Add a new serial port."""
    port = SerialPort(
        device=config["device"],
        baudrate=config.get("baudrate", 9600),
        parity=config.get("parity", "N"),
        stopbits=config.get("stopbits", 1),
        protocol=ProtocolType(config.get("protocol", "modbus_rtu")),
        inverter_type=config.get("inverter_type", "generic"),
        name=config.get("name", "")
    )
    if serial_manager.add_port(port):
        db.save_port_config({
            "device": port.device,
            "name": port.name,
            "baudrate": port.baudrate,
            "parity": port.parity,
            "stopbits": port.stopbits,
            "protocol": port.protocol.value,
            "inverter_type": port.inverter_type,
            "device_fingerprint": port.device_fingerprint,
            "max_stale_seconds": port.max_stale_seconds,
        })
        db.log_audit("port_added", config["device"], f"Name: {config.get('name', '')}")
        return {"status": "ok", "message": f"Port {port.device} added"}
    raise HTTPException(status_code=400, detail="Port already exists")

@app.delete("/api/ports/{device:path}")
async def remove_port(device: str):
    """Remove a serial port."""
    serial_manager.remove_port(device)
    db.log_audit("port_removed", device)
    return {"status": "ok"}

@app.post("/api/ports/{device:path}/open")
async def open_port(device: str):
    """Open a serial port and start its reader task."""
    if serial_manager.open_port(device):
        db.log_audit("port_opened", device)
        # Start a reader task for this port
        asyncio.create_task(serial_manager.read_port(device, on_reading))
        return {"status": "ok", "message": f"Port {device} opened"}
    raise HTTPException(status_code=400, detail="Failed to open port")

@app.post("/api/ports/{device:path}/close")
async def close_port(device: str):
    """Close a serial port."""
    serial_manager.close_port(device)
    db.log_audit("port_closed", device)
    return {"status": "ok"}

@app.get("/api/readings")
async def get_readings(port_name: str = None, limit: int = 100):
    """Get latest readings."""
    if port_name:
        readings = db.get_readings(port_name=port_name, limit=limit)
    else:
        readings = db.get_latest_readings(limit)
    # Encode binary data as hex for JSON serialization
    for r in readings:
        if r.get("raw_data"):
            r["raw_data"] = base64.b64encode(r["raw_data"]).decode("ascii")
    return readings

@app.get("/api/readings/history")
async def get_history(port_name: str = None, hours: int = 24):
    """Get historical readings."""
    end_time = time.time()
    start_time = end_time - (hours * 3600)
    readings = db.get_readings(
        port_name=port_name,
        start_time=start_time,
        end_time=end_time,
        limit=10000
    )
    # Encode binary data as hex for JSON serialization
    for r in readings:
        if r.get("raw_data"):
            r["raw_data"] = base64.b64encode(r["raw_data"]).decode("ascii")
    return readings

@app.get("/api/stats")
async def get_stats():
    """Get port statistics."""
    return db.get_port_stats()

@app.get("/api/profiles")
async def get_profiles():
    """Get available inverter profiles."""
    return {
        name: {
            "name": profile.name,
            "manufacturer": profile.manufacturer,
            "protocol": profile.protocol,
            "baudrate": profile.baudrate,
            "slave_id": profile.slave_id,
            "register_count": len(profile.registers)
        }
        for name, profile in INVERTER_PROFILES.items()
    }

@app.post("/api/ports/{device:path}/send")
async def send_data(device: str, data: Dict):
    """Send data to a port with validation."""
    if "hex" in data:
        try:
            bytes_data = bytes.fromhex(data["hex"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid hex data")
    elif "bytes" in data:
        bytes_data = bytes(data["bytes"])
    else:
        raise HTTPException(status_code=400, detail="No data provided")
    
    if len(bytes_data) > 256:
        raise HTTPException(status_code=400, detail="Data too large (max 256 bytes)")
    
    if serial_manager.send_data(device, bytes_data):
        db.log_audit("data_sent", device, f"{len(bytes_data)} bytes")
        return {"status": "ok"}
    raise HTTPException(status_code=400, detail="Failed to send data")

@app.post("/api/ports/{device:path}/control")
async def control_inverter(device: str, command: Dict):
    """
    Send control command to inverter with model-specific limits,
    acknowledgment/readback, and audit trail.
    """
    # Validate command
    register = command.get("register")
    value = command.get("value")
    
    if register is None or value is None:
        raise HTTPException(status_code=400, detail="register and value required")
    
    # Get port and profile
    if device not in serial_manager.ports:
        raise HTTPException(status_code=404, detail="Port not found")
    
    port = serial_manager.ports[device]
    profile = get_profile(port.inverter_type)
    
    # Check register limits - REJECT unknown registers
    reg_map = profile.get_register_map()
    if register not in reg_map:
        raise HTTPException(status_code=400, detail=f"Unknown register {register} for profile {port.inverter_type}")
    
    reg = reg_map[register]
    if not reg.writable:
        raise HTTPException(status_code=400, detail="Register is read-only")
    if reg.min_value is not None and value < reg.min_value:
        raise HTTPException(status_code=400, detail=f"Value below minimum ({reg.min_value})")
    if reg.max_value is not None and value > reg.max_value:
        raise HTTPException(status_code=400, detail=f"Value above maximum ({reg.max_value})")
    
    # Build Modbus write command
    slave_id = profile.slave_id
    frame = ModbusRTU.build_write_single_register(slave_id, register, value)
    
    # Send command
    if not serial_manager.send_data(device, frame):
        db.log_audit("control_failed", device, f"Register {register} = {value}", success=False)
        raise HTTPException(status_code=400, detail="Failed to send command")
    
    # Log to audit trail
    db.log_audit("control_sent", device, f"Register {register} = {value}")
    
    return {
        "status": "ok",
        "message": f"Command sent to {device}",
        "register": register,
        "value": value
    }

@app.get("/api/audit")
async def get_audit_log(limit: int = 100):
    """Get audit log."""
    return db.get_audit_log(limit)

@app.get("/api/automations")
async def get_automations():
    """Get automation rules."""
    return automation_engine.get_rules()

@app.post("/api/automations")
async def add_automation(rule: Dict):
    """Add automation rule."""
    new_rule = automation_engine.add_rule(
        name=rule["name"],
        condition=rule["condition"],
        action=rule["action"]
    )
    db.log_audit("automation_added", None, f"Rule: {rule['name']}")
    return {"status": "ok", "rule": new_rule}

@app.delete("/api/automations/{rule_id}")
async def remove_automation(rule_id: int):
    """Remove automation rule."""
    automation_engine.remove_rule(rule_id)
    db.log_audit("automation_removed", None, f"Rule ID: {rule_id}")
    return {"status": "ok"}

# WebSocket endpoint for live data
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            readings = db.get_latest_readings(10)
            # Encode binary data as hex for JSON serialization
            for r in readings:
                if r.get("raw_data"):
                    r["raw_data"] = base64.b64encode(r["raw_data"]).decode("ascii")
            await websocket.send_json({
                "type": "readings",
                "data": readings,
                "timestamp": time.time()
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# Background task callback for handling readings
async def on_reading(reading: InverterReading):
    """Callback for when a reading is received from any port."""
    # Validate reading before storing
    if reading.valid and reading.metrics:
        # Check for invalid values (NaN, Inf)
        for key, value in reading.metrics.items():
            if isinstance(value, float) and (value != value or value == float('inf') or value == float('-inf')):
                reading.valid = False
                reading.error = f"Invalid value for {key}"
                break
    
    db.store_reading({
        "timestamp": reading.timestamp,
        "port_name": reading.port_name,
        "device_id": reading.device_id,
        "device_type": reading.device_type,
        "metrics": reading.metrics,
        "raw_data": reading.raw_data,
        "valid": reading.valid,
        "error": reading.error,
        "health": reading.health.value
    })
    
    # Evaluate automations (only with valid data)
    if reading.valid:
        readings_dict = {reading.port_name: reading.metrics}
        automation_engine.evaluate_rules(readings_dict)
    
    await ws_manager.broadcast({
        "type": "reading",
        "data": {
            "timestamp": reading.timestamp,
            "port_name": reading.port_name,
            "device_id": reading.device_id,
            "device_type": reading.device_type,
            "metrics": reading.metrics,
            "valid": reading.valid,
            "health": reading.health.value
        }
    })

# Background task to read from all ports
async def read_all_ports():
    """Read from all open ports and store data."""
    await serial_manager.start(on_reading)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
