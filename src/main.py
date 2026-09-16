#!/usr/bin/env python3
"""
Solar Monitor - Main Application
Multi-serial solar monitoring platform with REST API, WebSocket, and web dashboard.

Features:
- Equipment writes disabled by default
- SQLite storage with per-device snapshot API
- Multi-page dashboard: Overview, Batteries, History, Compare, Alerts, System
"""
import asyncio
import json
import time
import os
import html
import logging
from typing import Dict, List, Optional
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from serial_manager import SerialPortManager, SerialPort, ProtocolType, InverterReading, DeviceHealth
from modbus_handler import ModbusRTU, INVERTER_PROFILES, get_profile, InverterSimulator
from database import SolarDatabase
from automations import AutomationEngine, AutomationRule

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENABLE_WRITES = os.environ.get("ENABLE_WRITES", "false").lower() == "true"

serial_manager = SerialPortManager()
db = SolarDatabase()
automation_engine = AutomationEngine()

DASHBOARD_DIR = Path(__file__).parent / "templates"


def handle_automation_action(action: Dict):
    action_type = action.get("type", "")
    if action_type == "alert":
        logger.warning(f"ALERT: {action.get('message', '')}")
    elif action_type == "command":
        logger.warning(f"Command action blocked (disabled): {action}")


automation_engine.on_action(handle_automation_action)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    logger.info(f"Equipment writes enabled: {ENABLE_WRITES}")
    logger.info(f"Loaded {len(configs)} port configs")

    asyncio.create_task(read_all_ports())

    yield

    await serial_manager.stop()


app = FastAPI(title="Solar Monitor", version="2.0.0", lifespan=lifespan)

# Mount static files
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ─── REST API ───────────────────────────────────────────────

@app.get("/api/devices")
async def get_devices():
    """Get complete device inventory with latest values."""
    snapshots = db.get_device_snapshot()
    devices = []
    for device_id, snap in snapshots.items():
        # Get port config for name
        port_config = None
        for p in db.get_port_configs():
            if p.get("device_fingerprint") == device_id:
                port_config = p
                break
        
        last_valid = snap.get("last_valid_read", 0)
        age_seconds = time.time() - last_valid if last_valid > 0 else float('inf')
        
        # Determine if stale
        max_stale = 30.0
        if port_config:
            max_stale = port_config.get("max_stale_seconds", 30.0)
        
        is_stale = age_seconds > max_stale
        
        devices.append({
            "device_id": device_id,
            "name": port_config.get("name", snap.get("port_name", device_id[:8])) if port_config else snap.get("port_name", device_id[:8]),
            "port_name": snap.get("port_name", ""),
            "device_type": snap.get("device_type", ""),
            "health": snap.get("health", "disconnected"),
            "is_stale": is_stale,
            "last_valid_read": last_valid,
            "age_seconds": age_seconds,
            "metrics": snap.get("latest_values", {}),
            "timestamps": snap.get("latest_timestamps", {}),
        })
    
    return {"devices": devices, "server_time": time.time()}


@app.get("/api/devices/{device_id}")
async def get_device_detail(device_id: str):
    """Get detailed snapshot for a single device."""
    snapshots = db.get_device_snapshot()
    if device_id not in snapshots:
        raise HTTPException(404, "Device not found")
    
    snap = snapshots[device_id]
    last_valid = snap.get("last_valid_read", 0)
    
    return {
        "device_id": device_id,
        "name": snap.get("port_name", device_id[:8]),
        "device_type": snap.get("device_type", ""),
        "health": snap.get("health", "disconnected"),
        "last_valid_read": last_valid,
        "metrics": snap.get("latest_values", {}),
        "timestamps": snap.get("latest_timestamps", {}),
    }


@app.get("/api/history")
async def get_history(
    device_id: str = None,
    metric: str = None,
    hours: int = 24,
    start: float = None,
    end: float = None,
    limit: int = 10000
):
    """Get historical readings with bounded time range."""
    now = time.time()
    if start is None:
        start = now - (hours * 3600)
    if end is None:
        end = now
    
    # Enforce max range (30 days)
    max_range = 30 * 86400
    if end - start > max_range:
        start = end - max_range
    
    port_name = None
    if device_id:
        for p in db.get_port_configs():
            if p.get("device_id") == device_id:
                port_name = p.get("name", "")
                break
    
    readings = db.get_history(
        port_name=port_name,
        start_time=start,
        end_time=end,
        limit=limit
    )
    
    # Filter by metric if specified
    if metric:
        filtered = []
        for r in readings:
            if metric in r.get("metrics", {}):
                filtered.append({
                    "timestamp": r["timestamp"],
                    "value": r["metrics"][metric],
                })
        readings = filtered
    
    return {
        "readings": readings,
        "start": start,
        "end": end,
        "count": len(readings),
        "hours": hours,
        "coverage": "complete" if len(readings) < limit else "truncated",
    }


@app.get("/api/readings")
async def get_readings(port_name: str = None, limit: int = 100):
    """Get latest readings (legacy endpoint for compatibility)."""
    if port_name:
        readings = db.get_readings(port_name=port_name, limit=limit)
    else:
        readings = db.get_latest_readings(limit)
    return readings


@app.get("/api/ports")
async def get_ports():
    """Get all registered ports and their status."""
    return {
        "registered": serial_manager.get_port_status(),
        "available": serial_manager.list_available_ports(),
    }


@app.post("/api/ports")
async def add_port(config: Dict):
    port = SerialPort(
        device=config["device"],
        baudrate=config.get("baudrate", 9600),
        parity=config.get("parity", "N"),
        stopbits=config.get("stopbits", 1),
        protocol=ProtocolType(config.get("protocol", "modbus_rtu")),
        inverter_type=config.get("inverter_type", "generic"),
        name=config.get("name", ""),
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
        if port.is_open:
            asyncio.create_task(serial_manager.read_port(port.device, on_reading))
        return {"status": "ok", "message": f"Port {port.device} added"}
    raise HTTPException(status_code=400, detail="Port already exists")


@app.delete("/api/ports/{device:path}")
async def remove_port(device: str):
    if not device.startswith("/"):
        device = "/" + device
    serial_manager.remove_port(device)
    db.delete_port_config(device)
    db.log_audit("port_removed", device)
    return {"status": "ok"}


@app.post("/api/ports/{device:path}/open")
async def open_port(device: str):
    if not device.startswith("/"):
        device = "/" + device
    if serial_manager.open_port(device):
        db.log_audit("port_opened", device)
        if device not in serial_manager._tasks:
            asyncio.create_task(serial_manager.read_port(device, on_reading))
        return {"status": "ok", "message": f"Port {device} opened"}
    raise HTTPException(status_code=400, detail="Failed to open port")


@app.post("/api/ports/{device:path}/close")
async def close_port(device: str):
    if not device.startswith("/"):
        device = "/" + device
    serial_manager.close_port(device)
    db.log_audit("port_closed", device)
    return {"status": "ok"}


@app.post("/api/ports/{device:path}/send")
async def send_data(device: str, data: Dict):
    if not ENABLE_WRITES:
        raise HTTPException(status_code=403, detail="Equipment writes disabled.")
    if not device.startswith("/"):
        device = "/" + device
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
    raise HTTPException(status_code=400, detail="Failed to send")


@app.get("/api/stats")
async def get_stats():
    return db.get_port_stats()


@app.get("/api/profiles")
async def get_profiles():
    return {
        name: {
            "name": p.name,
            "manufacturer": p.manufacturer,
            "protocol": p.protocol,
            "baudrate": p.baudrate,
            "slave_id": p.slave_id,
        }
        for name, p in INVERTER_PROFILES.items()
    }


@app.get("/api/audit")
async def get_audit_log(limit: int = 100):
    return db.get_audit_log(limit)


@app.get("/api/automations")
async def get_automations():
    return automation_engine.get_rules()


@app.post("/api/automations")
async def add_automation(rule: Dict):
    new_rule = automation_engine.add_rule(
        name=rule["name"],
        condition=rule["condition"],
        action=rule["action"],
    )
    db.log_audit("automation_added", None, f"Rule: {rule['name']}")
    return {"status": "ok", "rule": new_rule}


@app.delete("/api/automations/{rule_id}")
async def remove_automation(rule_id: int):
    automation_engine.remove_rule(rule_id)
    db.log_audit("automation_removed", None, f"Rule ID: {rule_id}")
    return {"status": "ok"}


# ─── WebSocket ──────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Send per-device snapshots instead of last-10
            snapshots = db.get_device_snapshot()
            devices = []
            for device_id, snap in snapshots.items():
                port_config = None
                for p in db.get_port_configs():
                    if p.get("device_fingerprint") == device_id:
                        port_config = p
                        break
                last_valid = snap.get("last_valid_read", 0)
                age = time.time() - last_valid if last_valid > 0 else float('inf')
                devices.append({
                    "device_id": device_id,
                    "name": port_config.get("name", snap.get("port_name", device_id[:8])) if port_config else device_id[:8],
                    "health": snap.get("health", "disconnected"),
                    "is_stale": age > 30,
                    "age_seconds": age,
                    "metrics": snap.get("latest_values", {}),
                })
            
            await websocket.send_json({
                "type": "snapshot",
                "data": devices,
                "server_time": time.time(),
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ─── Reading callback ───────────────────────────────────────

async def on_reading(reading: InverterReading):
    if reading.valid and reading.metrics:
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
        "health": reading.health.value,
    })

    if reading.valid:
        readings_dict = {reading.port_name: reading.metrics}
        automation_engine.evaluate_rules(readings_dict)


async def read_all_ports():
    await serial_manager.start(on_reading)


# ─── Dashboard ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return HTMLResponse(content=open(DASHBOARD_DIR / "dashboard.html").read())


@app.get("/batteries/{device_id}", response_class=HTMLResponse)
async def battery_detail(request: Request, device_id: str):
    return HTMLResponse(content=open(DASHBOARD_DIR / "dashboard.html").read())


@app.get("/{page}", response_class=HTMLResponse)
async def page(request: Request, page: str):
    return HTMLResponse(content=open(DASHBOARD_DIR / "dashboard.html").read())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
