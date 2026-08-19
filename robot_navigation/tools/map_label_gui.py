#!/usr/bin/env python3
"""Browser UI for placing map labels and sending saved labels to Nav2."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import subprocess
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = ROOT / "maps"


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QBot Map Labeler</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #eef3f1; --panel: #fff; --ink: #172321; --muted: #64726f;
      --line: #cad6d2; --accent: #08758a; --accent2: #055468;
      --danger: #b23a48; --success: #19734a; --control: #fff;
      --toolbar: rgba(255,255,255,.94); --checker: #dce5e1; --checker2: #eaf0ed;
      --card: #fbfcfb; --canvas-shadow: rgba(20,32,31,.16); --overlay: rgba(14,25,23,.46);
    }
    :root[data-theme="dark"] {
      color-scheme: dark;
      --bg: #111917; --panel: #182320; --ink: #ecf4f1; --muted: #9aaca7;
      --line: #344640; --accent: #39b6cc; --accent2: #77d4e3;
      --danger: #ff8a98; --success: #69d59d; --control: #202d29;
      --toolbar: rgba(24,35,32,.95); --checker: #202e2a; --checker2: #293a35;
      --card: #1c2925; --canvas-shadow: rgba(0,0,0,.42); --overlay: rgba(0,0,0,.66);
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; font: 14px/1.45 "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace; color: var(--ink); background: var(--bg); }
    button, input, select { min-height: 36px; border: 1px solid var(--line); border-radius: 7px; background: var(--control); color: var(--ink); font: inherit; }
    button { padding: 0 11px; cursor: pointer; }
    button:hover:not(:disabled) { border-color: var(--accent); }
    button.primary { border-color: var(--accent); background: var(--accent); color: #fff; }
    button.primary:hover:not(:disabled) { background: var(--accent2); }
    button.danger { color: var(--danger); }
    button.localize { border-color: var(--accent); color: var(--accent2); font-weight: 700; }
    button.stop { border-color: var(--danger); background: var(--danger); color: #fff; font-weight: 800; }
    button.stop:hover:not(:disabled) { filter: brightness(.9); }
    button:disabled { opacity: .48; cursor: not-allowed; }
    input, select { padding: 0 10px; }
    .app { display: grid; grid-template-columns: minmax(0, 1fr) 360px; min-height: 100vh; }
    .main { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; min-width: 0; }
    .toolbar, .status { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--line); background: var(--toolbar); }
    .toolbar .grow { flex: 1; }
    .status { min-height: 44px; border-top: 1px solid var(--line); border-bottom: 0; color: var(--muted); }
    .status.error { color: var(--danger); }
    .status.success { color: var(--success); }
    .viewer { position: relative; overflow: auto; background-color: var(--checker); background-image: linear-gradient(45deg,var(--checker2) 25%,transparent 25%,transparent 75%,var(--checker2) 75%),linear-gradient(45deg,var(--checker2) 25%,transparent 25%,transparent 75%,var(--checker2) 75%); background-size: 24px 24px; background-position: 0 0,12px 12px; }
    .canvas-wrap { width: max-content; min-width: 100%; min-height: 100%; padding: 24px; }
    canvas { display: block; image-rendering: pixelated; background: var(--control); box-shadow: 0 10px 28px var(--canvas-shadow); transform-origin: top left; cursor: crosshair; }
    aside { display: grid; grid-template-rows: auto auto minmax(0, 1fr); min-height: 100vh; border-left: 1px solid var(--line); background: var(--panel); }
    .section { padding: 14px; border-bottom: 1px solid var(--line); }
    .section h2 { margin: 0 0 7px; font-size: 14px; }
    .hint { margin: 0; color: var(--muted); }
    .form-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    .actions { display: flex; gap: 8px; margin-top: 8px; }
    .label-list { overflow: auto; padding: 10px; }
    .label-item { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 8px; padding: 7px; margin-bottom: 8px; border: 1px solid var(--line); border-radius: 9px; background: var(--card); }
    .label-item.active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(8,117,138,.14); }
    .label-select { min-width: 0; height: auto; padding: 3px 5px; border: 0; background: transparent; text-align: left; }
    .go { align-self: center; color: var(--accent2); font-weight: 700; }
    .label-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 700; }
    .label-meta { margin-top: 2px; color: var(--muted); font-size: 12px; }
    .badge { margin-left: 6px; color: var(--muted); font-size: 11px; }
    .empty { padding: 18px 8px; color: var(--muted); text-align: center; }
    .backdrop { position: fixed; inset: 0; z-index: 20; display: grid; place-items: center; padding: 20px; background: var(--overlay); }
    .backdrop[hidden] { display: none; }
    .modal { width: min(430px,100%); padding: 18px; border-radius: 12px; background: var(--panel); box-shadow: 0 22px 60px rgba(0,0,0,.28); }
    .modal h2 { margin: 0 0 6px; font-size: 20px; }
    .modal p { margin: 0 0 14px; color: var(--muted); }
    .modal input { width: 100%; }
    .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
    .field-error { min-height: 20px; margin-top: 5px; color: var(--danger); font-size: 12px; }
    @media (max-width: 900px) { .app { grid-template-columns: 1fr; } aside { min-height: 380px; border-left: 0; border-top: 1px solid var(--line); } .toolbar { flex-wrap: wrap; } }
  </style>
</head>
<body>
  <div class="app">
    <main class="main">
      <div class="toolbar">
        <select id="mapSelect" title="Map"></select>
        <button id="reloadBtn">Reload</button>
        <button id="zoomOutBtn">−</button><button id="zoomInBtn">+</button><button id="fitBtn">Fit</button>
        <span class="grow"></span>
        <button id="localizeBtn" class="localize" type="button" title="Reset AMCL globally and rotate to localize">Localize</button>
        <button id="stopBtn" class="stop" type="button" title="Cancel navigation and stop the robot">Stop robot</button>
        <button id="themeBtn" type="button" title="Switch color theme" aria-label="Switch color theme">Dark</button>
        <button id="saveBtn" class="primary" disabled>Save Labels</button>
        <button id="exportBtn">Export PNG</button>
      </div>
      <div id="viewer" class="viewer"><div class="canvas-wrap"><canvas id="mapCanvas"></canvas></div></div>
      <div id="status" class="status">Loading maps…</div>
    </main>
    <aside>
      <section class="section"><h2>Add a location</h2><p class="hint">Click a white, navigable spot on the map, then give it a name.</p></section>
      <section class="section">
        <h2>Selected label</h2>
        <div class="form-row"><input id="editInput" placeholder="Select a label" disabled><button id="renameBtn" disabled>Rename</button></div>
        <div class="actions"><button id="deleteBtn" class="danger" disabled>Delete</button><button id="clearBtn" class="danger">Clear non-system labels</button></div>
      </section>
      <section id="labelList" class="label-list"></section>
    </aside>
  </div>
  <div id="addDialog" class="backdrop" hidden>
    <form id="addForm" class="modal">
      <h2>Name this location</h2><p id="addCoordinates"></p>
      <input id="addName" placeholder="Example: Lab entrance" autocomplete="off">
      <div id="addError" class="field-error"></div>
      <div class="modal-actions"><button id="cancelAddBtn" type="button">Cancel</button><button type="submit" class="primary">Add label</button></div>
    </form>
  </div>
  <script>
    const canvas = document.getElementById('mapCanvas'), ctx = canvas.getContext('2d');
    const viewer = document.getElementById('viewer'), statusEl = document.getElementById('status');
    const mapSelect = document.getElementById('mapSelect'), editInput = document.getElementById('editInput');
    const labelList = document.getElementById('labelList'), saveBtn = document.getElementById('saveBtn');
    const addDialog = document.getElementById('addDialog'), addForm = document.getElementById('addForm');
    const addName = document.getElementById('addName'), addError = document.getElementById('addError');
    const state = {mapName:null,mapImage:null,mapPixels:null,mapMeta:null,labels:[],selectedId:null,pendingPoint:null,zoom:1,dirty:false,saving:false,localizing:false};
    let localizationUiTimer=null;
    const selectedMapStorageKey = 'qbot-map-labeler-selected-map';
    const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2,9)}`;
    const activeLabel = () => state.labels.find(label => label.id === state.selectedId);
    const isOrigin = label => (label?.name || '').trim().toLowerCase() === 'origin';

    function applyTheme(theme) {
      document.documentElement.dataset.theme = theme;
      const button = document.getElementById('themeBtn');
      const nextTheme = theme === 'dark' ? 'light' : 'dark';
      button.textContent = nextTheme === 'dark' ? 'Dark' : 'Light';
      button.title = `Switch to ${nextTheme} theme`;
      button.setAttribute('aria-label', button.title);
    }
    function initialTheme() {
      const saved = localStorage.getItem('qbot-map-labeler-theme');
      if (saved === 'light' || saved === 'dark') return saved;
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    applyTheme(initialTheme());

    function setStatus(message, tone='') { statusEl.textContent = message; statusEl.className = `status ${tone}`.trim(); }
    function updateSaveButton() { saveBtn.disabled = !state.dirty || state.saving; saveBtn.textContent = state.saving ? 'Saving…' : 'Save Labels'; }
    function canvasPoint(event) { const rect=canvas.getBoundingClientRect(); return {x:Math.round((event.clientX-rect.left)*canvas.width/rect.width),y:Math.round((event.clientY-rect.top)*canvas.height/rect.height)}; }
    function worldFromPixel(x,y) {
      const meta=state.mapMeta||{}, resolution=Number(meta.resolution||0), origin=Array.isArray(meta.origin)?meta.origin:[0,0,0];
      if (!resolution || !canvas.height) return null;
      const lx=x*resolution, ly=(canvas.height-y)*resolution, yaw=Number(origin[2]||0);
      return {x:Number(origin[0]||0)+Math.cos(yaw)*lx-Math.sin(yaw)*ly,y:Number(origin[1]||0)+Math.sin(yaw)*lx+Math.cos(yaw)*ly};
    }
    function pixelClassification(point) {
      if (!state.mapPixels) return 'unknown';
      const value=state.mapPixels[point.y*canvas.width+point.x], negate=Number(state.mapMeta?.negate||0);
      if (value === 205) return 'unknown';
      const occupied=Number(state.mapMeta?.occupied_thresh??.65), free=Number(state.mapMeta?.free_thresh??.25);
      const occupancy=negate?value/255:(255-value)/255;
      return occupancy>occupied?'occupied':occupancy<free?'free':'unknown';
    }
    function draw() {
      if (!state.mapImage) return; ctx.putImageData(state.mapImage,0,0);
      const scale=Math.max(state.zoom,.01), radius=Math.max(5,7/scale), font=Math.max(14,13/scale);
      ctx.font=`${font}px system-ui,sans-serif`; ctx.lineWidth=Math.max(2,2/scale); ctx.textBaseline='middle';
      for (const label of state.labels) {
        const x=Number(label.x), y=Number(label.y); if (!Number.isFinite(x)||!Number.isFinite(y)) continue;
        const selected=label.id===state.selectedId; ctx.fillStyle=selected?'#b23a48':'#08758a'; ctx.strokeStyle='#fff';
        ctx.beginPath(); ctx.arc(x,y,selected?radius*1.25:radius,0,Math.PI*2); ctx.fill(); ctx.stroke();
        const text=label.name||'Label', offset=radius+5/scale, tx=x+offset, ty=y-offset, pad=5/scale, height=font+8/scale, width=ctx.measureText(text).width+pad*2;
        ctx.fillStyle='rgba(255,255,255,.9)'; ctx.fillRect(tx,ty-height/2,width,height); ctx.strokeStyle=selected?'#b23a48':'#08758a'; ctx.strokeRect(tx,ty-height/2,width,height); ctx.fillStyle='#172321'; ctx.fillText(text,tx+pad,ty);
      }
    }
    function selectLabel(label) { state.selectedId=label?.id||null; syncSelection(); renderList(); draw(); }
    function centerLabel(label) { viewer.scrollTo({left:Math.max(0,Number(label.x)*state.zoom-viewer.clientWidth/2),top:Math.max(0,Number(label.y)*state.zoom-viewer.clientHeight/2),behavior:'smooth'}); }
    function renderList() {
      labelList.innerHTML='';
      if (!state.labels.length) { labelList.innerHTML='<div class="empty">No labels yet. Click a white spot on the map to add one.</div>'; return; }
      for (const label of state.labels) {
        const item=document.createElement('div'); item.className=`label-item ${label.id===state.selectedId?'active':''}`;
        const select=document.createElement('button'); select.className='label-select'; select.type='button';
        const world=label.world||worldFromPixel(Number(label.x),Number(label.y));
        select.innerHTML='<div class="label-name"></div><div class="label-meta"></div>'; select.querySelector('.label-name').textContent=label.name;
        if (isOrigin(label)) { const badge=document.createElement('span'); badge.className='badge'; badge.textContent='system'; select.querySelector('.label-name').appendChild(badge); }
        select.querySelector('.label-meta').textContent=world?`map ${Number(world.x).toFixed(2)}, ${Number(world.y).toFixed(2)}`:`pixel ${label.x}, ${label.y}`;
        select.addEventListener('click',()=>{selectLabel(label);centerLabel(label);});
        const go=document.createElement('button'); go.className='go'; go.type='button'; go.textContent='Go'; go.disabled=state.localizing;go.title=state.localizing?'Wait for localization or press Stop':`Navigate to ${label.name}`; go.addEventListener('click',()=>goToLabel(label,go));
        item.append(select,go); labelList.appendChild(item);
      }
    }
    function syncSelection() { const label=activeLabel(), protectedLabel=isOrigin(label); editInput.disabled=!label||protectedLabel; document.getElementById('renameBtn').disabled=!label||protectedLabel; document.getElementById('deleteBtn').disabled=!label||protectedLabel; editInput.value=label?label.name:''; }
    function markDirty() { state.dirty=true; updateSaveButton(); setStatus(`Unsaved label changes for ${state.mapName}`); }
    async function fetchJson(url,options) { const response=await fetch(url,options); let data; try{data=await response.json();}catch{data={error:`${response.status} ${response.statusText}`};} if(!response.ok)throw new Error(data.error||`${response.status} ${response.statusText}`); return data; }
    async function loadMaps() {
      const data=await fetchJson('/api/maps'); mapSelect.innerHTML='';
      for(const map of data.maps){const option=document.createElement('option');option.value=map.name;option.textContent=map.name;mapSelect.appendChild(option);}
      if(!data.maps.length){setStatus('No .pgm maps found in the maps folder.','error');return;}
      const remembered=localStorage.getItem(selectedMapStorageKey),available=data.maps.some(map=>map.name===remembered);
      await loadMap(available?remembered:data.maps[0].name);
    }
    async function loadMap(name) {
      setStatus(`Loading ${name}…`); const data=await fetchJson(`/api/map?name=${encodeURIComponent(name)}`);
      Object.assign(state,{mapName:name,mapMeta:data.meta||{},labels:data.labels||[],selectedId:null,dirty:false,saving:false}); mapSelect.value=name;localStorage.setItem(selectedMapStorageKey,name);
      const bytes=Uint8Array.from(atob(data.pixels),c=>c.charCodeAt(0)); state.mapPixels=bytes; const image=ctx.createImageData(data.width,data.height);
      for(let i=0;i<bytes.length;i++){const j=i*4;image.data[j]=bytes[i];image.data[j+1]=bytes[i];image.data[j+2]=bytes[i];image.data[j+3]=255;}
      canvas.width=data.width;canvas.height=data.height;state.mapImage=image;fitMap();syncSelection();renderList();updateSaveButton();setStatus(`${name}: ${data.width} × ${data.height}, ${state.labels.length} saved labels`,'success');
    }
    function applyZoom(){canvas.style.width=`${canvas.width*state.zoom}px`;canvas.style.height=`${canvas.height*state.zoom}px`;draw();}
    function fitMap(){const pad=64,zx=Math.max(.01,(viewer.clientWidth-pad)/canvas.width),zy=Math.max(.01,(viewer.clientHeight-pad)/canvas.height);state.zoom=Math.max(.02,Math.min(3,Math.min(zx,zy)));applyZoom();}
    async function saveLabels(){
      if(!state.dirty)return{labels:state.labels}; state.saving=true;updateSaveButton();setStatus('Saving labels…');
      try{const data=await fetchJson('/api/labels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName,labels:state.labels})});state.labels=data.labels||state.labels;state.dirty=false;if(!state.labels.some(l=>l.id===state.selectedId))state.selectedId=null;renderList();syncSelection();draw();setStatus(`Saved ${data.count} labels to ${data.file}`,'success');return data;}
      catch(error){state.dirty=true;setStatus(`Save failed: ${error.message}`,'error');throw error;}finally{state.saving=false;updateSaveButton();}
    }
    async function goToLabel(label,button){
      try{if(state.dirty)await saveLabels();const saved=state.labels.find(candidate=>candidate.id===label.id);if(!saved)throw new Error('The label was not found after saving.');const world=saved.world||worldFromPixel(saved.x,saved.y),coords=world?` (${Number(world.x).toFixed(2)}, ${Number(world.y).toFixed(2)})`:'';if(!confirm(`Send the robot to “${saved.name}”${coords}?`))return;
        const original=button.textContent;button.disabled=true;button.textContent='Sending…';setStatus(`Sending navigation command for ${saved.name}…`);
        try{const data=await fetchJson('/api/go',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName,label_id:saved.id})});if(data.cancelled_by_stop)setStatus(`Navigation to ${data.name} was cancelled by Stop.`,'success');else setStatus(`Navigation command sent for ${data.name} on ${data.topic} (ROS domain ${data.ros_domain_id})`,'success');}finally{button.disabled=false;button.textContent=original;}}
      catch(error){setStatus(`Could not navigate: ${error.message}`,'error');}
    }
    async function stopNavigation(){
      const button=document.getElementById('stopBtn'),original=button.textContent;button.disabled=true;button.textContent='Stopping…';setStatus('Sending emergency navigation stop…','error');
      try{const data=await fetchJson('/api/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(localizationUiTimer)clearTimeout(localizationUiTimer);localizationUiTimer=null;state.localizing=false;document.getElementById('localizeBtn').disabled=false;renderList();setStatus(`Stop command sent on ${data.topic} (ROS domain ${data.ros_domain_id})`,'success');}
      catch(error){setStatus(`Could not send stop command: ${error.message}`,'error');}
      finally{button.disabled=false;button.textContent=original;}
    }
    async function localizeRobot(){
      if(!confirm('The robot will stop navigation and slowly rotate 360° to localize. Make sure it has clear space. Continue?'))return;
      const button=document.getElementById('localizeBtn'),original=button.textContent;button.disabled=true;button.textContent='Starting…';setStatus('Starting AMCL global localization…');
      try{const data=await fetchJson('/api/localize',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(data.cancelled_by_stop){setStatus('Localization was cancelled by Stop.','success');}else{state.localizing=true;button.disabled=true;renderList();setStatus(`Localization started on ROS domain ${data.ros_domain_id}. Go is locked during the rotation; Stop remains available.`,'success');localizationUiTimer=setTimeout(()=>{state.localizing=false;button.disabled=false;localizationUiTimer=null;renderList();setStatus('Localization rotation finished. Verify that the AMCL pose matches the robot before using Go.','success');},23000);}}
      catch(error){setStatus(`Could not start localization: ${error.message}`,'error');}
      finally{if(!state.localizing)button.disabled=false;button.textContent=original;}
    }
    function nearestLabel(point){const threshold=15/Math.max(state.zoom,.02);let nearest=null,distance=threshold;for(const label of state.labels){const d=Math.hypot(Number(label.x)-point.x,Number(label.y)-point.y);if(d<distance){nearest=label;distance=d;}}return nearest;}
    function openAddDialog(point){state.pendingPoint=point;const world=worldFromPixel(point.x,point.y);document.getElementById('addCoordinates').textContent=world?`Map coordinates: ${world.x.toFixed(3)}, ${world.y.toFixed(3)}`:`Pixel: ${point.x}, ${point.y}`;addName.value='';addError.textContent='';addDialog.hidden=false;requestAnimationFrame(()=>addName.focus());}
    function closeAddDialog(){state.pendingPoint=null;addDialog.hidden=true;addName.value='';addError.textContent='';}
    canvas.addEventListener('click',event=>{if(!state.mapImage||!addDialog.hidden)return;const point=canvasPoint(event);if(point.x<0||point.y<0||point.x>=canvas.width||point.y>=canvas.height)return;const label=nearestLabel(point);if(label){selectLabel(label);return;}const classification=pixelClassification(point);if(classification!=='free'){setStatus(`That pixel is ${classification}. Click a white, navigable location.`,'error');return;}openAddDialog(point);});
    addForm.addEventListener('submit',event=>{event.preventDefault();const name=addName.value.trim();if(!name){addError.textContent='Enter a name for this location.';addName.focus();return;}if(state.labels.some(label=>label.name.trim().toLowerCase()===name.toLowerCase())){addError.textContent='A label with that name already exists.';addName.focus();return;}const point=state.pendingPoint,label={id:newId(),name,kind:'navigation',detail:'',source:'browser',x:point.x,y:point.y,world:worldFromPixel(point.x,point.y),yaw:0};state.labels.push(label);closeAddDialog();selectLabel(label);markDirty();});
    document.getElementById('cancelAddBtn').addEventListener('click',closeAddDialog);addDialog.addEventListener('click',event=>{if(event.target===addDialog)closeAddDialog();});document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!addDialog.hidden)closeAddDialog();});
    document.getElementById('renameBtn').addEventListener('click',()=>{const label=activeLabel();if(!label||isOrigin(label))return;const name=editInput.value.trim();if(!name){setStatus('A label name cannot be empty.','error');return;}if(state.labels.some(candidate=>candidate.id!==label.id&&candidate.name.trim().toLowerCase()===name.toLowerCase())){setStatus(`A label named “${name}” already exists.`,'error');return;}label.name=name;markDirty();renderList();draw();});
    editInput.addEventListener('keydown',event=>{if(event.key==='Enter')document.getElementById('renameBtn').click();});
    document.getElementById('deleteBtn').addEventListener('click',()=>{const label=activeLabel();if(!label||isOrigin(label)||!confirm(`Delete “${label.name}”?`))return;state.labels=state.labels.filter(candidate=>candidate.id!==label.id);state.selectedId=null;markDirty();syncSelection();renderList();draw();});
    document.getElementById('clearBtn').addEventListener('click',()=>{const removable=state.labels.filter(label=>!isOrigin(label));if(!removable.length||!confirm(`Delete ${removable.length} non-system labels?`))return;state.labels=state.labels.filter(isOrigin);state.selectedId=null;markDirty();syncSelection();renderList();draw();});
    saveBtn.addEventListener('click',()=>saveLabels().catch(()=>{}));document.getElementById('reloadBtn').addEventListener('click',()=>{if(state.dirty&&!confirm('Reload and discard unsaved label changes?'))return;loadMap(state.mapName).catch(error=>setStatus(error.message,'error'));});
    document.getElementById('fitBtn').addEventListener('click',fitMap);document.getElementById('zoomInBtn').addEventListener('click',()=>{state.zoom=Math.min(8,state.zoom*1.25);applyZoom();});document.getElementById('zoomOutBtn').addEventListener('click',()=>{state.zoom=Math.max(.02,state.zoom/1.25);applyZoom();});
    document.getElementById('themeBtn').addEventListener('click',()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';localStorage.setItem('qbot-map-labeler-theme',theme);applyTheme(theme);});
    document.getElementById('stopBtn').addEventListener('click',stopNavigation);
    document.getElementById('localizeBtn').addEventListener('click',localizeRobot);
    document.getElementById('exportBtn').addEventListener('click',()=>{draw();const link=document.createElement('a');link.href=canvas.toDataURL('image/png');link.download=`${state.mapName.replace(/\.[^.]+$/,'')}_annotated.png`;link.click();});
    mapSelect.addEventListener('change',()=>{if(state.dirty&&!confirm('Switch maps and discard unsaved label changes?')){mapSelect.value=state.mapName;return;}loadMap(mapSelect.value).catch(error=>setStatus(error.message,'error'));});
    window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});window.addEventListener('resize',()=>{if(state.mapImage)applyZoom();});loadMaps().catch(error=>setStatus(error.message,'error'));
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
            tokens.extend(line.split(b"#", 1)[0].split())
        width, height, max_value = (int(token) for token in tokens[:3])
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
        key, value = (part.strip() for part in line.split(":", 1))
        if key in {"resolution", "occupied_thresh", "free_thresh"}:
            meta[key] = float(value)
        elif key == "negate":
            meta[key] = int(value)
        elif key == "origin":
            meta[key] = json.loads(value.replace("'", '"'))
        else:
            meta[key] = value.strip('"')
    return meta


def map_geometry(map_path: Path) -> tuple[int, int, float, tuple[float, float, float]]:
    metadata = parse_yaml(map_path.with_suffix(".yaml"))
    resolution = float(metadata.get("resolution") or 0)
    raw_origin = metadata.get("origin")
    if resolution <= 0:
        raise ValueError(f"Missing positive resolution in {map_path.with_suffix('.yaml')}")
    if not isinstance(raw_origin, list) or len(raw_origin) < 3:
        raise ValueError(f"Invalid origin in {map_path.with_suffix('.yaml')}")
    width, height, _ = read_pgm(map_path)
    return width, height, resolution, tuple(float(value) for value in raw_origin[:3])


def world_from_pixel(map_path: Path, pixel_x: float, pixel_y: float) -> tuple[float, float]:
    _, height, resolution, origin = map_geometry(map_path)
    local_x, local_y = pixel_x * resolution, (height - pixel_y) * resolution
    cos_yaw, sin_yaw = math.cos(origin[2]), math.sin(origin[2])
    return (
        origin[0] + cos_yaw * local_x - sin_yaw * local_y,
        origin[1] + sin_yaw * local_x + cos_yaw * local_y,
    )


def pixel_from_world(map_path: Path, world_x: float, world_y: float) -> tuple[int, int]:
    _, height, resolution, origin = map_geometry(map_path)
    delta_x, delta_y = world_x - origin[0], world_y - origin[1]
    cos_yaw, sin_yaw = math.cos(origin[2]), math.sin(origin[2])
    local_x = cos_yaw * delta_x + sin_yaw * delta_y
    local_y = -sin_yaw * delta_x + cos_yaw * delta_y
    return round(local_x / resolution), round(height - local_y / resolution)


def pixel_classification(map_path: Path, pixel_x: float, pixel_y: float) -> str:
    width, height, pixels = read_pgm(map_path)
    x, y = round(pixel_x), round(pixel_y)
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError(f"Pixel ({pixel_x}, {pixel_y}) is outside the {width} x {height} map")
    metadata = parse_yaml(map_path.with_suffix(".yaml"))
    value = pixels[y * width + x]
    if value == 205:
        return "unknown"
    occupancy = value / 255 if int(metadata.get("negate", 0)) else (255 - value) / 255
    if occupancy > float(metadata.get("occupied_thresh", 0.65)):
        return "occupied"
    if occupancy < float(metadata.get("free_thresh", 0.25)):
        return "free"
    return "unknown"


def label_path_for(map_path: Path) -> Path:
    return map_path.with_name(f"{map_path.stem}_labels.json")


def origin_label_for(map_path: Path) -> dict:
    x, y = pixel_from_world(map_path, 0.0, 0.0)
    return {"id": "origin", "name": "origin", "kind": "navigation", "detail": "Robot origin", "source": "auto", "x": x, "y": y, "world": {"x": 0.0, "y": 0.0}, "yaw": 0.0}


def ensure_origin_label(map_path: Path, labels: list[dict]) -> list[dict]:
    if any(str(label.get("name", "")).strip().casefold() == "origin" for label in labels):
        return labels
    return [*labels, origin_label_for(map_path)]


def normalize_labels(map_path: Path, labels: list[dict], *, enforce_free: bool = False) -> list[dict]:
    if not isinstance(labels, list):
        raise ValueError("labels must be a list")
    width, height, _, _ = map_geometry(map_path)
    normalized, names, identifiers = [], set(), set()
    for index, raw_label in enumerate(ensure_origin_label(map_path, labels)):
        if not isinstance(raw_label, dict):
            raise ValueError(f"Label {index + 1} must be an object")
        label = dict(raw_label)
        name = str(label.get("name", "")).strip()
        if not name:
            raise ValueError(f"Label {index + 1} has an empty name")
        name_key = name.casefold()
        if name_key in names:
            raise ValueError(f"Duplicate label name: {name}")
        names.add(name_key)
        identifier = str(label.get("id") or f"label-{index + 1}").strip()
        if not identifier or identifier in identifiers:
            raise ValueError(f"Duplicate or empty label id: {identifier!r}")
        identifiers.add(identifier)
        pixel_x, pixel_y = label.get("x"), label.get("y")
        if pixel_x is None or pixel_y is None:
            world = label.get("world")
            if not isinstance(world, dict) or world.get("x") is None or world.get("y") is None:
                raise ValueError(f"Label {name!r} has neither pixel nor world coordinates")
            pixel_x, pixel_y = pixel_from_world(map_path, float(world["x"]), float(world["y"]))
        pixel_x, pixel_y = float(pixel_x), float(pixel_y)
        if not 0 <= pixel_x < width or not 0 <= pixel_y < height:
            raise ValueError(f"Label {name!r} is outside the {width} x {height} map")
        if enforce_free and name_key != "origin" and str(label.get("source", "")) == "browser":
            classification = pixel_classification(map_path, pixel_x, pixel_y)
            if classification != "free":
                raise ValueError(f"Label {name!r} is on {classification} space; click a white navigable location")
        world_x, world_y = world_from_pixel(map_path, pixel_x, pixel_y)
        label.update({"id": identifier, "name": name, "kind": str(label.get("kind") or "navigation"), "detail": str(label.get("detail") or ""), "source": str(label.get("source") or "manual"), "x": pixel_x, "y": pixel_y, "world": {"x": world_x, "y": world_y}, "yaw": float(label.get("yaw", 0.0))})
        normalized.append(label)
    return normalized


def read_labels(map_path: Path) -> list[dict]:
    path = label_path_for(map_path)
    if not path.exists():
        return normalize_labels(map_path, [])
    data = json.loads(path.read_text(encoding="utf-8"))
    return normalize_labels(map_path, data.get("labels", []) if isinstance(data, dict) else [])


def write_labels(map_path: Path, labels: list[dict]) -> tuple[Path, list[dict]]:
    normalized = normalize_labels(map_path, labels, enforce_free=True)
    output = {"map": map_path.name, "yaml": map_path.with_suffix(".yaml").name, "labels": normalized}
    label_path, temporary_path = label_path_for(map_path), None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=label_path.parent, prefix=f".{label_path.name}.", suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(output, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, label_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return label_path, normalized


def publish_label(label_name: str, topic: str, timeout: float, ros_domain_id: int = 63) -> None:
    command = ["ros2", "topic", "pub", "--once", topic, "std_msgs/msg/String", json.dumps({"data": label_name})]
    environment = os.environ.copy()
    environment["ROS_DOMAIN_ID"] = str(ros_domain_id)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ros2 was not found; start the labeler from a ROS-sourced terminal") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"No {topic} listener responded within {timeout:g} seconds on ROS domain "
            f"{ros_domain_id}; is navigation running?"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"ros2 topic pub exited with status {result.returncode}")


class Handler(BaseHTTPRequestHandler):
    server_version = "MapLabelGUI/2.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def write_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_text(self, value: str, content_type: str = "text/plain") -> None:
        body = value.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode())
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def resolve_map(self, name: str) -> Path:
        map_path = MAPS_DIR / safe_map_name(name)
        if not map_path.exists():
            raise FileNotFoundError("Map not found")
        return map_path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.write_text(INDEX_HTML, "text/html")
            elif parsed.path == "/api/maps":
                self.write_json({"maps": [{"name": path.name} for path in sorted(MAPS_DIR.glob("*.pgm"))]})
            elif parsed.path == "/api/map":
                map_path = self.resolve_map(parse_qs(parsed.query).get("name", [""])[0])
                width, height, pixels = read_pgm(map_path)
                self.write_json({"name": map_path.name, "width": width, "height": height, "pixels": base64.b64encode(pixels).decode(), "meta": parse_yaml(map_path.with_suffix(".yaml")), "labels": read_labels(map_path)})
            else:
                self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/labels":
                data = self.read_json_body()
                map_path = self.resolve_map(str(data.get("map", "")))
                path, labels = write_labels(map_path, data.get("labels", []))
                self.write_json({"file": str(path.relative_to(ROOT)), "count": len(labels), "labels": labels})
            elif self.path == "/api/go":
                data = self.read_json_body()
                map_path = self.resolve_map(str(data.get("map", "")))
                if not label_path_for(map_path).exists():
                    self.write_json({"error": "Save the labels before navigating"}, HTTPStatus.CONFLICT)
                    return
                label_id = str(data.get("label_id", ""))
                label = next((item for item in read_labels(map_path) if item["id"] == label_id), None)
                if label is None:
                    self.write_json({"error": "Saved label not found"}, HTTPStatus.NOT_FOUND)
                    return
                topic = str(getattr(self.server, "label_topic", "/label"))
                ros_domain_id = int(getattr(self.server, "ros_domain_id", 63))
                with self.server.navigation_lock:
                    stop_generation = self.server.stop_generation
                publish_label(
                    label["name"],
                    topic,
                    float(getattr(self.server, "go_timeout", 10)),
                    ros_domain_id,
                )
                with self.server.navigation_lock:
                    cancelled_by_stop = self.server.stop_generation != stop_generation
                if cancelled_by_stop:
                    # A concurrent Stop may have reached DDS before this short-lived Go
                    # publisher. Publish Stop again to guarantee Stop wins the race.
                    publish_label(
                        "__stop_navigation__",
                        topic,
                        float(getattr(self.server, "go_timeout", 10)),
                        ros_domain_id,
                    )
                self.write_json(
                    {
                        "name": label["name"],
                        "label_id": label["id"],
                        "topic": topic,
                        "ros_domain_id": ros_domain_id,
                        "cancelled_by_stop": cancelled_by_stop,
                    }
                )
            elif self.path == "/api/stop":
                self.read_json_body()
                topic = str(getattr(self.server, "label_topic", "/label"))
                ros_domain_id = int(getattr(self.server, "ros_domain_id", 63))
                with self.server.navigation_lock:
                    self.server.stop_generation += 1
                publish_label(
                    "__stop_navigation__",
                    topic,
                    float(getattr(self.server, "go_timeout", 10)),
                    ros_domain_id,
                )
                self.write_json(
                    {
                        "stopped": True,
                        "topic": topic,
                        "ros_domain_id": ros_domain_id,
                    }
                )
            elif self.path == "/api/localize":
                self.read_json_body()
                topic = str(getattr(self.server, "label_topic", "/label"))
                ros_domain_id = int(getattr(self.server, "ros_domain_id", 63))
                with self.server.navigation_lock:
                    stop_generation = self.server.stop_generation
                publish_label(
                    "__localize__",
                    topic,
                    float(getattr(self.server, "go_timeout", 10)),
                    ros_domain_id,
                )
                with self.server.navigation_lock:
                    cancelled_by_stop = self.server.stop_generation != stop_generation
                if cancelled_by_stop:
                    publish_label(
                        "__stop_navigation__",
                        topic,
                        float(getattr(self.server, "go_timeout", 10)),
                        ros_domain_id,
                    )
                self.write_json(
                    {
                        "localizing": not cancelled_by_stop,
                        "topic": topic,
                        "ros_domain_id": ros_domain_id,
                        "cancelled_by_stop": cancelled_by_stop,
                    }
                )
            else:
                self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except RuntimeError as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a browser GUI for labeling ROS PGM maps.")
    parser.add_argument("--host", default="0.0.0.0", help="Host/interface to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    parser.add_argument("--label-topic", default="/label", help="ROS String topic used by Go")
    parser.add_argument("--go-timeout", type=float, default=10, help="Seconds to wait for the ROS label publication")
    parser.add_argument(
        "--ros-domain-id",
        type=int,
        default=63,
        help="ROS domain used by the Go button (default: 63)",
    )
    args = parser.parse_args()
    if args.go_timeout <= 0:
        parser.error("--go-timeout must be positive")
    if not 0 <= args.ros_domain_id <= 232:
        parser.error("--ros-domain-id must be between 0 and 232")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.label_topic, server.go_timeout = args.label_topic, args.go_timeout
    server.ros_domain_id = args.ros_domain_id
    server.navigation_lock = threading.Lock()
    server.stop_generation = 0
    print(f"Map label GUI: http://{args.host}:{args.port}")
    print(f"Serving maps from: {MAPS_DIR}")
    print(f"Go publishes labels on: {args.label_topic}")
    print(f"Go uses ROS domain: {args.ros_domain_id}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping map label GUI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
