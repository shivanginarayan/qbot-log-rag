#!/usr/bin/env python3
"""Browser-based LaserScan viewer for measuring wedge filter candidates.

This tool is read-only with respect to ROS: it subscribes to a LaserScan topic
and serves a local web UI. It does not publish filtered scans or change Nav2.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlparse

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LaserScan Wedge GUI</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #111418;
      --panel: #181d23;
      --line: #313943;
      --text: #e6edf3;
      --muted: #96a1ad;
      --accent: #62b3ff;
      --warn: #ffcc66;
      --danger: #ff6b6b;
      --ok: #80d88a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.4 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      display: grid;
      grid-template-columns: minmax(480px, 1fr) 380px;
      min-height: 100vh;
    }
    #viewer {
      width: 100%;
      height: 100vh;
      display: block;
      background: #0b0e12;
      cursor: crosshair;
    }
    aside {
      border-left: 1px solid var(--line);
      background: var(--panel);
      padding: 14px;
      overflow-y: auto;
      max-height: 100vh;
    }
    h1 {
      font-size: 18px;
      margin: 0 0 12px;
      font-weight: 650;
    }
    h2 {
      font-size: 14px;
      margin: 18px 0 8px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-bottom: 8px;
    }
    .wide { grid-column: 1 / -1; }
    button, input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #0f1318;
      color: var(--text);
      padding: 8px;
      font: inherit;
    }
    button {
      cursor: pointer;
      background: #202833;
    }
    button:hover { border-color: var(--accent); }
    button.primary { background: #17476f; }
    button.danger { background: #4a2024; }
    label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }
    .metric {
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #0f1318;
      min-height: 35px;
    }
    .status {
      color: var(--muted);
      margin-bottom: 10px;
      word-break: break-word;
    }
    .legend {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      margin: 8px 0 10px;
    }
    .swatch {
      display: inline-block;
      width: 12px;
      height: 12px;
      border-radius: 3px;
      margin-right: 6px;
      vertical-align: -1px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 6px 4px;
      text-align: right;
    }
    th:first-child, td:first-child { text-align: left; }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #0f1318;
      max-height: 220px;
      overflow: auto;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      #viewer { height: 65vh; }
      aside { max-height: none; border-left: 0; border-top: 1px solid var(--line); }
    }
  </style>
</head>
<body>
<main>
  <canvas id="viewer"></canvas>
  <aside>
    <h1>LaserScan Wedge GUI</h1>
    <div class="status" id="status">Waiting for scan...</div>
    <div class="row">
      <button id="pauseBtn">Pause</button>
      <button id="clearBtn">Clear Unsaved</button>
    </div>
    <div class="row">
      <div>
        <label for="rangeScale">Display radius (m)</label>
        <input id="rangeScale" type="number" min="0.2" step="0.1" value="2.0">
      </div>
      <div>
        <label for="closeThreshold">Close point color &lt; m</label>
        <input id="closeThreshold" type="number" min="0.01" step="0.01" value="0.35">
      </div>
    </div>

    <h2>Filter File</h2>
    <div class="row">
      <div class="wide">
        <label for="filterFileSelect">Existing filter file</label>
        <select id="filterFileSelect"></select>
      </div>
      <button id="refreshFilesBtn">Refresh Files</button>
      <button id="loadFileBtn">Load Selected</button>
    </div>
    <div class="row">
      <div class="wide">
        <label for="saveFileName">Robot-side save filename</label>
        <input id="saveFileName" type="text" value="scan_wedge_filter.json">
      </div>
    </div>
    <div class="row">
      <div class="wide">
        <label for="viewMode">Scan view</label>
        <select id="viewMode">
          <option value="raw">Raw: show all scan points</option>
          <option value="filtered">Filtered: hide masked points</option>
          <option value="compare">Compare: dim masked points</option>
        </select>
      </div>
    </div>
    <div class="legend">
      <div><span class="swatch" style="background:#f2c94c;"></span>Saved wedges from file</div>
      <div><span class="swatch" style="background:#00c2ff;"></span>Unsaved wedges added in this session</div>
      <div><span class="swatch" style="background:#b19cff;"></span>Live preview wedge</div>
      <div><span class="swatch" style="background:#ffffff; border:1px solid #111418;"></span>Selected point</div>
    </div>

    <h2>Selected Point</h2>
	    <div class="row">
	      <div class="metric" id="selIndex">index: -</div>
	      <div class="metric" id="selAngle">angle: -</div>
	      <div class="metric" id="selRange">range: -</div>
	      <div class="metric" id="selXY">x/y: -</div>
	    </div>
	    <div class="row">
	      <div>
	        <label for="selectedAngleDeg">Manual angle (deg)</label>
	        <input id="selectedAngleDeg" type="number" step="0.1" value="">
	      </div>
	      <div>
	        <label for="selectedRangeM">Selected range (m)</label>
	        <input id="selectedRangeM" type="number" step="0.001" value="" disabled>
	      </div>
	    </div>
    <div class="row">
      <div>
        <label for="widthDeg">Wedge width (deg)</label>
        <input id="widthDeg" type="number" min="0.1" step="0.1" value="5.0">
      </div>
      <div>
        <label for="rangePad">Max range pad (m)</label>
        <input id="rangePad" type="number" min="0" step="0.01" value="0.05">
      </div>
    </div>
    <div class="row">
      <div>
        <label for="minRange">Min range (m)</label>
        <input id="minRange" type="number" min="0" step="0.01" value="0.03">
      </div>
      <button class="primary" id="addWedgeBtn">Add Wedge From Selection</button>
    </div>

    <h2>Wedges</h2>
    <table>
      <thead>
        <tr><th>#</th><th>angle</th><th>width</th><th>min</th><th>max</th><th></th></tr>
      </thead>
      <tbody id="wedgeRows"></tbody>
    </table>
	    <div class="row" style="margin-top: 10px;">
	      <button id="downloadJsonBtn">Download JSON</button>
	      <button id="downloadYamlBtn">Download YAML</button>
	    </div>
	    <div class="row">
	      <button class="primary" id="saveRobotJsonBtn">Save JSON On Robot</button>
	      <button class="primary" id="saveRobotYamlBtn">Save YAML On Robot</button>
	    </div>

    <h2>Export Preview</h2>
    <pre id="exportPreview">{ "wedges": [] }</pre>
  </aside>
</main>
<script>
const canvas = document.getElementById("viewer");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const pauseBtn = document.getElementById("pauseBtn");
const clearBtn = document.getElementById("clearBtn");
const addWedgeBtn = document.getElementById("addWedgeBtn");
const filterFileSelect = document.getElementById("filterFileSelect");
const refreshFilesBtn = document.getElementById("refreshFilesBtn");
const loadFileBtn = document.getElementById("loadFileBtn");
const saveFileNameInput = document.getElementById("saveFileName");
const viewModeSelect = document.getElementById("viewMode");
	const downloadJsonBtn = document.getElementById("downloadJsonBtn");
	const downloadYamlBtn = document.getElementById("downloadYamlBtn");
	const saveRobotJsonBtn = document.getElementById("saveRobotJsonBtn");
	const saveRobotYamlBtn = document.getElementById("saveRobotYamlBtn");
const rangeScaleInput = document.getElementById("rangeScale");
const closeThresholdInput = document.getElementById("closeThreshold");
	const widthDegInput = document.getElementById("widthDeg");
	const rangePadInput = document.getElementById("rangePad");
	const minRangeInput = document.getElementById("minRange");
	const selectedAngleDegInput = document.getElementById("selectedAngleDeg");
	const selectedRangeMInput = document.getElementById("selectedRangeM");
const wedgeRows = document.getElementById("wedgeRows");
const exportPreview = document.getElementById("exportPreview");

let scan = null;
let frozenScan = null;
let paused = false;
let selected = null;
let savedWedges = [];
let unsavedWedges = [];
let loadedFile = "";

function allWedges() {
  return savedWedges.concat(unsavedWedges);
}

function previewFilterWedges() {
  const preview = previewWedge();
  return preview ? allWedges().concat([preview]) : allWedges();
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}

function activeScan() {
  return paused && frozenScan ? frozenScan : scan;
}

function angleDiffDeg(a, b) {
  let d = a - b;
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  return d;
}

function pointXY(point) {
  const angle = point.angle_deg * Math.PI / 180;
  return {
    x: point.range * Math.cos(angle),
    y: point.range * Math.sin(angle),
  };
}

function worldToCanvas(x, y) {
  const rect = canvas.getBoundingClientRect();
  const radiusM = Number(rangeScaleInput.value) || 2.0;
  const scale = Math.min(rect.width, rect.height) * 0.45 / radiusM;
  return {
    x: rect.width / 2 + x * scale,
    y: rect.height / 2 - y * scale,
    scale,
  };
}

function canvasToWorld(px, py) {
  const rect = canvas.getBoundingClientRect();
  const radiusM = Number(rangeScaleInput.value) || 2.0;
  const scale = Math.min(rect.width, rect.height) * 0.45 / radiusM;
  return {
    x: (px - rect.width / 2) / scale,
    y: -(py - rect.height / 2) / scale,
  };
}

function drawGrid(rect, radiusM) {
  const origin = worldToCanvas(0, 0);
  ctx.strokeStyle = "#202833";
  ctx.lineWidth = 1;
  for (let r = 0.25; r <= radiusM + 0.001; r += 0.25) {
    ctx.beginPath();
    ctx.arc(origin.x, origin.y, r * origin.scale, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.strokeStyle = "#38424d";
  ctx.beginPath();
  ctx.moveTo(origin.x, 0);
  ctx.lineTo(origin.x, rect.height);
  ctx.moveTo(0, origin.y);
  ctx.lineTo(rect.width, origin.y);
  ctx.stroke();
  ctx.fillStyle = "#e6edf3";
  ctx.beginPath();
  ctx.arc(origin.x, origin.y, 4, 0, Math.PI * 2);
  ctx.fill();
}

	function drawWedgeShape(wedge, fillStyle, strokeStyle, lineWidth = 1) {
	  const radiusM = Number(rangeScaleInput.value) || 2.0;
	  const origin = worldToCanvas(0, 0);
	  const a0 = (wedge.angle_deg - wedge.width_deg / 2) * Math.PI / 180;
	  const a1 = (wedge.angle_deg + wedge.width_deg / 2) * Math.PI / 180;
	  const r0 = wedge.min_range * origin.scale;
	  const r1 = Math.min(wedge.max_range, radiusM) * origin.scale;
	  ctx.beginPath();
	  ctx.moveTo(origin.x + r0 * Math.cos(a0), origin.y - r0 * Math.sin(a0));
	  ctx.arc(origin.x, origin.y, r0, -a0, -a1, true);
	  ctx.lineTo(origin.x + r1 * Math.cos(a1), origin.y - r1 * Math.sin(a1));
	  ctx.arc(origin.x, origin.y, r1, -a1, -a0, false);
	  ctx.closePath();
	  ctx.fillStyle = fillStyle;
	  ctx.fill();
	  ctx.strokeStyle = strokeStyle;
	  ctx.lineWidth = lineWidth;
	  ctx.stroke();
	}

	function previewWedge() {
	  if (!selected) return null;
	  const pad = Number(rangePadInput.value) || 0;
	  const minRange = Math.max(0, Number(minRangeInput.value) || 0.03);
	  return {
	    angle_deg: selected.angle_deg,
	    width_deg: Number(widthDegInput.value) || 5,
	    min_range: minRange,
	    max_range: Math.max(selected.range + pad, minRange + 0.01),
	  };
	}

	function drawWedges() {
	  for (const wedge of savedWedges) {
	    drawWedgeShape(wedge, "rgba(242, 201, 76, 0.16)", "rgba(242, 201, 76, 0.85)");
	  }
	  for (const wedge of unsavedWedges) {
	    drawWedgeShape(wedge, "rgba(0, 194, 255, 0.14)", "rgba(0, 194, 255, 0.9)");
	  }
	  const preview = previewWedge();
	  if (preview) {
	    drawWedgeShape(preview, "rgba(147, 112, 219, 0.24)", "rgba(177, 156, 255, 0.98)", 2);
	  }
	}

function pointInWedge(point, wedge) {
  return point.range >= wedge.min_range
    && point.range <= wedge.max_range
    && Math.abs(angleDiffDeg(point.angle_deg, wedge.angle_deg)) <= wedge.width_deg / 2;
}

function pointMasked(point) {
  return previewFilterWedges().some(wedge => pointInWedge(point, wedge));
}

function draw() {
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  const radiusM = Number(rangeScaleInput.value) || 2.0;
  drawGrid(rect, radiusM);
  drawWedges();
  const data = activeScan();
  if (!data) return;

  const closeThreshold = Number(closeThresholdInput.value) || 0.35;
  const viewMode = viewModeSelect.value;
  for (const p of data.points) {
    if (!Number.isFinite(p.range) || p.range > radiusM) continue;
    const masked = pointMasked(p);
    if (viewMode === "filtered" && masked) continue;
    const xy = pointXY(p);
    const c = worldToCanvas(xy.x, xy.y);
    const close = p.range < closeThreshold;
    if (viewMode === "compare" && masked) {
      ctx.fillStyle = "#7c8794";
      ctx.globalAlpha = 0.24;
      ctx.fillRect(c.x - 1.5, c.y - 1.5, 3, 3);
    } else {
      ctx.fillStyle = close ? "#ff6b6b" : "#62b3ff";
      ctx.globalAlpha = close ? 0.95 : 0.75;
      ctx.fillRect(c.x - 1.5, c.y - 1.5, 3, 3);
    }
  }
  ctx.globalAlpha = 1;

	  if (selected) {
	    const xy = pointXY(selected);
	    const c = worldToCanvas(xy.x, xy.y);
	    ctx.strokeStyle = "#ffffff";
	    ctx.lineWidth = 3;
	    ctx.beginPath();
	    ctx.arc(c.x, c.y, 7, 0, Math.PI * 2);
	    ctx.stroke();
	    ctx.strokeStyle = "#111418";
	    ctx.lineWidth = 1;
	    ctx.beginPath();
	    ctx.arc(c.x, c.y, 11, 0, Math.PI * 2);
	    ctx.stroke();
	  }
	}

function updateSelected(point) {
  selected = point;
  if (!point) {
    document.getElementById("selIndex").textContent = "index: -";
	    document.getElementById("selAngle").textContent = "angle: -";
	    document.getElementById("selRange").textContent = "range: -";
	    document.getElementById("selXY").textContent = "x/y: -";
	    selectedAngleDegInput.value = "";
	    selectedRangeMInput.value = "";
	    draw();
	    return;
	  }
	  const xy = pointXY(point);
	  document.getElementById("selIndex").textContent = `index: ${point.index}`;
	  document.getElementById("selAngle").textContent = `angle: ${point.angle_deg.toFixed(2)} deg`;
	  document.getElementById("selRange").textContent = `range: ${point.range.toFixed(3)} m`;
	  document.getElementById("selXY").textContent = `x/y: ${xy.x.toFixed(3)}, ${xy.y.toFixed(3)} m`;
	  selectedAngleDegInput.value = point.angle_deg.toFixed(2);
	  selectedRangeMInput.value = point.range.toFixed(3);
	  draw();
	}

	function setSelectedAngle(angleDeg) {
	  if (!selected || !Number.isFinite(angleDeg)) return;
	  selected = {
	    ...selected,
	    angle_deg: angleDeg,
	    index: "manual",
	  };
	  updateSelected(selected);
	}

function nearestPoint(evt) {
  const data = activeScan();
  if (!data) return null;
  const rect = canvas.getBoundingClientRect();
  const target = canvasToWorld(evt.clientX - rect.left, evt.clientY - rect.top);
  let best = null;
  let bestD = Infinity;
  for (const p of data.points) {
    if (!Number.isFinite(p.range)) continue;
    const xy = pointXY(p);
    const d = Math.hypot(xy.x - target.x, xy.y - target.y);
    if (d < bestD) {
      bestD = d;
      best = p;
    }
  }
  return bestD < 0.08 ? best : null;
}

function exportObject() {
  return {
    input_topic: "/scan",
    output_topic: "/scan_filtered",
    generated_at: new Date().toISOString(),
    wedges: allWedges().map(w => ({
      angle_deg: Number(w.angle_deg.toFixed(3)),
      width_deg: Number(w.width_deg.toFixed(3)),
      min_range: Number(w.min_range.toFixed(3)),
      max_range: Number(w.max_range.toFixed(3)),
    })),
  };
}

function toYaml(obj) {
  const lines = [
    "input_topic: " + obj.input_topic,
    "output_topic: " + obj.output_topic,
    "wedges:",
  ];
  for (const w of obj.wedges) {
    lines.push(`  - angle_deg: ${w.angle_deg}`);
    lines.push(`    width_deg: ${w.width_deg}`);
    lines.push(`    min_range: ${w.min_range}`);
    lines.push(`    max_range: ${w.max_range}`);
  }
  return lines.join("\n") + "\n";
}

function refreshWedges() {
  wedgeRows.innerHTML = "";
  allWedges().forEach((w, i) => {
    const saved = i < savedWedges.length;
    const localIndex = saved ? i : i - savedWedges.length;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i + 1}${saved ? " S" : " U"}</td>
      <td>${w.angle_deg.toFixed(1)}</td>
      <td>${w.width_deg.toFixed(1)}</td>
      <td>${w.min_range.toFixed(2)}</td>
      <td>${w.max_range.toFixed(2)}</td>
      <td><button class="danger" data-saved="${saved ? "1" : "0"}" data-index="${localIndex}">X</button></td>
    `;
    wedgeRows.appendChild(tr);
  });
  wedgeRows.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      if (btn.dataset.saved === "1") {
        savedWedges.splice(Number(btn.dataset.index), 1);
      } else {
        unsavedWedges.splice(Number(btn.dataset.index), 1);
      }
      refreshWedges();
    });
  });
  exportPreview.textContent = JSON.stringify(exportObject(), null, 2);
  draw();
}

	function download(name, text) {
  const blob = new Blob([text], {type: "text/plain"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  URL.revokeObjectURL(a.href);
  a.remove();
	}

	async function saveOnRobot(format) {
	  const obj = exportObject();
	  const body = format === "yaml" ? toYaml(obj) : JSON.stringify(obj, null, 2) + "\n";
	  const filename = saveFileNameInput.value.trim() || `scan_wedge_filter.${format}`;
	  const res = await fetch(`/api/save?format=${format}&name=${encodeURIComponent(filename)}`, {
	    method: "POST",
	    headers: {"Content-Type": "text/plain"},
	    body,
	  });
	  const data = await res.json();
	  if (!res.ok || !data.ok) {
	    statusEl.textContent = data.error || "Save failed.";
	    return;
	  }
	  statusEl.textContent = `Saved on robot: ${data.path}`;
	  loadedFile = data.name || filename;
	  savedWedges = allWedges();
	  unsavedWedges = [];
	  saveFileNameInput.value = loadedFile;
	  await refreshFilterFiles();
	  refreshWedges();
	}

function normalizeWedges(items) {
  if (!Array.isArray(items)) return [];
  return items.map(w => ({
    angle_deg: Number(w.angle_deg),
    width_deg: Number(w.width_deg),
    min_range: Number(w.min_range),
    max_range: Number(w.max_range),
  })).filter(w =>
    Number.isFinite(w.angle_deg)
    && Number.isFinite(w.width_deg)
    && Number.isFinite(w.min_range)
    && Number.isFinite(w.max_range)
  );
}

async function refreshFilterFiles() {
  try {
    const res = await fetch("/api/files", {cache: "no-store"});
    const data = await res.json();
    filterFileSelect.innerHTML = "";
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = data.files && data.files.length ? "Choose a filter file..." : "No filter files found";
    filterFileSelect.appendChild(empty);
    for (const file of data.files || []) {
      const option = document.createElement("option");
      option.value = file.name;
      option.textContent = file.name;
      if (file.name === loadedFile) option.selected = true;
      filterFileSelect.appendChild(option);
    }
  } catch (err) {
    statusEl.textContent = "Could not list filter files: " + err;
  }
}

async function loadSelectedFile() {
  const name = filterFileSelect.value;
  if (!name) return;
  const res = await fetch(`/api/file?name=${encodeURIComponent(name)}`, {cache: "no-store"});
  const data = await res.json();
  if (!res.ok || !data.ok) {
    statusEl.textContent = data.error || "Load failed.";
    return;
  }
  loadedFile = name;
  saveFileNameInput.value = name;
  savedWedges = normalizeWedges(data.filter.wedges);
  unsavedWedges = [];
  statusEl.textContent = `Loaded ${savedWedges.length} wedges from ${name}`;
  refreshWedges();
}

async function pollScan() {
  try {
    const res = await fetch("/api/scan", {cache: "no-store"});
    if (res.ok) {
      const data = await res.json();
      if (data.ready) {
        scan = data;
        statusEl.textContent = `${data.topic}: ${data.points.length} points, stamp ${data.stamp_sec.toFixed(3)}, ${paused ? "paused" : "live"}`;
        if (!paused) draw();
      } else {
        statusEl.textContent = "Waiting for scan...";
      }
    }
  } catch (err) {
    statusEl.textContent = "Server unavailable: " + err;
  }
  setTimeout(pollScan, paused ? 500 : 150);
}

canvas.addEventListener("click", evt => updateSelected(nearestPoint(evt)));
pauseBtn.addEventListener("click", () => {
  paused = !paused;
  if (paused) frozenScan = scan;
  pauseBtn.textContent = paused ? "Resume" : "Pause";
  statusEl.textContent = paused ? "Paused on current scan." : "Live scan.";
  draw();
});
clearBtn.addEventListener("click", () => {
  unsavedWedges = [];
  refreshWedges();
});
addWedgeBtn.addEventListener("click", () => {
  if (!selected) return;
  const pad = Number(rangePadInput.value) || 0;
  const minRange = Number(minRangeInput.value) || 0.03;
  unsavedWedges.push({
    angle_deg: selected.angle_deg,
    width_deg: Number(widthDegInput.value) || 5,
    min_range: Math.max(0, minRange),
    max_range: Math.max(selected.range + pad, minRange + 0.01),
  });
  refreshWedges();
});
downloadJsonBtn.addEventListener("click", () => {
  download("scan_wedge_filter.json", JSON.stringify(exportObject(), null, 2) + "\n");
});
	downloadYamlBtn.addEventListener("click", () => {
	  download("scan_wedge_filter.yaml", toYaml(exportObject()));
	});
saveRobotJsonBtn.addEventListener("click", () => saveOnRobot("json"));
saveRobotYamlBtn.addEventListener("click", () => saveOnRobot("yaml"));
refreshFilesBtn.addEventListener("click", refreshFilterFiles);
loadFileBtn.addEventListener("click", loadSelectedFile);
selectedAngleDegInput.addEventListener("input", () => {
  setSelectedAngle(Number(selectedAngleDegInput.value));
});
[rangeScaleInput, closeThresholdInput, widthDegInput, rangePadInput, minRangeInput].forEach(el => {
  el.addEventListener("input", draw);
});
viewModeSelect.addEventListener("change", draw);
window.addEventListener("resize", resizeCanvas);
resizeCanvas();
refreshWedges();
refreshFilterFiles();
pollScan();
</script>
</body>
</html>
"""


class ScanState:
    def __init__(self, topic):
        self.topic = topic
        self.lock = threading.Lock()
        self.scan = None

    def update(self, msg):
        points = []
        for index, value in enumerate(msg.ranges):
            if not math.isfinite(value):
                continue
            if value < msg.range_min or value > msg.range_max:
                continue
            angle_rad = msg.angle_min + index * msg.angle_increment
            points.append(
                {
                    "index": index,
                    "angle_deg": math.degrees(angle_rad),
                    "range": float(value),
                }
            )

        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        with self.lock:
            self.scan = {
                "ready": True,
                "topic": self.topic,
                "frame_id": msg.header.frame_id,
                "stamp_sec": stamp,
                "angle_min_deg": math.degrees(msg.angle_min),
                "angle_max_deg": math.degrees(msg.angle_max),
                "range_min": float(msg.range_min),
                "range_max": float(msg.range_max),
                "points": points,
            }

    def snapshot(self):
        with self.lock:
            if self.scan is None:
                return {"ready": False, "topic": self.topic}
            return dict(self.scan)


class ScanGuiNode(Node):
    def __init__(self, state):
        super().__init__("scan_wedge_gui")
        self.state = state
        self.create_subscription(LaserScan, state.topic, self.scan_callback, 10)
        self.get_logger().info(f"Listening for LaserScan on {state.topic}")

    def scan_callback(self, msg):
        self.state.update(msg)


def filter_files(output_dir):
    if not output_dir.exists():
        return []
    return sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"}
    )


def safe_filter_path(output_dir, name):
    path = (output_dir / Path(name).name).resolve()
    root = output_dir.resolve()
    if root not in path.parents and path != root:
        raise ValueError("bad filename")
    if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
        raise ValueError("filename must end in .json, .yaml, or .yml")
    return path


def parse_scalar(value):
    value = value.strip().strip('"').strip("'")
    try:
        return float(value)
    except ValueError:
        return value


def parse_filter_text(text, suffix):
    if suffix.lower() == ".json":
        return json.loads(text)

    result = {"wedges": []}
    current = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "wedges:":
            continue
        if stripped.startswith("- "):
            if current:
                result["wedges"].append(current)
            current = {}
            stripped = stripped[2:].strip()
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                current[key.strip()] = parse_scalar(value)
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        if current is not None and raw_line.startswith((" ", "\t")):
            current[key] = parse_scalar(value)
        else:
            result[key] = parse_scalar(value)
    if current:
        result["wedges"].append(current)
    return result


def make_handler(state, output_dir):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.respond(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/scan":
                body = json.dumps(state.snapshot()).encode("utf-8")
                self.respond(200, body, "application/json")
                return
            if parsed.path == "/api/files":
                output_dir.mkdir(parents=True, exist_ok=True)
                files = [{"name": path.name} for path in filter_files(output_dir)]
                body = json.dumps({"ok": True, "files": files}).encode("utf-8")
                self.respond(200, body, "application/json")
                return
            if parsed.path == "/api/file":
                query = parse_qs(parsed.query)
                name = query.get("name", [""])[0]
                try:
                    path = safe_filter_path(output_dir, name)
                    data = parse_filter_text(path.read_text(encoding="utf-8"), path.suffix)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
                    self.respond(400, body, "application/json")
                    return
                body = json.dumps({"ok": True, "name": path.name, "filter": data}).encode("utf-8")
                self.respond(200, body, "application/json")
                return
            self.respond(404, b"not found\n", "text/plain")

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/api/save":
                self.respond(404, b'{"ok": false, "error": "not found"}\n', "application/json")
                return

            query = parse_qs(parsed.query)
            fmt = query.get("format", ["json"])[0]
            if fmt not in {"json", "yaml"}:
                self.respond(400, b'{"ok": false, "error": "bad format"}\n', "application/json")
                return

            length = int(self.headers.get("Content-Length", "0"))
            content = self.rfile.read(length).decode("utf-8")
            output_dir.mkdir(parents=True, exist_ok=True)
            name = query.get("name", [f"scan_wedge_filter.{fmt}"])[0] or f"scan_wedge_filter.{fmt}"
            if fmt == "yaml" and not name.lower().endswith((".yaml", ".yml")):
                name = f"{Path(name).stem}.yaml"
            if fmt == "json" and not name.lower().endswith(".json"):
                name = f"{Path(name).stem}.json"
            try:
                path = safe_filter_path(output_dir, name)
            except ValueError as exc:
                body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
                self.respond(400, body, "application/json")
                return
            path.write_text(content, encoding="utf-8")
            body = json.dumps({"ok": True, "name": path.name, "path": str(path)}).encode("utf-8")
            self.respond(200, body, "application/json")

        def log_message(self, fmt, *args):
            return

        def respond(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def spin_ros(state, stop_event):
    rclpy.init()
    node = ScanGuiNode(state)
    try:
        while rclpy.ok() and not stop_event.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def parse_args():
    parser = argparse.ArgumentParser(description="Web GUI for measuring LaserScan wedge masks.")
    parser.add_argument("--topic", default="/scan", help="LaserScan topic to inspect.")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=8090, help="HTTP port.")
    parser.add_argument(
        "--output-dir",
        default="/home/nvidia/857_Final_Project_Code/filters",
        help="Directory on the robot for server-side saved filter files.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    state = ScanState(args.topic)
    stop_event = threading.Event()
    ros_thread = threading.Thread(target=spin_ros, args=(state, stop_event), daemon=True)
    ros_thread.start()

    output_dir = Path(args.output_dir)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state, output_dir))
    print(f"Scan wedge GUI listening on http://{args.host}:{args.port}")
    print(f"Inspecting topic: {args.topic}")
    print(f"Robot-side saves go to: {output_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
        ros_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
