#!/usr/bin/env python3
"""Small browser GUI for viewing and labeling ROS occupancy-grid maps."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
from zipfile import ZipFile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree as ET
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = ROOT / "maps"
DIRECTORY_FILE = ROOT / "data" / "seic_public_directory_with_schedule.xlsx"
XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Map Labeler</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f3;
      --panel: #ffffff;
      --ink: #1d2525;
      --muted: #64706d;
      --line: #cfd8d4;
      --accent: #0b6f85;
      --accent-strong: #064c5b;
      --danger: #b23a48;
      --shadow: 0 8px 24px rgba(20, 32, 31, .12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font: 14px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }
    button, input, select {
      font: inherit;
    }
    button, select, input {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      min-height: 34px;
    }
    button {
      padding: 0 10px;
      cursor: pointer;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    button.primary:hover { background: var(--accent-strong); }
    button.danger { color: var(--danger); }
    button:disabled {
      opacity: .45;
      cursor: not-allowed;
    }
    input, select {
      padding: 0 9px;
    }
    .app {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      min-height: 100vh;
    }
    .main {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      min-width: 0;
    }
    .toolbar, .status {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, .88);
      backdrop-filter: blur(6px);
    }
    .status {
      border-top: 1px solid var(--line);
      border-bottom: 0;
      color: var(--muted);
      min-height: 43px;
    }
    .toolbar .grow { flex: 1; }
    .viewer {
      position: relative;
      overflow: auto;
      background:
        linear-gradient(45deg, #dfe6e2 25%, transparent 25%),
        linear-gradient(-45deg, #dfe6e2 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #dfe6e2 75%),
        linear-gradient(-45deg, transparent 75%, #dfe6e2 75%);
      background-size: 24px 24px;
      background-position: 0 0, 0 12px, 12px -12px, -12px 0;
    }
    .canvas-wrap {
      width: max-content;
      min-width: 100%;
      min-height: 100%;
      padding: 24px;
    }
    canvas {
      display: block;
      image-rendering: pixelated;
      background: #fff;
      box-shadow: var(--shadow);
      transform-origin: top left;
    }
    aside {
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      border-left: 1px solid var(--line);
      background: var(--panel);
      min-height: 100vh;
    }
    .side-section {
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .side-title {
      margin: 0 0 8px;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: .04em;
    }
    .form-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    .label-list {
      overflow: auto;
      padding: 8px 8px 12px;
    }
    .label-item {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 0 0 8px;
      background: #fbfcfb;
    }
    .label-item.active {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(11, 111, 133, .16);
    }
    .label-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 650;
    }
    .label-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }
    .empty {
      padding: 16px 8px;
      color: var(--muted);
      text-align: center;
    }
    @media (max-width: 860px) {
      .app { grid-template-columns: 1fr; }
      aside {
        min-height: 360px;
        border-left: 0;
        border-top: 1px solid var(--line);
      }
      .toolbar { flex-wrap: wrap; }
    }
  </style>
</head>
<body>
  <div class="app">
    <main class="main">
      <div class="toolbar">
        <select id="mapSelect" title="Map"></select>
        <button id="reloadBtn" title="Reload map">Reload</button>
        <button id="zoomOutBtn" title="Zoom out">-</button>
        <button id="zoomInBtn" title="Zoom in">+</button>
        <button id="fitBtn" title="Fit map">Fit</button>
        <span class="grow"></span>
        <button id="saveBtn" class="primary" title="Save labels">Save</button>
        <button id="exportBtn" title="Export annotated PNG">Export PNG</button>
      </div>
      <div id="viewer" class="viewer">
        <div class="canvas-wrap">
          <canvas id="mapCanvas"></canvas>
        </div>
      </div>
      <div id="status" class="status">Loading maps...</div>
    </main>
    <aside>
      <section class="side-section">
        <h2 class="side-title">Add Label</h2>
        <div class="form-row">
          <select id="labelSelect" title="Label"></select>
          <button id="addModeBtn" class="primary">Place</button>
        </div>
      </section>
      <section class="side-section">
        <h2 class="side-title">Selected</h2>
        <div class="form-row">
          <input id="editInput" placeholder="Select a label" autocomplete="off" disabled />
          <button id="renameBtn" disabled>Rename</button>
        </div>
        <div style="display:flex; gap:8px; margin-top:8px;">
          <button id="deleteBtn" class="danger" disabled>Delete</button>
          <button id="clearBtn" class="danger">Clear All</button>
        </div>
      </section>
      <section class="label-list" id="labelList"></section>
    </aside>
  </div>

  <script>
    const canvas = document.getElementById('mapCanvas');
    const ctx = canvas.getContext('2d');
    const viewer = document.getElementById('viewer');
    const statusEl = document.getElementById('status');
    const mapSelect = document.getElementById('mapSelect');
    const labelSelect = document.getElementById('labelSelect');
    const editInput = document.getElementById('editInput');
    const labelList = document.getElementById('labelList');

    let state = {
      mapName: null,
      mapImage: null,
      mapMeta: null,
      labels: [],
      selectedId: null,
      labelOptions: [],
      placing: false,
      zoom: 1,
      dirty: false,
    };

    const setStatus = (message) => { statusEl.textContent = message; };
    const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const activeLabel = () => state.labels.find(label => label.id === state.selectedId);

    function canvasPoint(event) {
      const rect = canvas.getBoundingClientRect();
      return {
        x: Math.round((event.clientX - rect.left) / state.zoom),
        y: Math.round((event.clientY - rect.top) / state.zoom),
      };
    }

    function worldFromPixel(x, y) {
      const meta = state.mapMeta || {};
      const resolution = Number(meta.resolution || 0);
      const origin = Array.isArray(meta.origin) ? meta.origin : [0, 0, 0];
      if (!resolution || !canvas.height) return null;
      return {
        x: origin[0] + x * resolution,
        y: origin[1] + (canvas.height - y) * resolution,
      };
    }

    function draw() {
      if (!state.mapImage) return;
      ctx.putImageData(state.mapImage, 0, 0);
      ctx.font = '14px system-ui, sans-serif';
      ctx.lineWidth = 2;
      ctx.textBaseline = 'middle';
      for (const label of state.labels) {
        const selected = label.id === state.selectedId;
        ctx.fillStyle = selected ? '#b23a48' : '#0b6f85';
        ctx.strokeStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(label.x, label.y, selected ? 7 : 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        const text = label.name || 'Label';
        const tx = label.x + 10;
        const ty = label.y - 10;
        const width = ctx.measureText(text).width + 10;
        ctx.fillStyle = 'rgba(255,255,255,.86)';
        ctx.fillRect(tx - 4, ty - 10, width, 20);
        ctx.strokeStyle = selected ? '#b23a48' : '#0b6f85';
        ctx.strokeRect(tx - 4, ty - 10, width, 20);
        ctx.fillStyle = '#1d2525';
        ctx.fillText(text, tx + 1, ty);
      }
    }

    function renderList() {
      if (!state.labels.length) {
        labelList.innerHTML = '<div class="empty">No labels yet. Type a name, press Place, then click the map.</div>';
        return;
      }
      labelList.innerHTML = '';
      for (const label of state.labels) {
        const item = document.createElement('button');
        item.className = `label-item ${label.id === state.selectedId ? 'active' : ''}`;
        item.type = 'button';
        const world = worldFromPixel(label.x, label.y);
        const meta = world
          ? `px ${label.x}, ${label.y} | world ${world.x.toFixed(2)}, ${world.y.toFixed(2)}`
          : `px ${label.x}, ${label.y}`;
        item.innerHTML = `<span><div class="label-name"></div><div class="label-meta"></div></span><span>Go</span>`;
        item.querySelector('.label-name').textContent = label.name;
        item.querySelector('.label-meta').textContent = meta;
        item.addEventListener('click', () => {
          state.selectedId = label.id;
          syncSelection();
          renderList();
          draw();
          viewer.scrollTo({
            left: Math.max(0, label.x * state.zoom - viewer.clientWidth / 2),
            top: Math.max(0, label.y * state.zoom - viewer.clientHeight / 2),
            behavior: 'smooth',
          });
        });
        labelList.appendChild(item);
      }
    }

    function syncSelection() {
      const label = activeLabel();
      editInput.disabled = !label;
      document.getElementById('renameBtn').disabled = !label;
      document.getElementById('deleteBtn').disabled = !label;
      editInput.value = label ? label.name : '';
    }

    function markDirty() {
      state.dirty = true;
      setStatus(`Unsaved labels for ${state.mapName}`);
    }

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `${response.status} ${response.statusText}`);
      }
      return response.json();
    }

    async function loadMaps() {
      const data = await fetchJson('/api/maps');
      mapSelect.innerHTML = '';
      for (const map of data.maps) {
        const option = document.createElement('option');
        option.value = map.name;
        option.textContent = map.name;
        mapSelect.appendChild(option);
      }
      if (!data.maps.length) {
        setStatus('No .pgm maps found in the maps folder.');
        return;
      }
      await loadMap(data.maps[0].name);
    }

    async function loadLabelOptions() {
      const data = await fetchJson('/api/label-options');
      state.labelOptions = data.labels || [];
      labelSelect.innerHTML = '';
      if (!state.labelOptions.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No directory labels found';
        labelSelect.appendChild(option);
        labelSelect.disabled = true;
        return;
      }
      for (const label of state.labelOptions) {
        const option = document.createElement('option');
        option.value = label.name;
        option.textContent = label.detail ? `${label.name} (${label.detail})` : label.name;
        option.dataset.kind = label.kind || '';
        option.dataset.detail = label.detail || '';
        option.dataset.source = label.source || '';
        labelSelect.appendChild(option);
      }
    }

    function selectedLabelTemplate() {
      const option = labelSelect.selectedOptions[0];
      if (!option || !option.value) {
        return { name: `Label ${state.labels.length + 1}` };
      }
      return {
        name: option.value,
        kind: option.dataset.kind || undefined,
        detail: option.dataset.detail || undefined,
        source: option.dataset.source || undefined,
      };
    }

    async function loadMap(name) {
      setStatus(`Loading ${name}...`);
      const data = await fetchJson(`/api/map?name=${encodeURIComponent(name)}`);
      state.mapName = name;
      state.mapMeta = data.meta || {};
      state.labels = data.labels || [];
      state.selectedId = null;
      state.dirty = false;
      mapSelect.value = name;

      const imageData = ctx.createImageData(data.width, data.height);
      const bytes = Uint8Array.from(atob(data.pixels), c => c.charCodeAt(0));
      for (let i = 0; i < bytes.length; i++) {
        const v = bytes[i];
        const j = i * 4;
        imageData.data[j] = v;
        imageData.data[j + 1] = v;
        imageData.data[j + 2] = v;
        imageData.data[j + 3] = 255;
      }
      canvas.width = data.width;
      canvas.height = data.height;
      state.mapImage = imageData;
      fitMap();
      syncSelection();
      renderList();
      draw();
      setStatus(`${name}: ${data.width} x ${data.height}, ${state.labels.length} labels`);
    }

    function applyZoom() {
      canvas.style.width = `${canvas.width * state.zoom}px`;
      canvas.style.height = `${canvas.height * state.zoom}px`;
      draw();
    }

    function fitMap() {
      const pad = 64;
      const zx = (viewer.clientWidth - pad) / canvas.width;
      const zy = (viewer.clientHeight - pad) / canvas.height;
      state.zoom = Math.max(0.1, Math.min(3, Math.min(zx, zy)));
      applyZoom();
    }

    async function saveLabels() {
      const labels = state.labels.map(label => ({
        ...label,
        world: worldFromPixel(label.x, label.y),
      }));
      const data = await fetchJson('/api/labels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ map: state.mapName, labels }),
      });
      state.dirty = false;
      setStatus(`Saved ${data.count} labels to ${data.file}`);
    }

    canvas.addEventListener('click', (event) => {
      if (!state.mapImage) return;
      const point = canvasPoint(event);
      if (point.x < 0 || point.y < 0 || point.x >= canvas.width || point.y >= canvas.height) return;

      if (state.placing) {
        const template = selectedLabelTemplate();
        const label = { id: newId(), ...template, x: point.x, y: point.y };
        state.labels.push(label);
        state.selectedId = label.id;
        state.placing = false;
        document.getElementById('addModeBtn').textContent = 'Place';
        markDirty();
      } else {
        let nearest = null;
        let nearestDistance = 18;
        for (const label of state.labels) {
          const d = Math.hypot(label.x - point.x, label.y - point.y);
          if (d < nearestDistance) {
            nearest = label;
            nearestDistance = d;
          }
        }
        state.selectedId = nearest ? nearest.id : null;
      }
      syncSelection();
      renderList();
      draw();
    });

    document.getElementById('addModeBtn').addEventListener('click', () => {
      state.placing = !state.placing;
      document.getElementById('addModeBtn').textContent = state.placing ? 'Click Map' : 'Place';
      setStatus(state.placing ? 'Click the map to place the label.' : `${state.mapName} ready`);
    });

    document.getElementById('renameBtn').addEventListener('click', () => {
      const label = activeLabel();
      if (!label) return;
      label.name = editInput.value.trim() || label.name;
      markDirty();
      renderList();
      draw();
    });

    document.getElementById('deleteBtn').addEventListener('click', () => {
      if (!state.selectedId) return;
      state.labels = state.labels.filter(label => label.id !== state.selectedId);
      state.selectedId = null;
      markDirty();
      syncSelection();
      renderList();
      draw();
    });

    document.getElementById('clearBtn').addEventListener('click', () => {
      if (!state.labels.length || !confirm('Clear all labels for this map?')) return;
      state.labels = [];
      state.selectedId = null;
      markDirty();
      syncSelection();
      renderList();
      draw();
    });

    document.getElementById('saveBtn').addEventListener('click', () => saveLabels().catch(error => setStatus(error.message)));
    document.getElementById('reloadBtn').addEventListener('click', () => loadMap(state.mapName).catch(error => setStatus(error.message)));
    document.getElementById('fitBtn').addEventListener('click', fitMap);
    document.getElementById('zoomInBtn').addEventListener('click', () => { state.zoom = Math.min(8, state.zoom * 1.25); applyZoom(); });
    document.getElementById('zoomOutBtn').addEventListener('click', () => { state.zoom = Math.max(.1, state.zoom / 1.25); applyZoom(); });
    document.getElementById('exportBtn').addEventListener('click', () => {
      draw();
      const link = document.createElement('a');
      link.href = canvas.toDataURL('image/png');
      link.download = `${state.mapName.replace(/\.[^.]+$/, '')}_annotated.png`;
      link.click();
    });
    mapSelect.addEventListener('change', () => {
      if (state.dirty && !confirm('Switch maps without saving labels?')) {
        mapSelect.value = state.mapName;
        return;
      }
      loadMap(mapSelect.value).catch(error => setStatus(error.message));
    });
    window.addEventListener('beforeunload', (event) => {
      if (!state.dirty) return;
      event.preventDefault();
      event.returnValue = '';
    });
    window.addEventListener('resize', () => {
      if (state.mapImage) applyZoom();
    });

    Promise.all([loadLabelOptions(), loadMaps()]).catch(error => setStatus(error.message));
  </script>
</body>
</html>
"""


def safe_map_name(name: str) -> str:
    decoded = unquote(name)
    if not re.fullmatch(r"[-A-Za-z0-9_ .]+\.pgm", decoded):
        raise ValueError("Invalid map name")
    return decoded


def read_pgm(path: Path) -> tuple[int, int, bytes]:
    with path.open("rb") as stream:
        if stream.readline().strip() != b"P5":
            raise ValueError("Only binary PGM/P5 maps are supported")

        tokens: list[bytes] = []
        while len(tokens) < 3:
            line = stream.readline()
            if not line:
                raise ValueError("Invalid PGM header")
            line = line.split(b"#", 1)[0]
            tokens.extend(line.split())

        width = int(tokens[0])
        height = int(tokens[1])
        max_value = int(tokens[2])
        if max_value > 255:
            raise ValueError("Only 8-bit PGM maps are supported")

        pixels = stream.read(width * height)
        if len(pixels) != width * height:
            raise ValueError("PGM file ended before all pixels were read")
        return width, height, pixels


def parse_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    meta: dict[str, object] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "resolution":
            meta[key] = float(value)
        elif key == "origin":
            meta[key] = json.loads(value.replace("'", '"'))
        else:
            meta[key] = value.strip('"')
    return meta


def xlsx_col(ref: str) -> str:
    return re.sub(r"\d+", "", ref)


def xlsx_cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", XLSX_NS)).strip()

    value = cell.find("a:v", XLSX_NS)
    text = "" if value is None else value.text or ""
    if cell.get("t") == "s" and text:
        text = shared_strings[int(text)]
    return text.strip()


def read_xlsx_rows(path: Path, sheet_path: str) -> list[dict[str, str]]:
    with ZipFile(path) as workbook:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(text.text or "" for text in item.findall(".//a:t", XLSX_NS))
                for item in root.findall("a:si", XLSX_NS)
            ]

        sheet = ET.fromstring(workbook.read(sheet_path))
        rows: list[dict[str, str]] = []
        for row in sheet.findall(".//a:sheetData/a:row", XLSX_NS):
            values: dict[str, str] = {}
            for cell in row.findall("a:c", XLSX_NS):
                values[xlsx_col(cell.get("r", ""))] = xlsx_cell_text(cell, shared_strings)
            rows.append(values)
        return rows


def load_label_options() -> list[dict[str, str]]:
    if not DIRECTORY_FILE.exists():
        return []

    options: list[dict[str, str]] = []

    try:
        for row in read_xlsx_rows(DIRECTORY_FILE, "xl/worksheets/sheet2.xml")[1:]:
            room = row.get("A", "")
            if room:
                detail = " - ".join(part for part in [row.get("C", ""), row.get("D", "")] if part)
                options.append(
                    {
                        "name": room,
                        "kind": "room",
                        "detail": detail,
                        "source": DIRECTORY_FILE.name,
                    }
                )

        for row in read_xlsx_rows(DIRECTORY_FILE, "xl/worksheets/sheet3.xml")[1:]:
            name = row.get("A", "")
            office = row.get("D", "")
            if name:
                options.append(
                    {
                        "name": name,
                        "kind": "person",
                        "detail": office,
                        "source": DIRECTORY_FILE.name,
                    }
                )

        for row in read_xlsx_rows(DIRECTORY_FILE, "xl/worksheets/sheet4.xml")[1:]:
            space = row.get("A", "")
            location = row.get("B", "")
            if space:
                options.append(
                    {
                        "name": space,
                        "kind": "space",
                        "detail": location,
                        "source": DIRECTORY_FILE.name,
                    }
                )
    except Exception as exc:
        print(f"Could not load label options from {DIRECTORY_FILE}: {exc}")
        return []

    seen: set[tuple[str, str]] = set()
    unique_options: list[dict[str, str]] = []
    for option in options:
        key = (option.get("kind", ""), option.get("name", ""))
        if key in seen:
            continue
        seen.add(key)
        unique_options.append(option)

    return sorted(unique_options, key=lambda item: (item.get("kind", ""), item.get("name", "")))


def label_path_for(map_path: Path) -> Path:
    return map_path.with_name(f"{map_path.stem}_labels.json")


def pixel_from_world(map_path: Path, world_x: float, world_y: float) -> tuple[int, int]:
    meta = parse_yaml(map_path.with_suffix(".yaml"))
    resolution = float(meta.get("resolution") or 0)
    origin = meta.get("origin") if isinstance(meta.get("origin"), list) else [0, 0, 0]
    if not resolution:
        raise ValueError(f"Missing resolution in {map_path.with_suffix('.yaml')}")

    _, height, _ = read_pgm(map_path)
    x = round((world_x - float(origin[0])) / resolution)
    y = round(height - ((world_y - float(origin[1])) / resolution))
    return x, y


def origin_label_for(map_path: Path) -> dict:
    x, y = pixel_from_world(map_path, 0.0, 0.0)
    return {
        "id": "origin",
        "name": "origin",
        "kind": "navigation",
        "detail": "Robot origin",
        "source": "auto",
        "x": x,
        "y": y,
        "world": {
            "x": 0.0,
            "y": 0.0,
        },
        "yaw": 0.0,
    }


def ensure_origin_label(map_path: Path, labels: list[dict]) -> list[dict]:
    if any(label.get("name") == "origin" for label in labels):
        return labels
    return [*labels, origin_label_for(map_path)]


def read_labels(map_path: Path) -> list[dict]:
    path = label_path_for(map_path)
    if not path.exists():
        return ensure_origin_label(map_path, [])
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = data.get("labels", []) if isinstance(data, dict) else []
    return ensure_origin_label(map_path, labels)


class Handler(BaseHTTPRequestHandler):
    server_version = "MapLabelGUI/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def write_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_text(self, text: str, status: HTTPStatus = HTTPStatus.OK, content_type: str = "text/plain") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.write_text(INDEX_HTML, content_type="text/html")
            elif parsed.path == "/api/maps":
                maps = [{"name": path.name} for path in sorted(MAPS_DIR.glob("*.pgm"))]
                self.write_json({"maps": maps})
            elif parsed.path == "/api/label-options":
                self.write_json({"labels": load_label_options()})
            elif parsed.path == "/api/map":
                params = parse_qs(parsed.query)
                name = safe_map_name(params.get("name", [""])[0])
                map_path = MAPS_DIR / name
                if not map_path.exists():
                    self.write_json({"error": "Map not found"}, HTTPStatus.NOT_FOUND)
                    return
                width, height, pixels = read_pgm(map_path)
                self.write_json(
                    {
                        "name": name,
                        "width": width,
                        "height": height,
                        "pixels": base64.b64encode(pixels).decode("ascii"),
                        "meta": parse_yaml(map_path.with_suffix(".yaml")),
                        "labels": read_labels(map_path),
                    }
                )
            else:
                self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/labels":
            self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            name = safe_map_name(data.get("map", ""))
            map_path = MAPS_DIR / name
            if not map_path.exists():
                self.write_json({"error": "Map not found"}, HTTPStatus.NOT_FOUND)
                return

            labels = data.get("labels", [])
            if not isinstance(labels, list):
                raise ValueError("labels must be a list")
            labels = ensure_origin_label(map_path, labels)

            output = {
                "map": name,
                "yaml": map_path.with_suffix(".yaml").name,
                "labels": labels,
            }
            label_path = label_path_for(map_path)
            label_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
            self.write_json({"file": str(label_path.relative_to(ROOT)), "count": len(labels)})
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a browser GUI for labeling ROS PGM maps.")
    parser.add_argument("--host", default="0.0.0.0", help="Host/interface to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    args = parser.parse_args()

    mimetypes.add_type("image/x-portable-graymap", ".pgm")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Map label GUI: http://{args.host}:{args.port}")
    print(f"Serving maps from: {MAPS_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
