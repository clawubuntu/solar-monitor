# Battery Monitor Platform — Redesign Proposal

**Date:** 2025-09-11
**Author:** Hermes (inspired by the name of the spirit)
**Status:** Proposal for review

---

## Executive Summary

The current Solar Monitor platform works but uses the wrong tools for the job. A Raspberry Pi running FastAPI + SQLite + a basic HTML dashboard is like using a semi-truck to deliver pizza — it'll get there, but it's wasteful and hard to maneuver.

**Current problems:**
- Raspberry Pi draws 15-20W 24/7 vs 1-2W for an ESP32
- SQLite isn't designed for time-series data (no retention, no downsampling)
- Dashboard is hand-rolled HTML/JS — reinventing the wheel
- No integration with Home Assistant (your primary automation platform)
- No MQTT — the universal language of IoT/automation
- Every protocol hand-coded instead of auto-discovered
- No historical analysis, anomaly detection, or capacity tracking

**Proposed redesign:**
- **ESP32** as the edge device ($5, 1W power draw, built-in WiFi)
- **MQTT** as the data backbone (universal, lightweight, HA-native)
- **InfluxDB** for time-series storage (retention, downsampling, compression)
- **Grafana** for visualization (professional, alerting, dashboards)
- **Telegraf** for metric collection
- **Node-RED** for logic/automation
- **Auto-discovery** of battery protocols instead of manual configuration

---

## Research Summary

### Existing Open-Source Projects

| Project | Approach | Strengths | Weaknesses |
|---------|----------|-----------|------------|
| **simat/BatteryMonitor** | Pi + Bluetooth BMS | Simple, $50-150 | Bluetooth only, dated |
| **foxBMS** | Fraunhofer IISB, research-grade | Redundant, safety-certified | Overkill for home use |
| **Rotoslider/bms-mqtt-ha** | ESP32 + BLE BMS + MQTT + HA | Auto-discovery, always read-only | BLE only, no RS-485 |
| **Green-bms** | Cell modules + Arduino Mega | Hardware BMS, protection | Custom hardware, complex |
| **OpenEnergyMonitor** | emonPi + RF sensors + EmonCMS | Mature ecosystem | Proprietary hardware |

### Architecture Patterns Discovered

1. **Edge + Cloud** (Rotoslider pattern): ESP32 reads sensor → MQTT → HA
2. **All-in-one** (emonPi pattern): Single device does everything
3. **Distributed** (foxBMS pattern): Cell modules → Controller → Backend
4. **Time-series stack** (BatteryStorageHQ pattern): Sensor → Telegraf → InfluxDB → Grafana

### Key Technologies Researched

| Technology | Use Case | Why |
|------------|----------|-----|
| **MQTT** | Data transport | Universal IoT protocol, HA-native, lightweight |
| **InfluxDB** | Time-series DB | Retention policies, downsampling, compression, 10:1 vs SQLite |
| **Grafana** | Visualization | Professional dashboards, alerting, annotations |
| **Telegraf** | Metric collection | Agent-based, auto-detection, 200+ plugins |
| **Node-RED** | Automation | Visual programming, MQTT-native, HA integration |
| **ESP32** | Edge device | $5, 1W, WiFi+BLE, sufficient for protocol decoding |
| **ESPHome** | Firmware | YAML config, auto-discovery, OTA updates |

---

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BATTERY MONITOR PLATFORM                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │
│  │ Battery #1  │    │ Battery #2  │    │ Battery #N  │              │
│  │ (JK-PB BMS) │    │ (JK-PB BMS) │    │ (any BMS)   │              │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘              │
│         │ RS-485            │ RS-485            │ RS-485/CAN         │
│         │                   │                   │                    │
│  ┌──────▼───────────────────▼───────────────────▼──────┐            │
│  │              ESP32 BRIDGE(S)                         │            │
│  │  ┌─────────────────────────────────────────────┐     │            │
│  │  │  ESPHome / Custom Firmware                   │     │            │
│  │  │  - Protocol auto-detection                   │     │            │
│  │  │  - Frame decoding (JK-PB, Pylontech, etc.)   │     │            │
│  │  │  - MQTT publishing                           │     │            │
│  │  │  - Health metrics                            │     │            │
│  │  └─────────────────────────────────────────────┘     │            │
│  └──────────────────────┬───────────────────────────────┘            │
│                         │ MQTT (WiFi)                                │
│  ┌──────────────────────▼───────────────────────────────┐            │
│  │                 MQTT BROKER (Mosquitto)               │            │
│  │  Topics:                                              │            │
│  │    battery/1/voltage                                  │            │
│  │    battery/1/cell_01_v                                │            │
│  │    battery/1/soc                                      │            │
│  │    battery/1/temperature                              │            │
│  │    battery/1/health                                   │            │
│  └──────────────────────┬───────────────────────────────┘            │
│                         │                                            │
│         ┌───────────────┼───────────────┐                            │
│         │               │               │                            │
│  ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐                    │
│  │  TELEGRAF   │ │  HOME       │ │  NODE-RED   │                    │
│  │  (metrics)  │ │  ASSISTANT  │ │  (logic)    │                    │
│  └──────┬──────┘ └─────────────┘ └─────────────┘                    │
│         │                                                            │
│  ┌──────▼──────┐                                                     │
│  │  INFLUXDB   │                                                     │
│  │  - Raw: 7d  │                                                     │
│  │  - 1m: 30d   │                                                     │
│  │  - 5m: 1y    │                                                     │
│  │  - 1h: ∞     │                                                     │
│  └──────┬──────┘                                                     │
│         │                                                            │
│  ┌──────▼──────┐                                                     │
│  │  GRAFANA    │                                                     │
│  │  - Live     │                                                     │
│  │  - History  │                                                     │
│  │  - Alerts   │                                                     │
│  │  - Analysis │                                                     │
│  └─────────────┘                                                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Deep-Dive

### 1. Edge Device: ESP32 Bridge

**Why ESP32 instead of Raspberry Pi:**

| Factor | Raspberry Pi 4 | ESP32 |
|--------|---------------|-------|
| Cost | $35-55 | $5-10 |
| Power | 15-20W | 0.5-2W |
| Size | Credit card | Matchbox |
| WiFi | Yes (built-in) | Yes (built-in) |
| BLE | Yes (built-in) | Yes (built-in) |
| GPIO | 40 pins | 30+ pins |
| RS-485 | Needs adapter | Needs adapter |
| OS | Linux (complex) | Bare-metal/RTOS |
| Boot time | 30-60 seconds | <1 second |
| Reliability | SD card corruption | Flash (more reliable) |

**ESP32 is better for:**
- Always-on, low-power operation
- Single-purpose device
- MQTT publishing
- Protocol decoding

**Raspberry Pi is better for:**
- Running multiple services
- Heavy computation
- Local web server
- Complex logic

**Recommendation:** Use ESP32 for protocol decoding + MQTT publishing. Use Pi only if you need local services (InfluxDB, Grafana).

### 2. Protocol Auto-Detection

**Current problem:** Every protocol hand-coded, manual configuration.

**Proposed solution:** Implement the "unknown protocol decoder" framework we built into the ESP32 firmware:

1. **Baud rate scan:** Try all common baud rates
2. **Delimiter detection:** Find frame delimiters (5AA5, AA55, etc.)
3. **Structure analysis:** Fixed vs changing fields
4. **Checksum detection:** XOR, sum8, CRC-16
5. **Semantic mapping:** Identify voltage, current, SOC fields
6. **Auto-publish:** MQTT with auto-discovery

**Existing projects with auto-detection:**
- ESPHome: YAML config, auto-discovers some devices
- Rotoslider: BLE scan + auto-config
- Unknown Protocol Decoder (our work): Full RE framework

### 3. Data Transport: MQTT

**Why MQTT:**

| Factor | REST API (current) | MQTT |
|--------|-------------------|------|
| Direction | Pull (poll) | Push (real-time) |
| Overhead | HTTP headers (~800 bytes) | 2-byte header |
| Latency | Polling interval | Instant |
| HA integration | Needs custom component | Native |
| Offline handling | Complex | Built-in (LWT) |
| QoS | None | 0, 1, 2 |
| Retention | None | Retained messages |

**MQTT Topics:**
```
battery/1/voltage              → 53.8
battery/1/current              → 11.8
battery/1/soc                  → 99
battery/1/temperature          → 25.3
battery/1/cell_01_v            → 3.357
battery/1/cell_02_v            → 3.360
...
battery/1/health               → OK
battery/1/lwt                  → online
```

**Home Assistant Auto-Discovery:**
```yaml
# ESP32 publishes to:
homeassistant/sensor/battery_1_voltage/config
homeassistant/sensor/battery_1_soc/config
# etc.
# HA creates entities automatically
```

### 4. Time-Series Database: InfluxDB

**Why InfluxDB instead of SQLite:**

| Factor | SQLite | InfluxDB |
|--------|--------|----------|
| Purpose | General relational | Time-series optimized |
| Compression | None | 10:1 (delta-of-delta) |
| Retention | Manual | Automatic policies |
| Downsampling | Manual | Built-in tasks |
| Cardinality | Limited | High (tags) |
| Queries | SQL | Flux / InfluxQL / SQL |
| Aggregation | Slow | Optimized |
| Storage growth | Linear | Bounded (retention) |

**Retention Strategy:**
```
Raw data (10s resolution):  7 days
Downsampled (1m):          30 days
Downsampled (5m):          1 year
Downsampled (1h):          Forever
```

**Space estimate:**
- 100 metrics/battery × 2 batteries = 200 metrics
- Raw: 200 × 8640 × 7 = 12M points → ~500MB
- Downsampled: 200 × 1440 × 30 = 8.6M → ~350MB
- Total: <2GB/year (manageable on Pi)

### 5. Visualization: Grafana

**Why Grafana instead of hand-rolled dashboard:**

| Factor | Hand-rolled HTML | Grafana |
|--------|-----------------|---------|
| Development time | Weeks | Hours |
| Responsiveness | Manual CSS | Built-in |
| Alerting | None | Built-in |
| Annotations | None | Built-in |
| Variables | None | Built-in |
| Sharing | None | Dashboard links |
| Mobile | Manual CSS | Responsive |
| Plugin ecosystem | None | 100+ panels |

**Grafana Dashboard Panels:**
- Pack voltage (time series)
- Current (time series)
- SOC (gauge)
- Cell voltages (bar chart)
- Temperature (time series)
- Cell delta (stat)
- Cycle count (stat)
- Health status (alert list)

### 6. Automation: Node-RED

**Why Node-RED:**

| Factor | Python scripts | Node-RED |
|--------|---------------|----------|
| Development | Code | Visual flow |
| MQTT | Manual | Built-in |
| HA integration | Manual | Built-in |
| Debugging | Print | Debug nodes |
| Deployment | Manual | One-click |
| Sharing | Code export | Flow export |

**Example Flow:**
```
[MQTT In: battery/1/soc] → [Function: soc < 20] → [MQTT Out: inverter/charge_enable]
```

### 7. Home Assistant Integration

**Current state:** No HA integration.

**Proposed integration:**

1. **MQTT Auto-Discovery:** ESP32 publishes HA discovery messages → entities appear automatically
2. **REST sensors:** If MQTT isn't desired, HA can query REST API
3. ** Lovelace cards:** Pre-built cards for battery monitoring
4. **Automations:** HA automations trigger based on battery state

**HA Entities:**
- `sensor.battery_1_voltage`
- `sensor.battery_1_soc`
- `sensor.battery_1_current`
- `sensor.battery_1_cell_01_v`
- `binary_sensor.battery_1_health`
- `sensor.battery_1_cycle_count`

---

## Redesign Options

### Option A: Full Migration (Recommended)

**Architecture:** ESP32 → MQTT → InfluxDB + Grafana + HA

**Pros:**
- Most efficient
- Lowest power
- Best integration
- Professional dashboards
- Historical analysis

**Cons:**
- Requires ESP32 purchase
- More initial setup
- Learning curve for new tools

**Hardware:**
- ESP32 dev board: $5
- RS-485 to TTL converter: $3
- Power supply: $5
- **Total: ~$15**

**Software stack:**
- ESPHome (or custom firmware)
- Mosquitto (MQTT broker)
- InfluxDB
- Grafana
- Node-RED (optional)

### Option B: Hybrid (Pi + ESP32)

**Architecture:** ESP32 → MQTT → Pi (InfluxDB + Grafana + HA)

**Pros:**
- Reuse existing Pi
- Lower power than current
- Keep HA local

**Cons:**
- Pi still draws 15-20W
- More complex than full cloud

### Option C: Pi Optimization

**Architecture:** Pi → MQTT → Grafana + InfluxDB (keep Pi as server)

**Pros:**
- Minimal changes
- Reuse existing code

**Cons:**
- Still high power draw
- Not as efficient as ESP32

---

## Migration Plan

### Phase 1: ESP32 Bridge (1-2 days)

1. Flash ESP32 with ESPHome or custom firmware
2. Connect RS-485 to ESP32
3. Configure protocol detection
4. Publish to MQTT
5. Verify data in MQTT explorer

### Phase 2: Backend (2-3 days)

1. Install InfluxDB on Pi or cloud
2. Install Grafana
3. Configure Telegraf to read MQTT
4. Create retention policies
5. Build Grafana dashboards

### Phase 3: Home Assistant (1 day)

1. Enable MQTT integration in HA
2. Verify auto-discovery
3. Create Lovelace cards
4. Set up automations

### Phase 4: Advanced Features (ongoing)

1. Capacity tracking (Ah in/out)
2. Cell balancing monitoring
3. Anomaly detection
4. Predictive maintenance
5. Multi-battery support

---

## Cost Comparison

| Component | Current | Proposed |
|-----------|---------|----------|
| Hardware | Raspberry Pi ($50) | ESP32 ($15) |
| Power (annual) | $15-25 | $1-2 |
| Storage | SQLite (unbounded) | InfluxDB (retention) |
| Dashboard | Hand-rolled | Grafana (free) |
| HA integration | None | Native MQTT |
| Maintenance | High (hand-coded) | Low (standard tools) |

---

## Recommended Action

**Go with Option A: Full Migration.**

1. **Order an ESP32** ($5) and RS-485 to TTL converter ($3)
2. **Set up MQTT broker** on your Pi or a cloud instance
3. **Flash ESP32** with ESPHome using the JK-PB protocol decoder
4. **Install InfluxDB + Grafana** on the Pi
5. **Connect HA** via MQTT auto-discovery

This gives you a professional, maintainable, and extensible battery monitoring platform that integrates natively with your existing Home Assistant setup.

---

## Open Questions

1. **Where should InfluxDB run?** On the Pi (local) or a cloud instance?
2. **Do you want to keep the Pi for anything else?** (e.g., MQTT broker, Node-RED)
3. **What batteries do you want to monitor long-term?** Just the 2 JK-PB units?
4. **Do you need real-time control?** (e.g., charge/discharge based on cell data)
5. **What's your preference for ESP32 firmware?** ESPHome (YAML) or custom (Python/MicroPython)

---

## Resources

- [Rotoslider bms-mqtt-ha](https://github.com/Rotoslider/bms-mqtt-ha) — ESP32 BMS to MQTT bridge
- [ESPHome RS-485](https://esphome.io/components/rs485.html) — RS-485 component
- [InfluxDB Retention Policies](https://docs.influxdata.com/influxdb/v2/admin/buckets/) — Data retention
- [Grafana Battery Dashboard](https://grafana.com/grafana/dashboards/?search=battery) — Pre-built dashboards
- [MQTT Auto-Discovery](https://www.home-assistant.io/integrations/mqtt/#discovery) — HA integration
- [OpenEnergyMonitor](https://guide.openenergymonitor.org/) — Open-source energy monitoring
- [foxBMS](https://foxbms.org/) — Research-grade BMS platform
