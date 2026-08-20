#!/usr/bin/env python3
"""Browser UI for placing map labels and sending saved labels to Nav2."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped
except ImportError as exc:
    rclpy = None
    PoseWithCovarianceStamped = None
    RCLPY_IMPORT_ERROR = str(exc)
else:
    RCLPY_IMPORT_ERROR = ""


ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = ROOT / "maps"
REPO_DIR = ROOT.parent
RUN_NAVIGATION_SCRIPT = REPO_DIR / "run_qbot_navigation.sh"
REBUILD_NAVIGATION_SCRIPT = REPO_DIR / "rebuild_qbot_navigation.sh"
NAVIGATION_SETUP = ROOT / "install" / "setup.bash"
SCAN_FILTER_FILE = ROOT / "filters" / "scan_wedge_filter.json"


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
      --danger: #b23a48; --success: #19734a; --warning: #9a5d00; --control: #fff;
      --toolbar: rgba(255,255,255,.94); --checker: #dce5e1; --checker2: #eaf0ed;
      --card: #fbfcfb; --canvas-shadow: rgba(20,32,31,.16); --overlay: rgba(14,25,23,.46);
    }
    :root[data-theme="dark"] {
      color-scheme: dark;
      --bg: #111917; --panel: #182320; --ink: #ecf4f1; --muted: #9aaca7;
      --line: #344640; --accent: #39b6cc; --accent2: #77d4e3;
      --danger: #ff8a98; --success: #69d59d; --warning: #ffbf69; --control: #202d29;
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
    .main { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; min-width: 0; }
    .toolbar, .status { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--line); background: var(--toolbar); }
    .toolbar .grow { flex: 1; }
    .status { min-height: 44px; border-top: 1px solid var(--line); border-bottom: 0; color: var(--muted); }
    .status.error { color: var(--danger); }
    .status.success { color: var(--success); }
    .navigation-panel { display: grid; gap: 8px; padding: 9px 12px; border-bottom: 1px solid var(--line); background: var(--panel); }
    .navigation-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .navigation-row .grow { flex: 1; }
    .nav-state { padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-weight: 700; text-transform: capitalize; }
    .nav-state.ready { border-color: var(--success); color: var(--success); }
    .nav-state.error { border-color: var(--danger); color: var(--danger); }
    .nav-state.building, .nav-state.starting, .nav-state.stopping { border-color: var(--warning); color: var(--warning); }
    .nav-message { color: var(--muted); }
    .map-warning { padding: 9px 11px; border: 1px solid var(--warning); border-radius: 8px; color: var(--warning); background: var(--card); }
    .map-warning[hidden] { display: none; }
    .toast { position: fixed; z-index: 30; top: 16px; right: 16px; width: min(440px,calc(100vw - 32px)); padding: 13px 15px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); box-shadow: 0 16px 45px var(--canvas-shadow); }
    .toast.success { border-color: var(--success); color: var(--success); }
    .toast.error { border-color: var(--danger); color: var(--danger); }
    .toast[hidden] { display: none; }
    .viewer { position: relative; overflow: auto; background-color: var(--checker); background-image: linear-gradient(45deg,var(--checker2) 25%,transparent 25%,transparent 75%,var(--checker2) 75%),linear-gradient(45deg,var(--checker2) 25%,transparent 25%,transparent 75%,var(--checker2) 75%); background-size: 24px 24px; background-position: 0 0,12px 12px; }
    .canvas-wrap { width: max-content; min-width: 100%; min-height: 100%; padding: 24px; }
    .canvas-stage { position: relative; width: max-content; }
    canvas { display: block; image-rendering: pixelated; transform-origin: top left; }
    #mapCanvas { background: var(--control); box-shadow: 0 10px 28px var(--canvas-shadow); cursor: crosshair; }
    #poseCanvas { position: absolute; inset: 0; pointer-events: none; }
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
    .pose-status { margin-top: 10px; padding: 8px; border: 1px solid var(--line); border-radius: 7px; color: var(--muted); font-size: 12px; }
    .pose-status.live { border-color: var(--success); color: var(--success); }
    .pose-status.stale { border-color: var(--danger); color: var(--danger); }
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
        <button id="savePoseBtn" type="button" title="Save the live AMCL pose as init_pose" disabled>Save init_pose</button>
        <button id="stopBtn" class="stop" type="button" title="Cancel navigation and stop the robot">Stop robot</button>
        <button id="themeBtn" type="button" title="Switch color theme" aria-label="Switch color theme">Dark</button>
        <button id="saveBtn" class="primary" disabled>Save Labels</button>
        <button id="exportBtn">Export PNG</button>
      </div>
      <div class="navigation-panel">
        <div class="navigation-row">
          <span id="navState" class="nav-state">Stopped</span>
          <span id="navMessage" class="nav-message">Navigation is stopped.</span>
          <span class="grow"></span>
          <button id="rebuildNavBtn" type="button">Rebuild</button>
          <button id="startNavBtn" class="primary" type="button">Start Navigation</button>
          <button id="stopNavBtn" class="danger" type="button" disabled>Stop Navigation</button>
        </div>
        <div id="mapWarning" class="map-warning" hidden></div>
      </div>
      <div id="viewer" class="viewer"><div class="canvas-wrap"><div class="canvas-stage"><canvas id="mapCanvas"></canvas><canvas id="poseCanvas"></canvas></div></div></div>
      <div id="status" class="status">Loading maps…</div>
    </main>
    <aside>
      <section class="section"><h2>Add a location</h2><p class="hint">Click a white, navigable spot on the map, then give it a name.</p><div id="poseStatus" class="pose-status">QBot pose: waiting for /amcl_pose…</div></section>
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
  <div id="toast" class="toast" role="status" aria-live="polite" hidden></div>
  <script>
    const canvas = document.getElementById('mapCanvas'), ctx = canvas.getContext('2d'),poseCanvas=document.getElementById('poseCanvas'),poseCtx=poseCanvas.getContext('2d');
    const viewer = document.getElementById('viewer'), statusEl = document.getElementById('status');
    const mapSelect = document.getElementById('mapSelect'), editInput = document.getElementById('editInput');
    const labelList = document.getElementById('labelList'), saveBtn = document.getElementById('saveBtn');
    const addDialog = document.getElementById('addDialog'), addForm = document.getElementById('addForm');
    const addName = document.getElementById('addName'), addError = document.getElementById('addError');
    const state = {mapName:null,mapImage:null,mapPixels:null,mapMeta:null,labels:[],selectedId:null,pendingPoint:null,zoom:1,dirty:false,saving:false,localizing:false,robotPose:null,navigation:{state:'stopped',active_map:null,ready:false,message:'Navigation is stopped.',error:null,managed_process:false}};
    let localizationUiTimer=null,toastTimer=null,lastNavigationState='stopped';
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
    function selectedMapIsActive(){return Boolean(state.navigation?.ready&&state.navigation.active_map===state.mapName);}
    function showToast(message,tone='success'){
      const toast=document.getElementById('toast');toast.textContent=message;toast.className=`toast ${tone}`;toast.hidden=false;
      if(toastTimer)clearTimeout(toastTimer);toastTimer=setTimeout(()=>{toast.hidden=true;toastTimer=null;},6500);
    }
    function applyNavigationStatus(status){
      const previous=lastNavigationState,previousNavigation=state.navigation,wasLocalizing=state.localizing;state.navigation=status;lastNavigationState=status.state;
      const stateEl=document.getElementById('navState'),messageEl=document.getElementById('navMessage'),warning=document.getElementById('mapWarning');
      stateEl.textContent=status.state||'unknown';stateEl.className=`nav-state ${status.state||''}`.trim();messageEl.textContent=status.error||status.message||'';
      const busy=['building','starting','stopping'].includes(status.state),canStart=['stopped','error'].includes(status.state);
      document.getElementById('startNavBtn').disabled=!state.mapName||!canStart||state.saving;
      document.getElementById('stopNavBtn').disabled=!(status.managed_process||['building','starting','ready'].includes(status.state))||status.state==='stopping';
      document.getElementById('rebuildNavBtn').disabled=!canStart;
      document.getElementById('stopBtn').disabled=!status.ready;
      const mapMismatch=Boolean(status.active_map&&state.mapName&&status.active_map!==state.mapName&&['building','starting','ready','stopping'].includes(status.state));
      warning.hidden=!mapMismatch;
      if(mapMismatch)warning.textContent=`Displayed map: ${state.mapName}. Active Nav2 map: ${status.active_map}. Stop Navigation, then Start Navigation to use the displayed map.`;
      if(previous!=='ready'&&status.state==='ready')showToast(`Navigation is ready with ${status.active_map}.`,'success');
      if(previous==='building'&&status.state==='stopped'&&String(status.message||'').toLowerCase().includes('build completed'))showToast('Navigation build completed successfully.','success');
      if(previous!=='error'&&status.state==='error')showToast(`${status.error||status.message} Check the terminal for details.`,'error');
      if(!busy&&status.state!=='ready'&&state.localizing){state.localizing=false;if(localizationUiTimer)clearTimeout(localizationUiTimer);localizationUiTimer=null;}
      document.getElementById('localizeBtn').disabled=!selectedMapIsActive()||state.localizing;
      if(previousNavigation.state!==status.state||previousNavigation.active_map!==status.active_map||previousNavigation.ready!==status.ready||wasLocalizing!==state.localizing)renderList();
      updatePoseDisplay();
    }
    async function refreshNavigationStatus(){
      try{applyNavigationStatus(await fetchJson('/api/navigation/status'));}
      catch(error){applyNavigationStatus({state:'error',active_map:null,ready:false,message:error.message,error:error.message,managed_process:false});}
    }
    function updateSaveButton() { saveBtn.disabled = !state.dirty || state.saving; saveBtn.textContent = state.saving ? 'Saving…' : 'Save Labels'; }
    function canvasPoint(event) { const rect=canvas.getBoundingClientRect(); return {x:Math.round((event.clientX-rect.left)*canvas.width/rect.width),y:Math.round((event.clientY-rect.top)*canvas.height/rect.height)}; }
    function worldFromPixel(x,y) {
      const meta=state.mapMeta||{}, resolution=Number(meta.resolution||0), origin=Array.isArray(meta.origin)?meta.origin:[0,0,0];
      if (!resolution || !canvas.height) return null;
      const lx=x*resolution, ly=(canvas.height-y)*resolution, yaw=Number(origin[2]||0);
      return {x:Number(origin[0]||0)+Math.cos(yaw)*lx-Math.sin(yaw)*ly,y:Number(origin[1]||0)+Math.sin(yaw)*lx+Math.cos(yaw)*ly};
    }
    function pixelFromWorld(x,y) {
      const meta=state.mapMeta||{},resolution=Number(meta.resolution||0),origin=Array.isArray(meta.origin)?meta.origin:[0,0,0];
      if(!resolution||!canvas.height)return null;
      const dx=x-Number(origin[0]||0),dy=y-Number(origin[1]||0),yaw=Number(origin[2]||0);
      const localX=Math.cos(yaw)*dx+Math.sin(yaw)*dy,localY=-Math.sin(yaw)*dx+Math.cos(yaw)*dy;
      return {x:localX/resolution,y:canvas.height-localY/resolution};
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
      drawRobotPose();
    }
    function drawRobotPose() {
      poseCtx.clearRect(0,0,poseCanvas.width,poseCanvas.height);
      const pose=state.robotPose;
      if(!selectedMapIsActive()||!pose?.available||!pose.world)return;
      const point=pixelFromWorld(Number(pose.world.x),Number(pose.world.y));
      if(!point||point.x<0||point.y<0||point.x>=canvas.width||point.y>=canvas.height)return;
      const scale=Math.max(state.zoom,.01),resolution=Number(state.mapMeta?.resolution||.05),originYaw=Number(state.mapMeta?.origin?.[2]||0);
      const uncertainty=Math.max(Number(pose.uncertainty?.x_std_dev||0),Number(pose.uncertainty?.y_std_dev||0));
      const uncertaintyRadius=Math.min(180/scale,Math.max(0,uncertainty/resolution));
      const markerRadius=Math.max(7,10/scale),arrowLength=Math.max(14,20/scale),color=pose.stale?'#b23a48':'#e68619';
      poseCtx.save();poseCtx.translate(point.x,point.y);
      if(uncertaintyRadius>markerRadius){poseCtx.beginPath();poseCtx.setLineDash([5/scale,4/scale]);poseCtx.lineWidth=Math.max(1.5,2/scale);poseCtx.strokeStyle=color;poseCtx.globalAlpha=.55;poseCtx.arc(0,0,uncertaintyRadius,0,Math.PI*2);poseCtx.stroke();poseCtx.globalAlpha=1;poseCtx.setLineDash([]);}
      poseCtx.rotate(-(Number(pose.yaw||0)-originYaw));poseCtx.fillStyle=color;poseCtx.strokeStyle='#fff';poseCtx.lineWidth=Math.max(2,2/scale);poseCtx.beginPath();poseCtx.moveTo(arrowLength,0);poseCtx.lineTo(-markerRadius,markerRadius*.8);poseCtx.lineTo(-markerRadius,-markerRadius*.8);poseCtx.closePath();poseCtx.fill();poseCtx.stroke();poseCtx.restore();
      const font=Math.max(14,13/scale);poseCtx.font=`700 ${font}px "JetBrains Mono",monospace`;poseCtx.textBaseline='bottom';poseCtx.fillStyle=color;poseCtx.strokeStyle='#fff';poseCtx.lineWidth=Math.max(2,3/scale);poseCtx.strokeText('QBot',point.x+markerRadius,point.y-markerRadius);poseCtx.fillText('QBot',point.x+markerRadius,point.y-markerRadius);
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
        const go=document.createElement('button'); go.className='go'; go.type='button'; go.textContent='Go'; go.disabled=state.localizing||!selectedMapIsActive();go.title=state.localizing?'Wait for localization or press Stop':(!selectedMapIsActive()?'Start navigation with this displayed map first':`Navigate to ${label.name}`); go.addEventListener('click',()=>goToLabel(label,go));
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
      canvas.width=data.width;canvas.height=data.height;poseCanvas.width=data.width;poseCanvas.height=data.height;state.mapImage=image;fitMap();syncSelection();renderList();updateSaveButton();setStatus(`${name}: ${data.width} × ${data.height}, ${state.labels.length} saved labels`,'success');
      applyNavigationStatus(state.navigation);
    }
    function applyZoom(){const width=`${canvas.width*state.zoom}px`,height=`${canvas.height*state.zoom}px`;canvas.style.width=width;canvas.style.height=height;poseCanvas.style.width=width;poseCanvas.style.height=height;draw();}
    function fitMap(){const pad=64,zx=Math.max(.01,(viewer.clientWidth-pad)/canvas.width),zy=Math.max(.01,(viewer.clientHeight-pad)/canvas.height);state.zoom=Math.max(.02,Math.min(3,Math.min(zx,zy)));applyZoom();}
    async function saveLabels(force=false){
      if(!state.dirty&&!force)return{labels:state.labels}; state.saving=true;updateSaveButton();document.getElementById('startNavBtn').disabled=true;setStatus('Saving labels…');
      try{const data=await fetchJson('/api/labels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName,labels:state.labels})});state.labels=data.labels||state.labels;state.dirty=false;if(!state.labels.some(l=>l.id===state.selectedId))state.selectedId=null;renderList();syncSelection();draw();setStatus(`Saved ${data.count} labels to ${data.file}`,'success');return data;}
      catch(error){state.dirty=true;setStatus(`Save failed: ${error.message}`,'error');throw error;}finally{state.saving=false;updateSaveButton();applyNavigationStatus(state.navigation);}
    }
    async function goToLabel(label,button){
      try{if(!selectedMapIsActive())throw new Error('Start navigation with the displayed map before using Go.');if(state.dirty)await saveLabels();const saved=state.labels.find(candidate=>candidate.id===label.id);if(!saved)throw new Error('The label was not found after saving.');const world=saved.world||worldFromPixel(saved.x,saved.y),coords=world?` (${Number(world.x).toFixed(2)}, ${Number(world.y).toFixed(2)})`:'';if(!confirm(`Send the robot to “${saved.name}”${coords}?`))return;
        const original=button.textContent;button.disabled=true;button.textContent='Sending…';setStatus(`Sending navigation command for ${saved.name}…`);
        try{const data=await fetchJson('/api/go',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName,label_id:saved.id})});if(data.cancelled_by_stop)setStatus(`Navigation to ${data.name} was cancelled by Stop.`,'success');else setStatus(`Navigation command sent for ${data.name} on ${data.topic} (ROS domain ${data.ros_domain_id})`,'success');}finally{button.disabled=false;button.textContent=original;}}
      catch(error){setStatus(`Could not navigate: ${error.message}`,'error');}
    }
    async function stopNavigation(){
      const button=document.getElementById('stopBtn'),original=button.textContent;button.disabled=true;button.textContent='Stopping…';setStatus('Sending emergency navigation stop…','error');
      try{const data=await fetchJson('/api/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(localizationUiTimer)clearTimeout(localizationUiTimer);localizationUiTimer=null;state.localizing=false;document.getElementById('localizeBtn').disabled=false;renderList();setStatus(`Stop command sent on ${data.topic} (ROS domain ${data.ros_domain_id})`,'success');}
      catch(error){setStatus(`Could not send stop command: ${error.message}`,'error');}
      finally{button.disabled=!state.navigation.ready;button.textContent=original;applyNavigationStatus(state.navigation);}
    }
    async function startNavigationStack(){
      if(!state.mapName)return;
      if(!confirm(`Start the QBot navigation stack with ${state.mapName}? Startup and build details will appear in the website terminal.`))return;
      const button=document.getElementById('startNavBtn'),original=button.textContent;button.disabled=true;button.textContent='Starting…';
      try{await saveLabels(true);const data=await fetchJson('/api/navigation/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName})});applyNavigationStatus(data);setStatus(`Navigation startup requested for ${state.mapName}. Watch the terminal for details.`,'success');}
      catch(error){setStatus(`Could not start navigation: ${error.message}`,'error');showToast(`Could not start navigation: ${error.message}`,'error');await refreshNavigationStatus();}
      finally{button.textContent=original;applyNavigationStatus(state.navigation);}
    }
    async function stopNavigationStack(){
      if(!confirm('Stop the entire QBot navigation stack?'))return;
      const button=document.getElementById('stopNavBtn'),original=button.textContent;button.disabled=true;button.textContent='Stopping…';
      try{const data=await fetchJson('/api/navigation/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});applyNavigationStatus(data);setStatus('Stopping the navigation stack. Shutdown details are in the terminal.');}
      catch(error){setStatus(`Could not stop navigation: ${error.message}`,'error');showToast(`Could not stop navigation: ${error.message}`,'error');}
      finally{button.textContent=original;await refreshNavigationStatus();}
    }
    async function rebuildNavigation(){
      if(!confirm('Rebuild qbot_platform now? Build output will appear in the website terminal.'))return;
      const button=document.getElementById('rebuildNavBtn'),original=button.textContent;button.disabled=true;button.textContent='Building…';
      try{const data=await fetchJson('/api/navigation/rebuild',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});applyNavigationStatus(data);setStatus('Navigation rebuild started. Watch the terminal for details.','success');}
      catch(error){setStatus(`Could not rebuild navigation: ${error.message}`,'error');showToast(`Could not rebuild navigation: ${error.message}`,'error');await refreshNavigationStatus();}
      finally{button.textContent=original;applyNavigationStatus(state.navigation);}
    }
    async function localizeRobot(){
      if(!selectedMapIsActive()){setStatus('Start navigation with the displayed map before localizing.','error');return;}
      if(!confirm('The robot will stop navigation and slowly rotate 360° to localize. Make sure it has clear space. Continue?'))return;
      const button=document.getElementById('localizeBtn'),original=button.textContent;button.disabled=true;button.textContent='Starting…';setStatus('Starting AMCL global localization…');
      try{const data=await fetchJson('/api/localize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName})});if(data.cancelled_by_stop){setStatus('Localization was cancelled by Stop.','success');}else{state.localizing=true;button.disabled=true;renderList();setStatus(`Localization started on ROS domain ${data.ros_domain_id}. Go is locked during the rotation; Stop remains available.`,'success');localizationUiTimer=setTimeout(()=>{state.localizing=false;button.disabled=!selectedMapIsActive();localizationUiTimer=null;renderList();setStatus('Localization rotation finished. Verify that the AMCL pose matches the robot before using Go.','success');},23000);}}
      catch(error){setStatus(`Could not start localization: ${error.message}`,'error');}
      finally{if(!state.localizing)button.disabled=!selectedMapIsActive();button.textContent=original;}
    }
    function updatePoseDisplay(){
      const element=document.getElementById('poseStatus'),button=document.getElementById('savePoseBtn'),pose=state.robotPose;
      if(!selectedMapIsActive()){element.className='pose-status';element.textContent=state.navigation.active_map&&state.navigation.active_map!==state.mapName?`QBot pose hidden: Nav2 is using ${state.navigation.active_map}`:'QBot pose: start navigation with this map to show AMCL';button.disabled=true;drawRobotPose();return;}
      if(!pose?.available){element.className='pose-status';element.textContent=`QBot pose: ${pose?.reason||'waiting for /amcl_pose…'}`;button.disabled=true;drawRobotPose();return;}
      const point=pixelFromWorld(Number(pose.world.x),Number(pose.world.y)),inside=point&&point.x>=0&&point.y>=0&&point.x<canvas.width&&point.y<canvas.height;
      const positionStd=Math.max(Number(pose.uncertainty?.x_std_dev||0),Number(pose.uncertainty?.y_std_dev||0));
      element.className=`pose-status ${pose.stale?'stale':'live'}`;element.textContent=`QBot ${pose.stale?'pose stale':'live'}: ${Number(pose.world.x).toFixed(2)}, ${Number(pose.world.y).toFixed(2)} · ±${positionStd.toFixed(2)} m${inside?'':' · outside selected map'}`;
      button.disabled=Boolean(pose.stale||!inside);drawRobotPose();
    }
    async function refreshRobotPose(){
      try{state.robotPose=await fetchJson('/api/robot-pose');}
      catch(error){state.robotPose={available:false,reason:error.message};}
      updatePoseDisplay();
    }
    async function saveInitialPose(){
      const pose=state.robotPose,button=document.getElementById('savePoseBtn');
      if(!selectedMapIsActive()){setStatus('Start navigation with the displayed map before saving init_pose.','error');return;}
      if(!pose?.available||pose.stale){setStatus('A fresh /amcl_pose is required before saving init_pose.','error');return;}
      const point=pixelFromWorld(Number(pose.world.x),Number(pose.world.y));
      if(!point||point.x<0||point.y<0||point.x>=canvas.width||point.y>=canvas.height){setStatus('The live QBot pose is outside the selected map. Select the map Nav2 is using.','error');return;}
      const classification=pixelClassification({x:Math.round(point.x),y:Math.round(point.y)});
      if(classification!=='free'){setStatus(`The live pose is on ${classification} map space and cannot be saved as init_pose.`,'error');return;}
      let label=state.labels.find(candidate=>candidate.name.trim().toLowerCase()==='init_pose');
      if(label&&!confirm('Update the existing init_pose label to the QBot’s current AMCL pose?'))return;
      if(!label){label={id:newId()};state.labels.push(label);}
      Object.assign(label,{name:'init_pose',kind:'navigation',detail:'Saved from live /amcl_pose',source:'browser',x:point.x,y:point.y,world:{x:Number(pose.world.x),y:Number(pose.world.y)},yaw:Number(pose.yaw||0)});
      selectLabel(label);markDirty();button.disabled=true;
      try{await saveLabels();const saved=state.labels.find(candidate=>candidate.id===label.id);if(saved)centerLabel(saved);}
      catch(_error){}
      finally{updatePoseDisplay();}
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
    document.getElementById('startNavBtn').addEventListener('click',startNavigationStack);
    document.getElementById('stopNavBtn').addEventListener('click',stopNavigationStack);
    document.getElementById('rebuildNavBtn').addEventListener('click',rebuildNavigation);
    document.getElementById('localizeBtn').addEventListener('click',localizeRobot);
    document.getElementById('savePoseBtn').addEventListener('click',saveInitialPose);
    document.getElementById('exportBtn').addEventListener('click',()=>{draw();const link=document.createElement('a');link.href=canvas.toDataURL('image/png');link.download=`${state.mapName.replace(/\.[^.]+$/,'')}_annotated.png`;link.click();});
    mapSelect.addEventListener('change',()=>{if(state.dirty&&!confirm('Switch maps and discard unsaved label changes?')){mapSelect.value=state.mapName;return;}loadMap(mapSelect.value).catch(error=>setStatus(error.message,'error'));});
    window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});window.addEventListener('resize',()=>{if(state.mapImage)applyZoom();});Promise.all([loadMaps(),refreshNavigationStatus()]).then(refreshRobotPose).catch(error=>setStatus(error.message,'error'));setInterval(refreshRobotPose,1000);setInterval(refreshNavigationStatus,1000);
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


def validate_navigation_map(map_path: Path) -> None:
    yaml_path = map_path.with_suffix(".yaml")
    if not yaml_path.exists():
        raise ValueError(f"Map metadata not found: {yaml_path.name}")
    metadata = parse_yaml(yaml_path)
    image_value = str(metadata.get("image") or "").strip()
    if not image_value:
        raise ValueError(f"Map metadata has no image entry: {yaml_path.name}")
    configured_image = Path(image_value)
    if not configured_image.is_absolute():
        configured_image = yaml_path.parent / configured_image
    if configured_image.resolve() != map_path.resolve():
        raise ValueError(
            f"{yaml_path.name} references {configured_image.name}, not {map_path.name}"
        )
    map_geometry(map_path)


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


class NavigationConflictError(RuntimeError):
    """Raised when a navigation lifecycle operation cannot safely begin."""


class NavigationManager:
    """Build, start, monitor, and stop the navigation stack launched by this GUI."""

    CONFLICTING_NODES = {
        "/amcl",
        "/behavior_server",
        "/bt_navigator",
        "/controller_server",
        "/lifecycle_manager_localization",
        "/lifecycle_manager_navigation",
        "/map_server",
        "/planner_server",
        "/velocity_smoother",
        "/waypoint_follower",
        "/Lidar",
        "/QBotPlatformDriver",
    }
    REQUIRED_READY_NODES = {
        "/amcl",
        "/bt_navigator",
        "/controller_server",
        "/planner_server",
    }

    def __init__(
        self,
        *,
        repo_dir: Path = REPO_DIR,
        navigation_setup: Path = NAVIGATION_SETUP,
        run_script: Path = RUN_NAVIGATION_SCRIPT,
        rebuild_script: Path = REBUILD_NAVIGATION_SCRIPT,
        scan_filter_file: Path = SCAN_FILTER_FILE,
        ros_domain_id: int = 63,
        readiness_timeout: float = 120.0,
        probe_interval: float = 1.0,
        popen_factory=None,
        run_factory=None,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.navigation_setup = Path(navigation_setup)
        self.run_script = Path(run_script)
        self.rebuild_script = Path(rebuild_script)
        self.scan_filter_file = Path(scan_filter_file)
        self.ros_domain_id = ros_domain_id
        self.readiness_timeout = readiness_timeout
        self.probe_interval = probe_interval
        self.popen_factory = popen_factory or subprocess.Popen
        self.run_factory = run_factory or subprocess.run
        self.lock = threading.RLock()
        self.state = "stopped"
        self.active_map: str | None = None
        self.message = "Navigation is stopped."
        self.error = ""
        self.process = None
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.operation_token = 0
        self.last_exit_code: int | None = None

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["ROS_DOMAIN_ID"] = str(self.ros_domain_id)
        return environment

    def snapshot(self) -> dict:
        with self.lock:
            process_alive = self.process is not None and self.process.poll() is None
            return {
                "state": self.state,
                "active_map": self.active_map,
                "ready": self.state == "ready" and process_alive,
                "message": self.message,
                "error": self.error or None,
                "managed_process": process_alive,
                "pid": self.process.pid if process_alive else None,
                "last_exit_code": self.last_exit_code,
                "ros_domain_id": self.ros_domain_id,
            }

    def _run_cli(self, command: list[str], *, strict: bool = False):
        try:
            result = self.run_factory(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
                env=self._environment(),
            )
        except FileNotFoundError as exc:
            if strict:
                raise RuntimeError(
                    "ros2 was not found; launch the website with run_qbot_map_labeler.sh"
                ) from exc
            return None
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0:
            if strict:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(detail or "Could not inspect the ROS graph")
            return None
        return result

    def conflicting_nodes(self) -> list[str]:
        result = self._run_cli(["ros2", "node", "list"], strict=True)
        nodes = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return sorted(nodes & self.CONFLICTING_NODES)

    def navigation_ready(self) -> bool:
        nodes_result = self._run_cli(["ros2", "node", "list"])
        if nodes_result is None:
            return False
        nodes = {
            line.strip() for line in nodes_result.stdout.splitlines() if line.strip()
        }
        if not self.REQUIRED_READY_NODES.issubset(nodes):
            return False
        for node in ("/amcl", "/bt_navigator"):
            lifecycle = self._run_cli(["ros2", "lifecycle", "get", node])
            if lifecycle is None or "active" not in lifecycle.stdout.casefold():
                return False
        actions = self._run_cli(["ros2", "action", "list"])
        if actions is None:
            return False
        return "/navigate_to_pose" in {
            line.strip() for line in actions.stdout.splitlines() if line.strip()
        }

    def _begin_operation(self, state: str, active_map: str | None, message: str) -> int:
        with self.lock:
            process_alive = self.process is not None and self.process.poll() is None
            if self.state in {"building", "starting", "ready", "stopping"} or process_alive:
                raise NavigationConflictError(
                    f"Navigation manager is currently {self.state}; stop it before starting another operation"
                )
            self.operation_token += 1
            token = self.operation_token
            self.stop_event = threading.Event()
            self.state = state
            self.active_map = active_map
            self.message = message
            self.error = ""
            self.last_exit_code = None
            return token

    def _set_state(
        self,
        token: int,
        state: str,
        message: str,
        *,
        error: str = "",
        clear_active_map: bool = False,
    ) -> bool:
        with self.lock:
            if token != self.operation_token:
                return False
            self.state = state
            self.message = message
            self.error = error
            if clear_active_map:
                self.active_map = None
            return True

    def _spawn(self, token: int, command: list[str]):
        with self.lock:
            if token != self.operation_token or self.stop_event.is_set():
                raise RuntimeError("Navigation operation was stopped")
        process = self.popen_factory(
            command,
            cwd=str(self.repo_dir),
            env=self._environment(),
            start_new_session=True,
            stdout=None,
            stderr=None,
        )
        with self.lock:
            if token != self.operation_token or self.stop_event.is_set():
                self._terminate_process_group(process)
                raise RuntimeError("Navigation operation was stopped")
            self.process = process
        return process

    def _clear_process(self, process) -> None:
        with self.lock:
            if self.process is process:
                self.process = None

    def _wait_for_process(self, process) -> int:
        return int(process.wait())

    def start(self, map_path: Path) -> dict:
        map_path = Path(map_path).resolve()
        if not map_path.exists() or map_path.suffix != ".pgm":
            raise ValueError("Select an existing .pgm map before starting navigation")
        validate_navigation_map(map_path)
        labels_path = label_path_for(map_path)
        if not labels_path.exists():
            raise ValueError("Save the selected map's labels before starting navigation")
        if not self.run_script.exists():
            raise RuntimeError(f"Navigation script not found: {self.run_script}")
        if not self.scan_filter_file.exists():
            raise RuntimeError(f"Scan filter file not found: {self.scan_filter_file}")
        conflicts = self.conflicting_nodes()
        if conflicts:
            raise NavigationConflictError(
                "Navigation nodes are already running: " + ", ".join(conflicts)
            )
        needs_build = not self.navigation_setup.exists()
        initial_state = "building" if needs_build else "starting"
        initial_message = (
            "Building navigation workspace; details are in the terminal."
            if needs_build
            else f"Starting navigation with {map_path.name}; details are in the terminal."
        )
        token = self._begin_operation(initial_state, map_path.name, initial_message)
        worker = threading.Thread(
            target=self._start_worker,
            args=(token, map_path, needs_build),
            name="qbot-navigation-start",
            daemon=True,
        )
        with self.lock:
            self.worker = worker
        worker.start()
        return self.snapshot()

    def _start_worker(self, token: int, map_path: Path, needs_build: bool) -> None:
        process = None
        try:
            if self.stop_event.is_set():
                self._set_state(
                    token,
                    "stopped",
                    "Navigation startup was stopped.",
                    clear_active_map=True,
                )
                return
            if needs_build:
                if not self.rebuild_script.exists():
                    raise RuntimeError(f"Rebuild script not found: {self.rebuild_script}")
                process = self._spawn(token, [str(self.rebuild_script)])
                return_code = self._wait_for_process(process)
                self._clear_process(process)
                process = None
                if self.stop_event.is_set():
                    self._set_state(
                        token,
                        "stopped",
                        "Navigation startup was stopped.",
                        clear_active_map=True,
                    )
                    return
                if return_code != 0:
                    raise RuntimeError(
                        f"Navigation build failed with status {return_code}; check the terminal"
                    )
                if not self.navigation_setup.exists():
                    raise RuntimeError(
                        "Build finished but robot_navigation/install/setup.bash was not created"
                    )
                self._set_state(
                    token,
                    "starting",
                    f"Starting navigation with {map_path.name}; details are in the terminal.",
                )

            if self.stop_event.is_set():
                self._set_state(
                    token,
                    "stopped",
                    "Navigation startup was stopped.",
                    clear_active_map=True,
                )
                return

            command = [
                str(self.run_script),
                "--map",
                str(map_path.with_suffix(".yaml")),
                "--labels",
                str(label_path_for(map_path)),
                "--scan-filter-file",
                str(self.scan_filter_file),
            ]
            process = self._spawn(token, command)
            deadline = time.monotonic() + self.readiness_timeout
            while time.monotonic() < deadline:
                return_code = process.poll()
                if return_code is not None:
                    self.last_exit_code = int(return_code)
                    raise RuntimeError(
                        f"Navigation exited with status {return_code} before becoming ready; check the terminal"
                    )
                if self.stop_event.is_set():
                    self._terminate_process_group(process)
                    self._clear_process(process)
                    self._set_state(
                        token,
                        "stopped",
                        "Navigation was stopped.",
                        clear_active_map=True,
                    )
                    return
                if self.navigation_ready():
                    self._set_state(
                        token,
                        "ready",
                        f"Navigation is ready with {map_path.name}.",
                    )
                    return_code = self._wait_for_process(process)
                    self.last_exit_code = return_code
                    self._clear_process(process)
                    if self.stop_event.is_set():
                        self._set_state(
                            token,
                            "stopped",
                            "Navigation was stopped.",
                            clear_active_map=True,
                        )
                    else:
                        raise RuntimeError(
                            f"Navigation exited unexpectedly with status {return_code}; check the terminal"
                        )
                    return
                time.sleep(self.probe_interval)
            raise RuntimeError(
                f"Navigation did not become ready within {self.readiness_timeout:g} seconds; check the terminal"
            )
        except Exception as exc:
            if process is not None and process.poll() is None:
                self._terminate_process_group(process)
            if process is not None:
                self._clear_process(process)
            if self.stop_event.is_set():
                self._set_state(
                    token,
                    "stopped",
                    "Navigation was stopped.",
                    clear_active_map=True,
                )
            else:
                self._set_state(
                    token,
                    "error",
                    str(exc),
                    error=str(exc),
                    clear_active_map=True,
                )
        finally:
            with self.lock:
                if token == self.operation_token:
                    self.worker = None

    def rebuild(self) -> dict:
        if not self.rebuild_script.exists():
            raise RuntimeError(f"Rebuild script not found: {self.rebuild_script}")
        conflicts = self.conflicting_nodes()
        if conflicts:
            raise NavigationConflictError(
                "Stop the running navigation stack before rebuilding: "
                + ", ".join(conflicts)
            )
        token = self._begin_operation(
            "building",
            None,
            "Rebuilding navigation workspace; details are in the terminal.",
        )
        worker = threading.Thread(
            target=self._rebuild_worker,
            args=(token,),
            name="qbot-navigation-rebuild",
            daemon=True,
        )
        with self.lock:
            self.worker = worker
        worker.start()
        return self.snapshot()

    def _rebuild_worker(self, token: int) -> None:
        process = None
        try:
            if self.stop_event.is_set():
                self._set_state(token, "stopped", "Build was stopped.")
                return
            process = self._spawn(token, [str(self.rebuild_script)])
            return_code = self._wait_for_process(process)
            self.last_exit_code = return_code
            self._clear_process(process)
            if self.stop_event.is_set():
                self._set_state(token, "stopped", "Build was stopped.")
            elif return_code == 0:
                self._set_state(token, "stopped", "Build completed successfully.")
            else:
                raise RuntimeError(
                    f"Navigation build failed with status {return_code}; check the terminal"
                )
        except Exception as exc:
            if process is not None and process.poll() is None:
                self._terminate_process_group(process)
            if process is not None:
                self._clear_process(process)
            if self.stop_event.is_set():
                self._set_state(token, "stopped", "Build was stopped.")
            else:
                self._set_state(token, "error", str(exc), error=str(exc))
        finally:
            with self.lock:
                if token == self.operation_token:
                    self.worker = None

    def stop(self) -> dict:
        with self.lock:
            if self.state in {"stopped", "error"} and (
                self.process is None or self.process.poll() is not None
            ):
                self.state = "stopped"
                self.active_map = None
                self.error = ""
                self.message = "Navigation is already stopped."
                return self.snapshot()
            token = self.operation_token
            self.stop_event.set()
            self.state = "stopping"
            self.message = "Stopping navigation; shutdown details are in the terminal."
            process = self.process
        thread = threading.Thread(
            target=self._stop_worker,
            args=(token, process),
            name="qbot-navigation-stop",
            daemon=True,
        )
        thread.start()
        return self.snapshot()

    def _stop_worker(self, token: int, process) -> None:
        if process is not None:
            self._terminate_process_group(process)
            self._clear_process(process)
        self._set_state(
            token,
            "stopped",
            "Navigation was stopped.",
            clear_active_map=True,
        )

    @staticmethod
    def _terminate_process_group(process) -> None:
        if process.poll() is not None:
            return
        try:
            process_group = os.getpgid(process.pid)
        except (ProcessLookupError, OSError):
            return
        for sig, timeout in (
            (signal.SIGINT, 15.0),
            (signal.SIGTERM, 5.0),
            (signal.SIGKILL, 2.0),
        ):
            try:
                os.killpg(process_group, sig)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                continue

    def shutdown(self) -> None:
        self.stop()
        with self.lock:
            worker = self.worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=24.0)


class RobotPoseMonitor:
    """Keep the latest AMCL pose available to the HTTP server without polling ros2 CLI."""

    def __init__(self, topic: str = "/amcl_pose") -> None:
        self.topic = topic
        self.lock = threading.Lock()
        self.pose: dict | None = None
        self.error = ""
        self.node = None
        self.subscription = None
        self.thread: threading.Thread | None = None

    def start(self, ros_domain_id: int) -> None:
        if rclpy is None or PoseWithCovarianceStamped is None:
            self.error = f"rclpy is unavailable: {RCLPY_IMPORT_ERROR}"
            return

        os.environ["ROS_DOMAIN_ID"] = str(ros_domain_id)
        try:
            if not rclpy.ok():
                rclpy.init(args=None)
            self.node = rclpy.create_node("qbot_map_labeler_pose_monitor")
            self.subscription = self.node.create_subscription(
                PoseWithCovarianceStamped,
                self.topic,
                self.pose_callback,
                10,
            )
            self.thread = threading.Thread(
                target=self.spin,
                name="qbot-map-labeler-pose-monitor",
                daemon=True,
            )
            self.thread.start()
        except Exception as exc:
            self.error = f"Could not subscribe to {self.topic}: {exc}"

    def spin(self) -> None:
        try:
            rclpy.spin(self.node)
        except Exception as exc:
            with self.lock:
                self.error = f"Pose monitor stopped: {exc}"

    def pose_callback(self, message) -> None:
        pose = message.pose.pose
        orientation = pose.orientation
        yaw = math.atan2(
            2.0
            * (
                orientation.w * orientation.z
                + orientation.x * orientation.y
            ),
            1.0
            - 2.0
            * (
                orientation.y * orientation.y
                + orientation.z * orientation.z
            ),
        )
        covariance = list(message.pose.covariance)
        with self.lock:
            self.pose = {
                "frame_id": message.header.frame_id or "map",
                "world": {
                    "x": float(pose.position.x),
                    "y": float(pose.position.y),
                },
                "yaw": yaw,
                "uncertainty": {
                    "x_std_dev": math.sqrt(max(0.0, float(covariance[0]))),
                    "y_std_dev": math.sqrt(max(0.0, float(covariance[7]))),
                    "yaw_std_dev": math.sqrt(max(0.0, float(covariance[35]))),
                },
                "received_at": time.time(),
            }
            self.error = ""

    def snapshot(self) -> dict:
        with self.lock:
            if self.pose is None:
                return {
                    "available": False,
                    "topic": self.topic,
                    "reason": self.error or f"Waiting for the first message on {self.topic}",
                }
            pose = {
                **self.pose,
                "world": dict(self.pose["world"]),
                "uncertainty": dict(self.pose["uncertainty"]),
            }
        age = max(0.0, time.time() - pose["received_at"])
        return {
            "available": True,
            "topic": self.topic,
            "age_seconds": age,
            "stale": age > 3.0,
            **pose,
        }

    def stop(self) -> None:
        if rclpy is not None and rclpy.ok():
            rclpy.shutdown()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        if self.node is not None:
            self.node.destroy_node()
        self.node = None
        self.subscription = None
        self.thread = None


class Handler(BaseHTTPRequestHandler):
    server_version = "MapLabelGUI/2.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def write_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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

    def navigation_manager(self) -> NavigationManager | None:
        return getattr(self.server, "navigation_manager", None)

    def require_navigation_map(self, map_name: str) -> None:
        manager = self.navigation_manager()
        if manager is None:
            return
        status = manager.snapshot()
        if not status["ready"]:
            raise NavigationConflictError(
                "Navigation is not ready; start it from the website first"
            )
        if status["active_map"] != map_name:
            raise NavigationConflictError(
                f"Nav2 is using {status['active_map']}, not {map_name}; stop navigation and start it with the selected map"
            )

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
            elif parsed.path == "/api/robot-pose":
                monitor = getattr(self.server, "pose_monitor", None)
                if monitor is None:
                    self.write_json(
                        {
                            "available": False,
                            "topic": "/amcl_pose",
                            "reason": "Pose monitor is not configured",
                        }
                    )
                else:
                    self.write_json(monitor.snapshot())
            elif parsed.path == "/api/navigation/status":
                manager = self.navigation_manager()
                if manager is None:
                    self.write_json(
                        {
                            "state": "error",
                            "active_map": None,
                            "ready": False,
                            "message": "Navigation manager is not configured",
                            "error": "Navigation manager is not configured",
                            "managed_process": False,
                        },
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                else:
                    self.write_json(manager.snapshot())
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
                self.require_navigation_map(map_path.name)
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
                data = self.read_json_body()
                map_path = self.resolve_map(str(data.get("map", "")))
                self.require_navigation_map(map_path.name)
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
            elif self.path == "/api/navigation/start":
                data = self.read_json_body()
                map_path = self.resolve_map(str(data.get("map", "")))
                if not label_path_for(map_path).exists():
                    write_labels(map_path, read_labels(map_path))
                manager = self.navigation_manager()
                if manager is None:
                    raise RuntimeError("Navigation manager is not configured")
                self.write_json(manager.start(map_path), HTTPStatus.ACCEPTED)
            elif self.path == "/api/navigation/stop":
                self.read_json_body()
                manager = self.navigation_manager()
                if manager is None:
                    raise RuntimeError("Navigation manager is not configured")
                self.write_json(manager.stop(), HTTPStatus.ACCEPTED)
            elif self.path == "/api/navigation/rebuild":
                self.read_json_body()
                manager = self.navigation_manager()
                if manager is None:
                    raise RuntimeError("Navigation manager is not configured")
                self.write_json(manager.rebuild(), HTTPStatus.ACCEPTED)
            else:
                self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except NavigationConflictError as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except RuntimeError as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a browser GUI for labeling ROS PGM maps.")
    parser.add_argument("--host", default="0.0.0.0", help="Host/interface to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    parser.add_argument("--label-topic", default="/label", help="ROS String topic used by Go")
    parser.add_argument("--pose-topic", default="/amcl_pose", help="AMCL pose topic shown on the map")
    parser.add_argument("--go-timeout", type=float, default=10, help="Seconds to wait for the ROS label publication")
    parser.add_argument(
        "--navigation-timeout",
        type=float,
        default=120,
        help="Seconds to wait for AMCL and Nav2 to become ready",
    )
    parser.add_argument(
        "--ros-domain-id",
        type=int,
        default=63,
        help="ROS domain used by the Go button (default: 63)",
    )
    args = parser.parse_args()
    if args.go_timeout <= 0:
        parser.error("--go-timeout must be positive")
    if args.navigation_timeout <= 0:
        parser.error("--navigation-timeout must be positive")
    if not 0 <= args.ros_domain_id <= 232:
        parser.error("--ros-domain-id must be between 0 and 232")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.label_topic, server.go_timeout = args.label_topic, args.go_timeout
    server.ros_domain_id = args.ros_domain_id
    server.navigation_lock = threading.Lock()
    server.stop_generation = 0
    pose_monitor = RobotPoseMonitor(args.pose_topic)
    pose_monitor.start(args.ros_domain_id)
    server.pose_monitor = pose_monitor
    navigation_manager = NavigationManager(
        ros_domain_id=args.ros_domain_id,
        readiness_timeout=args.navigation_timeout,
    )
    server.navigation_manager = navigation_manager
    print(f"Map label GUI: http://{args.host}:{args.port}")
    print(f"Serving maps from: {MAPS_DIR}")
    print(f"Go publishes labels on: {args.label_topic}")
    print(f"Go uses ROS domain: {args.ros_domain_id}")
    print(f"Live robot pose topic: {args.pose_topic}")
    if pose_monitor.error:
        print(f"WARNING: {pose_monitor.error}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping map label GUI.")
    finally:
        server.server_close()
        navigation_manager.shutdown()
        pose_monitor.stop()


if __name__ == "__main__":
    main()
