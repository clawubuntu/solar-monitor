# Solar Monitor — Multi-Serial Battery Monitoring Platform

A Raspberry Pi-based alternative to Solar Assistant that supports **multiple simultaneous serial connections** for multi-inverter/multi-BMS ingestion.

---

## JK-BMS V19 Parallel Battery Setup

This project was developed and tested with the following hardware:

- **Batteries:** 2× JK-PB2A16S20P (16S LiFePO4, 200A BMS)
- **BMS Version:** V19A communication board
- **Topology:** RS-485 parallel bus (both batteries daisy-chained on RS485-2)
- **Pi:** Raspberry Pi 3 (Debian Trixie, 64-bit)
- **Adapters:** CH340 USB-to-Serial (RS-485 via ZK-U10)

---

## DIP Switch Configuration

For master/slave parallel operation:

| Battery | DIP 1 | DIP 2 | DIP 3 | DIP 4 | Address |
|---------|-------|-------|-------|-------|---------|
| **1 (Master)** | OFF | OFF | OFF | OFF | 0x00 |
| **2 (Slave)** | **ON** | OFF | OFF | OFF | 0x01 |

- **Battery 1:** All DIP switches OFF = master mode (address 0)
- **Battery 2:** DIP 1 ON = slave mode (address 1)

---

## Protocol Settings

- **UART Protocol:** `001` — JK BMS RS485 Modbus V1.0
- **Baud Rate:** 115200
- **Data Format:** 8N1

Set via the JK-BMS Bluetooth app:
```
Settings → UART Settings → UART2 Protocol → 001
```

---

## Communication Protocol

The "JK BMS RS485 Modbus V1.0" protocol uses **5AA5 proprietary framing**, NOT standard Modbus RTU. The Pi triggers data output by sending a Modbus write command, then receives 300-byte binary frames.

### Trigger Command

```
Modbus Write: 01 06 00 20 00 05 [CRC16]
```

| Byte | Value | Description |
|------|-------|-------------|
| 0 | 0x01 | Slave address |
| 1 | 0x06 | Function code (write single register) |
| 2-3 | 0x0020 | Register address |
| 4-5 | 0x0005 | Value (trigger runtime data output) |
| 6-7 | [CRC16] | Modbus CRC16 checksum |

### Response Frame (300 bytes)

```
[0:4]   Header: 55 AA EB 90
[4]     Frame code (0x01-0x06)
[5]     Counter
[6:299] Data (293 bytes)
[299]   Checksum (sum8 of bytes 0-298)
```

### Frame Codes

| Code | Name | Direction |
|------|------|-----------|
| 0x01 | Config Read | BMS → Host |
| 0x02 | Runtime Data | BMS → Host |
| 0x03 | Device Info | BMS → Host |
| 0x04 | Config Write | Host → BMS |
| 0x05 | System Log | BMS → Host |
| 0x06 | Fault Info | BMS → Host |

---

## Raw Data Example

### Encoded 5AA5 Frame (Runtime Data, 0x02)

```
55 AA EB 90 02 00 8A 0D 8A 0D 8A 0D 8A 0D
85 0D 85 0D 85 0D 88 0D 85 0D 8A 0D 88 0D
86 0D 88 0D 85 0D 86 0D 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00
...
```

### Decoded Register Map

```
[06-37] Cell Voltages 1-16 (u16 LE, scale 0.001V):
  Cell 01: 0x0D8A = 3466 = 3.466V
  Cell 02: 0x0D8A = 3466 = 3.466V
  Cell 03: 0x0D8A = 3466 = 3.466V
  Cell 04: 0x0D8A = 3466 = 3.466V
  Cell 05: 0x0D85 = 3461 = 3.461V
  Cell 06: 0x0D85 = 3461 = 3.461V
  Cell 07: 0x0D85 = 3461 = 3.461V
  Cell 08: 0x0D88 = 3464 = 3.464V
  Cell 09: 0x0D85 = 3461 = 3.461V
  Cell 10: 0x0D8A = 3466 = 3.466V
  Cell 11: 0x0D88 = 3464 = 3.464V
  Cell 12: 0x0D86 = 3462 = 3.462V
  Cell 13: 0x0D88 = 3464 = 3.464V
  Cell 14: 0x0D85 = 3461 = 3.461V
  Cell 15: 0x0D86 = 3462 = 3.462V
  Cell 16: 0x0D00 = 0 = (unused)

[74] Average Cell Voltage: 3.464V
[76] Voltage Delta: 0.005V
[78] SOC: 100%
[80] Current: +2.27A (positive = charging)
[82] Pack Voltage: 55.42V
[84] Temperature 1: 17.1°C
[86] Temperature 2: 17.4°C
```

### Decoded Values Summary

| Metric | Value |
|--------|-------|
| **Pack Voltage** | 55.42V |
| **Current** | +2.27A |
| **SOC** | 100% |
| **Avg Cell** | 3.464V |
| **Cell Delta** | 0.005V |
| **Temp 1** | 17.1°C |
| **Temp 2** | 17.4°C |
| **Active Cells** | 16 |

---

## Wiring Diagram

```
Battery 1 (Master)          Battery 2 (Slave)
┌──────────────┐            ┌──────────────┐
│  RS485-2     │◄──────────►│  RS485-2     │
│  (RJ45)      │   Bus      │  (RJ45)      │
└──────────────┘            └──────────────┘
       │
       │ RS-485 A/B/GND
       ▼
┌──────────────┐
│  ZK-U10      │
│  Adapter     │
│  (RS-485)    │
└──────────────┘
       │ USB
       ▼
┌──────────────┐
│  CH340       │
│  USB-Serial  │
└──────────────┘
       │ USB
       ▼
┌──────────────┐
│  Raspberry Pi│
│  10.10.10.33 │
└──────────────┘
```

**Note:** Only ONE USB adapter needed for both batteries. The RS-485 bus is daisy-chained.

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/ports` | List configured and available ports |
| `POST /api/ports` | Add a new port |
| `POST /api/ports/{device}/open` | Open a port for reading |
| `GET /api/readings` | Get latest readings |
| `GET /api/stats` | Get system statistics |
| `GET /` | Web dashboard |

---

## Quick Start

```bash
# Clone repository
git clone https://github.com/clawubuntu/solar-monitor.git
cd solar-monitor

# Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pyserial sqlalchemy aiosqlite jinja2 python-multipart aiofiles

# Start the platform
python src/main.py

# Access dashboard
# http://<pi-ip>:8000
```

---

## Hardware Bill of Materials

| Component | Qty | Notes |
|-----------|-----|-------|
| Raspberry Pi 3/4/5 | 1 | Any Pi with USB |
| JK-PB2A16S20P BMS | 2 | V19A comm board |
| ZK-U10 RS-485 Adapter | 1 | Per battery pair |
| CH340 USB-Serial | 1 | Per RS-485 bus |
| RJ45 Cable | 2 | For RS45 daisy-chain |
| USB Cable | 1 | Pi to CH340 |

---

## Troubleshooting

### No data flowing
- Verify DIP switches (all OFF for master, DIP 1 ON for slave)
- Check baud rate is 115200
- Confirm protocol is "001" not "000"
- Power cycle BMS after protocol change
- Try swapping A/B polarity on RS-485

### Port shows "error" health
- Normal during startup — takes a few seconds to receive valid frames
- Non-runtime frames (config, device info) may show zero values
- Runtime frames (0x02) should show valid cell voltages

### Duplicate readings
- Use only ONE adapter per RS-485 bus
- Multiple adapters cause bus conflicts

---

## License

MIT
