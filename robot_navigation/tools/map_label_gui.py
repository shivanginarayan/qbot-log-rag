#!/usr/bin/env python3
"""Browser UI for mapping, labeling saved maps, and controlling QBot Nav2."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import os
import re
import shutil
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
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
    from nav_msgs.msg import OccupancyGrid
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Empty as RosEmpty
    from std_msgs.msg import String as RosString
except ImportError as exc:
    rclpy = None
    PoseStamped = None
    PoseWithCovarianceStamped = None
    OccupancyGrid = None
    DurabilityPolicy = None
    HistoryPolicy = None
    QoSProfile = None
    ReliabilityPolicy = None
    RosEmpty = None
    RosString = None
    RCLPY_IMPORT_ERROR = str(exc)
else:
    RCLPY_IMPORT_ERROR = ""


ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = ROOT / "maps"
REPO_DIR = ROOT.parent
RUN_NAVIGATION_SCRIPT = REPO_DIR / "run_qbot_navigation.sh"
RUN_MAPPING_SCRIPT = REPO_DIR / "run_qbot_mapping.sh"
REBUILD_NAVIGATION_SCRIPT = REPO_DIR / "rebuild_qbot_navigation.sh"
NAVIGATION_SETUP = ROOT / "install" / "setup.bash"
QBOT_BUILD_STAMP = ROOT / "install" / ".qbot_platform_source_stamp"
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
    .main { display: grid; grid-template-rows: auto auto auto minmax(0, 1fr) auto; min-width: 0; }
    .toolbar, .status { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--line); background: var(--toolbar); }
    .toolbar .grow { flex: 1; }
    .status { min-height: 44px; border-top: 1px solid var(--line); border-bottom: 0; color: var(--muted); }
    .status.error { color: var(--danger); }
    .status.success { color: var(--success); }
    .navigation-panel, .mapping-panel { display: grid; gap: 8px; padding: 9px 12px; border-bottom: 1px solid var(--line); background: var(--panel); }
    .navigation-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .navigation-row .grow { flex: 1; }
    .nav-state { padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-weight: 700; text-transform: capitalize; }
    .nav-state.ready { border-color: var(--success); color: var(--success); }
    .nav-state.error { border-color: var(--danger); color: var(--danger); }
    .nav-state.building, .nav-state.starting, .nav-state.stopping { border-color: var(--warning); color: var(--warning); }
    .mapping-panel { background: var(--card); }
    .mapping-state { padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-weight: 700; text-transform: capitalize; }
    .mapping-state.mapping { border-color: var(--success); color: var(--success); }
    .mapping-state.error { border-color: var(--danger); color: var(--danger); }
    .mapping-state.building, .mapping-state.starting, .mapping-state.saving, .mapping-state.stopping { border-color: var(--warning); color: var(--warning); }
    .mapping-message { color: var(--muted); }
    .nav-message { color: var(--muted); }
    .map-warning { padding: 9px 11px; border: 1px solid var(--warning); border-radius: 8px; color: var(--warning); background: var(--card); }
    .map-warning[hidden] { display: none; }
    .toast { position: fixed; z-index: 30; top: 16px; right: 16px; width: min(440px,calc(100vw - 32px)); padding: 13px 15px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); box-shadow: 0 16px 45px var(--canvas-shadow); }
    .toast.success { border-color: var(--success); color: var(--success); }
    .toast.error { border-color: var(--danger); color: var(--danger); }
    .toast.warning { border-color: var(--warning); color: var(--warning); }
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
    .label-item.navigating { border-color: var(--warning); box-shadow: 0 0 0 2px rgba(154,93,0,.14); }
    .label-select { min-width: 0; height: auto; padding: 3px 5px; border: 0; background: transparent; text-align: left; }
    .go { align-self: center; color: var(--accent2); font-weight: 700; }
    .label-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 700; }
    .label-meta { margin-top: 2px; color: var(--muted); font-size: 12px; }
    .badge { margin-left: 6px; color: var(--muted); font-size: 11px; }
    .navigation-badge { display: inline-flex; align-items: center; gap: 5px; margin-left: 7px; color: var(--warning); font-size: 11px; }
    .navigation-badge::before { width: 7px; height: 7px; border-radius: 50%; background: currentColor; content: ""; animation: navigation-pulse 1.2s ease-in-out infinite; }
    @keyframes navigation-pulse { 50% { opacity: .3; transform: scale(.75); } }
    @media (prefers-reduced-motion: reduce) { .navigation-badge::before { animation: none; } }
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
        <button id="deleteMapBtn" class="danger" type="button">Delete Map</button>
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
          <button id="startNavBtn" class="primary" type="button" title="Start navigation with the displayed map">Start Navigation</button>
          <button id="stopNavBtn" class="danger" type="button" disabled>Stop Navigation</button>
        </div>
        <div id="mapWarning" class="map-warning" hidden></div>
      </div>
      <div class="mapping-panel">
        <div class="navigation-row">
          <span id="mappingState" class="mapping-state">Stopped</span>
          <span id="mappingMessage" class="mapping-message">Manual mapping is stopped.</span>
          <span class="grow"></span>
          <button id="newMapBtn" class="primary" type="button">New Map</button>
          <button id="finishMapBtn" type="button" disabled>Finish &amp; Save</button>
          <button id="cancelMapBtn" class="danger" type="button" disabled>Cancel Mapping</button>
        </div>
      </div>
      <div id="viewer" class="viewer"><div class="canvas-wrap"><div class="canvas-stage"><canvas id="mapCanvas"></canvas><canvas id="poseCanvas"></canvas></div></div></div>
      <div id="status" class="status">Loading maps…</div>
    </main>
    <aside>
      <section class="section"><h2>Add a location</h2><p class="hint">On a saved map, click white space. While mapping, release LB and press B to drop label1, label2, and so on.</p><div id="poseStatus" class="pose-status">QBot pose: waiting for /amcl_pose…</div></section>
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
  <div id="newMapDialog" class="backdrop" hidden>
    <form id="newMapForm" class="modal">
      <h2>Create a new map</h2>
      <p>Choose a unique filename, then drive with the physical gamepad. Hold LB to enable motion and release LB to stop.</p>
      <input id="newMapName" placeholder="Example: conference_room_1" autocomplete="off" maxlength="64">
      <p id="newMapFilename" class="hint"></p>
      <div id="newMapError" class="field-error"></div>
      <div class="modal-actions"><button id="cancelNewMapBtn" type="button">Cancel</button><button type="submit" class="primary">Start Mapping</button></div>
    </form>
  </div>
  <div id="deleteMapDialog" class="backdrop" hidden>
    <form id="deleteMapForm" class="modal">
      <h2>Delete this map?</h2>
      <p id="deleteMapMessage"></p>
      <input id="deleteMapConfirmation" autocomplete="off" spellcheck="false">
      <div id="deleteMapError" class="field-error"></div>
      <div class="modal-actions"><button id="cancelDeleteMapBtn" type="button">Cancel</button><button id="confirmDeleteMapBtn" type="submit" class="danger">Move to Trash</button></div>
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
    const newMapDialog=document.getElementById('newMapDialog'),newMapForm=document.getElementById('newMapForm'),newMapName=document.getElementById('newMapName'),newMapError=document.getElementById('newMapError');
    const deleteMapDialog=document.getElementById('deleteMapDialog'),deleteMapForm=document.getElementById('deleteMapForm'),deleteMapConfirmation=document.getElementById('deleteMapConfirmation'),deleteMapError=document.getElementById('deleteMapError');
    const state = {mapName:null,mapImage:null,mapPixels:null,mapMeta:null,labels:[],selectedId:null,pendingPoint:null,zoom:1,dirty:false,saving:false,deletingMap:false,localizing:false,robotPose:null,viewingLiveMap:false,mappingPreviewRevision:0,mappingPreviewGeometry:null,navigation:{state:'stopped',active_map:null,ready:false,message:'Navigation is stopped.',error:null,managed_process:false,localization_state:'required'},mapping:{state:'stopped',reserved_map:null,ready:false,message:'Manual mapping is stopped.',error:null,managed_process:false,preview_revision:0,saved_map:null,pending_labels:[],robot_pose:null,label_event_sequence:0},goal:{available:false,sequence:0,event:'idle',outcome:'idle'}};
    let toastTimer=null,mappingPreviewPending=false,lastNavigationState='stopped',lastLocalizationState='required',lastMappingState='stopped',lastMappingError='',lastHandledSavedMap=null,lastMappingLabelSequence=0,lastGoalSequence=0,goalStatusInitialized=false;
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
    function mappingIsActive(){return ['building','starting','mapping','saving','stopping'].includes(state.mapping?.state);}
    function selectedMapIsActive(){return Boolean(state.navigation?.ready&&state.navigation.active_map===state.mapName);}
    function navigationIsLocalized(){return selectedMapIsActive()&&state.navigation?.localization_state==='ready';}
    function showToast(message,tone='success'){
      const toast=document.getElementById('toast');toast.textContent=message;toast.className=`toast ${tone}`;toast.hidden=false;
      if(toastTimer)clearTimeout(toastTimer);toastTimer=setTimeout(()=>{toast.hidden=true;toastTimer=null;},6500);
    }
    function applyNavigationStatus(status){
      const previous=lastNavigationState,previousLocalization=lastLocalizationState,previousNavigation=state.navigation;state.navigation=status;lastNavigationState=status.state;lastLocalizationState=status.localization_state||'required';state.localizing=status.localization_state==='in_progress';
      const stateEl=document.getElementById('navState'),messageEl=document.getElementById('navMessage'),warning=document.getElementById('mapWarning');
      stateEl.textContent=status.state||'unknown';stateEl.className=`nav-state ${status.state||''}`.trim();messageEl.textContent=status.error||(status.state==='ready'&&status.localization_message?status.localization_message:status.message)||'';
      const busy=['building','starting','stopping'].includes(status.state),canStart=['stopped','error'].includes(status.state)&&!mappingIsActive();
      const startButton=document.getElementById('startNavBtn'),stopButton=document.getElementById('stopNavBtn'),rebuildButton=document.getElementById('rebuildNavBtn'),localizeButton=document.getElementById('localizeBtn');
      startButton.disabled=!state.mapName||!canStart||state.saving||state.deletingMap;startButton.textContent=status.state==='building'?'Building…':status.state==='starting'?'Starting…':'Start Navigation';
      document.getElementById('stopNavBtn').disabled=!(status.managed_process||['building','starting','ready'].includes(status.state))||status.state==='stopping';
      stopButton.textContent=status.state==='stopping'?'Stopping…':'Stop Navigation';
      rebuildButton.disabled=!canStart||state.deletingMap;rebuildButton.textContent=status.state==='building'?'Building…':'Rebuild';
      document.getElementById('stopBtn').disabled=!status.ready||mappingIsActive();
      const mapMismatch=Boolean(status.active_map&&state.mapName&&status.active_map!==state.mapName&&['building','starting','ready','stopping'].includes(status.state));
      warning.hidden=!mapMismatch;
      if(mapMismatch)warning.textContent=`Displayed map: ${state.mapName}. Active Nav2 map: ${status.active_map}. Stop Navigation, then Start Navigation to use the displayed map.`;
      if(previous!=='ready'&&status.state==='ready')showToast(`Navigation is ready with ${status.active_map}. Press Localize before using Go.`,'success');
      if(previousLocalization!=='ready'&&status.localization_state==='ready')showToast('Localization completed. Navigation goals are now enabled.','success');
      if(previousLocalization==='in_progress'&&status.localization_state==='failed')showToast(status.localization_message||'Localization failed. Run Localize again.','error');
      if(previous==='building'&&status.state==='stopped'&&String(status.message||'').toLowerCase().includes('build completed'))showToast('Navigation build completed successfully.','success');
      if(previous!=='error'&&status.state==='error')showToast(`${status.error||status.message} Check the terminal for details.`,'error');
      localizeButton.disabled=!selectedMapIsActive()||state.localizing||state.deletingMap;localizeButton.textContent=state.localizing?'Localizing…':'Localize';
      if(previousNavigation.state!==status.state||previousNavigation.active_map!==status.active_map||previousNavigation.ready!==status.ready||previousLocalization!==status.localization_state)renderList();
      updateDeleteMapButton();
      updatePoseDisplay();
    }
    async function refreshNavigationStatus(){
      try{applyNavigationStatus(await fetchJson('/api/navigation/status'));}
      catch(error){applyNavigationStatus({state:'error',active_map:null,ready:false,message:error.message,error:error.message,managed_process:false});}
    }
    function applyMappingStatus(status){
      const previous=lastMappingState,previousError=lastMappingError,wasLive=state.viewingLiveMap;state.mapping=status;lastMappingState=status.state;lastMappingError=status.error||'';
      const stateEl=document.getElementById('mappingState'),messageEl=document.getElementById('mappingMessage'),active=['building','starting','mapping','saving','stopping'].includes(status.state),navIdle=['stopped','error'].includes(state.navigation?.state);
      stateEl.textContent=status.state||'unknown';stateEl.className=`mapping-state ${status.state||''}`.trim();messageEl.textContent=status.error?`${status.message||status.error}`:(status.message||'');
      const newMapButton=document.getElementById('newMapBtn'),finishButton=document.getElementById('finishMapBtn'),cancelButton=document.getElementById('cancelMapBtn');
      newMapButton.disabled=!navIdle||active||state.saving||state.deletingMap;newMapButton.textContent=['building','starting'].includes(status.state)?'Starting…':'New Map';
      finishButton.disabled=status.state!=='mapping';finishButton.textContent=status.state==='saving'?'Saving…':status.state==='stopping'&&status.saved_map?'Saved…':'Finish & Save';
      cancelButton.disabled=!['building','starting','mapping'].includes(status.state);cancelButton.textContent=status.state==='stopping'&&!status.saved_map?'Canceling…':'Cancel Mapping';
      mapSelect.disabled=active||state.deletingMap;document.getElementById('reloadBtn').disabled=active||state.deletingMap;document.getElementById('exportBtn').disabled=active||state.deletingMap;document.getElementById('stopBtn').title=active?'Release LB on the physical gamepad to stop manual mapping motion':'Cancel navigation and stop the robot';
      saveBtn.disabled=active||!state.dirty||state.saving;
      if(!['building','starting','mapping','saving','stopping'].includes(previous)&&active)lastMappingLabelSequence=0;
      if(active&&!state.viewingLiveMap){state.viewingLiveMap=true;state.mappingPreviewRevision=0;renderList();syncSelection();}
      if(previous!=='mapping'&&status.state==='mapping')showToast(`Manual mapping is ready for ${status.reserved_map}. Drive with the gamepad.`,'success');
      const labelSequence=Number(status.label_event_sequence||0);if(labelSequence>lastMappingLabelSequence){lastMappingLabelSequence=labelSequence;const event=status.last_label_event;if(event){showToast(event.message,event.accepted?'success':'error');setStatus(event.message,event.accepted?'success':'error');}}
      if(status.error&&status.error!==previousError){showToast(`Mapping: ${status.message||status.error} Check the terminal for details.`,'error');setStatus(status.message||status.error,'error');}
      if(status.state==='stopped'&&status.saved_map&&status.saved_map!==lastHandledSavedMap){lastHandledSavedMap=status.saved_map;state.viewingLiveMap=false;loadMaps(status.saved_map).then(()=>{showToast(`Saved ${status.saved_map}. It is ready for labels and navigation.`,'success');setStatus(`Saved and loaded ${status.saved_map}.`,'success');}).catch(error=>setStatus(`Map saved, but reload failed: ${error.message}`,'error'));}
      else if(wasLive&&!active&&['stopped','error'].includes(status.state)&&!status.saved_map){state.viewingLiveMap=false;if(state.mapName)loadMap(state.mapName).catch(error=>setStatus(error.message,'error'));}
      applyNavigationStatus(state.navigation);renderList();syncSelection();updateSaveButton();updateDeleteMapButton();updatePoseDisplay();draw();
    }
    async function refreshMappingStatus(){
      try{applyMappingStatus(await fetchJson('/api/mapping/status'));}
      catch(error){applyMappingStatus({state:'error',reserved_map:null,ready:false,message:error.message,error:error.message,managed_process:false,preview_revision:0,saved_map:null});}
    }
    function goalMatchesLabel(label){
      const goal=state.goal;if(!goal?.available||goal.event!=='running')return false;
      if(goal.map&&goal.map!==state.mapName)return false;
      if(goal.label_id)return goal.label_id===label.id;
      return String(goal.name||'').toLowerCase()===String(label.name||'').toLowerCase();
    }
    function goalResultMessage(goal){
      const name=goal.label||goal.name||'the goal',detail=goal.message?` ${goal.message}`:'';
      if(goal.name==='localize'){
        if(goal.outcome==='succeeded')return{message:'AMCL localization completed successfully.',tone:'success'};
        if(goal.outcome==='canceled')return{message:`AMCL localization was canceled.${detail}`,tone:'warning'};
        return{message:`AMCL localization failed.${detail}`,tone:'error'};
      }
      if(goal.outcome==='succeeded')return{message:`QBot reached “${name}”.`,tone:'success'};
      if(goal.outcome==='canceled')return{message:`Navigation to “${name}” was canceled.${detail}`,tone:'warning'};
      return{message:`QBot failed to reach “${name}”.${detail}`,tone:'error'};
    }
    function applyGoalStatus(goal){
      const sequence=Number(goal?.sequence||0),isNew=sequence>lastGoalSequence,wasInitialized=goalStatusInitialized;
      state.goal=goal||{available:false,sequence:0,event:'idle',outcome:'idle'};goalStatusInitialized=true;lastGoalSequence=Math.max(lastGoalSequence,sequence);
      if(state.goal.name==='localize'&&state.goal.event==='finished')refreshNavigationStatus();
      if(isNew&&state.goal.event==='running'){setStatus(`Navigating to ${state.goal.label||state.goal.name||'goal'}…`);}
      const age=Number(state.goal.age_seconds),recent=Number.isFinite(age)&&age<3;
      if(isNew&&state.goal.event==='finished'&&(wasInitialized||recent)){
        const result=goalResultMessage(state.goal);showToast(result.message,result.tone);setStatus(result.message,result.tone==='warning'?'':result.tone);
      }
      renderList();
    }
    async function refreshGoalStatus(){
      try{applyGoalStatus(await fetchJson('/api/navigation/goal-status'));}
      catch(error){if(!goalStatusInitialized)applyGoalStatus({available:false,sequence:0,event:'idle',outcome:'idle',reason:error.message});}
    }
    function updateSaveButton() { saveBtn.disabled = mappingIsActive() || state.deletingMap || !state.dirty || state.saving; saveBtn.textContent = state.saving ? 'Saving…' : 'Save Labels'; }
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
      if(state.viewingLiveMap){drawMappingOverlay();return;}
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
    function mappingPointFromWorld(x,y){
      const geometry=state.mappingPreviewGeometry,origin=geometry?.origin;if(!geometry||!Array.isArray(origin)||!geometry.resolution||!geometry.step)return null;
      const dx=x-Number(origin[0]||0),dy=y-Number(origin[1]||0),yaw=Number(origin[2]||0),localX=Math.cos(yaw)*dx+Math.sin(yaw)*dy,localY=-Math.sin(yaw)*dx+Math.cos(yaw)*dy;
      return{x:(localX/geometry.resolution)/geometry.step,y:(geometry.sourceHeight-localY/geometry.resolution)/geometry.step};
    }
    function drawMappingOverlay(){
      poseCtx.clearRect(0,0,poseCanvas.width,poseCanvas.height);const scale=Math.max(state.zoom,.01),radius=Math.max(5,7/scale),font=Math.max(14,13/scale);poseCtx.font=`${font}px "JetBrains Mono",monospace`;poseCtx.lineWidth=Math.max(2,2/scale);poseCtx.textBaseline='middle';
      for(const label of state.mapping?.pending_labels||[]){const world=label.world||{},point=mappingPointFromWorld(Number(world.x),Number(world.y));if(!point||point.x<0||point.y<0||point.x>=canvas.width||point.y>=canvas.height)continue;poseCtx.fillStyle='#08758a';poseCtx.strokeStyle='#fff';poseCtx.beginPath();poseCtx.arc(point.x,point.y,radius,0,Math.PI*2);poseCtx.fill();poseCtx.stroke();const text=label.name||'Label',offset=radius+5/scale,tx=point.x+offset,ty=point.y-offset,pad=5/scale,height=font+8/scale,width=poseCtx.measureText(text).width+pad*2;poseCtx.fillStyle='rgba(255,255,255,.9)';poseCtx.fillRect(tx,ty-height/2,width,height);poseCtx.strokeStyle='#08758a';poseCtx.strokeRect(tx,ty-height/2,width,height);poseCtx.fillStyle='#172321';poseCtx.fillText(text,tx+pad,ty);}
      const pose=state.mapping?.robot_pose;if(!pose?.available||pose.stale||!pose.world)return;const point=mappingPointFromWorld(Number(pose.world.x),Number(pose.world.y));if(!point||point.x<0||point.y<0||point.x>=canvas.width||point.y>=canvas.height)return;const markerRadius=Math.max(7,10/scale),arrowLength=Math.max(14,20/scale),originYaw=Number(state.mappingPreviewGeometry?.origin?.[2]||0),color='#e68619';poseCtx.save();poseCtx.translate(point.x,point.y);poseCtx.rotate(-(Number(pose.yaw||0)-originYaw));poseCtx.fillStyle=color;poseCtx.strokeStyle='#fff';poseCtx.lineWidth=Math.max(2,2/scale);poseCtx.beginPath();poseCtx.moveTo(arrowLength,0);poseCtx.lineTo(-markerRadius,markerRadius*.8);poseCtx.lineTo(-markerRadius,-markerRadius*.8);poseCtx.closePath();poseCtx.fill();poseCtx.stroke();poseCtx.restore();poseCtx.font=`700 ${font}px "JetBrains Mono",monospace`;poseCtx.textBaseline='bottom';poseCtx.fillStyle=color;poseCtx.strokeStyle='#fff';poseCtx.lineWidth=Math.max(2,3/scale);poseCtx.strokeText('QBot',point.x+markerRadius,point.y-markerRadius);poseCtx.fillText('QBot',point.x+markerRadius,point.y-markerRadius);
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
      if(state.viewingLiveMap){const pending=state.mapping?.pending_labels||[];if(!pending.length){labelList.innerHTML='<div class="empty">Live Cartographer preview. Release LB, then press B to drop label1.</div>';return;}for(const label of pending){const item=document.createElement('div');item.className='label-item';const content=document.createElement('div');content.className='label-select';const world=label.world||{};content.innerHTML='<div class="label-name"></div><div class="label-meta"></div>';content.querySelector('.label-name').textContent=label.name;content.querySelector('.label-meta').textContent=`mapping ${Number(world.x).toFixed(2)}, ${Number(world.y).toFixed(2)} · rename after save`;item.append(content);labelList.appendChild(item);}return;}
      if (!state.labels.length) { labelList.innerHTML='<div class="empty">No labels yet. Click a white spot on the map to add one.</div>'; return; }
      for (const label of state.labels) {
        const navigating=goalMatchesLabel(label),goalRunning=state.goal?.event==='running';
        const item=document.createElement('div'); item.className=`label-item ${label.id===state.selectedId?'active':''} ${navigating?'navigating':''}`.trim();
        const select=document.createElement('button'); select.className='label-select'; select.type='button';
        const world=label.world||worldFromPixel(Number(label.x),Number(label.y));
        select.innerHTML='<div class="label-name"></div><div class="label-meta"></div>'; select.querySelector('.label-name').textContent=label.name;
        if (isOrigin(label)) { const badge=document.createElement('span'); badge.className='badge'; badge.textContent='system'; select.querySelector('.label-name').appendChild(badge); }
        if(navigating){const badge=document.createElement('span');badge.className='navigation-badge';badge.textContent='Navigating';select.querySelector('.label-name').appendChild(badge);}
        select.querySelector('.label-meta').textContent=world?`map ${Number(world.x).toFixed(2)}, ${Number(world.y).toFixed(2)}`:`pixel ${label.x}, ${label.y}`;
        select.addEventListener('click',()=>{selectLabel(label);centerLabel(label);});
        const go=document.createElement('button'); go.className='go'; go.type='button'; go.textContent=navigating?'Running…':'Go'; go.disabled=!navigationIsLocalized()||goalRunning;go.title=state.localizing?'Wait for localization or press Stop':(!selectedMapIsActive()?'Start navigation with this displayed map first':(!navigationIsLocalized()?'Run Localize and wait for it to complete':(goalRunning?'Wait for the current navigation goal to finish':`Navigate to ${label.name}`))); go.addEventListener('click',()=>goToLabel(label,go));
        item.append(select,go); labelList.appendChild(item);
      }
    }
    function syncSelection() { const label=activeLabel(), protectedLabel=isOrigin(label),locked=mappingIsActive()||state.deletingMap; editInput.disabled=locked||!label||protectedLabel; document.getElementById('renameBtn').disabled=locked||!label||protectedLabel; document.getElementById('deleteBtn').disabled=locked||!label||protectedLabel;document.getElementById('clearBtn').disabled=locked; editInput.value=label?label.name:''; }
    function markDirty() { state.dirty=true; updateSaveButton(); setStatus(`Unsaved label changes for ${state.mapName}`); }
    async function fetchJson(url,options={}) { const {timeoutMs=15000,...fetchOptions}=options,controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs),requestOptions={...fetchOptions,signal:fetchOptions.signal||controller.signal};try{const response=await fetch(url,requestOptions);let data;try{data=await response.json();}catch{data={error:`${response.status} ${response.statusText}`};}if(!response.ok)throw new Error(data.error||`${response.status} ${response.statusText}`);return data;}catch(error){if(error.name==='AbortError')throw new Error('The command request timed out; checking robot status.');throw error;}finally{clearTimeout(timer);} }
    function updateDeleteMapButton(){const navIdle=['stopped','error'].includes(state.navigation?.state),mappingIdle=['stopped','error'].includes(state.mapping?.state);const button=document.getElementById('deleteMapBtn');button.disabled=!state.mapName||!navIdle||!mappingIdle||state.saving||state.deletingMap;button.textContent=state.deletingMap?'Deleting…':'Delete Map';}
    function openDeleteMapDialog(){updateDeleteMapButton();if(document.getElementById('deleteMapBtn').disabled)return;document.getElementById('deleteMapMessage').textContent=`Type ${state.mapName} exactly. Its PGM, YAML, and labels JSON will be moved to recoverable trash.${state.dirty?' Unsaved label changes will be discarded.':''}`;deleteMapConfirmation.value='';deleteMapError.textContent='';deleteMapConfirmation.placeholder=state.mapName;deleteMapDialog.hidden=false;requestAnimationFrame(()=>deleteMapConfirmation.focus());}
    function closeDeleteMapDialog(){if(state.deletingMap)return;deleteMapDialog.hidden=true;deleteMapConfirmation.value='';deleteMapError.textContent='';}
    async function deleteSelectedMap(event){event.preventDefault();const mapName=state.mapName,confirmation=deleteMapConfirmation.value;if(confirmation!==mapName){deleteMapError.textContent=`Type ${mapName} exactly.`;deleteMapConfirmation.focus();return;}const button=document.getElementById('confirmDeleteMapBtn'),original=button.textContent;state.deletingMap=true;button.disabled=true;button.textContent='Deleting…';applyMappingStatus(state.mapping);try{const data=await fetchJson('/api/maps/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:mapName,confirmation})});state.dirty=false;deleteMapDialog.hidden=true;localStorage.removeItem(selectedMapStorageKey);showToast(`Moved ${data.deleted_map} to recoverable trash.`,'success');setStatus(`Deleted ${data.deleted_map}. Recovery files: ${data.trash}`,'success');state.mapName=null;await loadMaps();}catch(error){deleteMapError.textContent=error.message;setStatus(`Could not delete map: ${error.message}`,'error');showToast(`Could not delete map: ${error.message}`,'error');await Promise.all([refreshNavigationStatus(),refreshMappingStatus()]);}finally{state.deletingMap=false;button.disabled=false;button.textContent=original;applyMappingStatus(state.mapping);}}
    async function loadMaps(preferredName=null) {
      const data=await fetchJson('/api/maps'); mapSelect.innerHTML='';
      for(const map of data.maps){const option=document.createElement('option');option.value=map.name;option.textContent=map.name;mapSelect.appendChild(option);}
      if(!data.maps.length){state.mapName=null;state.mapImage=null;state.labels=[];canvas.width=0;canvas.height=0;poseCanvas.width=0;poseCanvas.height=0;setStatus('No saved maps yet. Use New Map to create one.');applyNavigationStatus(state.navigation);updateDeleteMapButton();return;}
      const remembered=preferredName||localStorage.getItem(selectedMapStorageKey),available=data.maps.some(map=>map.name===remembered);
      await loadMap(available?remembered:data.maps[0].name);
    }
    async function loadMap(name) {
      setStatus(`Loading ${name}…`); const data=await fetchJson(`/api/map?name=${encodeURIComponent(name)}`,{timeoutMs:120000});
      Object.assign(state,{mapName:name,mapMeta:data.meta||{},labels:data.labels||[],selectedId:null,dirty:false,saving:false,viewingLiveMap:false,mappingPreviewRevision:0,mappingPreviewGeometry:null}); mapSelect.value=name;localStorage.setItem(selectedMapStorageKey,name);
      const decoded=atob(data.pixels),bytes=new Uint8Array(decoded.length);for(let i=0;i<decoded.length;i++)bytes[i]=decoded.charCodeAt(i);state.mapPixels=bytes; const image=ctx.createImageData(data.width,data.height);
      for(let i=0;i<bytes.length;i++){const j=i*4;image.data[j]=bytes[i];image.data[j+1]=bytes[i];image.data[j+2]=bytes[i];image.data[j+3]=255;}
      canvas.width=data.width;canvas.height=data.height;poseCanvas.width=data.width;poseCanvas.height=data.height;state.mapImage=image;fitMap();syncSelection();renderList();updateSaveButton();setStatus(`${name}: ${data.width} × ${data.height}, ${state.labels.length} saved labels`,'success');
      applyNavigationStatus(state.navigation);
      updateDeleteMapButton();
    }
    function applyZoom(){const width=`${canvas.width*state.zoom}px`,height=`${canvas.height*state.zoom}px`;canvas.style.width=width;canvas.style.height=height;poseCanvas.style.width=width;poseCanvas.style.height=height;draw();}
    function fitMap(){const pad=64,zx=Math.max(.01,(viewer.clientWidth-pad)/canvas.width),zy=Math.max(.01,(viewer.clientHeight-pad)/canvas.height);state.zoom=Math.max(.02,Math.min(3,Math.min(zx,zy)));applyZoom();}
    async function saveLabels(force=false){
      if(!state.dirty&&!force)return{labels:state.labels}; state.saving=true;updateSaveButton();document.getElementById('startNavBtn').disabled=true;setStatus('Saving labels…');
      try{const data=await fetchJson('/api/labels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName,labels:state.labels})});state.labels=data.labels||state.labels;state.dirty=false;if(!state.labels.some(l=>l.id===state.selectedId))state.selectedId=null;renderList();syncSelection();draw();setStatus(`Saved ${data.count} labels to ${data.file}`,'success');return data;}
      catch(error){state.dirty=true;setStatus(`Save failed: ${error.message}`,'error');throw error;}finally{state.saving=false;updateSaveButton();applyNavigationStatus(state.navigation);}
    }
    async function goToLabel(label,button){
      try{if(!selectedMapIsActive())throw new Error('Start navigation with the displayed map before using Go.');if(!navigationIsLocalized())throw new Error('Run Localize and wait for it to complete before using Go.');if(state.goal?.event==='running')throw new Error('Wait for the current navigation goal to finish or press Stop robot.');if(state.dirty)await saveLabels();const saved=state.labels.find(candidate=>candidate.id===label.id);if(!saved)throw new Error('The label was not found after saving.');const world=saved.world||worldFromPixel(saved.x,saved.y),coords=world?` (${Number(world.x).toFixed(2)}, ${Number(world.y).toFixed(2)})`:'';if(!confirm(`Send the robot to “${saved.name}”${coords}?`))return;
        const original=button.textContent;button.disabled=true;button.textContent='Sending…';setStatus(`Sending navigation command for ${saved.name}…`);
        try{const data=await fetchJson('/api/go',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName,label_id:saved.id})});if(data.goal)applyGoalStatus(data.goal);if(data.cancelled_by_stop)setStatus(`Navigation to ${data.name} was cancelled by Stop.`,'success');else if(!data.goal||data.goal.event==='running')setStatus(`Navigating to ${data.name} on ROS domain ${data.ros_domain_id}…`,'success');}finally{button.disabled=false;button.textContent=original;renderList();}}
      catch(error){setStatus(`Could not navigate: ${error.message}`,'error');await refreshGoalStatus();}
    }
    async function stopNavigation(){
      const button=document.getElementById('stopBtn'),original=button.textContent;button.disabled=true;button.textContent='Stopping…';setStatus('Sending emergency navigation stop…','error');
      try{const data=await fetchJson('/api/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});state.localizing=false;renderList();setStatus(`Stop command sent on ${data.topic} (ROS domain ${data.ros_domain_id})`,'success');}
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
    function renderMappingPreview(data){
      if(!data?.available)return;
      const firstFrame=state.mappingPreviewRevision===0,bytes=Uint8Array.from(atob(data.pixels),character=>character.charCodeAt(0)),image=ctx.createImageData(data.width,data.height),dimensionsChanged=canvas.width!==data.width||canvas.height!==data.height;
      for(let index=0;index<bytes.length;index++){const output=index*4,value=bytes[index];image.data[output]=value;image.data[output+1]=value;image.data[output+2]=value;image.data[output+3]=255;}
      canvas.width=data.width;canvas.height=data.height;poseCanvas.width=data.width;poseCanvas.height=data.height;state.mapImage=image;state.mapPixels=bytes;state.mapMeta={...(data.meta||{}),resolution:Number(data.meta?.resolution||.01)*Number(data.step||1)};state.mappingPreviewGeometry={sourceWidth:Number(data.source_width),sourceHeight:Number(data.source_height),step:Number(data.step||1),resolution:Number(data.meta?.resolution||.01),origin:Array.isArray(data.meta?.origin)?data.meta.origin:[0,0,0]};state.viewingLiveMap=true;state.mappingPreviewRevision=Number(data.revision||0);
      if(firstFrame||dimensionsChanged)fitMap();else applyZoom();
      renderList();syncSelection();setStatus(`Live map: ${data.source_width} × ${data.source_height} full-resolution cells · preview step ${data.step}`,'success');
    }
    async function refreshMappingPreview(){
      if(mappingPreviewPending||!mappingIsActive()||!['starting','mapping','saving'].includes(state.mapping.state))return;mappingPreviewPending=true;
      try{const response=await fetch(`/api/mapping/preview?after=${encodeURIComponent(state.mappingPreviewRevision)}`,{cache:'no-store'});if(response.status===204)return;let data;try{data=await response.json();}catch{throw new Error(`${response.status} ${response.statusText}`);}if(!response.ok)throw new Error(data.error||`${response.status} ${response.statusText}`);if(data.available)renderMappingPreview(data);else state.mappingPreviewRevision=Math.max(state.mappingPreviewRevision,Number(data.revision||0));}
      catch(error){if(state.mapping.state==='mapping')document.getElementById('mappingMessage').textContent=`Mapping is active; live preview unavailable: ${error.message}`;}
      finally{mappingPreviewPending=false;}
    }
    function openNewMapDialog(){
      if(mappingIsActive()){setStatus('Stop or finish the current mapping session first.','error');return;}
      if(!['stopped','error'].includes(state.navigation.state)){setStatus('Stop Navigation before starting a new map.','error');return;}
      newMapName.value='';newMapError.textContent='';document.getElementById('newMapFilename').textContent='Filename: .pgm';newMapDialog.hidden=false;requestAnimationFrame(()=>newMapName.focus());
    }
    function closeNewMapDialog(){newMapDialog.hidden=true;newMapName.value='';newMapError.textContent='';}
    async function startMappingSession(event){
      event.preventDefault();const stem=newMapName.value.trim(),valid=/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(stem);if(!valid){newMapError.textContent='Use 1–64 letters, numbers, underscores, or hyphens.';newMapName.focus();return;}
      const button=newMapForm.querySelector('button[type="submit"]'),original=button.textContent;button.disabled=true;button.textContent='Starting…';newMapError.textContent='';
      try{if(state.dirty)await saveLabels();const data=await fetchJson('/api/mapping/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:stem})});closeNewMapDialog();applyMappingStatus(data);setStatus(`Mapping startup requested for ${stem}.pgm. Watch the terminal for details.`,'success');}
      catch(error){newMapError.textContent=error.message;setStatus(`Could not start mapping: ${error.message}`,'error');showToast(`Could not start mapping: ${error.message}`,'error');await refreshMappingStatus();}
      finally{button.disabled=false;button.textContent=original;}
    }
    async function finishMapping(){
      if(!confirm('Release LB and make sure the robot is stopped. Save this map and stop Cartographer?'))return;
      const button=document.getElementById('finishMapBtn'),original=button.textContent;button.disabled=true;button.textContent='Saving…';
      try{const data=await fetchJson('/api/mapping/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});applyMappingStatus(data);setStatus('Saving the full-resolution map. Details are in the terminal.');}
      catch(error){setStatus(`Could not save mapping: ${error.message}`,'error');showToast(`Could not save mapping: ${error.message}`,'error');await refreshMappingStatus();}
      finally{button.textContent=original;applyMappingStatus(state.mapping);}
    }
    async function cancelMapping(){
      if(!confirm('Cancel mapping and discard this unsaved map?'))return;
      const button=document.getElementById('cancelMapBtn'),original=button.textContent;button.disabled=true;button.textContent='Canceling…';
      try{const data=await fetchJson('/api/mapping/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});applyMappingStatus(data);setStatus('Canceling mapping without saving.');}
      catch(error){setStatus(`Could not cancel mapping: ${error.message}`,'error');showToast(`Could not cancel mapping: ${error.message}`,'error');await refreshMappingStatus();}
      finally{button.textContent=original;applyMappingStatus(state.mapping);}
    }
    async function localizeRobot(){
      if(!selectedMapIsActive()){setStatus('Start navigation with the displayed map before localizing.','error');return;}
      if(!confirm('The robot will stop navigation and slowly rotate 360° to localize. Make sure it has clear space. Continue?'))return;
      const button=document.getElementById('localizeBtn'),original=button.textContent;button.disabled=true;button.textContent='Starting…';setStatus('Starting AMCL global localization…');
      try{const data=await fetchJson('/api/localize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({map:state.mapName})});if(data.cancelled_by_stop){setStatus('Localization was cancelled by Stop.','success');}else{state.localizing=true;button.disabled=true;renderList();setStatus(`Localization started on ROS domain ${data.ros_domain_id}. Go remains locked until the real localization result arrives.`,'success');await refreshNavigationStatus();}}
      catch(error){setStatus(`Could not start localization: ${error.message}`,'error');await refreshNavigationStatus();}
      finally{button.textContent=original;applyNavigationStatus(state.navigation);}
    }
    function updatePoseDisplay(){
      const element=document.getElementById('poseStatus'),button=document.getElementById('savePoseBtn'),pose=state.robotPose;
      if(state.viewingLiveMap){const mappingPose=state.mapping?.robot_pose;if(!mappingPose?.available){element.className='pose-status';element.textContent=`Mapping pose: ${mappingPose?.reason||'waiting for /tracked_pose…'} · release LB, then press B to label`;button.disabled=true;draw();return;}element.className=`pose-status ${mappingPose.stale?'stale':'live'}`;element.textContent=mappingPose.stale?'Mapping pose is stale; label drops are locked.':`QBot mapping pose: ${Number(mappingPose.world.x).toFixed(2)}, ${Number(mappingPose.world.y).toFixed(2)} · release LB, press B to drop next label`;button.disabled=true;draw();return;}
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
    canvas.addEventListener('click',event=>{if(mappingIsActive()||state.deletingMap||state.viewingLiveMap||!state.mapImage||!addDialog.hidden)return;const point=canvasPoint(event);if(point.x<0||point.y<0||point.x>=canvas.width||point.y>=canvas.height)return;const label=nearestLabel(point);if(label){selectLabel(label);return;}const classification=pixelClassification(point);if(classification!=='free'){setStatus(`That pixel is ${classification}. Click a white, navigable location.`,'error');return;}openAddDialog(point);});
    addForm.addEventListener('submit',event=>{event.preventDefault();const name=addName.value.trim();if(!name){addError.textContent='Enter a name for this location.';addName.focus();return;}if(state.labels.some(label=>label.name.trim().toLowerCase()===name.toLowerCase())){addError.textContent='A label with that name already exists.';addName.focus();return;}const point=state.pendingPoint,label={id:newId(),name,kind:'navigation',detail:'',source:'browser',x:point.x,y:point.y,world:worldFromPixel(point.x,point.y),yaw:0};state.labels.push(label);closeAddDialog();selectLabel(label);markDirty();});
    document.getElementById('cancelAddBtn').addEventListener('click',closeAddDialog);addDialog.addEventListener('click',event=>{if(event.target===addDialog)closeAddDialog();});document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!addDialog.hidden)closeAddDialog();if(event.key==='Escape'&&!newMapDialog.hidden)closeNewMapDialog();if(event.key==='Escape'&&!deleteMapDialog.hidden)closeDeleteMapDialog();});
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
    document.getElementById('deleteMapBtn').addEventListener('click',openDeleteMapDialog);deleteMapForm.addEventListener('submit',deleteSelectedMap);document.getElementById('cancelDeleteMapBtn').addEventListener('click',closeDeleteMapDialog);deleteMapDialog.addEventListener('click',event=>{if(event.target===deleteMapDialog)closeDeleteMapDialog();});
    document.getElementById('newMapBtn').addEventListener('click',openNewMapDialog);
    document.getElementById('finishMapBtn').addEventListener('click',finishMapping);
    document.getElementById('cancelMapBtn').addEventListener('click',cancelMapping);
    newMapForm.addEventListener('submit',startMappingSession);document.getElementById('cancelNewMapBtn').addEventListener('click',closeNewMapDialog);newMapDialog.addEventListener('click',event=>{if(event.target===newMapDialog)closeNewMapDialog();});newMapName.addEventListener('input',()=>{const stem=newMapName.value.trim();document.getElementById('newMapFilename').textContent=`Filename: ${stem||''}.pgm`;newMapError.textContent='';});
    document.getElementById('localizeBtn').addEventListener('click',localizeRobot);
    document.getElementById('savePoseBtn').addEventListener('click',saveInitialPose);
    document.getElementById('exportBtn').addEventListener('click',()=>{draw();const link=document.createElement('a');link.href=canvas.toDataURL('image/png');link.download=`${state.mapName.replace(/\.[^.]+$/,'')}_annotated.png`;link.click();});
    mapSelect.addEventListener('change',()=>{if(mappingIsActive()){mapSelect.value=state.mapName||'';return;}if(state.dirty&&!confirm('Switch maps and discard unsaved label changes?')){mapSelect.value=state.mapName;return;}loadMap(mapSelect.value).catch(error=>setStatus(error.message,'error'));});
    window.addEventListener('beforeunload',event=>{if(state.dirty||mappingIsActive()){event.preventDefault();event.returnValue='';}});window.addEventListener('resize',()=>{if(state.mapImage)applyZoom();});Promise.all([loadMaps(),refreshNavigationStatus(),refreshMappingStatus(),refreshGoalStatus()]).then(refreshRobotPose).catch(error=>setStatus(error.message,'error'));setInterval(refreshRobotPose,1000);setInterval(refreshNavigationStatus,1000);setInterval(refreshMappingStatus,1000);setInterval(refreshMappingPreview,1000);setInterval(refreshGoalStatus,750);
  </script>
</body>
</html>
"""


def safe_map_name(name: str) -> str:
    decoded = unquote(name)
    if not re.fullmatch(r"[-A-Za-z0-9_ .]+\.pgm", decoded):
        raise ValueError("Invalid map name")
    return decoded


def safe_new_map_stem(name: str) -> str:
    """Validate a user-selected filename stem for a newly mapped area."""
    candidate = str(name).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", candidate):
        raise ValueError(
            "Map name must be 1-64 letters, numbers, underscores, or hyphens"
        )
    return candidate


def qbot_platform_build_required(
    repo_dir: Path,
    navigation_setup: Path,
    build_stamp: Path | None = None,
) -> bool:
    """Return true when qbot_platform is missing or source is newer than its stamp."""
    repo_dir = Path(repo_dir)
    navigation_setup = Path(navigation_setup)
    if not navigation_setup.exists():
        return True
    source_dir = repo_dir / "robot_navigation" / "src" / "qbot_platform"
    if not source_dir.exists():
        # Unit tests and custom embeddings may provide only an installed setup.
        return False
    stamp = Path(build_stamp) if build_stamp is not None else (
        repo_dir / "robot_navigation" / "install" / ".qbot_platform_source_stamp"
    )
    if not stamp.exists():
        return True
    source_suffixes = {".cpp", ".hpp", ".h", ".lua", ".py", ".xml", ".yaml", ".yml"}
    newest_source = 0.0
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "CMakeLists.txt" or path.suffix.casefold() in source_suffixes:
            newest_source = max(newest_source, path.stat().st_mtime)
    return newest_source > stamp.stat().st_mtime


def map_artifact_paths(map_dir: Path, stem: str) -> tuple[Path, Path, Path]:
    return (
        map_dir / f"{stem}.pgm",
        map_dir / f"{stem}.yaml",
        map_dir / f"{stem}_labels.json",
    )


def map_name_collisions(map_dir: Path, stem: str) -> list[Path]:
    wanted = {
        path.name.casefold() for path in map_artifact_paths(Path(map_dir), stem)
    }
    if not Path(map_dir).exists():
        return []
    return sorted(
        (path for path in Path(map_dir).iterdir() if path.name.casefold() in wanted),
        key=lambda path: path.name.casefold(),
    )


def trash_map_artifacts(
    map_path: Path,
    confirmation: str,
    *,
    trash_root: Path | None = None,
) -> tuple[Path, list[Path]]:
    """Move one complete map into a hidden, recoverable trash directory."""
    map_path = Path(map_path)
    if confirmation != map_path.name:
        raise ValueError(f"Type {map_path.name!r} exactly to confirm deletion")
    validate_navigation_map(map_path)
    source_paths = [map_path.with_suffix(".yaml"), label_path_for(map_path), map_path]
    source_paths = [path for path in source_paths if path.exists()]
    if map_path not in source_paths or map_path.with_suffix(".yaml") not in source_paths:
        raise FileNotFoundError("The complete map file set was not found")

    root = Path(trash_root) if trash_root is not None else map_path.parent / ".trash"
    root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    destination = root / f"{timestamp}-{map_path.stem}"
    suffix = 1
    while destination.exists():
        destination = root / f"{timestamp}-{map_path.stem}-{suffix}"
        suffix += 1
    destination.mkdir()

    moved: list[tuple[Path, Path]] = []
    try:
        for source in source_paths:
            target = destination / source.name
            os.replace(source, target)
            moved.append((source, target))
        manifest = {
            "deleted_at": timestamp,
            "map": map_path.name,
            "original_directory": str(map_path.parent.resolve()),
            "files": [target.name for _, target in moved],
        }
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination, [target for _, target in moved]
    except Exception:
        for source, target in reversed(moved):
            if target.exists() and not source.exists():
                os.replace(target, source)
        try:
            (destination / "manifest.json").unlink()
        except FileNotFoundError:
            pass
        try:
            destination.rmdir()
        except OSError:
            pass
        raise


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


def discover_maps(map_dir: Path = MAPS_DIR) -> list[Path]:
    """Return complete, valid top-level maps and ignore partial/staging output."""
    discovered = []
    for map_path in sorted(Path(map_dir).glob("*.pgm"), key=lambda path: path.name.casefold()):
        try:
            validate_navigation_map(map_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        discovered.append(map_path)
    return discovered


def normalize_saved_map_yaml(yaml_path: Path, image_name: str) -> None:
    """Rewrite a map YAML's image entry without disturbing its other settings."""
    lines = yaml_path.read_text(encoding="utf-8").splitlines()
    found_image = False
    normalized_lines = []
    for line in lines:
        if re.match(r"^\s*image\s*:", line):
            indentation = line[: len(line) - len(line.lstrip())]
            normalized_lines.append(f"{indentation}image: {image_name}")
            found_image = True
        else:
            normalized_lines.append(line)
    if not found_image:
        raise ValueError(f"Map metadata has no image entry: {yaml_path.name}")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=yaml_path.parent,
            prefix=f".{yaml_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write("\n".join(normalized_lines) + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, yaml_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


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


def write_labels(
    map_path: Path,
    labels: list[dict],
    *,
    output_path: Path | None = None,
    output_map_name: str | None = None,
) -> tuple[Path, list[dict]]:
    normalized = normalize_labels(map_path, labels, enforce_free=True)
    map_name = output_map_name or map_path.name
    if not map_name.endswith(".pgm"):
        raise ValueError("output_map_name must end with .pgm")
    output = {
        "map": map_name,
        "yaml": f"{Path(map_name).stem}.yaml",
        "labels": normalized,
    }
    label_path = Path(output_path) if output_path is not None else label_path_for(map_path)
    temporary_path = None
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


class RobotOperationCoordinator:
    """Atomically reserve the physical robot for one website-managed stack."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.owner: str | None = None

    def claim(self, owner: str) -> None:
        with self.lock:
            if self.owner is not None:
                raise NavigationConflictError(
                    f"The QBot is currently managed by {self.owner}; stop it first"
                )
            self.owner = owner

    def release(self, owner: str) -> None:
        with self.lock:
            if self.owner == owner:
                self.owner = None

    def snapshot(self) -> str | None:
        with self.lock:
            return self.owner


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
        "/smoother_server",
        "/velocity_smoother",
        "/waypoint_follower",
        "/cartographer_node",
        "/cartographer_occupancy_grid_node",
        "/slam_toolbox",
        "/async_slam_toolbox_node",
        "/sync_slam_toolbox_node",
        "/fixed_lidar_frame",
        "/joystickCommands",
        "/joystick_publisher",
        "/scan_wedge_filter",
        "/wheel_odometry",
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
        adaptive_goal_tolerance: bool = True,
        readiness_timeout: float = 120.0,
        probe_interval: float = 1.0,
        coordinator: RobotOperationCoordinator | None = None,
        popen_factory=None,
        run_factory=None,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.navigation_setup = Path(navigation_setup)
        self.run_script = Path(run_script)
        self.rebuild_script = Path(rebuild_script)
        self.scan_filter_file = Path(scan_filter_file)
        self.ros_domain_id = ros_domain_id
        self.adaptive_goal_tolerance = bool(adaptive_goal_tolerance)
        self.readiness_timeout = readiness_timeout
        self.probe_interval = probe_interval
        self.coordinator = coordinator or RobotOperationCoordinator()
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
        self.localization_state = "required"
        self.localization_message = "Start navigation, then run Localize."
        self.localization_generation = 0
        self.localization_started_at: float | None = None

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
                "adaptive_goal_tolerance": self.adaptive_goal_tolerance,
                "localization_state": self.localization_state,
                "localization_required": self.localization_state != "ready",
                "localized": self.localization_state == "ready",
                "localization_message": self.localization_message,
                "localization_generation": self.localization_generation,
                "localization_started_at": self.localization_started_at,
            }

    def _reset_localization(self, message: str) -> None:
        self.localization_generation += 1
        self.localization_state = "required"
        self.localization_message = message
        self.localization_started_at = None

    def begin_localization(self) -> dict:
        with self.lock:
            process_alive = self.process is not None and self.process.poll() is None
            if self.state != "ready" or not process_alive:
                raise NavigationConflictError("Navigation must be ready before localizing")
            if self.localization_state == "in_progress":
                raise NavigationConflictError("Localization is already in progress")
            self.localization_generation += 1
            self.localization_state = "in_progress"
            self.localization_message = "AMCL global localization is running."
            self.localization_started_at = time.time()
            return self.snapshot()

    def fail_localization(self, message: str) -> None:
        with self.lock:
            if self.localization_state == "in_progress":
                self.localization_state = "failed"
                self.localization_message = message

    def handle_navigation_event(self, event: dict, pose: dict | None = None) -> None:
        if str(event.get("name") or "").casefold() != "localize":
            return
        with self.lock:
            if self.state != "ready":
                return
            if event.get("event") == "running":
                if self.localization_state != "in_progress":
                    self.localization_generation += 1
                    self.localization_started_at = time.time()
                self.localization_state = "in_progress"
                self.localization_message = "AMCL global localization is running."
                return
            if event.get("outcome") != "succeeded":
                self.localization_state = "failed"
                self.localization_message = str(
                    event.get("message") or "Localization did not complete successfully."
                )
                return
            started_at = self.localization_started_at
            pose_received_at = float((pose or {}).get("received_at") or 0.0)
            pose_is_fresh = bool(
                pose
                and pose.get("available")
                and not pose.get("stale")
                and started_at is not None
                and pose_received_at >= started_at
            )
            if not pose_is_fresh:
                self.localization_state = "failed"
                self.localization_message = (
                    "Localization spin finished, but no fresh AMCL pose was received."
                )
                return
            self.localization_state = "ready"
            self.localization_message = "Localization completed; navigation goals are enabled."

    def require_localized(self, _pose: dict | None) -> None:
        with self.lock:
            if self.localization_state != "ready":
                raise NavigationConflictError(
                    "Run Localize and wait for it to complete before sending a navigation goal"
                )

    def reconcile_localization(self, _pose: dict | None) -> None:
        # Freshness is authoritative when a localization result arrives. Once
        # accepted, keep the gate open while this Nav2 process remains active;
        # AMCL may publish infrequently while a correctly localized robot is idle.
        return None

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
            self._reset_localization("Navigation started; run Localize before using Go.")
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
        self.coordinator.claim("navigation")
        try:
            conflicts = self.conflicting_nodes()
            if conflicts:
                raise NavigationConflictError(
                    "Navigation nodes are already running: " + ", ".join(conflicts)
                )
            needs_build = qbot_platform_build_required(
                self.repo_dir,
                self.navigation_setup,
            )
            initial_state = "building" if needs_build else "starting"
            initial_message = (
                "Building navigation workspace; details are in the terminal."
                if needs_build
                else f"Starting navigation with {map_path.name}; details are in the terminal."
            )
            token = self._begin_operation(initial_state, map_path.name, initial_message)
        except Exception:
            self.coordinator.release("navigation")
            raise
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
                if qbot_platform_build_required(self.repo_dir, self.navigation_setup):
                    raise RuntimeError(
                        "Build finished but the qbot_platform source stamp was not updated"
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
            if not self.adaptive_goal_tolerance:
                command.append("--fixed-goal-tolerance")
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
                        f"Navigation is ready with {map_path.name}; localization is required.",
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
                    inactive = self.state in {"stopped", "error"}
                else:
                    inactive = False
            if inactive:
                self.coordinator.release("navigation")

    def rebuild(self) -> dict:
        if not self.rebuild_script.exists():
            raise RuntimeError(f"Rebuild script not found: {self.rebuild_script}")
        self.coordinator.claim("navigation build")
        try:
            conflicts = self.conflicting_nodes()
            if conflicts:
                raise NavigationConflictError(
                    "Stop the running robot stack before rebuilding: "
                    + ", ".join(conflicts)
                )
            token = self._begin_operation(
                "building",
                None,
                "Rebuilding navigation workspace; details are in the terminal.",
            )
        except Exception:
            self.coordinator.release("navigation build")
            raise
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
            self.coordinator.release("navigation build")

    def stop(self) -> dict:
        with self.lock:
            if self.state in {"stopped", "error"} and (
                self.process is None or self.process.poll() is not None
            ):
                self.state = "stopped"
                self.active_map = None
                self.error = ""
                self.message = "Navigation is already stopped."
                self._reset_localization("Navigation is stopped.")
                self.coordinator.release("navigation")
                return self.snapshot()
            token = self.operation_token
            self.stop_event.set()
            self.state = "stopping"
            self.message = "Stopping navigation; shutdown details are in the terminal."
            self._reset_localization("Navigation is stopping.")
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
        self.coordinator.release("navigation")

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


class MappingManager:
    """Start Cartographer, save a validated map transactionally, and stop it."""

    CONFLICTING_NODES = NavigationManager.CONFLICTING_NODES
    REQUIRED_READY_NODES = {
        "/cartographer_node",
        "/cartographer_occupancy_grid_node",
        "/fixed_lidar_frame",
        "/wheel_odometry",
        "/Lidar",
        "/QBotPlatformDriver",
    }

    def __init__(
        self,
        *,
        map_monitor=None,
        coordinator: RobotOperationCoordinator | None = None,
        repo_dir: Path = REPO_DIR,
        maps_dir: Path = MAPS_DIR,
        navigation_setup: Path = NAVIGATION_SETUP,
        run_script: Path = RUN_MAPPING_SCRIPT,
        rebuild_script: Path = REBUILD_NAVIGATION_SCRIPT,
        scan_filter_file: Path = SCAN_FILTER_FILE,
        ros_domain_id: int = 63,
        readiness_timeout: float = 120.0,
        save_timeout: float = 30.0,
        probe_interval: float = 1.0,
        mapping_label_topic: str = "/mapping/drop_label",
        mapping_label_button_bit: int = 1,
        maps_lock: threading.RLock | None = None,
        popen_factory=None,
        run_factory=None,
    ) -> None:
        self.map_monitor = map_monitor
        self.coordinator = coordinator or RobotOperationCoordinator()
        self.repo_dir = Path(repo_dir)
        self.maps_dir = Path(maps_dir)
        self.navigation_setup = Path(navigation_setup)
        self.run_script = Path(run_script)
        self.rebuild_script = Path(rebuild_script)
        self.scan_filter_file = Path(scan_filter_file)
        self.ros_domain_id = int(ros_domain_id)
        self.readiness_timeout = float(readiness_timeout)
        self.save_timeout = float(save_timeout)
        self.probe_interval = float(probe_interval)
        self.mapping_label_topic = str(mapping_label_topic)
        self.mapping_label_button_bit = int(mapping_label_button_bit)
        if not self.mapping_label_topic:
            raise ValueError("mapping_label_topic cannot be empty")
        if not 0 <= self.mapping_label_button_bit <= 31:
            raise ValueError("mapping_label_button_bit must be between 0 and 31")
        self.maps_lock = maps_lock or threading.RLock()
        self.popen_factory = popen_factory or subprocess.Popen
        self.run_factory = run_factory or subprocess.run
        self.lock = threading.RLock()
        self.commit_lock = threading.Lock()
        self.state = "stopped"
        self.reserved_stem: str | None = None
        self.saved_map: str | None = None
        self.message = "Mapping is stopped."
        self.error = ""
        self.process = None
        self.save_process = None
        self.worker: threading.Thread | None = None
        self.save_worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.operation_token = 0
        self.last_exit_code: int | None = None
        self.staging_dir: Path | None = None
        self.started_at: float | None = None
        self.pending_labels: list[dict] = []
        self.label_event_sequence = 0
        self.last_label_event: dict | None = None

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["ROS_DOMAIN_ID"] = str(self.ros_domain_id)
        return environment

    def _preview_status(self) -> dict:
        if self.map_monitor is None or not hasattr(
            self.map_monitor, "mapping_map_snapshot"
        ):
            return {"available": False, "revision": 0}
        return self.map_monitor.mapping_map_snapshot()

    def snapshot(self) -> dict:
        preview = self._preview_status()
        mapping_pose = (
            self.map_monitor.mapping_pose_snapshot()
            if self.map_monitor is not None
            and hasattr(self.map_monitor, "mapping_pose_snapshot")
            else {"available": False, "reason": "Mapping pose monitor is unavailable"}
        )
        with self.lock:
            process_alive = self.process is not None and self.process.poll() is None
            return {
                "state": self.state,
                "reserved_map": (
                    f"{self.reserved_stem}.pgm" if self.reserved_stem else None
                ),
                "ready": self.state == "mapping" and process_alive,
                "message": self.message,
                "error": self.error or None,
                "managed_process": process_alive,
                "pid": self.process.pid if process_alive else None,
                "last_exit_code": self.last_exit_code,
                "ros_domain_id": self.ros_domain_id,
                "preview_available": bool(preview.get("available")),
                "preview_revision": int(preview.get("revision", 0)),
                "saved_map": self.saved_map,
                "robot_pose": mapping_pose,
                "pending_labels": [dict(label) for label in self.pending_labels],
                "label_event_sequence": self.label_event_sequence,
                "last_label_event": (
                    dict(self.last_label_event) if self.last_label_event else None
                ),
            }

    def drop_label(self, pose: dict | None) -> dict:
        """Capture a mapping label from the latest fresh Cartographer pose."""
        with self.lock:
            process_alive = self.process is not None and self.process.poll() is None
            if self.state != "mapping" or not process_alive:
                raise NavigationConflictError("Mapping is not ready for label drops")
            if not pose or not pose.get("available") or pose.get("stale"):
                raise NavigationConflictError(
                    "Cannot drop a label until /tracked_pose is fresh"
                )
            world = pose.get("world") or {}
            world_x = float(world["x"])
            world_y = float(world["y"])
            next_number = 1
            existing_names = {
                str(label.get("name") or "").casefold()
                for label in self.pending_labels
            }
            while f"label{next_number}" in existing_names:
                next_number += 1
            name = f"label{next_number}"
            label = {
                "id": f"mapping-{self.operation_token}-{next_number}",
                "name": name,
                "kind": "navigation",
                "detail": "Dropped from the gamepad during mapping",
                "source": "mapping_gamepad",
                "world": {"x": world_x, "y": world_y},
                "yaw": float(pose.get("yaw") or 0.0),
            }
            self.pending_labels.append(label)
            self.label_event_sequence += 1
            self.last_label_event = {
                "sequence": self.label_event_sequence,
                "accepted": True,
                "name": name,
                "message": f"Dropped {name} at {world_x:.2f}, {world_y:.2f}.",
                "received_at": time.time(),
            }
            return dict(label)

    def record_label_error(self, message: str) -> None:
        with self.lock:
            self.label_event_sequence += 1
            self.last_label_event = {
                "sequence": self.label_event_sequence,
                "accepted": False,
                "name": None,
                "message": message,
                "received_at": time.time(),
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

    def mapping_ready(self) -> bool:
        nodes_result = self._run_cli(["ros2", "node", "list"])
        topics_result = self._run_cli(["ros2", "topic", "list"])
        if nodes_result is None or topics_result is None:
            return False
        nodes = {
            line.strip() for line in nodes_result.stdout.splitlines() if line.strip()
        }
        topics = {
            line.strip() for line in topics_result.stdout.splitlines() if line.strip()
        }
        required_nodes = {*self.REQUIRED_READY_NODES, "/joystickCommands"}
        if not required_nodes.issubset(nodes) or "/map" not in topics:
            return False
        preview = self._preview_status()
        return self.map_monitor is None or bool(preview.get("available"))

    def _begin_operation(self, state: str, stem: str, message: str) -> int:
        with self.lock:
            process_alive = self.process is not None and self.process.poll() is None
            if self.state not in {"stopped", "error"} or process_alive:
                raise NavigationConflictError(
                    f"Mapping manager is currently {self.state}; stop it first"
                )
            self.operation_token += 1
            token = self.operation_token
            self.stop_event = threading.Event()
            self.state = state
            self.reserved_stem = stem
            self.saved_map = None
            self.message = message
            self.error = ""
            self.last_exit_code = None
            self.started_at = time.time()
            self.pending_labels = []
            self.label_event_sequence = 0
            self.last_label_event = None
            return token

    def _set_state(
        self,
        token: int,
        state: str,
        message: str,
        *,
        error: str = "",
        clear_reserved: bool = False,
    ) -> bool:
        with self.lock:
            if token != self.operation_token:
                return False
            self.state = state
            self.message = message
            self.error = error
            if clear_reserved:
                self.reserved_stem = None
            return True

    def _spawn(self, token: int, command: list[str], *, save_process: bool = False):
        with self.lock:
            if token != self.operation_token or self.stop_event.is_set():
                raise RuntimeError("Mapping operation was stopped")
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
                NavigationManager._terminate_process_group(process)
                raise RuntimeError("Mapping operation was stopped")
            if save_process:
                self.save_process = process
            else:
                self.process = process
        return process

    def _clear_process(self, process, *, save_process: bool = False) -> None:
        with self.lock:
            attribute = "save_process" if save_process else "process"
            if getattr(self, attribute) is process:
                setattr(self, attribute, None)

    def start(self, name: str) -> dict:
        stem = safe_new_map_stem(name)
        collisions = map_name_collisions(self.maps_dir, stem)
        if collisions:
            raise ValueError(
                "A map with that name already exists: "
                + ", ".join(path.name for path in collisions)
            )
        if not self.run_script.exists():
            raise RuntimeError(f"Mapping script not found: {self.run_script}")
        if not self.scan_filter_file.exists():
            raise RuntimeError(f"Scan filter file not found: {self.scan_filter_file}")

        self.coordinator.claim("mapping")
        try:
            conflicts = self.conflicting_nodes()
            if conflicts:
                raise NavigationConflictError(
                    "Robot or navigation nodes are already running: "
                    + ", ".join(conflicts)
                    + ". Stop Navigation before starting mapping."
                )
            needs_build = qbot_platform_build_required(
                self.repo_dir,
                self.navigation_setup,
            )
            state = "building" if needs_build else "starting"
            message = (
                "Building qbot_platform before mapping; details are in the terminal."
                if needs_build
                else f"Starting manual mapping for {stem}.pgm; details are in the terminal."
            )
            token = self._begin_operation(state, stem, message)
            if self.map_monitor is not None and hasattr(
                self.map_monitor, "clear_mapping_map"
            ):
                self.map_monitor.clear_mapping_map()
        except Exception:
            self.coordinator.release("mapping")
            raise

        worker = threading.Thread(
            target=self._start_worker,
            args=(token, needs_build),
            name="qbot-mapping-start",
            daemon=True,
        )
        with self.lock:
            self.worker = worker
        worker.start()
        return self.snapshot()

    def _start_worker(self, token: int, needs_build: bool) -> None:
        process = None
        try:
            if needs_build:
                if not self.rebuild_script.exists():
                    raise RuntimeError(f"Rebuild script not found: {self.rebuild_script}")
                process = self._spawn(token, [str(self.rebuild_script)])
                return_code = int(process.wait())
                self._clear_process(process)
                process = None
                if self.stop_event.is_set():
                    self._set_state(
                        token,
                        "stopped",
                        "Mapping startup was canceled.",
                        clear_reserved=True,
                    )
                    return
                if return_code != 0:
                    raise RuntimeError(
                        f"qbot_platform build failed with status {return_code}; check the terminal"
                    )
                if not self.navigation_setup.exists():
                    raise RuntimeError(
                        "Build finished but robot_navigation/install/setup.bash was not created"
                    )
                if qbot_platform_build_required(self.repo_dir, self.navigation_setup):
                    raise RuntimeError(
                        "Build finished but the qbot_platform source stamp was not updated"
                    )
                self._set_state(
                    token,
                    "starting",
                    f"Starting manual mapping for {self.reserved_stem}.pgm; details are in the terminal.",
                )

            command = [
                str(self.run_script),
                "--scan-filter-file",
                str(self.scan_filter_file),
                "--resolution",
                "0.01",
                "--publish-period",
                "1.0",
                "--label-topic",
                self.mapping_label_topic,
                "--label-button-bit",
                str(self.mapping_label_button_bit),
            ]
            process = self._spawn(token, command)
            deadline = time.monotonic() + self.readiness_timeout
            while time.monotonic() < deadline:
                return_code = process.poll()
                if return_code is not None:
                    self.last_exit_code = int(return_code)
                    raise RuntimeError(
                        f"Mapping exited with status {return_code} before becoming ready; check the terminal"
                    )
                if self.stop_event.is_set():
                    NavigationManager._terminate_process_group(process)
                    break
                if self.mapping_ready():
                    self._set_state(
                        token,
                        "mapping",
                        f"Mapping {self.reserved_stem}.pgm. Drive with the gamepad and release LB to stop motion.",
                    )
                    return_code = int(process.wait())
                    self.last_exit_code = return_code
                    self._clear_process(process)
                    process = None
                    if self.stop_event.is_set():
                        with self.lock:
                            saved_map = self.saved_map
                        self._set_state(
                            token,
                            "stopped",
                            (
                                f"Saved {saved_map} and stopped mapping."
                                if saved_map
                                else "Mapping was canceled without saving."
                            ),
                            clear_reserved=True,
                        )
                    else:
                        raise RuntimeError(
                            f"Mapping exited unexpectedly with status {return_code}; check the terminal"
                        )
                    return
                time.sleep(self.probe_interval)

            if self.stop_event.is_set():
                if process is not None and process.poll() is None:
                    NavigationManager._terminate_process_group(process)
                if process is not None:
                    self._clear_process(process)
                self._set_state(
                    token,
                    "stopped",
                    "Mapping startup was canceled.",
                    clear_reserved=True,
                )
                return
            raise RuntimeError(
                f"Mapping did not become ready within {self.readiness_timeout:g} seconds; check the terminal"
            )
        except Exception as exc:
            if process is not None and process.poll() is None:
                NavigationManager._terminate_process_group(process)
            if process is not None:
                self._clear_process(process)
            if self.stop_event.is_set():
                self._set_state(
                    token,
                    "stopped",
                    "Mapping was canceled without saving.",
                    clear_reserved=True,
                )
            else:
                self._set_state(
                    token,
                    "error",
                    str(exc),
                    error=str(exc),
                    clear_reserved=True,
                )
        finally:
            with self.lock:
                if token == self.operation_token:
                    self.worker = None
                    inactive = self.state in {"stopped", "error"}
                else:
                    inactive = False
            if inactive:
                self.coordinator.release("mapping")
                self._clear_preview()

    def finish(self) -> dict:
        with self.lock:
            if self.state != "mapping" or self.process is None:
                raise NavigationConflictError(
                    "Mapping must be running before it can be saved"
                )
            if self.save_worker is not None and self.save_worker.is_alive():
                raise NavigationConflictError("A map save is already in progress")
            token = self.operation_token
            stem = self.reserved_stem
            self.state = "saving"
            self.message = f"Saving {stem}.pgm; details are in the terminal."
            self.error = ""
        worker = threading.Thread(
            target=self._finish_worker,
            args=(token, stem),
            name="qbot-mapping-save",
            daemon=True,
        )
        with self.lock:
            self.save_worker = worker
        worker.start()
        return self.snapshot()

    def _finish_worker(self, token: int, stem: str) -> None:
        staging_dir = None
        save_process = None
        try:
            self.maps_dir.mkdir(parents=True, exist_ok=True)
            staging_dir = Path(
                tempfile.mkdtemp(prefix=f".{stem}.mapping-", dir=self.maps_dir)
            )
            with self.lock:
                self.staging_dir = staging_dir
            prefix = staging_dir / stem
            command = [
                "ros2",
                "run",
                "nav2_map_server",
                "map_saver_cli",
                "-t",
                "/map",
                "-f",
                str(prefix),
            ]
            save_process = self._spawn(token, command, save_process=True)
            try:
                return_code = int(save_process.wait(timeout=self.save_timeout))
            except subprocess.TimeoutExpired as exc:
                NavigationManager._terminate_process_group(save_process)
                raise RuntimeError(
                    f"Map save timed out after {self.save_timeout:g} seconds"
                ) from exc
            self._clear_process(save_process, save_process=True)
            save_process = None
            if self.stop_event.is_set():
                return
            if return_code != 0:
                raise RuntimeError(
                    f"Map saver exited with status {return_code}; mapping is still running"
                )

            with self.commit_lock:
                if self.stop_event.is_set():
                    return
                with self.lock:
                    pending_labels = [dict(label) for label in self.pending_labels]
                with self.maps_lock:
                    saved_name = self._commit_staged_map(
                        staging_dir,
                        stem,
                        pending_labels,
                    )
                with self.lock:
                    if token != self.operation_token:
                        raise RuntimeError("Mapping session changed during the save")
                    self.saved_map = saved_name
                    self.state = "stopping"
                    self.message = f"Saved {saved_name}; stopping Cartographer."
                    self.error = ""
                    stack_process = self.process
                    self.stop_event.set()
            if stack_process is not None:
                NavigationManager._terminate_process_group(stack_process)
        except Exception as exc:
            if save_process is not None and save_process.poll() is None:
                NavigationManager._terminate_process_group(save_process)
            if save_process is not None:
                self._clear_process(save_process, save_process=True)
            if not self.stop_event.is_set():
                self._set_state(
                    token,
                    "mapping",
                    f"Save failed: {exc}. Mapping is still running; retry or cancel.",
                    error=str(exc),
                )
        finally:
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)
            with self.lock:
                if self.staging_dir == staging_dir:
                    self.staging_dir = None
                if token == self.operation_token:
                    self.save_worker = None

    def _commit_staged_map(
        self,
        staging_dir: Path,
        stem: str,
        pending_labels: list[dict] | None = None,
    ) -> str:
        initial_collisions = map_name_collisions(self.maps_dir, stem)
        if initial_collisions:
            raise RuntimeError(
                "Map files already exist; refusing to overwrite: "
                + ", ".join(path.name for path in initial_collisions)
            )
        staged_pgm, staged_yaml, staged_labels = map_artifact_paths(
            staging_dir, stem
        )
        if not staged_pgm.exists() or not staged_yaml.exists():
            raise RuntimeError("Map saver did not create both PGM and YAML files")
        normalize_saved_map_yaml(staged_yaml, staged_pgm.name)
        validate_navigation_map(staged_pgm)
        write_labels(
            staged_pgm,
            pending_labels or [],
            output_path=staged_labels,
            output_map_name=f"{stem}.pgm",
        )

        collisions = map_name_collisions(self.maps_dir, stem)
        if collisions:
            raise RuntimeError(
                "Map files appeared while mapping was active; refusing to overwrite: "
                + ", ".join(path.name for path in collisions)
            )
        final_pgm, final_yaml, final_labels = map_artifact_paths(self.maps_dir, stem)
        placed: list[Path] = []
        try:
            for source, destination in (
                (staged_pgm, final_pgm),
                (staged_labels, final_labels),
                (staged_yaml, final_yaml),
            ):
                # Hard-linking on this same filesystem is atomic and fails if
                # the destination appeared after the collision check. Unlike
                # os.replace(), it can never overwrite an operator's map.
                os.link(source, destination)
                placed.append(destination)
                source.unlink()
            try:
                directory_fd = os.open(self.maps_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except Exception:
            for path in reversed(placed):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            raise
        return final_pgm.name

    def cancel(self, *, force: bool = False) -> dict:
        with self.lock:
            if self.state == "saving" and not force:
                raise NavigationConflictError(
                    "The map is being saved; wait for it to finish before canceling"
                )
        self.commit_lock.acquire()
        try:
            return self._cancel_locked()
        finally:
            self.commit_lock.release()

    def _cancel_locked(self) -> dict:
        with self.lock:
            if self.state in {"stopped", "error"} and (
                self.process is None or self.process.poll() is not None
            ):
                self.state = "stopped"
                self.reserved_stem = None
                self.error = ""
                self.message = "Mapping is already stopped."
                self.pending_labels = []
                self.last_label_event = None
                self.coordinator.release("mapping")
                self._clear_preview()
                return self.snapshot()
            token = self.operation_token
            self.stop_event.set()
            self.state = "stopping"
            self.message = "Canceling mapping without saving."
            save_process = self.save_process
            stack_process = self.process
        thread = threading.Thread(
            target=self._cancel_worker,
            args=(token, save_process, stack_process),
            name="qbot-mapping-cancel",
            daemon=True,
        )
        thread.start()
        return self.snapshot()

    def _cancel_worker(self, token: int, save_process, stack_process) -> None:
        if save_process is not None:
            NavigationManager._terminate_process_group(save_process)
            self._clear_process(save_process, save_process=True)
        if stack_process is not None:
            NavigationManager._terminate_process_group(stack_process)
            self._clear_process(stack_process)
        with self.lock:
            staging_dir = self.staging_dir
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        self._set_state(
            token,
            "stopped",
            "Mapping was canceled without saving.",
            clear_reserved=True,
        )
        with self.lock:
            self.pending_labels = []
            self.last_label_event = None
        self.coordinator.release("mapping")
        self._clear_preview()

    def _clear_preview(self) -> None:
        if self.map_monitor is not None and hasattr(
            self.map_monitor, "clear_mapping_map"
        ):
            self.map_monitor.clear_mapping_map()

    def preview(self, after_revision: int, max_edge: int) -> dict | None:
        if self.map_monitor is None or not hasattr(
            self.map_monitor, "mapping_map_preview"
        ):
            return {
                "available": False,
                "revision": 0,
                "reason": "Live map monitor is unavailable",
            }
        return self.map_monitor.mapping_map_preview(after_revision, max_edge)

    def shutdown(self) -> None:
        self.cancel(force=True)
        with self.lock:
            workers = [self.save_worker, self.worker]
        for worker in workers:
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=24.0)


class RobotPoseMonitor:
    """Keep AMCL, navigation results, and live Cartographer map data available."""

    def __init__(
        self,
        topic: str = "/amcl_pose",
        navigation_status_topic: str = "/robot/navigation_status",
        mapping_pose_topic: str = "/tracked_pose",
        mapping_drop_topic: str = "/mapping/drop_label",
    ) -> None:
        self.topic = topic
        self.navigation_status_topic = navigation_status_topic
        self.mapping_pose_topic = mapping_pose_topic
        self.mapping_drop_topic = mapping_drop_topic
        self.lock = threading.Lock()
        self.pose: dict | None = None
        self.mapping_pose: dict | None = None
        self.navigation_event: dict | None = None
        self.navigation_sequence = 0
        self.mapping_map = None
        self.mapping_map_revision = 0
        self.mapping_preview_cache: dict | None = None
        self.error = ""
        self.node = None
        self.subscription = None
        self.navigation_status_subscription = None
        self.mapping_map_subscription = None
        self.mapping_pose_subscription = None
        self.mapping_drop_subscription = None
        self.mapping_manager = None
        self.navigation_manager = None
        self.thread: threading.Thread | None = None

    def connect_managers(
        self,
        navigation_manager=None,
        mapping_manager=None,
    ) -> None:
        self.navigation_manager = navigation_manager
        self.mapping_manager = mapping_manager

    def start(self, ros_domain_id: int) -> None:
        if (
            rclpy is None
            or PoseStamped is None
            or PoseWithCovarianceStamped is None
            or OccupancyGrid is None
            or RosEmpty is None
            or RosString is None
        ):
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
            self.navigation_status_subscription = self.node.create_subscription(
                RosString,
                self.navigation_status_topic,
                self.navigation_status_callback,
                10,
            )
            map_qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self.mapping_map_subscription = self.node.create_subscription(
                OccupancyGrid,
                "/map",
                self.mapping_map_callback,
                map_qos,
            )
            self.mapping_pose_subscription = self.node.create_subscription(
                PoseStamped,
                self.mapping_pose_topic,
                self.mapping_pose_callback,
                10,
            )
            self.mapping_drop_subscription = self.node.create_subscription(
                RosEmpty,
                self.mapping_drop_topic,
                self.mapping_drop_callback,
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

    @staticmethod
    def navigation_outcome(status: int | None, event: str) -> str:
        if event in {"started", "running"} or status in {1, 2, 3}:
            return "running"
        if status == 4:
            return "succeeded"
        if status == 5:
            return "canceled"
        return "failed"

    def _store_navigation_event(self, payload: dict) -> dict:
        event = str(payload.get("event") or "finished").strip().casefold()
        if event == "started":
            normalized_event = "running"
        elif event in {"running", "finished"}:
            normalized_event = event
        else:
            normalized_event = "finished"
        raw_status = payload.get("status")
        try:
            status = int(raw_status) if raw_status is not None else None
        except (TypeError, ValueError):
            status = None
        with self.lock:
            previous = self.navigation_event or {}
            same_goal = (
                str(previous.get("name") or "").casefold()
                == str(payload.get("name") or "").casefold()
            )
            self.navigation_sequence += 1
            stored = {
                "available": True,
                "sequence": self.navigation_sequence,
                "event": normalized_event,
                "outcome": self.navigation_outcome(status, normalized_event),
                "status": status,
                "name": payload.get("name"),
                "label": payload.get("label") or payload.get("name"),
                "kind": payload.get("kind"),
                "detail": payload.get("detail"),
                "message": payload.get("message"),
                "map": payload.get("map") or (previous.get("map") if same_goal else None),
                "label_id": payload.get("label_id") or (previous.get("label_id") if same_goal else None),
                "received_at": time.time(),
            }
            self.navigation_event = stored
            return dict(stored)

    def navigation_status_callback(self, message) -> None:
        try:
            payload = json.loads(message.data)
            if not isinstance(payload, dict):
                raise ValueError("navigation status must be a JSON object")
            event = self._store_navigation_event(payload)
            manager = self.navigation_manager
            if manager is not None and hasattr(manager, "handle_navigation_event"):
                manager.handle_navigation_event(event, self.snapshot())
        except Exception as exc:
            print(f"WARNING: Ignoring invalid {self.navigation_status_topic} message: {exc}")

    def mapping_pose_callback(self, message) -> None:
        pose = message.pose
        orientation = pose.orientation
        yaw = math.atan2(
            2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
            1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
        )
        with self.lock:
            self.mapping_pose = {
                "frame_id": message.header.frame_id or "map",
                "world": {
                    "x": float(pose.position.x),
                    "y": float(pose.position.y),
                },
                "yaw": yaw,
                "received_at": time.time(),
            }

    def mapping_drop_callback(self, _message) -> None:
        manager = self.mapping_manager
        if manager is None or not hasattr(manager, "drop_label"):
            return
        try:
            manager.drop_label(self.mapping_pose_snapshot())
        except Exception as exc:
            if hasattr(manager, "record_label_error"):
                manager.record_label_error(str(exc))

    def mapping_map_callback(self, message) -> None:
        width = int(message.info.width)
        height = int(message.info.height)
        if width <= 0 or height <= 0 or len(message.data) != width * height:
            return
        orientation = message.info.origin.orientation
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
        with self.lock:
            self.mapping_map_revision += 1
            self.mapping_preview_cache = None
            self.mapping_map = {
                "width": width,
                "height": height,
                "resolution": float(message.info.resolution),
                "origin": [
                    float(message.info.origin.position.x),
                    float(message.info.origin.position.y),
                    yaw,
                ],
                # Keep the received ROS message alive instead of duplicating a
                # potentially very large occupancy array on every publication.
                "data": message.data,
                "received_at": time.time(),
                "revision": self.mapping_map_revision,
            }

    def clear_mapping_map(self) -> None:
        with self.lock:
            self.mapping_map = None
            self.mapping_pose = None
            self.mapping_map_revision += 1
            self.mapping_preview_cache = None

    def mapping_pose_snapshot(self) -> dict:
        with self.lock:
            if self.mapping_pose is None:
                return {
                    "available": False,
                    "topic": self.mapping_pose_topic,
                    "reason": f"Waiting for the first message on {self.mapping_pose_topic}",
                }
            pose = {
                **self.mapping_pose,
                "world": dict(self.mapping_pose["world"]),
            }
        age = max(0.0, time.time() - float(pose["received_at"]))
        return {
            "available": True,
            "topic": self.mapping_pose_topic,
            "age_seconds": age,
            "stale": age > 2.0,
            **pose,
        }

    def mapping_map_snapshot(self) -> dict:
        with self.lock:
            if self.mapping_map is None:
                return {
                    "available": False,
                    "revision": self.mapping_map_revision,
                }
            revision = int(self.mapping_map["revision"])
            received_at = float(self.mapping_map["received_at"])
            width = int(self.mapping_map["width"])
            height = int(self.mapping_map["height"])
        return {
            "available": True,
            "revision": revision,
            "source_width": width,
            "source_height": height,
            "age_seconds": max(0.0, time.time() - received_at),
        }

    def mapping_map_preview(
        self, after_revision: int = 0, max_edge: int = 1200
    ) -> dict | None:
        if max_edge < 64:
            raise ValueError("Preview maximum edge must be at least 64 pixels")
        with self.lock:
            if self.mapping_map is None:
                return {
                    "available": False,
                    "revision": self.mapping_map_revision,
                    "reason": "Waiting for Cartographer's first /map message",
                }
            if (
                self.mapping_preview_cache is not None
                and self.mapping_preview_cache.get("revision")
                == self.mapping_map.get("revision")
                and self.mapping_preview_cache.get("max_edge") == max_edge
            ):
                cached = self.mapping_preview_cache["payload"]
                if int(after_revision) >= int(cached["revision"]):
                    return None
                return dict(cached)
            source = dict(self.mapping_map)
        revision = int(source["revision"])
        if int(after_revision) >= revision:
            return None

        source_width = int(source["width"])
        source_height = int(source["height"])
        step = max(1, math.ceil(max(source_width, source_height) / max_edge))
        width = math.ceil(source_width / step)
        height = math.ceil(source_height / step)
        data = source["data"]
        pixels = bytearray(width * height)
        output_index = 0
        for output_y in range(height):
            source_y = source_height - 1 - min(output_y * step, source_height - 1)
            row_offset = source_y * source_width
            for output_x in range(width):
                occupancy = int(data[row_offset + min(output_x * step, source_width - 1)])
                if occupancy < 0:
                    value = 205
                else:
                    value = round(255 * (100 - min(100, occupancy)) / 100)
                pixels[output_index] = value
                output_index += 1
        payload = {
            "available": True,
            "revision": revision,
            "width": width,
            "height": height,
            "source_width": source_width,
            "source_height": source_height,
            "step": step,
            "pixels": base64.b64encode(pixels).decode(),
            "meta": {
                "resolution": float(source["resolution"]),
                "origin": list(source["origin"]),
            },
            "age_seconds": max(0.0, time.time() - float(source["received_at"])),
        }
        with self.lock:
            if (
                self.mapping_map is not None
                and self.mapping_map.get("revision") == revision
            ):
                self.mapping_preview_cache = {
                    "revision": revision,
                    "max_edge": max_edge,
                    "payload": payload,
                }
        return payload

    def goal_started(self, label: dict, map_name: str) -> dict:
        return self._store_navigation_event(
            {
                "event": "running",
                "status": 2,
                "name": label.get("name"),
                "label": label.get("name"),
                "kind": label.get("kind"),
                "detail": label.get("detail"),
                "map": map_name,
                "label_id": label.get("id"),
            }
        )

    def goal_publish_failed(self, label: dict, map_name: str, message: str) -> dict:
        return self._store_navigation_event(
            {
                "event": "finished",
                "status": 6,
                "name": label.get("name"),
                "label": label.get("name"),
                "kind": label.get("kind"),
                "detail": label.get("detail"),
                "map": map_name,
                "label_id": label.get("id"),
                "message": message,
            }
        )

    def interrupt_active_goal(self, message: str) -> dict | None:
        with self.lock:
            active = dict(self.navigation_event) if self.navigation_event else None
        if active is None or active.get("event") != "running":
            return None
        return self._store_navigation_event(
            {
                **active,
                "event": "finished",
                "status": 5,
                "message": message,
            }
        )

    def navigation_snapshot(self) -> dict:
        with self.lock:
            if self.navigation_event is None:
                return {
                    "available": False,
                    "topic": self.navigation_status_topic,
                    "sequence": self.navigation_sequence,
                    "event": "idle",
                    "outcome": "idle",
                }
            event = dict(self.navigation_event)
        return {
            **event,
            "topic": self.navigation_status_topic,
            "age_seconds": max(0.0, time.time() - event["received_at"]),
        }

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
        self.navigation_status_subscription = None
        self.mapping_map_subscription = None
        self.mapping_pose_subscription = None
        self.mapping_drop_subscription = None
        self.thread = None


class Handler(BaseHTTPRequestHandler):
    server_version = "MapLabelGUI/4.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def write_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode()
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "").casefold()
        use_gzip = accepts_gzip and len(body) >= 1024
        if use_gzip:
            body = gzip.compress(body, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
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
        validate_navigation_map(map_path)
        return map_path

    def navigation_manager(self) -> NavigationManager | None:
        return getattr(self.server, "navigation_manager", None)

    def mapping_manager(self) -> MappingManager | None:
        return getattr(self.server, "mapping_manager", None)

    def goal_monitor(self):
        monitor = getattr(self.server, "pose_monitor", None)
        if monitor is None or not hasattr(monitor, "navigation_snapshot"):
            return None
        return monitor

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

    def require_map_files_idle(self) -> None:
        navigation = self.navigation_manager()
        mapping = self.mapping_manager()
        navigation_status = navigation.snapshot() if navigation is not None else {}
        mapping_status = mapping.snapshot() if mapping is not None else {}
        if navigation_status.get("managed_process") or navigation_status.get("state") not in {
            None,
            "stopped",
            "error",
        }:
            raise NavigationConflictError("Stop Navigation before deleting a map")
        if mapping_status.get("managed_process") or mapping_status.get("state") not in {
            None,
            "stopped",
            "error",
        }:
            raise NavigationConflictError("Finish or cancel mapping before deleting a map")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.write_text(INDEX_HTML, "text/html")
            elif parsed.path == "/api/maps":
                self.write_json(
                    {"maps": [{"name": path.name} for path in discover_maps(MAPS_DIR)]}
                )
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
                    monitor = self.goal_monitor()
                    if hasattr(manager, "reconcile_localization"):
                        manager.reconcile_localization(
                            monitor.snapshot() if monitor is not None else None
                        )
                    navigation_status = manager.snapshot()
                    if navigation_status["state"] in {"stopped", "error"}:
                        monitor = self.goal_monitor()
                        if monitor is not None:
                            monitor.interrupt_active_goal(
                                "Navigation stack stopped before the goal finished"
                            )
                    self.write_json(navigation_status)
            elif parsed.path == "/api/navigation/goal-status":
                monitor = self.goal_monitor()
                if monitor is None:
                    self.write_json(
                        {
                            "available": False,
                            "topic": "/robot/navigation_status",
                            "sequence": 0,
                            "event": "idle",
                            "outcome": "idle",
                            "reason": "Navigation result monitor is not configured",
                        }
                    )
                else:
                    self.write_json(monitor.navigation_snapshot())
            elif parsed.path == "/api/mapping/status":
                manager = self.mapping_manager()
                if manager is None:
                    self.write_json(
                        {
                            "state": "error",
                            "reserved_map": None,
                            "ready": False,
                            "message": "Mapping manager is not configured",
                            "error": "Mapping manager is not configured",
                            "managed_process": False,
                            "preview_available": False,
                            "preview_revision": 0,
                            "saved_map": None,
                        },
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                else:
                    self.write_json(manager.snapshot())
            elif parsed.path == "/api/mapping/preview":
                manager = self.mapping_manager()
                if manager is None:
                    raise RuntimeError("Mapping manager is not configured")
                query = parse_qs(parsed.query)
                after_revision = int(query.get("after", ["0"])[0])
                max_edge = int(getattr(self.server, "mapping_preview_max_edge", 1200))
                preview = manager.preview(after_revision, max_edge)
                if preview is None:
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                else:
                    self.write_json(preview)
            else:
                self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.write_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/maps/delete":
                data = self.read_json_body()
                navigation = self.navigation_manager()
                mapping = self.mapping_manager()
                coordinator = getattr(navigation, "coordinator", None) or getattr(
                    mapping, "coordinator", None
                )
                if coordinator is not None:
                    coordinator.claim("map deletion")
                try:
                    self.require_map_files_idle()
                    map_path = self.resolve_map(str(data.get("map", "")))
                    confirmation = str(data.get("confirmation", ""))
                    maps_lock = getattr(self.server, "maps_lock", None)
                    if maps_lock is None:
                        maps_lock = threading.RLock()
                    with maps_lock:
                        destination, moved = trash_map_artifacts(
                            map_path,
                            confirmation,
                        )
                        remaining = [path.name for path in discover_maps(MAPS_DIR)]
                    try:
                        trash_display = str(destination.relative_to(ROOT))
                    except ValueError:
                        trash_display = str(destination)
                finally:
                    if coordinator is not None:
                        coordinator.release("map deletion")
                self.write_json(
                    {
                        "deleted_map": map_path.name,
                        "trash": trash_display,
                        "files": [path.name for path in moved],
                        "remaining_maps": remaining,
                    }
                )
            elif self.path == "/api/labels":
                data = self.read_json_body()
                map_path = self.resolve_map(str(data.get("map", "")))
                maps_lock = getattr(self.server, "maps_lock", None)
                if maps_lock is None:
                    maps_lock = threading.RLock()
                with maps_lock:
                    path, labels = write_labels(map_path, data.get("labels", []))
                self.write_json({"file": str(path.relative_to(ROOT)), "count": len(labels), "labels": labels})
            elif self.path == "/api/go":
                data = self.read_json_body()
                map_path = self.resolve_map(str(data.get("map", "")))
                self.require_navigation_map(map_path.name)
                manager = self.navigation_manager()
                monitor = self.goal_monitor()
                if manager is not None and hasattr(manager, "require_localized"):
                    manager.require_localized(
                        monitor.snapshot() if monitor is not None else None
                    )
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
                if monitor is not None:
                    current_goal = monitor.navigation_snapshot()
                    if current_goal.get("event") == "running":
                        raise NavigationConflictError(
                            f"Already navigating to {current_goal.get('label') or current_goal.get('name') or 'another goal'}"
                        )
                    monitor.goal_started(label, map_path.name)
                with self.server.navigation_lock:
                    stop_generation = self.server.stop_generation
                try:
                    publish_label(
                        label["name"],
                        topic,
                        float(getattr(self.server, "go_timeout", 10)),
                        ros_domain_id,
                    )
                except Exception as exc:
                    if monitor is not None:
                        monitor.goal_publish_failed(label, map_path.name, str(exc))
                    raise
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
                        "goal": monitor.navigation_snapshot() if monitor is not None else None,
                    }
                )
            elif self.path == "/api/stop":
                self.read_json_body()
                topic = str(getattr(self.server, "label_topic", "/label"))
                ros_domain_id = int(getattr(self.server, "ros_domain_id", 63))
                with self.server.navigation_lock:
                    self.server.stop_generation += 1
                manager = self.navigation_manager()
                if manager is not None and hasattr(manager, "fail_localization"):
                    manager.fail_localization("Localization was stopped")
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
                manager = self.navigation_manager()
                if manager is None:
                    raise RuntimeError("Navigation manager is not configured")
                topic = str(getattr(self.server, "label_topic", "/label"))
                ros_domain_id = int(getattr(self.server, "ros_domain_id", 63))
                if hasattr(manager, "begin_localization"):
                    manager.begin_localization()
                with self.server.navigation_lock:
                    stop_generation = self.server.stop_generation
                try:
                    publish_label(
                        "__localize__",
                        topic,
                        float(getattr(self.server, "go_timeout", 10)),
                        ros_domain_id,
                    )
                except Exception:
                    if hasattr(manager, "fail_localization"):
                        manager.fail_localization("Could not publish the localization command")
                    raise
                with self.server.navigation_lock:
                    cancelled_by_stop = self.server.stop_generation != stop_generation
                if cancelled_by_stop:
                    if hasattr(manager, "fail_localization"):
                        manager.fail_localization("Localization was stopped")
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
                monitor = self.goal_monitor()
                if monitor is not None:
                    monitor.interrupt_active_goal(
                        "A new navigation stack was started before the goal finished"
                    )
                self.write_json(manager.start(map_path), HTTPStatus.ACCEPTED)
            elif self.path == "/api/navigation/stop":
                self.read_json_body()
                manager = self.navigation_manager()
                if manager is None:
                    raise RuntimeError("Navigation manager is not configured")
                monitor = self.goal_monitor()
                if monitor is not None:
                    monitor.interrupt_active_goal("Navigation stack was stopped")
                self.write_json(manager.stop(), HTTPStatus.ACCEPTED)
            elif self.path == "/api/navigation/rebuild":
                self.read_json_body()
                manager = self.navigation_manager()
                if manager is None:
                    raise RuntimeError("Navigation manager is not configured")
                self.write_json(manager.rebuild(), HTTPStatus.ACCEPTED)
            elif self.path == "/api/mapping/start":
                data = self.read_json_body()
                manager = self.mapping_manager()
                if manager is None:
                    raise RuntimeError("Mapping manager is not configured")
                self.write_json(
                    manager.start(str(data.get("name", ""))),
                    HTTPStatus.ACCEPTED,
                )
            elif self.path == "/api/mapping/finish":
                self.read_json_body()
                manager = self.mapping_manager()
                if manager is None:
                    raise RuntimeError("Mapping manager is not configured")
                self.write_json(manager.finish(), HTTPStatus.ACCEPTED)
            elif self.path == "/api/mapping/cancel":
                self.read_json_body()
                manager = self.mapping_manager()
                if manager is None:
                    raise RuntimeError("Mapping manager is not configured")
                self.write_json(manager.cancel(), HTTPStatus.ACCEPTED)
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
    parser.add_argument(
        "--navigation-status-topic",
        default="/robot/navigation_status",
        help="ROS String topic containing navigation start/result events",
    )
    parser.add_argument(
        "--mapping-pose-topic",
        default="/tracked_pose",
        help="Cartographer PoseStamped topic shown during mapping",
    )
    parser.add_argument(
        "--mapping-drop-topic",
        default="/mapping/drop_label",
        help="ROS Empty topic used by the gamepad to drop mapping labels",
    )
    parser.add_argument(
        "--mapping-label-button-bit",
        type=int,
        default=1,
        help="Zero-based game-controller button bit used to drop a mapping label",
    )
    parser.add_argument("--go-timeout", type=float, default=10, help="Seconds to wait for the ROS label publication")
    parser.add_argument(
        "--navigation-timeout",
        type=float,
        default=120,
        help="Seconds to wait for AMCL and Nav2 to become ready",
    )
    parser.add_argument(
        "--mapping-timeout",
        type=float,
        default=120,
        help="Seconds to wait for Cartographer and its live map to become ready",
    )
    parser.add_argument(
        "--mapping-preview-max-edge",
        type=int,
        default=1200,
        help="Maximum width or height of the downsampled live mapping preview",
    )
    parser.add_argument(
        "--fixed-goal-tolerance",
        action="store_true",
        help="Keep Nav2's fixed 0.25 m XY tolerance instead of adapting to AMCL",
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
    if args.mapping_timeout <= 0:
        parser.error("--mapping-timeout must be positive")
    if args.mapping_preview_max_edge < 64:
        parser.error("--mapping-preview-max-edge must be at least 64")
    if not 0 <= args.mapping_label_button_bit <= 31:
        parser.error("--mapping-label-button-bit must be between 0 and 31")
    if not 0 <= args.ros_domain_id <= 232:
        parser.error("--ros-domain-id must be between 0 and 232")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.label_topic, server.go_timeout = args.label_topic, args.go_timeout
    server.ros_domain_id = args.ros_domain_id
    server.mapping_preview_max_edge = args.mapping_preview_max_edge
    server.maps_lock = threading.RLock()
    server.navigation_lock = threading.Lock()
    server.stop_generation = 0
    pose_monitor = RobotPoseMonitor(
        args.pose_topic,
        args.navigation_status_topic,
        args.mapping_pose_topic,
        args.mapping_drop_topic,
    )
    server.pose_monitor = pose_monitor
    coordinator = RobotOperationCoordinator()
    navigation_manager = NavigationManager(
        ros_domain_id=args.ros_domain_id,
        adaptive_goal_tolerance=not args.fixed_goal_tolerance,
        readiness_timeout=args.navigation_timeout,
        coordinator=coordinator,
    )
    server.navigation_manager = navigation_manager
    mapping_manager = MappingManager(
        map_monitor=pose_monitor,
        coordinator=coordinator,
        ros_domain_id=args.ros_domain_id,
        readiness_timeout=args.mapping_timeout,
        mapping_label_topic=args.mapping_drop_topic,
        mapping_label_button_bit=args.mapping_label_button_bit,
        maps_lock=server.maps_lock,
    )
    server.mapping_manager = mapping_manager

    pose_monitor.connect_managers(
        navigation_manager,
        mapping_manager,
    )
    pose_monitor.start(args.ros_domain_id)
    print(f"Map label GUI: http://{args.host}:{args.port}")
    print(f"Serving maps from: {MAPS_DIR}")
    print(f"Go publishes labels on: {args.label_topic}")
    print(f"Go uses ROS domain: {args.ros_domain_id}")
    print(f"Live robot pose topic: {args.pose_topic}")
    print(f"Navigation result topic: {args.navigation_status_topic}")
    print(f"Live mapping pose topic: {args.mapping_pose_topic}")
    print(f"Mapping label button topic: {args.mapping_drop_topic}")
    print(
        "Live mapping preview: /map, max edge "
        f"{args.mapping_preview_max_edge}px"
    )
    print(
        "Goal tolerance mode: "
        + ("fixed from Nav2 YAML" if args.fixed_goal_tolerance else "adaptive")
    )
    if pose_monitor.error:
        print(f"WARNING: {pose_monitor.error}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping map label GUI.")
    finally:
        server.server_close()
        mapping_manager.shutdown()
        navigation_manager.shutdown()
        pose_monitor.stop()


if __name__ == "__main__":
    main()
