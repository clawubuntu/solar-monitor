#!/bin/bash
"""
Solar Monitor Setup Script
Run this on the Raspberry Pi to start the platform
"""
set -e

echo "=== Solar Monitor Setup ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root or with sudo"
    exit 1
fi

# Load USB serial modules
echo "Loading USB serial modules..."
modprobe ch341 2>/dev/null || true
modprobe pl2303 2>/dev/null || true
modprobe ftdi_sio 2>/dev/null || true
modprobe cp210x 2>/dev/null || true

# Check for USB devices
echo "USB devices:"
lsusb

# Check for serial ports
echo "Serial ports:"
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "No USB serial devices found"

# Create virtual environment if it doesn't exist
cd /home/raspberryuser/solar-monitor
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install -q fastapi uvicorn pyserial sqlalchemy aiosqlite jinja2 python-multipart aiofiles

# Create systemd service
cat > /etc/systemd/system/solar-monitor.service << 'EOF'
[Unit]
Description=Solar Monitor Platform
After=network.target

[Service]
Type=simple
User=raspberryuser
WorkingDirectory=/home/raspberryuser/solar-monitor
Environment=PATH=/home/raspberryuser/solar-monitor/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/home/raspberryuser/solar-monitor/venv/bin/python src/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
systemctl daemon-reload
systemctl enable solar-monitor
systemctl start solar-monitor

echo "=== Setup Complete ==="
echo "Access the dashboard at: http://$(hostname -I | awk '{print $1}'):8000"
echo ""
echo "To check status: systemctl status solar-monitor"
echo "To view logs: journalctl -u solar-monitor -f"
echo "To stop: systemctl stop solar-monitor"
