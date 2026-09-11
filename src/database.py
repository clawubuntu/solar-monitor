#!/usr/bin/env python3
"""
Database Layer
Stores all readings, configurations, and historical data
Uses SQLite for local storage (no cloud dependency)

Single source of truth for all configuration.
Binary data stored as BLOB, encoded as hex only at API boundary.
"""
import sqlite3
import json
import time
from typing import Dict, List, Optional
from pathlib import Path

class SolarDatabase:
    def __init__(self, db_path: str = "database/solar.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()
    
    def init_db(self):
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    port_name TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    device_type TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    raw_data BLOB,
                    valid INTEGER DEFAULT 1,
                    error TEXT,
                    health TEXT DEFAULT 'healthy'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device TEXT UNIQUE NOT NULL,
                    name TEXT,
                    baudrate INTEGER DEFAULT 9600,
                    parity TEXT DEFAULT 'N',
                    stopbits INTEGER DEFAULT 1,
                    protocol TEXT DEFAULT 'modbus_rtu',
                    inverter_type TEXT DEFAULT 'generic',
                    is_open INTEGER DEFAULT 0,
                    last_read REAL,
                    error_count INTEGER DEFAULT 0,
                    device_fingerprint TEXT,
                    max_stale_seconds REAL DEFAULT 30.0
                )
            """)
            # Migration: add columns if missing
            try:
                conn.execute("ALTER TABLE ports ADD COLUMN parity TEXT DEFAULT 'N'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE ports ADD COLUMN stopbits INTEGER DEFAULT 1")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS automations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    condition_json TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    action TEXT NOT NULL,
                    port_name TEXT,
                    details TEXT,
                    user TEXT DEFAULT 'system',
                    success INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_timestamp 
                ON readings(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_port 
                ON readings(port_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp 
                ON audit_log(timestamp)
            """)
            conn.commit()
    
    def store_reading(self, reading: Dict):
        """Store a single reading."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO readings 
                (timestamp, port_name, device_id, device_type, metrics, 
                 raw_data, valid, error, health)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reading["timestamp"],
                reading["port_name"],
                reading.get("device_id", ""),
                reading["device_type"],
                json.dumps(reading["metrics"]),
                reading.get("raw_data", b""),
                1 if reading.get("valid", True) else 0,
                reading.get("error", ""),
                reading.get("health", "healthy")
            ))
            conn.commit()
    
    def get_readings(self, port_name: str = None, start_time: float = None, 
                     end_time: float = None, limit: int = 1000) -> List[Dict]:
        """Get readings with optional filters."""
        query = "SELECT * FROM readings WHERE 1=1"
        params = []
        
        if port_name:
            query += " AND port_name = ?"
            params.append(port_name)
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [self._format_reading(dict(row)) for row in rows]
    
    def get_latest_readings(self, count: int = 100) -> List[Dict]:
        """Get latest readings across all ports."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM readings 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (count,)).fetchall()
            return [self._format_reading(dict(row)) for row in rows]
    
    def _format_reading(self, row: Dict) -> Dict:
        """Format a reading row for API response."""
        # Convert raw_data bytes to hex string for JSON serialization
        raw_data = row.get("raw_data")
        if raw_data is not None:
            if isinstance(raw_data, bytes):
                row["raw_data"] = raw_data.hex()
            elif isinstance(raw_data, str):
                pass  # Already hex string
        else:
            row["raw_data"] = ""
        
        # Decode metrics JSON string to dict
        metrics = row.get("metrics")
        if isinstance(metrics, str):
            try:
                row["metrics"] = json.loads(metrics)
            except (json.JSONDecodeError, TypeError):
                row["metrics"] = {}
        
        return row
    
    def get_port_stats(self) -> List[Dict]:
        """Get statistics for each port."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT 
                    port_name,
                    COUNT(*) as total_readings,
                    MIN(timestamp) as first_reading,
                    MAX(timestamp) as last_reading,
                    SUM(CASE WHEN valid = 0 THEN 1 ELSE 0 END) as error_count
                FROM readings
                GROUP BY port_name
            """).fetchall()
            return [dict(row) for row in rows]
    
    def save_port_config(self, port: Dict):
        """Save port configuration with all settings."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO ports 
                (device, name, baudrate, parity, stopbits, protocol, inverter_type, device_fingerprint, max_stale_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                port["device"],
                port.get("name", ""),
                port.get("baudrate", 9600),
                port.get("parity", "N"),
                port.get("stopbits", 1),
                port.get("protocol", "modbus_rtu"),
                port.get("inverter_type", "generic"),
                port.get("device_fingerprint", ""),
                port.get("max_stale_seconds", 30.0)
            ))
            conn.commit()
    
    def get_port_configs(self) -> List[Dict]:
        """Get all port configurations."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM ports").fetchall()
            return [dict(row) for row in rows]
    
    def delete_port_config(self, device: str):
        """Delete port configuration from database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM ports WHERE device = ?", (device,))
            conn.commit()
    
    def get_setting(self, key: str, default: str = "") -> str:
        """Get a setting value."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else default
    
    def set_setting(self, key: str, value: str):
        """Set a setting value."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)
            """, (key, value))
            conn.commit()
    
    def log_audit(self, action: str, port_name: str = None, details: str = None, 
                  user: str = "system", success: bool = True):
        """Log an audit trail entry."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO audit_log (timestamp, action, port_name, details, user, success)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (time.time(), action, port_name, details, user, 1 if success else 0))
            conn.commit()
    
    def get_audit_log(self, limit: int = 100) -> List[Dict]:
        """Get audit log entries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM audit_log 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]
    
    def cleanup_old_data(self, days: int = 30):
        """Remove data older than specified days."""
        cutoff = time.time() - (days * 86400)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM readings WHERE timestamp < ?", (cutoff,))
            conn.commit()
