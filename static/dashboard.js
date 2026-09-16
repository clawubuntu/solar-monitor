// Solar Monitor Dashboard
// Handles navigation, overview, batteries, history, compare, alerts, system

const state = {
  devices: [],
  wsConnected: false,
  lastUpdate: null,
  currentPage: 'overview',
  currentBattery: null,
  historyChart: null,
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initWebSocket();
  initForms();
  loadDevices();
});

// ─── Navigation ────────────────────────────────────────────

function initNavigation() {
  const items = document.querySelectorAll('.nav-item');
  items.forEach(item => {
    item.addEventListener('click', () => {
      const page = item.dataset.page;
      navigateTo(page);
    });
  });
}

function navigateTo(page) {
  state.currentPage = page;
  
  // Update nav
  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  const navItem = document.querySelector(`[data-page="${page}"]`);
  if (navItem) navItem.classList.add('active');
  
  // Update pages
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) pageEl.classList.add('active');
  
  // Update URL
  window.location.hash = page;
  
  // Page-specific init
  if (page === 'batteries') loadBatteryDetail();
  if (page === 'history') loadHistory();
  if (page === 'compare') loadCompare();
  if (page === 'system') loadSystem();
}

// ─── WebSocket ─────────────────────────────────────────────

function initWebSocket() {
  const wsUrl = `ws://${window.location.host}/ws`;
  const ws = new WebSocket(wsUrl);
  
  ws.onopen = () => {
    state.wsConnected = true;
    updateWsStatus();
  };
  
  ws.onclose = () => {
    state.wsConnected = false;
    updateWsStatus();
    // Reconnect
    setTimeout(initWebSocket, 3000);
  };
  
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'snapshot') {
      state.devices = msg.data;
      state.lastUpdate = msg.server_time;
      renderOverview();
      updateWsStatus();
    }
  };
}

function updateWsStatus() {
  const el = document.getElementById('ws-status');
  if (el) {
    el.textContent = state.wsConnected ? '● Live' : '● Offline';
    el.className = `ws-status ${state.wsConnected ? 'online' : 'offline'}`;
  }
  if (state.lastUpdate) {
    const d = new Date(state.lastUpdate * 1000);
    document.getElementById('last-update').textContent = 
      `Last update: ${d.toLocaleTimeString()}`;
  }
}

// ─── Device loading ────────────────────────────────────────

async function loadDevices() {
  try {
    const resp = await fetch('/api/devices');
    const data = await resp.json();
    state.devices = data.devices;
    renderOverview();
  } catch (e) {
    console.error('Failed to load devices:', e);
  }
}

// ─── Overview ──────────────────────────────────────────────

function renderOverview() {
  const devices = state.devices;
  
  // Fresh count
  const fresh = devices.filter(d => !d.is_stale).length;
  document.getElementById('fresh-count').textContent = fresh;
  document.getElementById('total-count').textContent = devices.length;
  document.getElementById('server-time').textContent = state.lastUpdate 
    ? `Updated ${new Date(state.lastUpdate * 1000).toLocaleTimeString()}`
    : '';
  
  // Attention panel
  const attention = [];
  devices.forEach(d => {
    if (d.is_stale) attention.push({ type: 'stale', device: d, msg: `${d.name} data is stale` });
    if (d.health === 'error') attention.push({ type: 'error', device: d, msg: `${d.name} has communication errors` });
  });
  
  const panel = document.getElementById('attention-panel');
  const list = document.getElementById('attention-list');
  if (attention.length > 0) {
    panel.classList.remove('hidden');
    list.innerHTML = attention.map(a => `<li>${a.msg}</li>`).join('');
  } else {
    panel.classList.add('hidden');
  }
  
  // Summary cards
  const validDevices = devices.filter(d => d.health === 'healthy' || d.metrics.voltage > 40);
  
  if (validDevices.length > 0) {
    // Bank SOC (weighted average would go here, for now simple avg)
    const socs = validDevices.map(d => d.metrics.soc || 0).filter(s => s > 0);
    const avgSoc = socs.length ? Math.round(socs.reduce((a,b) => a+b, 0) / socs.length) : null;
    document.getElementById('bank-soc').textContent = avgSoc != null ? `${avgSoc}%` : '—';
    
    // Net power
    const powers = validDevices.map(d => d.metrics.power || 0);
    const netPower = powers.reduce((a,b) => a+b, 0);
    const powerEl = document.getElementById('bank-power');
    if (Math.abs(netPower) > 10) {
      const label = netPower > 0 ? 'Charging' : 'Discharging';
      powerEl.innerHTML = `${Math.abs(netPower).toFixed(0)}W <span class="status-badge ${netPower > 0 ? 'healthy' : 'warning'}">${label}</span>`;
    } else {
      powerEl.textContent = 'Idle';
    }
  }
  
  // Data coverage
  const staleCount = devices.filter(d => d.is_stale).length;
  document.getElementById('data-coverage').textContent = 
    devices.length === 0 ? '—' : `${devices.length - staleCount}/${devices.length} fresh`;
  
  // Battery table
  const tbody = document.getElementById('battery-table-body');
  if (devices.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No batteries configured</td></tr>';
  } else {
    tbody.innerHTML = devices.map(d => {
      const cells = [];
      for (let i = 1; i <= 16; i++) {
        cells.push(d.metrics[`cell_${i.toString().padStart(2, '0')}_v`] || 0);
      }
      const nz = cells.filter(c => c > 0.1);
      const delta = nz.length > 0 ? (Math.max(...nz) - Math.min(...nz)) * 1000 : 0;
      
      const healthClass = d.is_stale ? 'stale' : (d.health || 'disconnected');
      const age = d.age_seconds != null 
        ? (d.age_seconds < 60 ? `${Math.round(d.age_seconds)}s` : `${Math.round(d.age_seconds/60)}m`)
        : '—';
      
      return `<tr>
        <td><a href="#batteries" onclick="selectBattery('${d.device_id}')">${d.name}</a></td>
        <td><span class="status-badge ${healthClass}">${d.is_stale ? 'Stale' : d.health}</span></td>
        <td>${d.metrics.soc != null ? d.metrics.soc + '%' : '—'}</td>
        <td>${d.metrics.voltage != null ? d.metrics.voltage.toFixed(2) + 'V' : '—'}</td>
        <td>${d.metrics.current != null ? d.metrics.current.toFixed(2) + 'A' : '—'}</td>
        <td>${d.metrics.power != null ? d.metrics.power.toFixed(0) + 'W' : '—'}</td>
        <td>${d.metrics.temp1 != null ? d.metrics.temp1.toFixed(1) + '°C' : '—'}</td>
        <td>${delta.toFixed(0)}mV</td>
        <td>${age}</td>
      </tr>`;
    }).join('');
  }
  
  // Update battery selects
  updateBatterySelects();
}

function updateBatterySelects() {
  const selects = ['battery-select', 'history-device', 'compare-device-1', 'compare-device-2'];
  selects.forEach(id => {
    const sel = document.getElementById(id);
    if (sel) {
      const val = sel.value;
      sel.innerHTML = '<option value="">Select...</option>' + 
        state.devices.map(d => `<option value="${d.device_id}">${d.name}</option>`).join('');
      sel.value = val;
    }
  });
}

// ─── Battery Detail ────────────────────────────────────────

function selectBattery(deviceId) {
  state.currentBattery = deviceId;
  const sel = document.getElementById('battery-select');
  if (sel) sel.value = deviceId;
  navigateTo('batteries');
}

function loadBatteryDetail() {
  const container = document.getElementById('battery-detail');
  
  if (state.devices.length === 0) {
    container.innerHTML = '<p class="empty-state">No batteries configured</p>';
    container.classList.remove('hidden');
    return;
  }
  
  let device;
  if (state.currentBattery) {
    device = state.devices.find(d => d.device_id === state.currentBattery);
  }
  if (!device && state.devices.length > 0) {
    device = state.devices[0];
    state.currentBattery = device.device_id;
  }
  
  if (!device) return;
  
  container.classList.remove('hidden');
  
  // Summary tab
  const m = device.metrics;
  document.getElementById('batt-soc').textContent = m.soc != null ? `${m.soc}%` : '—';
  document.getElementById('batt-voltage').textContent = m.voltage != null ? `${m.voltage.toFixed(2)}V` : '—';
  document.getElementById('batt-current').textContent = m.current != null ? `${m.current.toFixed(2)}A` : '—';
  document.getElementById('batt-power').textContent = m.power != null ? `${m.power.toFixed(0)}W` : '—';
  document.getElementById('batt-temp1').textContent = m.temp1 != null ? `${m.temp1.toFixed(1)}°C` : '—';
  document.getElementById('batt-temp2').textContent = m.temp2 != null ? `${m.temp2.toFixed(1)}°C` : '—';
  
  // Cells tab
  const cellContainer = document.getElementById('cell-container');
  const cells = [];
  for (let i = 1; i <= 16; i++) {
    const v = m[`cell_${i.toString().padStart(2, '0')}_v`];
    cells.push({ num: i, v: v || 0 });
  }
  const validCells = cells.filter(c => c.v > 0.1);
  const minV = validCells.length ? Math.min(...validCells.map(c => c.v)) : 0;
  const maxV = validCells.length ? Math.max(...validCells.map(c => c.v)) : 0;
  const delta = (maxV - minV) * 1000;
  const avg = validCells.length ? validCells.reduce((a,c) => a+c.v, 0) / validCells.length : 0;
  
  cellContainer.innerHTML = cells.map(c => {
    const cls = c.v === minV && minV > 0 ? 'cell-min' : (c.v === maxV && maxV > 0 ? 'cell-max' : '');
    return `<div class="cell-tile ${cls}">
      <div class="cell-number">Cell ${c.num}</div>
      <div class="cell-value">${c.v > 0.1 ? c.v.toFixed(3) : '—'}</div>
    </div>`;
  }).join('');
  
  document.getElementById('cell-min').textContent = `Min: ${minV.toFixed(3)}V`;
  document.getElementById('cell-max').textContent = `Max: ${maxV.toFixed(3)}V`;
  document.getElementById('cell-delta').textContent = `Delta: ${delta.toFixed(0)}mV`;
  document.getElementById('cell-avg').textContent = `Avg: ${avg.toFixed(3)}V`;
  
  // Settings tab (placeholder)
  document.getElementById('settings-tbody').innerHTML = `
    <tr><td>Cell Undervoltage</td><td>—</td><td>Not yet supported</td></tr>
    <tr><td>Cell Overvoltage</td><td>—</td><td>Not yet supported</td></tr>
    <tr><td>Charge Current</td><td>—</td><td>Not yet supported</td></tr>
  `;
  
  // Diagnostics
  document.getElementById('diagnostics-content').textContent = JSON.stringify({
    device_id: device.device_id,
    name: device.name,
    device_type: device.device_type,
    health: device.health,
    last_valid_read: device.last_valid_read ? new Date(device.last_valid_read * 1000).toISOString() : null,
    metrics: device.metrics,
  }, null, 2);
  
  // Tab handlers
  document.querySelectorAll('.tab').forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
    };
  });
}

// ─── History ───────────────────────────────────────────────

async function loadHistory() {
  const device = document.getElementById('history-device').value;
  const metric = document.getElementById('history-metric').value;
  const hours = document.getElementById('history-range').value;
  
  try {
    const resp = await fetch(`/api/history?hours=${hours}&metric=${metric}`);
    const data = await resp.json();
    drawChart(data.readings.reverse(), metric);
    document.getElementById('history-info').textContent = 
      `${data.count} data points | ${data.coverage} | ${new Date(data.start*1000).toLocaleString()} → ${new Date(data.end*1000).toLocaleString()}`;
  } catch (e) {
    console.error('History load failed:', e);
  }
}

function drawChart(readings, metric) {
  const canvas = document.getElementById('history-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  
  // Clear
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  
  if (readings.length === 0) {
    ctx.fillStyle = '#9ca3af';
    ctx.textAlign = 'center';
    ctx.fillText('No data available', canvas.width / 2, canvas.height / 2);
    return;
  }
  
  const padding = 40;
  const w = canvas.width - padding * 2;
  const h = canvas.height - padding * 2;
  
  const values = readings.map(r => r.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  
  // Grid
  ctx.strokeStyle = '#374151';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padding + (h / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(padding + w, y);
    ctx.stroke();
    
    // Y labels
    ctx.fillStyle = '#9ca3af';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'right';
    const val = max - (range / 4) * i;
    ctx.fillText(val.toFixed(1), padding - 5, y + 4);
  }
  
  // Line
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  ctx.beginPath();
  
  readings.forEach((r, i) => {
    const x = padding + (w / (readings.length - 1 || 1)) * i;
    const y = padding + h - ((r.value - min) / range) * h;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  
  // Title
  ctx.fillStyle = '#e5e7eb';
  ctx.font = '12px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(metric, padding, 15);
}

// ─── Compare ───────────────────────────────────────────────

function loadCompare() {
  const id1 = document.getElementById('compare-device-1').value;
  const id2 = document.getElementById('compare-device-2').value;
  const diffOnly = document.getElementById('differences-only').checked;
  
  const tbody = document.getElementById('compare-tbody');
  
  if (!id1 || !id2) {
    tbody.innerHTML = '<tr><td>Select two devices to compare</td></tr>';
    return;
  }
  
  const d1 = state.devices.find(d => d.device_id === id1);
  const d2 = state.devices.find(d => d.device_id === id2);
  
  if (!d1 || !d2) {
    tbody.innerHTML = '<tr><td>Device not found</td></tr>';
    return;
  }
  
  // Compare all metrics
  const allKeys = new Set([...Object.keys(d1.metrics), ...Object.keys(d2.metrics)]);
  const rows = [];
  
  allKeys.forEach(key => {
    const v1 = d1.metrics[key];
    const v2 = d2.metrics[key];
    
    const isDiff = v1 !== v2;
    if (diffOnly && !isDiff) return;
    
    rows.push(`<tr class="${isDiff ? 'diff' : ''}">
      <td>${key}</td>
      <td>${v1 != null ? (typeof v1 === 'number' ? v1.toFixed(3) : v1) : '—'}</td>
      <td>${v2 != null ? (typeof v2 === 'number' ? v2.toFixed(3) : v2) : '—'}</td>
    </tr>`);
  });
  
  tbody.innerHTML = rows.join('') || '<tr><td colspan="3">No differences found</td></tr>';
}

// ─── System ────────────────────────────────────────────────

function loadSystem() {
  // Ports config
  fetch('/api/ports').then(r => r.json()).then(data => {
    document.getElementById('ports-config').innerHTML = data.registered.map(p => 
      `<div class="metric">
        <label>${p.name || p.device}</label>
        <span>${p.health} | ${p.baudrate} | ${p.total_reads} reads</span>
        <button onclick="togglePort('${p.device}', ${!p.is_open})" class="btn btn-secondary">
          ${p.is_open ? 'Close' : 'Open'}
        </button>
      </div>`
    ).join('') || '<p>No ports configured</p>';
    
    // Available ports for add form
    const select = document.getElementById('new-port-device');
    if (select && data.available) {
      select.innerHTML = data.available.map(p => 
        `<option value="${p.device}">${p.device} (${p.description})</option>`
      ).join('') || '<option value="">No available ports</option>';
    }
  });
  
  // Stats
  fetch('/api/stats').then(r => r.json()).then(data => {
    document.getElementById('system-stats').textContent = JSON.stringify(data, null, 2);
  });
  
  // Audit log
  fetch('/api/audit?limit=20').then(r => r.json()).then(data => {
    document.getElementById('audit-log').innerHTML = data.map(a => 
      `<li>${new Date(a.timestamp * 1000).toLocaleString()} — ${a.action} ${a.port_name || ''} ${a.details || ''}</li>`
    ).join('') || '<li>No audit entries</li>';
  });
}

// ─── Forms ─────────────────────────────────────────────────

function initForms() {
  document.getElementById('add-port-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const data = {
      device: form.device.value,
      name: form.name.value,
      baudrate: parseInt(form.baudrate.value),
      protocol: form.protocol.value,
    };
    
    try {
      await fetch('/api/ports', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
      });
      form.reset();
      loadDevices();
    } catch (err) {
      alert('Failed to add port: ' + err);
    }
  });
  
  document.getElementById('battery-select')?.addEventListener('change', (e) => {
    state.currentBattery = e.target.value;
    loadBatteryDetail();
  });
  
  document.getElementById('history-range')?.addEventListener('change', loadHistory);
  document.getElementById('export-csv')?.addEventListener('click', exportCsv);
}

function togglePort(device, open) {
  const method = open ? 'POST' : 'POST';
  const endpoint = open ? `/api/ports/${device}/open` : `/api/ports/${data}/close`;
  fetch(endpoint, { method }).then(() => loadSystem());
}

function exportCsv() {
  loadHistory().then(() => {
    // Simple CSV export
    const readings = [];
    const device = document.getElementById('history-device').value;
    const metric = document.getElementById('history-metric').value;
    const hours = document.getElementById('history-range').value;
    
    fetch(`/api/history?hours=${hours}&metric=${metric}&device_id=${device}`)
      .then(r => r.json())
      .then(data => {
        const rows = ['timestamp,' + metric];
        data.readings.forEach(r => rows.push(`${r.timestamp},${r.value}`));
        const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${metric}_${hours}h.csv`;
        a.click();
      });
  });
}

// Initial load from URL
const hash = window.location.hash.replace('#', '');
if (hash) navigateTo(hash);
