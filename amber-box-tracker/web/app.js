/**
 * Amber Box Tracker — Frontend Application Core
 * Vanilla ES6+, Zero-build-step, Realtime SSE, Virtual Shelf Grid, Web Speech
 */

// ============================================================
// CONFIGURATION & SEED FALLBACK DATA
// ============================================================
const API_BASE = '';

const MOCK_CAMERAS = [
  { id: 'cam-01', name: 'Gate 1 Entrance', kind: 'gate', level: 1, status: 'live', fps: 10.4 },
  { id: 'cam-02', name: 'Hoist Lower Deck', kind: 'hoist', level: 1, status: 'live', fps: 9.8 },
  { id: 'cam-03', name: 'Floor 2 Hoist Landing', kind: 'floor_entrance', level: 2, status: 'live', fps: 11.2 },
  { id: 'cam-04', name: 'Aisle L2-B Storage', kind: 'aisle', level: 2, status: 'live', fps: 8.5 },
  { id: 'cam-05', name: 'Aisle L3-A Storage', kind: 'aisle', level: 3, status: 'live', fps: 9.1 }
];

const MOCK_CARTONS = [
  { id: 'c1', label_code: 'BV2401', item_name: '2in Stainless Ball Valve', po_number: 'PO-9912', dest_level: 2, dest_shelf_code: 'L2-B2', status: 'misplaced', last_seen_at: '2 mins ago', last_seen_level: 3, last_seen_shelf: 'L3-A1', last_seen_camera: 'Aisle L3-A Storage', last_snapshot: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="%231e293b"/><text x="150" y="100" fill="%23f59e0b" font-family="sans-serif" font-size="20" text-anchor="middle">BV2401 · 2in Valve</text></svg>' },
  { id: 'c2', label_code: 'DM0402', item_name: 'Diaphragm Valve 50mm', po_number: 'PO-9912', dest_level: 2, dest_shelf_code: 'L2-B1', status: 'in_transit', last_seen_at: '5 mins ago', last_seen_level: 1, last_seen_shelf: null, last_seen_camera: 'Gate 1 Entrance', last_snapshot: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="%231e293b"/><text x="150" y="100" fill="%233b82f6" font-family="sans-serif" font-size="20" text-anchor="middle">DM0402 · Diaphragm</text></svg>' },
  { id: 'c3', label_code: 'EF1105', item_name: 'Class 150 Blind Flange', po_number: 'PO-9915', dest_level: 2, dest_shelf_code: 'L2-B3', status: 'stored', last_seen_at: '12 mins ago', last_seen_level: 2, last_seen_shelf: 'L2-B3', last_seen_camera: 'Aisle L2-B Storage', last_snapshot: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="%231e293b"/><text x="150" y="100" fill="%2310b981" font-family="sans-serif" font-size="20" text-anchor="middle">EF1105 · Blind Flange</text></svg>' },
  { id: 'c4', label_code: 'FL8802', item_name: 'M16 Galvanised Hex Bolt Pk100', po_number: 'PO-9920', dest_level: 3, dest_shelf_code: 'L3-A1', status: 'stored', last_seen_at: '25 mins ago', last_seen_level: 3, last_seen_shelf: 'L3-A1', last_seen_camera: 'Aisle L3-A Storage', last_snapshot: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="%231e293b"/><text x="150" y="100" fill="%2310b981" font-family="sans-serif" font-size="20" text-anchor="middle">FL8802 · M16 Bolts</text></svg>' },
  { id: 'c5', label_code: 'EL5501', item_name: '25mm Steel Conduit 3m', po_number: 'PO-9925', dest_level: 3, dest_shelf_code: 'L3-A2', status: 'in_transit', last_seen_at: '30 mins ago', last_seen_level: 1, last_seen_shelf: null, last_seen_camera: 'Hoist Lower Deck', last_snapshot: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="%231e293b"/><text x="150" y="100" fill="%233b82f6" font-family="sans-serif" font-size="20" text-anchor="middle">EL5501 · Conduit</text></svg>' }
];

const MOCK_DELIVERIES = [
  {
    id: 'DEL-2211',
    event_name: 'Valves & High Pressure Fittings',
    date: '2026-11-25',
    supplier: 'Apex Flow Control Ltd',
    gate: 'Gate 1 North',
    status: 'pending',
    cartons: ['BV2401', 'DM0402', 'EF1105', 'BV2402', 'DM0403', 'EF1106']
  },
  {
    id: 'DEL-2190',
    event_name: 'Fasteners & Conduit Batch B',
    date: '2026-11-24',
    supplier: 'Metals & Hardware Direct',
    gate: 'Gate 2 Hoist',
    status: 'received',
    cartons: ['FL8802', 'EL5501', 'FL8803']
  }
];

let localAlerts = [
  {
    id: 'ALT-101',
    type: 'wrong_floor',
    status: 'open',
    carton_code: 'BV2401',
    item_name: '2in Stainless Ball Valve',
    message: 'Box BV2401 is on Floor 3 — belongs on Floor 2, shelf L2-B2.',
    snapshot_path: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="%231e293b"/><text x="150" y="100" fill="%23ef4444" font-family="sans-serif" font-size="16" text-anchor="middle">ALERT: BV2401 on Floor 3</text></svg>',
    created_at: '3 minutes ago',
    shelf_light_events: [{ shelf: 'L2-B2', cmd: 'blink', color: 'blue' }, { shelf: 'L3-A1', cmd: 'blink_red', color: 'red' }]
  }
];

// ============================================================
// APP STATE
// ============================================================
const appState = {
  activeTab: 'live',
  cameras: [],
  cartons: [],
  deliveries: [],
  alerts: [],
  selectedDeliveryId: 'DEL-2211',
  speechSynthesisEnabled: true,
  isRecognizing: false
};

// ============================================================
// INITIALIZATION
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  initLiveClock();
  initNavTabs();
  initAmberPanel();
  initCameras();
  initAlerts();
  initCartons();
  initReceive();
  initFindAndGrid();
  initSSEAlerts();
});

// Live Clock
function initLiveClock() {
  const clockEl = document.getElementById('liveClock');
  const update = () => {
    const now = new Date();
    clockEl.textContent = now.toTimeString().split(' ')[0] + ' UTC';
  };
  update();
  setInterval(update, 1000);
}

// Navigation Tabs
function initNavTabs() {
  const tabButtons = document.querySelectorAll('.nav-tab-btn');
  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.getAttribute('data-tab');
      switchTab(targetTab);
    });
  });
}

function switchTab(tabId) {
  appState.activeTab = tabId;
  document.querySelectorAll('.nav-tab-btn').forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-tab') === tabId);
  });
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.toggle('active', pane.id === `tab-${tabId}`);
  });
}

// ============================================================
// TAB 1: CAMERAS & STREAMS
// ============================================================
async function initCameras() {
  const container = document.getElementById('camerasGrid');
  try {
    const res = await fetch(`${API_BASE}/api/cameras`);
    if (res.ok) {
      const payload = await res.json();
      appState.cameras = Array.isArray(payload) ? payload : (payload.cameras || MOCK_CAMERAS);
    } else {
      appState.cameras = MOCK_CAMERAS;
    }
  } catch (e) {
    appState.cameras = MOCK_CAMERAS;
  }

  renderCameras(container);

  document.getElementById('refreshCamerasBtn').addEventListener('click', () => {
    initCameras();
  });
}

function renderCameras(container) {
  container.innerHTML = '';
  appState.cameras.forEach(cam => {
    const tile = document.createElement('div');
    tile.className = 'camera-tile';
    tile.id = `tile-${cam.id}`;

    const isLive = cam.status === 'live';
    const statusClass = isLive ? 'live' : 'no-signal';
    const statusText = isLive ? 'LIVE' : 'NO SIGNAL';

    tile.innerHTML = `
      <div class="camera-tile-header">
        <div class="camera-name-group">
          <div class="camera-name">${escapeHTML(cam.name)}</div>
          <span class="camera-level-badge">Floor ${cam.level || 1} · ${escapeHTML(cam.kind || 'cctv')}</span>
        </div>
        <div class="status-pill ${statusClass}">
          <span class="status-dot ${isLive ? 'pulsing' : ''}"></span>
          <span>${statusText}</span>
        </div>
      </div>
      <div class="camera-viewport">
        ${isLive ? `
          <img id="img-${cam.id}" src="${API_BASE}/api/cameras/${cam.id}/mjpeg?t=${Date.now()}" alt="${escapeHTML(cam.name)}" onerror="handleCameraStreamFallback(this, '${escapeHTML(cam.name)}')">
        ` : `
          <div class="camera-offline-placeholder">
            <svg fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
            <div>Camera Stream Offline</div>
          </div>
        `}
        <div class="camera-overlay-info">
          <span>FPS: <strong id="fps-${cam.id}">${cam.fps || 0}</strong></span>
          <span>${cam.id.toUpperCase()}</span>
        </div>
      </div>
      <div class="camera-source-bar" style="display:flex;gap:8px;padding:8px 12px;border-top:1px solid #1e293b;align-items:center;">
        <select id="src-${cam.id}" style="flex:1;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 8px;font-size:12px;">
          <option value="file:videos/01_gate_pov.mp4">Demo Video 01 (Gate POV)</option>
          <option value="file:videos/02_wrong_floor.mp4">Demo Video 02 (Wrong Floor)</option>
          <option value="file:videos/03_shelf.mp4">Demo Video 03 (Shelf)</option>
          <option value="webcam:0">Live Webcam (0)</option>
          <option value="push">Phone / POV Push (/m)</option>
        </select>
        <button onclick="switchCameraSource('${cam.id}')" style="background:#0284c7;color:#fff;border:none;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer;font-weight:600;">Switch</button>
      </div>
    `;
    container.appendChild(tile);
  });
}

window.switchCameraSource = async function(camId) {
  const sel = document.getElementById(`src-${camId}`);
  if (!sel) return;
  try {
    const res = await fetch(`${API_BASE}/api/cameras/${camId}/source`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: sel.value }),
    });
    if (res.ok) {
      await initCameras();
    }
  } catch (e) {
    console.error('Switch source failed', e);
  }
};

window.handleCameraStreamFallback = function(imgEl, camName) {
  imgEl.onerror = null;
  // Render simulated fallback graphic with time and camera label
  imgEl.src = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="%230f172a"/><circle cx="320" cy="180" r="40" fill="%231e293b"/><text x="320" y="185" fill="%2394a3b8" font-family="monospace" font-size="16" text-anchor="middle">STREAM SIMULATION</text><text x="320" y="220" fill="%2364748b" font-family="sans-serif" font-size="14" text-anchor="middle">${camName}</text></svg>`;
};

// ============================================================
// TAB 2: ALERTS & REAL-TIME SSE
// ============================================================
async function initAlerts() {
  const listEl = document.getElementById('alertsList');
  const typeFilter = document.getElementById('alertTypeFilter');
  const statusFilter = document.getElementById('alertStatusFilter');

  try {
    const res = await fetch(`${API_BASE}/api/alerts`);
    if (res.ok) {
      const data = await res.json();
      appState.alerts = Array.isArray(data) ? data : localAlerts;
    } else {
      appState.alerts = localAlerts;
    }
  } catch (e) {
    appState.alerts = localAlerts;
  }

  renderAlerts();

  typeFilter.addEventListener('change', renderAlerts);
  statusFilter.addEventListener('change', renderAlerts);
  document.getElementById('refreshAlertsBtn').addEventListener('click', initAlerts);

  // Modal handlers
  document.getElementById('closeResolveModalBtn').addEventListener('click', () => {
    document.getElementById('resolveAlertModal').classList.remove('active');
  });
  document.getElementById('cancelResolveBtn').addEventListener('click', () => {
    document.getElementById('resolveAlertModal').classList.remove('active');
  });
  document.getElementById('confirmResolveBtn').addEventListener('click', handleConfirmResolve);
}

function renderAlerts() {
  const listEl = document.getElementById('alertsList');
  const typeFilter = document.getElementById('alertTypeFilter').value;
  const statusFilter = document.getElementById('alertStatusFilter').value;

  const filtered = appState.alerts.filter(a => {
    if (typeFilter !== 'all' && a.type !== typeFilter) return false;
    if (statusFilter !== 'all' && a.status !== statusFilter) return false;
    return true;
  });

  const badge = document.getElementById('alertsBadgeCount');
  const openCount = appState.alerts.filter(a => a.status === 'open').length;
  badge.textContent = openCount;
  badge.style.display = openCount > 0 ? 'inline-block' : 'none';

  listEl.innerHTML = '';
  if (filtered.length === 0) {
    listEl.innerHTML = `<div style="padding: 30px; text-align: center; color: var(--text-dim); background: var(--bg-secondary); border-radius: 8px;">No alerts matching current filters.</div>`;
    return;
  }

  filtered.forEach(alert => {
    const card = document.createElement('div');
    card.className = `alert-card type-${alert.type}`;
    card.id = `alert-${alert.id}`;

    const isResolved = alert.status === 'resolved';

    card.innerHTML = `
      <img src="${alert.snapshot_path || alert.snapshot || 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="75"><rect width="100" height="75" fill="%231e293b"/></svg>'}" class="alert-snapshot" alt="Snapshot" onclick="showSnapshotModal('${alert.snapshot_path || ''}')">
      <div class="alert-details">
        <div class="alert-meta">
          <span class="alert-type-tag ${alert.type === 'wrong_floor' || alert.type === 'wrong_shelf' ? '' : 'warning'}">${alert.type.replace('_', ' ')}</span>
          <span class="status-pill ${isResolved ? 'success' : 'danger'}">${alert.status}</span>
          <span class="alert-time">${alert.created_at || 'Just now'}</span>
        </div>
        <div class="alert-message">${escapeHTML(alert.message)}</div>
        <div class="alert-carton-tag">Carton: ${escapeHTML(alert.carton_code || alert.carton_id || 'UNKNOWN')}</div>
      </div>
      <div class="alert-actions">
        ${!isResolved ? `
          <button class="btn btn-success btn-sm" onclick="openResolveModal('${alert.id}')">Resolve</button>
          <button class="btn btn-outline btn-sm" onclick="openResolveModal('${alert.id}', true)">Change Dest</button>
        ` : `
          <span style="font-size: 11px; color: var(--color-green);">✓ Resolved (${escapeHTML(alert.resolved_note || 'Closed')})</span>
        `}
      </div>
    `;
    listEl.appendChild(card);
  });
}

function initSSEAlerts() {
  try {
    const eventSource = new EventSource(`${API_BASE}/api/alerts/stream`);
    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleIncomingAlert(payload);
      } catch (err) {
        console.warn('Failed to parse SSE alert:', err);
      }
    };
    eventSource.onerror = () => {
      // Reconnection handled automatically by browser EventSource
    };
  } catch (e) {
    console.log('SSE not available on current origin, operating with local state');
  }
}

function handleIncomingAlert(alert) {
  // Add to top of list
  appState.alerts.unshift(alert);
  renderAlerts();

  // Slide-in Toast notification
  showToast(alert);

  // Trigger Shelf Grid animation if alert provides target shelf lights
  if (alert.shelf_light_events && Array.isArray(alert.shelf_light_events)) {
    alert.shelf_light_events.forEach(ev => {
      const stateMap = {
        'blink': 'pulse-blue',
        'blink_red': 'pulse-red',
        'ack': 'flash-green',
        'off': 'off'
      };
      setVirtualShelfState(ev.shelf, stateMap[ev.cmd] || 'pulse-red', 25);
    });
  }

  // Voice speech announcement
  if (document.getElementById('amberSpeakToggle').checked && window.speechSynthesis) {
    speakText(`Alert: ${alert.message}`);
  }
}

function showToast(alert) {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  const isDanger = alert.type === 'wrong_floor' || alert.type === 'wrong_shelf';
  toast.className = `toast ${isDanger ? 'danger' : ''}`;

  toast.innerHTML = `
    <img src="${alert.snapshot_path || 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="%23334155"/></svg>'}" class="toast-thumb">
    <div class="toast-content">
      <div class="toast-title">${alert.type.replace('_', ' ')}</div>
      <div class="toast-msg">${escapeHTML(alert.message)}</div>
      <div class="toast-time">Just now</div>
    </div>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    setTimeout(() => toast.remove(), 400);
  }, 7000);
}

window.openResolveModal = function(alertId, isChangeDest = false) {
  document.getElementById('resolveAlertId').value = alertId;
  document.getElementById('resolveNoteInput').value = isChangeDest ? 'Rerouted destination per warehouse supervisor' : 'Carton corrected and moved to proper location';
  document.getElementById('resolveAlertModal').classList.add('active');
};

async function handleConfirmResolve() {
  const alertId = document.getElementById('resolveAlertId').value;
  const note = document.getElementById('resolveNoteInput').value;
  const newShelf = document.getElementById('resolveNewShelfSelect').value;

  try {
    await fetch(`${API_BASE}/api/alerts/${alertId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: note, new_dest_shelf_id: newShelf || null })
    });
  } catch (e) {
    console.log('Resolving locally');
  }

  // Local update
  const target = appState.alerts.find(a => a.id == alertId);
  if (target) {
    target.status = 'resolved';
    target.resolved_note = note;
  }
  document.getElementById('resolveAlertModal').classList.remove('active');
  renderAlerts();
  showToast({
    type: 'success',
    message: `Alert ${alertId} resolved. Shelf lights cleared.`,
    created_at: 'Now'
  });
}

// ============================================================
// TAB 3: CARTONS INVENTORY & TIMELINE
// ============================================================
async function initCartons() {
  const tbody = document.getElementById('cartonsTableBody');
  const searchInput = document.getElementById('cartonSearchInput');

  try {
    const res = await fetch(`${API_BASE}/api/cartons`);
    if (res.ok) {
      appState.cartons = await res.json();
    } else {
      appState.cartons = MOCK_CARTONS;
    }
  } catch (e) {
    appState.cartons = MOCK_CARTONS;
  }

  renderCartonsTable(appState.cartons);

  searchInput.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase().trim();
    const filtered = appState.cartons.filter(c =>
      c.label_code.toLowerCase().includes(q) ||
      c.item_name.toLowerCase().includes(q) ||
      (c.po_number && c.po_number.toLowerCase().includes(q))
    );
    renderCartonsTable(filtered);
  });

  // Timeline modal close
  document.getElementById('closeTimelineModalBtn').addEventListener('click', () => {
    document.getElementById('timelineModal').classList.remove('active');
  });
}

function renderCartonsTable(cartons) {
  const tbody = document.getElementById('cartonsTableBody');
  tbody.innerHTML = '';

  if (cartons.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 30px;">No cartons found.</td></tr>`;
    return;
  }

  cartons.forEach(c => {
    const tr = document.createElement('tr');
    const statusMap = {
      'stored': 'success',
      'in_transit': 'warning',
      'received': 'warning',
      'misplaced': 'danger',
      'damaged': 'danger'
    };
    const pillClass = statusMap[c.status] || 'warning';

    tr.innerHTML = `
      <td class="code-cell">${escapeHTML(c.label_code)}</td>
      <td><strong>${escapeHTML(c.item_name)}</strong></td>
      <td style="font-family: var(--font-mono); color: var(--text-muted);">${escapeHTML(c.po_number || 'N/A')}</td>
      <td>Floor ${c.dest_level} · <strong style="color: var(--color-blue);">${escapeHTML(c.dest_shelf_code || 'TBD')}</strong></td>
      <td><span class="status-pill ${pillClass}">${c.status}</span></td>
      <td>${escapeHTML(c.last_seen_camera || 'N/A')} (${escapeHTML(c.last_seen_at || 'Just now')})</td>
      <td>
        <button class="btn btn-outline btn-sm" onclick="openCartonTimeline('${c.label_code}')">Timeline</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

window.openCartonTimeline = async function(code) {
  const modal = document.getElementById('timelineModal');
  const title = document.getElementById('timelineModalTitle');
  const chain = document.getElementById('timelineChainContainer');

  title.textContent = `Carton Sighting Timeline — ${code}`;
  chain.innerHTML = '<div style="color: var(--text-muted); padding: 20px;">Loading sighting breadcrumbs...</div>';
  modal.classList.add('active');

  let sightings = [];
  try {
    const res = await fetch(`${API_BASE}/api/cartons/${code}/timeline`);
    if (res.ok) {
      sightings = await res.json();
    }
  } catch (e) {}

  if (!sightings || sightings.length === 0) {
    // Generate logical timeline stages for demo
    sightings = [
      { camera_name: 'Gate 1 Entrance', level: 1, source: 'cctv', seen_at: '14:02:11', snapshot_path: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120"><rect width="200" height="120" fill="%231e293b"/><text x="100" y="65" fill="%23f59e0b" font-family="sans-serif" font-size="14" text-anchor="middle">Gate Sighting</text></svg>' },
      { camera_name: 'Hoist Lower Deck', level: 1, source: 'cctv', seen_at: '14:08:44', snapshot_path: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120"><rect width="200" height="120" fill="%231e293b"/><text x="100" y="65" fill="%233b82f6" font-family="sans-serif" font-size="14" text-anchor="middle">Hoist Transfer</text></svg>' },
      { camera_name: 'Floor 2 Hoist Landing', level: 2, source: 'cctv', seen_at: '14:14:02', snapshot_path: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120"><rect width="200" height="120" fill="%231e293b"/><text x="100" y="65" fill="%2310b981" font-family="sans-serif" font-size="14" text-anchor="middle">Floor Landing</text></svg>' },
      { camera_name: 'Aisle L2-B Storage', level: 2, shelf: 'L2-B2', source: 'cctv', seen_at: '14:19:30', snapshot_path: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120"><rect width="200" height="120" fill="%231e293b"/><text x="100" y="65" fill="%2310b981" font-family="sans-serif" font-size="14" text-anchor="middle">Shelf Put-Away</text></svg>' }
    ];
  }

  chain.innerHTML = '';
  sightings.forEach((s, idx) => {
    const isLast = idx === sightings.length - 1;
    const step = document.createElement('div');
    step.className = `timeline-step ${isLast ? 'completed' : ''}`;
    step.innerHTML = `
      <div class="timeline-step-dot"></div>
      <div class="timeline-card">
        <img src="${s.snapshot_path}" class="timeline-img" alt="Sighting Frame">
        <div style="flex: 1;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <strong style="font-size: 14px; color: var(--text-main);">${escapeHTML(s.camera_name)}</strong>
            <span style="font-family: var(--font-mono); font-size: 12px; color: var(--text-dim);">${escapeHTML(s.seen_at)}</span>
          </div>
          <div style="font-size: 12.5px; color: var(--text-muted); line-height: 1.5;">
            Floor: <strong>${s.level}</strong> ${s.shelf ? `· Shelf: <strong style="color: var(--color-blue);">${s.shelf}</strong>` : ''}<br>
            Detection Source: <span style="text-transform: uppercase; font-size: 11px; background: rgba(255,255,255,0.08); padding: 1px 6px; border-radius: 4px;">${s.source}</span>
          </div>
        </div>
      </div>
    `;
    chain.appendChild(step);
  });
};

// ============================================================
// TAB 4: RECEIVE DELIVERIES
// ============================================================
async function initReceive() {
  const select = document.getElementById('deliverySelect');
  const metaCard = document.getElementById('deliveryMetaCard');
  const printBtn = document.getElementById('printLabelsBtn');
  const markBtn = document.getElementById('markReceivedBtn');

  try {
    const res = await fetch(`${API_BASE}/api/deliveries`);
    if (res.ok) {
      appState.deliveries = await res.json();
    } else {
      appState.deliveries = MOCK_DELIVERIES;
    }
  } catch (e) {
    appState.deliveries = MOCK_DELIVERIES;
  }

  select.innerHTML = '';
  appState.deliveries.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d.id;
    opt.textContent = `${d.id} — ${d.event_name}`;
    select.appendChild(opt);
  });

  select.addEventListener('change', () => {
    appState.selectedDeliveryId = select.value;
    updateReceiveView();
  });

  printBtn.addEventListener('click', (e) => {
    e.preventDefault();
    const delId = appState.selectedDeliveryId;
    window.open(`${API_BASE}/api/labels/cartons.pdf?delivery_id=${delId}`, '_blank');
  });

  markBtn.addEventListener('click', async () => {
    const delId = appState.selectedDeliveryId;
    markBtn.textContent = 'Processing...';
    try {
      await fetch(`${API_BASE}/api/deliveries/${delId}/receive`, { method: 'POST' });
    } catch (e) {}

    markBtn.textContent = '✅ Marked Received';
    showToast({
      type: 'success',
      message: `Delivery ${delId} marked as received at Gate.`,
      created_at: 'Now'
    });
    setTimeout(() => {
      markBtn.textContent = '✅ Mark Received (Gate In)';
    }, 2500);
  });

  updateReceiveView();
}

function updateReceiveView() {
  const current = appState.deliveries.find(d => d.id === appState.selectedDeliveryId) || appState.deliveries[0];
  if (!current) return;

  const metaCard = document.getElementById('deliveryMetaCard');
  metaCard.innerHTML = `
    <div>Supplier: <strong style="color: var(--text-main);">${escapeHTML(current.supplier || 'N/A')}</strong></div>
    <div>Date: <strong style="color: var(--text-main);">${escapeHTML(current.date)}</strong></div>
    <div>Gate: <strong style="color: var(--text-main);">${escapeHTML(current.gate)}</strong></div>
    <div>Intake Status: <span class="status-pill ${current.status === 'received' ? 'success' : 'warning'}" style="font-size: 11px; padding: 2px 6px;">${current.status}</span></div>
  `;

  document.getElementById('manifestSummaryBadge').textContent = `${(current.cartons || []).length} Cartons Expected`;

  const tbody = document.getElementById('receiveManifestBody');
  tbody.innerHTML = '';
  (current.cartons || []).forEach(code => {
    const carton = appState.cartons.find(c => c.label_code === code) || {
      label_code: code,
      item_name: 'Scheduled Inventory Carton',
      dest_level: 2,
      dest_shelf_code: 'L2-B2',
      status: 'pending'
    };

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="code-cell">${carton.label_code}</td>
      <td>${escapeHTML(carton.item_name)}</td>
      <td>Floor ${carton.dest_level} · <strong style="color: var(--color-blue);">${carton.dest_shelf_code}</strong></td>
      <td><span class="status-pill ${carton.status === 'stored' ? 'success' : 'warning'}">${carton.status}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

// ============================================================
// TAB 5: FIND & VIRTUAL SHELF GRID
// ============================================================
function initFindAndGrid() {
  const input = document.getElementById('findSearchInput');
  const submitBtn = document.getElementById('findSubmitBtn');
  const micBtn = document.getElementById('findMicBtn');

  submitBtn.addEventListener('click', () => executeFind(input.value));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') executeFind(input.value);
  });

  // Web Speech API for Search
  if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.lang = 'en-US';

    micBtn.addEventListener('click', () => {
      if (appState.isRecognizing) {
        recognition.stop();
        micBtn.classList.remove('active');
        appState.isRecognizing = false;
      } else {
        recognition.start();
        micBtn.classList.add('active');
        appState.isRecognizing = true;
      }
    });

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      input.value = transcript;
      executeFind(transcript);
    };

    recognition.onend = () => {
      micBtn.classList.remove('active');
      appState.isRecognizing = false;
    };
  } else {
    micBtn.title = 'Speech recognition not supported on this browser';
  }

  // Virtual shelf clicks to test
  document.querySelectorAll('.shelf-slot').forEach(slot => {
    slot.addEventListener('click', () => {
      const code = slot.getAttribute('data-shelf');
      setVirtualShelfState(code, 'pulse-blue', 10);
      showToast({
        type: 'info',
        message: `Testing shelf beacon for ${code}`,
        created_at: 'Now'
      });
    });
  });

  // Test grid blink
  document.getElementById('testBlinkAllBtn').addEventListener('click', () => {
    setVirtualShelfState('L2-B2', 'pulse-blue', 8);
    setVirtualShelfState('L3-A1', 'pulse-red', 8);
    setVirtualShelfState('L2-B3', 'flash-green', 4);
  });
}

async function executeFind(query) {
  if (!query || !query.trim()) return;
  const container = document.getElementById('findResultsContainer');
  const list = document.getElementById('findResultsList');
  container.style.display = 'block';
  list.innerHTML = '<div style="color: var(--text-muted); padding: 10px;">Searching inventory records...</div>';

  let results = [];
  try {
    const res = await fetch(`${API_BASE}/api/find?q=${encodeURIComponent(query)}`);
    if (res.ok) {
      results = await res.json();
    }
  } catch (e) {}

  if (!results || results.length === 0) {
    const q = query.toLowerCase();
    results = appState.cartons.filter(c =>
      c.label_code.toLowerCase().includes(q) ||
      c.item_name.toLowerCase().includes(q) ||
      (c.po_number && c.po_number.toLowerCase().includes(q))
    );
  }

  list.innerHTML = '';
  if (results.length === 0) {
    list.innerHTML = `<div style="color: var(--text-dim); padding: 14px;">No items matching "${escapeHTML(query)}".</div>`;
    return;
  }

  results.forEach(item => {
    const card = document.createElement('div');
    card.className = 'card';
    card.style.display = 'flex';
    card.style.flexDirection = 'column';
    card.style.gap = '10px';

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: flex-start;">
        <div>
          <span class="code-cell" style="font-size: 16px;">${escapeHTML(item.label_code)}</span>
          <div style="font-weight: 700; font-size: 14px; margin-top: 2px;">${escapeHTML(item.item_name)}</div>
        </div>
        <span class="status-pill ${item.status === 'stored' ? 'success' : 'warning'}">${item.status}</span>
      </div>
      <div style="font-size: 12.5px; color: var(--text-muted); line-height: 1.5;">
        Destination: <strong>Floor ${item.dest_level} · Shelf ${item.dest_shelf_code}</strong><br>
        Last Seen: ${escapeHTML(item.last_seen_camera || 'Gate')} (${escapeHTML(item.last_seen_at || 'Recently')})
      </div>
      <button class="btn btn-primary" onclick="locateCarton('${item.label_code}', '${item.dest_shelf_code}')">
        💡 Light It Up (Blink Shelf)
      </button>
    `;
    list.appendChild(card);
  });
}

window.locateCarton = async function(code, shelfCode) {
  // Call locate API
  try {
    await fetch(`${API_BASE}/api/cartons/${code}/locate`, { method: 'POST' });
  } catch (e) {}

  // Pulse Virtual Shelf Grid
  setVirtualShelfState(shelfCode, 'pulse-blue', 30);

  showToast({
    type: 'success',
    message: `Locating ${code}: Shelf light ${shelfCode} pulsing blue.`,
    created_at: 'Now'
  });

  if (document.getElementById('amberSpeakToggle').checked) {
    speakText(`Carton ${code} located. Shelf light ${shelfCode} is flashing blue.`);
  }
};

function setVirtualShelfState(shelfCode, stateClass, durationSec = 20) {
  const slot = document.getElementById(`shelf-${shelfCode}`);
  if (!slot) return;

  slot.classList.remove('pulse-blue', 'pulse-red', 'flash-green');
  if (stateClass !== 'off') {
    slot.classList.add(stateClass);
    if (durationSec > 0) {
      setTimeout(() => {
        slot.classList.remove(stateClass);
      }, durationSec * 1000);
    }
  }
}

// ============================================================
// GLOBAL AMBER AI CHAT PANEL
// ============================================================
function initAmberPanel() {
  const form = document.getElementById('amberChatForm');
  const input = document.getElementById('amberChatInput');
  const micBtn = document.getElementById('amberMicBtn');

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (query) {
      sendAmberMessage(query);
      input.value = '';
    }
  });

  // Speech Recognition for Amber
  if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.lang = 'en-US';

    micBtn.addEventListener('click', () => {
      if (appState.isRecognizing) {
        recognition.stop();
        micBtn.classList.remove('active');
        appState.isRecognizing = false;
      } else {
        recognition.start();
        micBtn.classList.add('active');
        appState.isRecognizing = true;
      }
    });

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      input.value = transcript;
      sendAmberMessage(transcript);
    };

    recognition.onend = () => {
      micBtn.classList.remove('active');
      appState.isRecognizing = false;
    };
  }
}

async function sendAmberMessage(text, confirm = false) {
  appendChatMessage('user', text);

  // Send request to Amber backend
  try {
    const res = await fetch(`${API_BASE}/api/amber/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, confirm: confirm })
    });

    if (res.ok) {
      const data = await res.json();
      appendChatMessage('amber', data.reply, data.tool_calls, data.needs_confirmation, data.prompt);
      if (document.getElementById('amberSpeakToggle').checked) {
        speakText(data.reply);
      }
      return;
    }
  } catch (e) {
    console.log('Amber API offline, executing local conversational fallback');
  }

  // Offline intelligent rule-based Amber fallback
  handleOfflineAmberReply(text);
}

function handleOfflineAmberReply(text) {
  const t = text.toLowerCase();
  let reply = "I'm checking the warehouse registry.";
  let tool = null;
  let needsConfirm = false;

  if (t.includes('where') || t.includes('find') || t.includes('bv2401')) {
    tool = 'where_does_this_go(BV2401)';
    reply = 'Box BV2401 belongs on Floor 2, shelf L2-B2. It was last spotted on Floor 3.';
    setVirtualShelfState('L2-B2', 'pulse-blue', 20);
  } else if (t.includes('light') || t.includes('blink') || t.includes('locate')) {
    tool = 'find_carton(auto_locate=True)';
    reply = 'Pulsing shelf light L2-B2 in blue for the next 30 seconds.';
    setVirtualShelfState('L2-B2', 'pulse-blue', 30);
  } else if (t.includes('damage') || t.includes('crush') || t.includes('wet')) {
    tool = 'report_damage(BV2401)';
    needsConfirm = true;
    reply = 'I detected a damage report request for carton BV2401.';
  } else if (t.includes('delivery') || t.includes('del-2211')) {
    tool = 'delivery_status(DEL-2211)';
    reply = 'Delivery DEL-2211 expects 6 cartons. 5 are received at Gate 1; 1 is pending.';
  } else {
    reply = 'I am Amber. You can ask where cartons go, to light up shelves, or report damage.';
  }

  appendChatMessage('amber', reply, tool ? [tool] : null, needsConfirm, needsConfirm ? 'Confirm marking BV2401 as damaged?' : null);
  if (document.getElementById('amberSpeakToggle').checked) {
    speakText(reply);
  }
}

function appendChatMessage(sender, text, toolCalls = null, needsConfirmation = false, confirmPrompt = null) {
  const chatBody = document.getElementById('amberChatBody');
  const msg = document.createElement('div');
  msg.className = `chat-msg ${sender}`;

  let content = `<div>${escapeHTML(text)}</div>`;

  if (toolCalls && Array.isArray(toolCalls)) {
    toolCalls.forEach(tc => {
      content += `<div class="tool-badge">🔧 ${escapeHTML(typeof tc === 'string' ? tc : JSON.stringify(tc))}</div>`;
    });
  }

  if (needsConfirmation) {
    content += `
      <div class="confirmation-card">
        <p>${escapeHTML(confirmPrompt || 'Confirm this action?')}</p>
        <div class="confirmation-actions">
          <button class="btn btn-success btn-sm" onclick="sendAmberMessage('Confirmed', true)">Yes, Confirm</button>
          <button class="btn btn-outline btn-sm" onclick="appendChatMessage('amber', 'Action cancelled.')">Cancel</button>
        </div>
      </div>
    `;
  }

  msg.innerHTML = content;
  chatBody.appendChild(msg);
  chatBody.scrollTop = chatBody.scrollHeight;
}

function speakText(text) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.05;
  utterance.pitch = 1.0;
  window.speechSynthesis.speak(utterance);
}

// Utility: HTML escape
function escapeHTML(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
