const DATA_DIR = "../data/mock";
const MIN_PRESSURE = 15;
const MARGINAL_PRESSURE = 20;
const CURRENT_YEAR = 2026;
const DRAWING_SAMPLE_LIMIT = 100;

const PIPE_COLORS = {
  ok: "#2563eb",
  marginal: "#d97706",
  low: "#dc2626",
  leak: "#7c3aed",
  overpressure: "#111827",
};

const WATER_DENSITY_KG_M3 = 1000;
const GRAVITY_M_S2 = 9.80665;

const materialPressureModel = {
  PVC: { allowableStressMPa: 7.5, sdr: 17, floorHeadM: 45, capHeadM: 115 },
  HDPE: { allowableStressMPa: 8.0, sdr: 17, floorHeadM: 50, capHeadM: 125 },
  ductile_iron: { allowableStressMPa: 40, sdr: 55, floorHeadM: 80, capHeadM: 180 },
  concrete: { allowableStressMPa: 4.5, sdr: 13, floorHeadM: 35, capHeadM: 90 },
  steel: { allowableStressMPa: 55, sdr: 70, floorHeadM: 85, capHeadM: 190 },
  cast_iron: { allowableStressMPa: 18, sdr: 45, floorHeadM: 35, capHeadM: 95 },
  unknown: { allowableStressMPa: 7, sdr: 20, floorHeadM: 35, capHeadM: 90 },
};

const materialRisk = {
  PVC: 0.12,
  HDPE: 0.1,
  ductile_iron: 0.35,
  concrete: 0.42,
  steel: 0.62,
  cast_iron: 0.86,
  unknown: 0.5,
};

const designLife = {
  PVC: 75,
  HDPE: 80,
  ductile_iron: 80,
  concrete: 70,
  steel: 65,
  cast_iron: 75,
  unknown: 70,
};

const demandProfiles = {
  metro: {
    label: "대도시",
    multipliers: [0.52, 0.46, 0.42, 0.4, 0.48, 0.78, 1.18, 1.38, 1.26, 1.08, 1.0, 1.04, 1.12, 1.06, 0.98, 0.96, 1.05, 1.24, 1.42, 1.32, 1.12, 0.9, 0.72, 0.6],
  },
  midsize: {
    label: "중소도시",
    multipliers: [0.5, 0.44, 0.4, 0.38, 0.46, 0.72, 1.08, 1.28, 1.2, 1.04, 0.96, 1.0, 1.1, 1.04, 0.96, 0.94, 1.02, 1.18, 1.3, 1.2, 1.02, 0.84, 0.68, 0.58],
  },
  rural: {
    label: "농촌",
    multipliers: [0.42, 0.36, 0.34, 0.34, 0.44, 0.82, 1.3, 1.44, 1.18, 0.94, 0.84, 0.88, 0.98, 0.94, 0.9, 0.96, 1.12, 1.36, 1.48, 1.18, 0.9, 0.68, 0.54, 0.46],
  },
};

const weights = {
  age: 0.2,
  material: 0.16,
  repair: 0.13,
  leak_history: 0.15,
  geometry: 0.09,
  soil: 0.09,
  traffic: 0.08,
};

const state = {
  nodes: [],
  pipes: [],
  reservoirs: [],
  pumps: [],
  valves: [],
  households: [],
  demandSeries: [],
  demandProfile: "metro",
  initialData: null,
  demandByMinute: new Map(),
  timeline: [],
  pipeEdits: new Map(),
  leakDemands: new Map(),
  baseNodeGeometry: new Map(),
  originalNodeGeometry: new Map(),
  aging: new Map(),
  selected: null,
  editorTab: "source",
  addMode: false,
  pipeDrawMode: false,
  sourceDrawMode: false,
  pendingJunction: null,
  pendingPipe: null,
  pendingSource: null,
  mapFrame: null,
  mapZoom: 1,
  mapCenter: { x: 560, y: 325 },
  mapViewBox: { x: 0, y: 0, width: 1120, height: 650 },
  draggingNodeId: "",
  multiSelectedNodes: new Set(),
  multiSelectedPipes: new Set(),
  selectionBox: null,
  selectionMoved: false,
  bulkMove: null,
  playbackTimer: null,
  playbackSpeed: 1,
  drawingFile: null,
  drawingFileType: null,
  drawingImage: null,
  drawingAssets: null,
  drawingAssetsApplied: false,
  drawingRecognition: null,
  drawingPipeSamples: [],
  drawingJunctionSamples: [],
  drawingSourceSamples: [],
  drawingSampleMode: false,
  drawingJunctionMode: false,
  drawingSourceMode: false,
};

const $ = (id) => document.getElementById(id);

boot();

async function boot() {
  const [nodes, pipes, reservoirs, pumps, valves, households, demandSeries] = await Promise.all([
    loadCsv("nodes.csv"),
    loadCsv("pipes.csv"),
    loadCsv("reservoirs.csv"),
    loadCsv("pumps.csv"),
    loadCsv("valves.csv"),
    loadCsv("households.csv"),
    loadCsv("household_demand_timeseries.csv"),
  ]);

  Object.assign(state, { nodes, pipes, reservoirs, pumps, valves, households, demandSeries });
  state.initialData = {
    nodes: cloneRows(nodes),
    pipes: cloneRows(pipes),
    reservoirs: cloneRows(reservoirs),
    pumps: cloneRows(pumps),
    valves: cloneRows(valves),
    households: cloneRows(households),
    demandSeries: cloneRows(demandSeries),
  };
  state.baseNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.originalNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.aging = new Map(state.pipes.map((pipe) => [pipe.pipe_id, agingScore(pipe)]));
  buildDemandIndex();
  initControls();
  render();
  applyInjectedRecognitionAssets();
}

async function loadCsv(file) {
  try {
    const response = await fetch(`${DATA_DIR}/${file}`);
    if (!response.ok) throw new Error(`${file} load failed`);
    return parseCsv(await response.text());
  } catch {
    return fallbackData()[file] || [];
  }
}

function parseCsv(text) {
  const [headerLine, ...lines] = text.trim().split(/\r?\n/);
  const headers = headerLine.split(",");
  return lines
    .filter(Boolean)
    .map((line) => {
      const values = line.split(",");
      return Object.fromEntries(headers.map((key, index) => [key, parseValue(values[index])]));
    });
}

function parseValue(value) {
  if (value === undefined || value === "") return "";
  const number = Number(value);
  return Number.isFinite(number) && value.trim() !== "" ? number : value;
}

function cloneRows(rows) {
  return rows.map((row) => ({ ...row }));
}

function buildDemandIndex() {
  const householdToNode = new Map(state.households.map((row) => [row.household_id, row.node_id]));
  state.demandByMinute = new Map();

  for (const row of state.demandSeries) {
    const minute = minuteOfDay(row.timestamp);
    const node = householdToNode.get(row.household_id);
    if (!node) continue;
    if (!state.demandByMinute.has(minute)) state.demandByMinute.set(minute, new Map());
    const demand = state.demandByMinute.get(minute);
    demand.set(node, (demand.get(node) || 0) + Number(row.demand_lps || 0));
  }

  state.timeline = Array.from({ length: 24 * 6 }, (_, index) => index * 10);
}

function initControls() {
  initViewIndex();
  initDrawingRecognition();

  const slider = $("time-slider");
  slider.max = Math.max(state.timeline.length - 1, 0);
  slider.value = Math.min(42, state.timeline.length - 1);
  $("timeline-scale").innerHTML = ["00:00", "06:00", "12:00", "18:00", "24:00"].map((label) => `<span>${label}</span>`).join("");

  refreshAssetOptions();
  $("leak-pipe").value = state.pipes.some((pipe) => pipe.pipe_id === "P14") ? "P14" : state.pipes[0]?.pipe_id || "";
  $("selected-pipe").value = $("leak-pipe").value;
  $("selected-junction").value = firstJunctionId();
  $("source-junction").value = firstJunctionId();
  $("source-connect-junction").value = firstJunctionId();
  $("selected-source").value = firstSourceId();
  $("new-source-id").value = nextSourceId();

  const reservoirHead = Number(state.reservoirs[0]?.head_m || 58);
  const pump = state.pumps.find((item) => String(item.status || "on").toLowerCase() !== "off");
  $("source-head").value = reservoirHead;
  $("pump-head").value = pump ? Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1) : 0;
  $("source-design-head").value = reservoirHead;
  $("source-pump-gain").value = $("pump-head").value;
  syncSourceControlLabels();
  suggestSourcePumpPosition();

  ["time-slider", "demand-profile", "demand-scale", "source-head", "pump-head", "leak-pipe", "leak-demand"].forEach((id) => {
    $(id).addEventListener("input", render);
  });

  [
    "pipe-angle",
    "pipe-length",
    "pipe-diameter",
    "pipe-roughness",
    "pipe-minor-loss",
    "pipe-bend-angle",
    "pipe-bend-count",
    "pipe-valve-count",
    "pipe-material",
    "pipe-service-type",
  ].forEach((id) => {
    $(id).addEventListener("input", updatePipeEditFromControls);
  });
  ["junction-x", "junction-y", "junction-elevation", "junction-demand", "junction-dma"].forEach((id) => {
    $(id).addEventListener("input", updateJunctionEditFromControls);
  });
  ["source-design-head", "source-pump-gain", "source-pipe-diameter", "source-pipe-roughness", "source-x", "source-y", "source-pipe-length"].forEach((id) => {
    $(id).addEventListener("input", updateSourceEditFromControls);
  });

  document.querySelectorAll("[data-angle]").forEach((button) => {
    button.addEventListener("click", () => {
      $("pipe-angle").value = button.dataset.angle;
      updatePipeEditFromControls();
    });
  });

  document.querySelectorAll(".speed-button").forEach((button) => {
    button.addEventListener("click", () => setPlaybackSpeed(Number(button.dataset.speed)));
  });
  document.querySelectorAll("[data-editor-tab]").forEach((button) => {
    button.addEventListener("click", () => setEditorTab(button.dataset.editorTab));
  });

  $("map-zoom-in").addEventListener("click", () => zoomMap(1.25));
  $("map-zoom-out").addEventListener("click", () => zoomMap(0.8));
  $("map-zoom-reset").addEventListener("click", resetMapZoom);
  $("play-toggle").addEventListener("click", togglePlayback);
  $("reset-scenario").addEventListener("click", resetScenario);
  $("add-leak-pipe").addEventListener("click", () => addLeakPipe($("leak-pipe").value, Number($("leak-demand").value || 0)));
  $("reset-pipe-edit").addEventListener("click", resetSelectedPipeEdit);
  $("add-junction-mode").addEventListener("click", enterAddJunctionMode);
  $("draw-pipe-mode").addEventListener("click", enterPipeDrawMode);
  $("cancel-junction").addEventListener("click", cancelAddJunctionMode);
  $("confirm-junction").addEventListener("click", confirmPendingJunction);
  $("confirm-pipe").addEventListener("click", confirmPendingPipe);
  $("delete-pipe").addEventListener("click", deleteSelectedPipe);
  $("delete-junction").addEventListener("click", deleteSelectedJunction);
  $("reset-junction-edit").addEventListener("click", resetSelectedJunctionEdit);
  $("bulk-delete").addEventListener("click", deleteBulkSelection);
  $("bulk-analyze").addEventListener("click", analyzeBulkSelection);
  $("bulk-apply-pipes").addEventListener("click", applyBulkPipeProperties);
  $("bulk-apply-junctions").addEventListener("click", applyBulkJunctionProperties);
  $("add-source-pump").addEventListener("click", addSourcePump);
  $("delete-source-pump").addEventListener("click", deleteSelectedSourcePump);
  $("source-junction").addEventListener("input", () => {
    if (state.addMode || state.pipeDrawMode) {
      state.pendingJunction = null;
      state.pendingPipe = null;
      updateDrawReadout();
      render();
    }
  });
  $("source-connect-junction").addEventListener("input", suggestSourcePumpPosition);
  $("selected-source").addEventListener("input", () => selectSourcePump($("selected-source").value));
  $("selected-pipe").addEventListener("input", () => selectPipe($("selected-pipe").value));
  $("selected-junction").addEventListener("input", () => selectNode($("selected-junction").value));
  $("pipe-tool").addEventListener("click", () => selectPipe($("selected-pipe").value));
  $("junction-tool").addEventListener("click", () => selectNode($("selected-junction").value));
  $("set-leak-pipe").addEventListener("click", () => {
    $("leak-pipe").value = $("selected-pipe").value;
    addLeakPipe($("selected-pipe").value, Number($("leak-demand").value || 0));
    selectPipe($("selected-pipe").value);
  });

  state.selected = `pipe:${$("selected-pipe").value}`;
  syncPipeEditor();
}

function initViewIndex() {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => setAppView(button.dataset.viewTarget));
  });
}

function setAppView(view) {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewTarget === view);
  });
  document.querySelectorAll("[data-view]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.view === view);
  });
}

function initDrawingRecognition() {
  $("drawing-file").addEventListener("change", handleDrawingFile);
  ["drawing-min-line", "drawing-merge-tolerance"].forEach((id) => {
    $(id).addEventListener("input", () => {
      $("drawing-min-line-value").textContent = `${$("drawing-min-line").value} px`;
      $("drawing-merge-tolerance-value").textContent = `${$("drawing-merge-tolerance").value} px`;
    });
  });
  ["drawing-scale", "drawing-diameter", "drawing-material"].forEach((id) => {
    $(id).addEventListener("input", () => {
      if (state.drawingRecognition && state.drawingAssets) renderDrawingRecognition(state.drawingAssets);
    });
  });
  $("analyze-drawing").addEventListener("click", analyzeDrawingImage);
  $("apply-recognition-assets").addEventListener("click", applyCurrentRecognitionAssets);
  $("reset-drawing").addEventListener("click", resetDrawingRecognition);
  $("drawing-canvas").addEventListener("click", handleDrawingCanvasClick);
  $("pipe-sample-mode").addEventListener("click", togglePipeSampleMode);
  $("clear-pipe-samples").addEventListener("click", clearPipeSamples);
  $("junction-sample-mode").addEventListener("click", toggleJunctionSampleMode);
  $("clear-junction-samples").addEventListener("click", clearJunctionSamples);
  $("source-sample-mode").addEventListener("click", toggleSourceSampleMode);
  $("clear-source-samples").addEventListener("click", clearSourceSamples);
  $("download-assets-json").addEventListener("click", () => downloadRecognitionAsset("json"));
  $("download-nodes-csv").addEventListener("click", () => downloadRecognitionAsset("nodes"));
  $("download-pipes-csv").addEventListener("click", () => downloadRecognitionAsset("pipes"));
  $("download-reservoirs-csv").addEventListener("click", () => downloadRecognitionAsset("reservoirs"));
}

function handleDrawingFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const fileType = classifyDrawingFile(file);
  if (fileType !== "image") {
    state.drawingFile = file;
    state.drawingFileType = fileType;
    state.drawingImage = null;
    state.drawingRecognition = null;
    state.drawingAssets = null;
    state.drawingAssetsApplied = false;
    state.drawingPipeSamples = [];
    state.drawingJunctionSamples = [];
    state.drawingSourceSamples = [];
    state.drawingSampleMode = false;
    state.drawingJunctionMode = false;
    state.drawingSourceMode = false;
    syncPipeSampleControls();
    syncJunctionSampleControls();
    syncSourceSampleControls();
    $("recognized-export-state").textContent = "waiting";
    toggleRecognitionDownloads(false);
    toggleRecognitionApply(false);
    drawRecognitionCanvas();
    $("recognized-image-size").textContent = file.name;
    const routeName = fileType === "pdf" ? "PDF loaded" : fileType === "cad" ? "CAD loaded" : "unsupported file";
    const routeHint = fileType === "pdf" ? "ready for PDF route" : fileType === "cad" ? "ready for CAD route" : "JPG / PNG / PDF / DWG / DXF";
    updateRecognitionStatus(routeName, routeHint);
    return;
  }
  const image = new Image();
  image.onload = () => {
    state.drawingFile = file;
    state.drawingFileType = fileType;
    state.drawingImage = image;
    state.drawingRecognition = null;
    state.drawingAssets = null;
    state.drawingAssetsApplied = false;
    state.drawingPipeSamples = [];
    state.drawingJunctionSamples = [];
    state.drawingSourceSamples = [];
    state.drawingSampleMode = false;
    state.drawingJunctionMode = false;
    state.drawingSourceMode = false;
    syncPipeSampleControls();
    syncJunctionSampleControls();
    syncSourceSampleControls();
    drawRecognitionCanvas();
    updateRecognitionStatus("image loaded", "0 pipes / 0 nodes");
    $("recognized-image-size").textContent = `${image.naturalWidth} x ${image.naturalHeight}`;
    $("recognized-export-state").textContent = "대기";
    toggleRecognitionDownloads(false);
    toggleRecognitionApply(false);
  };
  image.src = URL.createObjectURL(file);
}

function resetDrawingRecognition() {
  state.drawingFile = null;
  state.drawingFileType = null;
  state.drawingImage = null;
  state.drawingRecognition = null;
  state.drawingAssets = null;
  state.drawingAssetsApplied = false;
  state.drawingPipeSamples = [];
  state.drawingJunctionSamples = [];
  state.drawingSourceSamples = [];
  state.drawingSampleMode = false;
  state.drawingJunctionMode = false;
  state.drawingSourceMode = false;
  syncPipeSampleControls();
  syncJunctionSampleControls();
  syncSourceSampleControls();
  restoreInitialDashboardNetwork();
  $("drawing-file").value = "";
  $("recognized-pipe-count").textContent = 0;
  $("recognized-node-count").textContent = 0;
  $("recognized-image-size").textContent = "--";
  $("recognized-export-state").textContent = "reset";
  renderRecognitionTable("recognized-nodes-table", [], ["node_id", "x", "y", "node_type", "dma_id"]);
  renderRecognitionTable("recognized-pipes-table", [], ["pipe_id", "from_node", "to_node", "length_m", "diameter_mm", "material"]);
  toggleRecognitionDownloads(false);
  toggleRecognitionApply(false);
  updateRecognitionStatus("drawing waiting", "0 pipes / 0 nodes");
  drawRecognitionCanvas();
}

function restoreInitialDashboardNetwork() {
  if (!state.initialData) return;
  state.nodes = cloneRows(state.initialData.nodes);
  state.pipes = cloneRows(state.initialData.pipes);
  state.reservoirs = cloneRows(state.initialData.reservoirs);
  state.pumps = cloneRows(state.initialData.pumps);
  state.valves = cloneRows(state.initialData.valves);
  state.households = cloneRows(state.initialData.households);
  state.demandSeries = cloneRows(state.initialData.demandSeries);
  buildDemandIndex();
  state.pipeEdits = new Map();
  state.leakDemands = new Map();
  clearBulkSelection();
  state.baseNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.originalNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.aging = new Map(state.pipes.map((pipe) => [pipe.pipe_id, agingScore(pipe)]));
  state.addMode = false;
  state.pipeDrawMode = false;
  state.sourceDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
  state.pendingSource = null;
  state.editorTab = "pipe";
  state.selected = state.pipes[0] ? `pipe:${state.pipes[0].pipe_id}` : `node:${firstJunctionId()}`;
  fitMapToCurrentNetwork();
  refreshAssetOptions();
  syncDashboardControlsAfterNetworkRestore();
  updateDrawReadout("도면 인식 이미지와 가져온 관망을 초기화하고 기본 관망으로 되돌렸습니다.");
  render();
}

function syncDashboardControlsAfterNetworkRestore() {
  const firstPipe = state.pipes[0]?.pipe_id || "";
  const firstNode = firstJunctionId();
  const firstSource = firstSourceId();
  if ($("selected-pipe")) $("selected-pipe").value = firstPipe;
  if ($("leak-pipe")) $("leak-pipe").value = state.pipes.some((pipe) => pipe.pipe_id === "P14") ? "P14" : firstPipe;
  if ($("selected-junction")) $("selected-junction").value = firstNode;
  if ($("source-junction")) $("source-junction").value = firstNode;
  if ($("source-connect-junction")) $("source-connect-junction").value = firstNode;
  if ($("selected-source")) $("selected-source").value = firstSource;
  if ($("new-source-id")) $("new-source-id").value = nextSourceId();
  const reservoirHead = Number(state.reservoirs[0]?.head_m || 58);
  const pump = state.pumps.find((item) => String(item.status || "on").toLowerCase() !== "off");
  if ($("source-head")) $("source-head").value = reservoirHead;
  if ($("source-design-head")) $("source-design-head").value = reservoirHead;
  if ($("pump-head")) $("pump-head").value = pump ? Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1) : 0;
  if ($("source-pump-gain")) $("source-pump-gain").value = $("pump-head")?.value || 0;
  if ($("demand-profile")) $("demand-profile").value = state.demandProfile || "metro";
  if ($("leak-demand")) $("leak-demand").value = 2;
  if ($("time-slider")) $("time-slider").value = Math.min(42, state.timeline.length - 1);
  syncSourceControlLabels();
  syncPipeEditor();
}

function drawRecognitionCanvas(segments = [], nodes = []) {
  const canvas = $("drawing-canvas");
  const ctx = canvas.getContext("2d");
  const image = state.drawingImage;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!image && !segments.length && !nodes.length) {
    $("drawing-empty-state").style.display = "grid";
    return;
  }
  $("drawing-empty-state").style.display = "none";
  const frame = recognitionFrameBounds(segments, nodes);
  const sourceWidth = image ? image.naturalWidth : frame.width;
  const sourceHeight = image ? image.naturalHeight : frame.height;
  const scale = Math.min(canvas.width / sourceWidth, canvas.height / sourceHeight);
  const width = sourceWidth * scale;
  const height = sourceHeight * scale;
  const offsetX = (canvas.width - width) / 2;
  const offsetY = (canvas.height - height) / 2;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (image) ctx.drawImage(image, offsetX, offsetY, width, height);
  ctx.lineCap = "round";
  ctx.lineWidth = 3;
  ctx.strokeStyle = "#2563eb";
  for (const segment of segments) {
    ctx.beginPath();
    const points = Array.isArray(segment.points) && segment.points.length >= 2 ? segment.points : null;
    if (points) {
      ctx.moveTo(offsetX + Number(points[0].x || 0) * scale, offsetY + Number(points[0].y || 0) * scale);
      for (const point of points.slice(1)) {
        ctx.lineTo(offsetX + Number(point.x || 0) * scale, offsetY + Number(point.y || 0) * scale);
      }
    } else {
      ctx.moveTo(offsetX + segment.x1 * scale, offsetY + segment.y1 * scale);
      ctx.lineTo(offsetX + segment.x2 * scale, offsetY + segment.y2 * scale);
    }
    ctx.stroke();
  }
  ctx.fillStyle = "#16a34a";
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  for (const node of nodes) {
    const x = offsetX + node.x * scale;
    const y = offsetY + node.y * scale;
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  drawPipeSampleMarkers(ctx, offsetX, offsetY, scale);
  drawJunctionSampleMarkers(ctx, offsetX, offsetY, scale);
  drawSourceSampleMarkers(ctx, offsetX, offsetY, scale);
}

function drawPipeSampleMarkers(ctx, offsetX, offsetY, scale) {
  if (!state.drawingPipeSamples.length) return;
  ctx.save();
  ctx.strokeStyle = "#f59e0b";
  ctx.fillStyle = "rgba(245, 158, 11, 0.12)";
  ctx.lineWidth = 3;
  for (const sample of state.drawingPipeSamples) {
    const x = offsetX + Number(sample.x || 0) * scale;
    const y = offsetY + Number(sample.y || 0) * scale;
    ctx.beginPath();
    ctx.arc(x, y, Math.max(9, Number(sample.radius_px || 10) * scale), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - 8, y);
    ctx.lineTo(x + 8, y);
    ctx.moveTo(x, y - 8);
    ctx.lineTo(x, y + 8);
    ctx.stroke();
  }
  ctx.restore();
}

function handleDrawingCanvasClick(event) {
  if ((!state.drawingSampleMode && !state.drawingJunctionMode && !state.drawingSourceMode) || !state.drawingImage) return;
  const canvasPoint = drawingCanvasToImagePoint(event);
  if (!canvasPoint) return;
  if (state.drawingSourceMode) {
    state.drawingSourceSamples.push({ ...canvasPoint, radius_px: 14 });
    state.drawingSourceSamples = state.drawingSourceSamples.slice(-DRAWING_SAMPLE_LIMIT);
    syncSourceSampleControls();
    drawRecognitionCanvas(state.drawingRecognition?.segments || [], state.drawingRecognition?.nodes || []);
    updateRecognitionStatus("source/pump candidate added", `${state.drawingSourceSamples.length} / ${DRAWING_SAMPLE_LIMIT} sources`);
    return;
  }
  if (state.drawingJunctionMode) {
    state.drawingJunctionSamples.push({ ...canvasPoint, radius_px: 12 });
    state.drawingJunctionSamples = state.drawingJunctionSamples.slice(-DRAWING_SAMPLE_LIMIT);
    syncJunctionSampleControls();
    drawRecognitionCanvas(state.drawingRecognition?.segments || [], state.drawingRecognition?.nodes || []);
    updateRecognitionStatus("junction candidate added", `${state.drawingJunctionSamples.length} / ${DRAWING_SAMPLE_LIMIT} anchors`);
    return;
  }
  state.drawingPipeSamples.push({ ...canvasPoint, radius_px: 10 });
  state.drawingPipeSamples = state.drawingPipeSamples.slice(-DRAWING_SAMPLE_LIMIT);
  syncPipeSampleControls();
  drawRecognitionCanvas(state.drawingRecognition?.segments || [], state.drawingRecognition?.nodes || []);
  updateRecognitionStatus("pipe candidate added", `${state.drawingPipeSamples.length} / ${DRAWING_SAMPLE_LIMIT} pipe candidates`);
}

function drawingCanvasToImagePoint(event) {
  const canvas = $("drawing-canvas");
  const image = state.drawingImage;
  if (!image) return null;
  const rect = canvas.getBoundingClientRect();
  const scale = Math.min(canvas.width / image.naturalWidth, canvas.height / image.naturalHeight);
  const width = image.naturalWidth * scale;
  const height = image.naturalHeight * scale;
  const offsetX = (canvas.width - width) / 2;
  const offsetY = (canvas.height - height) / 2;
  const canvasX = ((event.clientX - rect.left) / rect.width) * canvas.width;
  const canvasY = ((event.clientY - rect.top) / rect.height) * canvas.height;
  if (canvasX < offsetX || canvasX > offsetX + width || canvasY < offsetY || canvasY > offsetY + height) return null;
  return {
    x: Number(((canvasX - offsetX) / scale).toFixed(2)),
    y: Number(((canvasY - offsetY) / scale).toFixed(2)),
  };
}

function togglePipeSampleMode() {
  state.drawingSampleMode = !state.drawingSampleMode;
  if (state.drawingSampleMode) {
    state.drawingJunctionMode = false;
    state.drawingSourceMode = false;
  }
  syncPipeSampleControls();
  syncJunctionSampleControls();
  syncSourceSampleControls();
}

function clearPipeSamples() {
  state.drawingPipeSamples = [];
  state.drawingSampleMode = false;
  syncPipeSampleControls();
  drawRecognitionCanvas(state.drawingRecognition?.segments || [], state.drawingRecognition?.nodes || []);
}

function syncPipeSampleControls() {
  const modeButton = $("pipe-sample-mode");
  const countLabel = $("pipe-sample-count");
  if (!modeButton || !countLabel) return;
  modeButton.classList.toggle("active", state.drawingSampleMode);
  modeButton.textContent = state.drawingSampleMode ? "Pipe 후보 선택 중" : "Pipe 후보 선택";
  countLabel.textContent = `${state.drawingPipeSamples.length} / ${DRAWING_SAMPLE_LIMIT}`;
}

function drawJunctionSampleMarkers(ctx, offsetX, offsetY, scale) {
  if (!state.drawingJunctionSamples.length) return;
  ctx.save();
  ctx.strokeStyle = "#0f766e";
  ctx.fillStyle = "rgba(15, 118, 110, 0.16)";
  ctx.lineWidth = 3;
  ctx.font = "700 12px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  state.drawingJunctionSamples.forEach((sample, index) => {
    const x = offsetX + Number(sample.x || 0) * scale;
    const y = offsetY + Number(sample.y || 0) * scale;
    ctx.beginPath();
    ctx.arc(x, y, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#0f766e";
    ctx.fillText(String(index + 1), x, y - 18);
    ctx.fillStyle = "rgba(15, 118, 110, 0.16)";
  });
  ctx.restore();
}

function toggleJunctionSampleMode() {
  state.drawingJunctionMode = !state.drawingJunctionMode;
  if (state.drawingJunctionMode) {
    state.drawingSampleMode = false;
    state.drawingSourceMode = false;
  }
  syncPipeSampleControls();
  syncJunctionSampleControls();
  syncSourceSampleControls();
}

function clearJunctionSamples() {
  state.drawingJunctionSamples = [];
  state.drawingJunctionMode = false;
  syncJunctionSampleControls();
  drawRecognitionCanvas(state.drawingRecognition?.segments || [], state.drawingRecognition?.nodes || []);
}

function syncJunctionSampleControls() {
  const modeButton = $("junction-sample-mode");
  const countLabel = $("junction-sample-count");
  if (!modeButton || !countLabel) return;
  modeButton.classList.toggle("active", state.drawingJunctionMode);
  modeButton.textContent = state.drawingJunctionMode ? "Junction 후보 선택 중" : "Junction 후보 선택";
  countLabel.textContent = `${state.drawingJunctionSamples.length} / ${DRAWING_SAMPLE_LIMIT}`;
}

function drawSourceSampleMarkers(ctx, offsetX, offsetY, scale) {
  if (!state.drawingSourceSamples.length) return;
  ctx.save();
  ctx.strokeStyle = "#7c3aed";
  ctx.fillStyle = "rgba(124, 58, 237, 0.14)";
  ctx.lineWidth = 3;
  ctx.font = "700 12px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  state.drawingSourceSamples.forEach((sample, index) => {
    const x = offsetX + Number(sample.x || 0) * scale;
    const y = offsetY + Number(sample.y || 0) * scale;
    const size = Math.max(11, Number(sample.radius_px || 14) * scale);
    ctx.beginPath();
    ctx.moveTo(x, y - size);
    ctx.lineTo(x + size, y);
    ctx.lineTo(x, y + size);
    ctx.lineTo(x - size, y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#6d28d9";
    ctx.fillText(`S${index + 1}`, x, y - size - 10);
    ctx.fillStyle = "rgba(124, 58, 237, 0.14)";
  });
  ctx.restore();
}

function toggleSourceSampleMode() {
  state.drawingSourceMode = !state.drawingSourceMode;
  if (state.drawingSourceMode) {
    state.drawingSampleMode = false;
    state.drawingJunctionMode = false;
  }
  syncPipeSampleControls();
  syncJunctionSampleControls();
  syncSourceSampleControls();
}

function clearSourceSamples() {
  state.drawingSourceSamples = [];
  state.drawingSourceMode = false;
  syncSourceSampleControls();
  drawRecognitionCanvas(state.drawingRecognition?.segments || [], state.drawingRecognition?.nodes || []);
}

function syncSourceSampleControls() {
  const modeButton = $("source-sample-mode");
  const countLabel = $("source-sample-count");
  if (!modeButton || !countLabel) return;
  modeButton.classList.toggle("active", state.drawingSourceMode);
  modeButton.textContent = state.drawingSourceMode ? "Source/Pump 후보 선택 중" : "Source/Pump 후보 선택";
  countLabel.textContent = `${state.drawingSourceSamples.length} / ${DRAWING_SAMPLE_LIMIT}`;
}

async function analyzeDrawingImage() {
  if (!state.drawingFile) {
    updateRecognitionStatus("drawing file required", "0 pipes / 0 nodes");
    return;
  }
  if (state.drawingFileType === "unknown") {
    updateRecognitionStatus("unsupported file", "JPG / PNG / PDF / DWG / DXF");
    return;
  }
  updateRecognitionStatus("analyzing", recognitionRouteLabel(state.drawingFileType));
  $("analyze-drawing").disabled = true;
  try {
    const serverResult = await recognizeDrawingGeometryWithApi(state.drawingFile);
    state.drawingRecognition = serverResult.recognition;
    state.drawingFileType = serverResult.recognition.file_type || state.drawingFileType;
    renderDrawingRecognition(serverResult.assets);
  } catch (error) {
    console.warn("Server recognition failed.", error);
    updateRecognitionStatus("recognition failed", error.message || "server error");
  } finally {
    $("analyze-drawing").disabled = false;
  }
}

function renderDrawingRecognition(prebuiltAssets = null) {
  if (!state.drawingRecognition) return;
  if (!prebuiltAssets) {
    updateRecognitionStatus("recognition incomplete", "server assets required");
    return;
  }
  const assets = prebuiltAssets;
  state.drawingAssets = assets;
  state.drawingAssetsApplied = false;
  drawRecognitionCanvas(state.drawingRecognition.segments, state.drawingRecognition.nodes);
  $("recognized-pipe-count").textContent = assets.pipes.length;
  $("recognized-node-count").textContent = Math.max(assets.nodes.length - assets.reservoirs.length, 0);
  const width = Number(state.drawingRecognition.width || 0);
  const height = Number(state.drawingRecognition.height || 0);
  $("recognized-image-size").textContent = width && height ? `${width} x ${height}` : state.drawingRecognition.filename || state.drawingFile?.name || "--";
  const lowConfidence = state.drawingRecognition.low_confidence_pipes?.length || 0;
  const qualityReview = state.drawingRecognition.quality_report?.counts?.review_items || 0;
  $("recognized-export-state").textContent = assets.pipes.length ? "후보 준비" : "확인";
  updateRecognitionStatus(recognitionReadyLabel(state.drawingRecognition.file_type), `${assets.pipes.length} high-confidence pipes / ${lowConfidence} low-confidence / ${qualityReview} quality flags`);
  renderRecognitionTable("recognized-nodes-table", assets.nodes, ["node_id", "x", "y", "node_type", "dma_id"]);
  renderRecognitionTable("recognized-pipes-table", recognitionPipeCandidateRows(assets, state.drawingRecognition), [
    "pipe_id",
    "from_node",
    "to_node",
    "length_m",
    "geometry_type",
    "confidence",
    "candidate_state",
  ]);
  toggleRecognitionDownloads(Boolean(assets.nodes.length && assets.pipes.length));
  toggleRecognitionApply(Boolean(assets.nodes.length && assets.pipes.length));
}

function applyCurrentRecognitionAssets() {
  if (!state.drawingAssets) return;
  applyRecognitionAssetsToDashboard(state.drawingAssets);
}

async function recognizeDrawingGeometryWithApi(file) {
  const fileBase64 = await fileToBase64(file);
  const apiBase = String(window.__DRAWING_RECOGNITION_API_BASE__ || "").replace(/\/$/, "");
  const response = await fetch(`${apiBase}/api/recognize-drawing`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      file_base64: fileBase64,
      filename: file.name || "",
      mime_type: file.type || mimeTypeFromFilename(file.name),
      min_line_length: Number($("drawing-min-line").value || 45),
      merge_tolerance_px: Number($("drawing-merge-tolerance").value || 18),
      scale_m_per_px: Number($("drawing-scale").value || 1),
      default_diameter_mm: Number($("drawing-diameter").value || 150),
      default_material: $("drawing-material").value || "PVC",
      pipe_candidate_samples: state.drawingPipeSamples,
      pipe_style_samples: state.drawingPipeSamples,
      junction_anchor_samples: state.drawingJunctionSamples,
      source_pump_candidate_samples: state.drawingSourceSamples,
      use_gemini: true,
    }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "recognition API failed");
  if (!payload.recognition || !payload.assets) throw new Error("recognition API returned an incomplete payload");
  return payload;
}

function classifyDrawingFile(file) {
  const name = String(file.name || "").toLowerCase();
  const mimeType = String(file.type || "").toLowerCase();
  if (mimeType === "image/png" || mimeType === "image/jpeg" || /\.(png|jpe?g)$/.test(name)) return "image";
  if (mimeType === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (/\.(dwg|dxf)$/.test(name) || mimeType.includes("dwg") || mimeType.includes("autocad")) return "cad";
  return "unknown";
}

function mimeTypeFromFilename(filename) {
  const name = String(filename || "").toLowerCase();
  if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "image/jpeg";
  if (name.endsWith(".png")) return "image/png";
  if (name.endsWith(".pdf")) return "application/pdf";
  if (name.endsWith(".dwg")) return "application/x-dwg";
  if (name.endsWith(".dxf")) return "application/dxf";
  return "application/octet-stream";
}

function recognitionRouteLabel(fileType) {
  if (fileType === "pdf") return "PDF geometry route";
  if (fileType === "cad") return "CAD parser route";
  return "Gemini vision + geometry candidates";
}

function recognitionReadyLabel(fileType) {
  if (fileType === "pdf") return "PDF analysis ready";
  if (fileType === "cad") return "CAD analysis ready";
  return "image analysis ready";
}

function recognitionFrameBounds(segments, nodes) {
  const recognition = state.drawingRecognition || {};
  const width = Number(recognition.width || 0);
  const height = Number(recognition.height || 0);
  if (width > 0 && height > 0) return { width, height };
  const xs = [];
  const ys = [];
  for (const segment of segments) {
    xs.push(Number(segment.x1 || 0), Number(segment.x2 || 0));
    ys.push(Number(segment.y1 || 0), Number(segment.y2 || 0));
  }
  for (const node of nodes) {
    xs.push(Number(node.x || 0));
    ys.push(Number(node.y || 0));
  }
  if (!xs.length || !ys.length) return { width: 1120, height: 620 };
  return {
    width: Math.max(1, Math.ceil(Math.max(...xs) + 20)),
    height: Math.max(1, Math.ceil(Math.max(...ys) + 20)),
  };
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",")[1] || "");
    reader.onerror = () => reject(reader.error || new Error("file read failed"));
    reader.readAsDataURL(file);
  });
}

function applyRecognitionAssetsToDashboard(assets) {
  if (!assets.nodes.length || !assets.pipes.length) return;
  state.drawingAssetsApplied = true;
  state.nodes = assets.nodes.map((node) => ({ ...node }));
  state.pipes = assets.pipes.map((pipe) => ({ ...pipe }));
  state.reservoirs = assets.reservoirs.map((reservoir) => ({ ...reservoir }));
  state.pumps = (assets.pumps || []).map((pump) => ({ ...pump }));
  state.valves = [];
  state.households = [];
  state.demandByMinute = new Map();
  state.pipeEdits = new Map();
  state.leakDemands = new Map();
  clearBulkSelection();
  state.baseNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.originalNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.aging = new Map(state.pipes.map((pipe) => [pipe.pipe_id, agingScore(pipe)]));
  state.addMode = false;
  state.pipeDrawMode = false;
  state.sourceDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
  state.pendingSource = null;
  state.editorTab = "pipe";
  state.selected = state.pipes[0] ? `pipe:${state.pipes[0].pipe_id}` : `node:${firstJunctionId()}`;
  fitMapToCurrentNetwork();
  refreshAssetOptions();
  if (state.pipes[0]) {
    $("selected-pipe").value = state.pipes[0].pipe_id;
    $("leak-pipe").value = state.pipes[0].pipe_id;
  }
  const firstNode = firstJunctionId();
  if (firstNode) {
    $("selected-junction").value = firstNode;
    $("source-junction").value = firstNode;
  }
  $("source-head").value = Number(state.reservoirs[0]?.head_m || 58);
  $("pump-head").value = 0;
  $("recognized-export-state").textContent = "관망맵 반영";
  updateDrawReadout("도면 인식 관망이 관망맵에 실시간 반영되었습니다. Pipe/Junction 패널에서 세부 값을 편집하세요.");
  render();
}

function applyInjectedRecognitionAssets() {
  const assets = window.__STREAMLIT_RECOGNIZED_ASSETS__;
  if (!assets || window.__STREAMLIT_RECOGNIZED_ASSETS_APPLIED__) return;
  window.__STREAMLIT_RECOGNIZED_ASSETS_APPLIED__ = true;
  state.drawingAssets = assets;
  state.drawingAssetsApplied = false;
  renderRecognitionTable("recognized-nodes-table", assets.nodes || [], ["node_id", "x", "y", "node_type", "dma_id"]);
  renderRecognitionTable("recognized-pipes-table", assets.pipes || [], ["pipe_id", "from_node", "to_node", "length_m", "diameter_mm", "material"]);
  $("recognized-pipe-count").textContent = assets.pipes?.length || 0;
  $("recognized-node-count").textContent = Math.max((assets.nodes?.length || 0) - (assets.reservoirs?.length || 0), 0);
  $("recognized-export-state").textContent = "Streamlit 반영";
  updateRecognitionStatus("streamlit analysis ready", `${assets.pipes?.length || 0} pipes / ${assets.nodes?.length || 0} nodes`);
  toggleRecognitionDownloads(Boolean(assets.nodes?.length && assets.pipes?.length));
  toggleRecognitionApply(Boolean(assets.nodes?.length && assets.pipes?.length));
}

function recognitionPipeCandidateRows(assets, recognition) {
  const lowConfidence = recognition?.low_confidence_pipes || [];
  const highConfidenceRows = (assets.pipes || []).map((pipe) => ({
    ...pipe,
    confidence: ">= 0.55",
    geometry_type: pipe.geometry_type || "straight",
    candidate_state: "apply-ready",
  }));
  const reviewRows = lowConfidence.map((pipe) => ({
    pipe_id: pipe.id || pipe.pipe_id || "",
    from_node: pipe.from_node || "",
    to_node: pipe.to_node || "",
    length_m: pipe.length_px ? `${pipe.length_px} px` : "",
    geometry_type: pipe.geometry_type || "straight",
    confidence: Number.isFinite(Number(pipe.confidence)) ? Number(pipe.confidence).toFixed(2) : "",
    candidate_state: "review-only",
  }));
  return [...highConfidenceRows, ...reviewRows];
}

function fitMapToCurrentNetwork() {
  const points = state.nodes.filter((node) => Number.isFinite(Number(node.x)) && Number.isFinite(Number(node.y)));
  if (!points.length) {
    resetMapZoom();
    return;
  }
  const xs = points.map((node) => Number(node.x));
  const ys = points.map((node) => Number(node.y));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const width = Math.max(maxX - minX, 120);
  const height = Math.max(maxY - minY, 120);
  state.mapCenter = { x: 560, y: 325 };
  state.mapZoom = clamp(Math.min(1120 / (width + 180), 650 / (height + 160)), 0.6, 2.8);
}

function renderRecognitionTable(id, rows, columns) {
  if (!rows.length) {
    $(id).innerHTML = `<div class="empty-row">후보 없음</div>`;
    return;
  }
  $(id).innerHTML = `<table><thead><tr>${columns.map((col) => `<th>${col}</th>`).join("")}</tr></thead><tbody>${rows
    .slice(0, 80)
    .map((row) => `<tr>${columns.map((col) => `<td>${row[col] ?? ""}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;
}

function toggleRecognitionDownloads(enabled) {
  ["download-assets-json", "download-nodes-csv", "download-pipes-csv", "download-reservoirs-csv"].forEach((id) => {
    $(id).disabled = !enabled;
  });
}

function toggleRecognitionApply(enabled) {
  const button = $("apply-recognition-assets");
  if (button) button.disabled = !enabled;
}

function downloadRecognitionAsset(kind) {
  if (!state.drawingAssets) return;
  if (kind === "json") downloadBlob("recognized_network_assets.json", JSON.stringify(state.drawingAssets, null, 2), "application/json");
  if (kind === "nodes") downloadBlob("nodes.csv", rowsToCsv(state.drawingAssets.nodes), "text/csv");
  if (kind === "pipes") downloadBlob("pipes.csv", rowsToCsv(state.drawingAssets.pipes), "text/csv");
  if (kind === "reservoirs") downloadBlob("reservoirs.csv", rowsToCsv(state.drawingAssets.reservoirs), "text/csv");
}

function rowsToCsv(rows) {
  if (!rows.length) return "";
  const columns = Object.keys(rows[0]);
  return `${columns.join(",")}\n${rows.map((row) => columns.map((col) => csvCell(row[col])).join(",")).join("\n")}`;
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadBlob(fileName, content, mimeType) {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function updateRecognitionStatus(status, count) {
  $("recognition-status").textContent = status;
  $("recognition-count").textContent = count;
}

function render() {
  const snapshot = computeSnapshot();
  const junctions = snapshot.nodes.filter((node) => node.node_type !== "reservoir");
  const minPressure = Math.min(...junctions.map((node) => node.pressure));
  const selectedMinute = currentMinute();

  $("time-label").textContent = formatMinute(selectedMinute);
  $("timeline-title").textContent = `${formatMinute(selectedMinute)} 관망 상태`;
  state.demandProfile = $("demand-profile")?.value || state.demandProfile || "metro";
  $("demand-scale-value").textContent = `${Number($("demand-scale").value).toFixed(2)}x`;
  $("source-head-value").textContent = `${Number($("source-head").value).toFixed(1)} m`;
  $("pump-head-value").textContent = `${Number($("pump-head").value).toFixed(1)} m`;
  $("leak-demand-value").textContent = `${Number($("leak-demand").value).toFixed(2)} L/s`;

  $("node-count").textContent = junctions.length;
  $("pipe-count").textContent = state.pipes.length;
  $("min-pressure").textContent = `${minPressure.toFixed(1)} m`;
  $("low-node-count").textContent = junctions.filter((node) => node.pressure < MIN_PRESSURE).length;

  updateBulkSelectionControls();
  syncPipeEditor();
  syncJunctionEditor();
  syncSourceControlLabels();
  syncDrawWorkflow();
  syncEditorConsole();
  renderMap(snapshot);
  renderPressureBars(snapshot);
  renderDemandChart();
  renderReplacementRanking(snapshot);
  renderRecommendations(snapshot);
  renderAlerts(snapshot);
  renderLeakList();
}

function refreshAssetOptions() {
  const previousPipe = $("selected-pipe").value;
  const previousLeak = $("leak-pipe").value;
  const previousNode = $("selected-junction").value;
  const previousSource = $("source-junction").value;
  const previousSourceConnect = $("source-connect-junction").value;
  const previousSelectedSource = $("selected-source").value;
  const junctions = state.nodes.filter((node) => node.node_type !== "reservoir");
  const sources = state.nodes.filter((node) => node.node_type === "reservoir");

  $("leak-pipe").innerHTML = state.pipes.map((pipe) => `<option value="${pipe.pipe_id}">${pipe.pipe_id}</option>`).join("");
  $("selected-pipe").innerHTML = state.pipes
    .map((pipe) => `<option value="${pipe.pipe_id}">${pipe.pipe_id} · ${pipe.material || "unknown"}</option>`)
    .join("");
  $("selected-junction").innerHTML = junctions.map((node) => `<option value="${node.node_id}">${node.node_id} · ${node.dma_id}</option>`).join("");
  $("source-junction").innerHTML = junctions.map((node) => `<option value="${node.node_id}">${node.node_id} · ${node.dma_id}</option>`).join("");
  $("source-connect-junction").innerHTML = junctions.map((node) => `<option value="${node.node_id}">${node.node_id} · ${node.dma_id}</option>`).join("");
  $("selected-source").innerHTML = sources.map((node) => `<option value="${node.node_id}">${node.node_id} · ${node.dma_id}</option>`).join("");

  keepSelectValue("selected-pipe", previousPipe || state.pipes[0]?.pipe_id || "");
  keepSelectValue("leak-pipe", previousLeak || state.pipes[0]?.pipe_id || "");
  keepSelectValue("selected-junction", previousNode || firstJunctionId());
  keepSelectValue("source-junction", previousSource || firstJunctionId());
  keepSelectValue("source-connect-junction", previousSourceConnect || firstJunctionId());
  keepSelectValue("selected-source", previousSelectedSource || firstSourceId());
}

function keepSelectValue(id, value) {
  const select = $(id);
  if (select.querySelector(`option[value="${value}"]`)) select.value = value;
}

function setEditorTab(tab) {
  state.editorTab = tab;
  syncEditorConsole();
}

function syncEditorConsole() {
  document.querySelectorAll("[data-editor-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.editorTab === state.editorTab);
  });
  document.querySelectorAll("[data-editor-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.editorPanel === state.editorTab);
  });
  const [kind, id] = (state.selected || "").split(":");
  const modeLabel = state.addMode ? "Junction 생성 중" : state.pipeDrawMode ? "Pipe 그리기 중" : state.editorTab === "source" ? "Source/Pump 편집 중" : kind === "node" ? "Junction 편집 중" : kind === "pipe" ? "Pipe 편집 중" : "시나리오 편집 중";
  $("editor-context-title").textContent = modeLabel;
  $("editor-context-subtitle").textContent =
    state.editorTab === "leak"
      ? `${activeLeakDemands().size}개 누수 지점 활성`
      : state.editorTab === "junction"
        ? `${id || firstJunctionId()} 좌표·표고·수요 편집`
        : state.editorTab === "source"
          ? `현재 Source ${state.reservoirs[0]?.node_id || "없음"} · 공급원/Pump 추가`
          : `${id || selectedPipeId()} 길이·각도·관경·부속 설계`;
}

function firstJunctionId() {
  return state.nodes.find((node) => node.node_type !== "reservoir")?.node_id || "";
}

function firstSourceId() {
  return state.nodes.find((node) => node.node_type === "reservoir")?.node_id || "";
}

function computeSnapshot() {
  const sourceHead = Number($("source-head").value || 58) + Number($("pump-head").value || 0);
  const demandScale = Number($("demand-scale").value || 1);
  const leakDemands = activeLeakDemands();
  const demandByNode = nodeDemandAt(currentMinute());
  const source = state.reservoirs[0]?.node_id || "R1";
  const distances = weightedDistances(source);

  const nodes = state.nodes.map((node) => {
    const localDemand = (demandByNode.get(node.node_id) || node.base_demand_lps || 0) * demandScale;
    const leakPenalty = leakPenaltyAtNode(node.node_id, leakDemands);
    const distancePenalty = (distances.get(node.node_id) || 0) * 0.62;
    const pressure = sourceHead - node.elevation_m - distancePenalty - localDemand * 0.64 - leakPenalty;
    return {
      ...node,
      localDemand,
      pressure,
      hydraulicHead: pressure + Number(node.elevation_m || 0),
      status: pressure < MIN_PRESSURE ? "low" : pressure < MARGINAL_PRESSURE ? "marginal" : "ok",
      compliant: pressure >= MIN_PRESSURE,
    };
  });

  const nodeById = new Map(nodes.map((node) => [node.node_id, node]));
  const pipes = state.pipes.map((pipe) => {
    const design = pipeDesign(pipe);
    const from = nodeById.get(pipe.from_node);
    const to = nodeById.get(pipe.to_node);
    const endpointPressure = Math.min(from?.pressure ?? 999, to?.pressure ?? 999);
    const maxEndpointPressure = Math.max(from?.pressure ?? 0, to?.pressure ?? 0);
    const flow = estimatePipeFlow({ ...pipe, ...design }, from, to);
    const pressureSafety = pipePressureSafety({ ...pipe, ...design }, maxEndpointPressure);
    const leakDemand = leakDemands.get(pipe.pipe_id) || 0;
    const isLeak = leakDemand > 0;
    const status = isLeak
      ? "leak"
      : pressureSafety.overpressure
        ? "overpressure"
        : endpointPressure < MIN_PRESSURE
          ? "low"
          : endpointPressure < MARGINAL_PRESSURE
            ? "marginal"
            : "ok";
    return {
      ...pipe,
      ...design,
      status,
      endpointPressure,
      maxEndpointPressure,
      pressureSafety,
      flow_lps: flow.flow_lps,
      flowDirection: flow.direction,
      flowVelocityMps: flow.velocityMps,
      headDeltaM: flow.headDeltaM,
      fromHead: flow.fromHead,
      toHead: flow.toHead,
      fromPressure: from?.pressure,
      toPressure: to?.pressure,
      leakDemand,
    };
  });

  return { nodes, pipes, leakDemands, sourceHead };
}

function activeLeakDemands() {
  return new Map([...state.leakDemands].filter(([, demand]) => Number(demand) > 0));
}

function pipePressureSafety(pipe, appliedHeadM) {
  const model = materialPressureModel[pipe.material] || materialPressureModel.unknown;
  const rawAllowableHead = (2 * model.allowableStressMPa * 1_000_000) / (model.sdr * WATER_DENSITY_KG_M3 * GRAVITY_M_S2);
  const aging = state.aging.get(pipe.pipe_id) ?? agingScore(pipe);
  const agingFactor = clamp(1 - aging * 0.48, 0.52, 1);
  const diameterFactor = clamp(Math.sqrt(300 / Math.max(Number(pipe.diameter_mm || 300), 80)), 0.78, 1.12);
  const fittingFactor = clamp(1 - (Number(pipe.bend_count || 0) * 0.025 + Number(pipe.valve_count || 0) * 0.03 + Number(pipe.bend_angle_deg || 0) / 180 * 0.04), 0.82, 1);
  const allowableHead = clamp(rawAllowableHead * agingFactor * diameterFactor * fittingFactor, model.floorHeadM, model.capHeadM);
  const utilization = appliedHeadM / Math.max(allowableHead, 1);
  return {
    allowableHead,
    appliedHead: appliedHeadM,
    utilization,
    marginHead: allowableHead - appliedHeadM,
    overpressure: utilization >= 1,
    warning: utilization >= 0.85 && utilization < 1,
  };
}

function pointAlong(from, to, ratio) {
  return {
    x: from.x + (to.x - from.x) * ratio,
    y: from.y + (to.y - from.y) * ratio,
  };
}

function pipeProjectedPath(pipe, from, to, project) {
  const geometry = Array.isArray(pipe.geometry_m) ? pipe.geometry_m : [];
  if (geometry.length < 2) return [from, to];
  return geometry.map((point) => project({ x: Number(point.x || 0), y: Number(point.y || 0) }));
}

function svgPathFromPoints(points) {
  if (!points.length) return "";
  return `M${points.map((point) => `${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" L")}`;
}

function pointAlongPolyline(points, ratio) {
  if (points.length < 2) return points[0] || { x: 0, y: 0 };
  const lengths = [];
  let total = 0;
  for (let index = 1; index < points.length; index += 1) {
    const length = Math.hypot(points[index].x - points[index - 1].x, points[index].y - points[index - 1].y);
    lengths.push(length);
    total += length;
  }
  let target = total * ratio;
  for (let index = 1; index < points.length; index += 1) {
    const length = lengths[index - 1];
    if (target <= length || index === points.length - 1) {
      return pointAlong(points[index - 1], points[index], length ? target / length : 0);
    }
    target -= length;
  }
  return points[points.length - 1];
}

function tangentAngleAtPolyline(points, ratio) {
  if (points.length < 2) return 0;
  const center = Math.max(1, Math.min(points.length - 1, Math.round((points.length - 1) * ratio)));
  const start = points[center - 1];
  const end = points[center];
  return Math.atan2(end.y - start.y, end.x - start.x) * (180 / Math.PI);
}

function flowStrokeWidth(flowLps, diameterMm) {
  const baseWidth = Math.max(3.5, Math.min(9, Number(diameterMm || 150) / 75));
  const flowBoost = Math.min(8, Math.sqrt(Math.max(Number(flowLps || 0), 0)) * 1.15);
  return Math.max(4, Math.min(16, baseWidth + flowBoost));
}

function estimatePipeFlow(pipe, from, to) {
  if (!from || !to) {
    return { flow_lps: 0, direction: "none", velocityMps: 0, headDeltaM: 0 };
  }
  const fromHead = Number(from.hydraulicHead ?? Number(from.pressure || 0) + Number(from.elevation_m || 0));
  const toHead = Number(to.hydraulicHead ?? Number(to.pressure || 0) + Number(to.elevation_m || 0));
  const headDelta = fromHead - toHead;
  const direction = Math.abs(headDelta) < 0.05 ? "none" : headDelta >= 0 ? "forward" : "reverse";
  const length = Math.max(Number(pipe.length_m || 1), 1);
  const diameterM = Math.max(Number(pipe.diameter_mm || 1) / 1000, 0.05);
  const roughness = Math.max(Number(pipe.roughness_c || 100), 1);
  const minorLoss = Math.max(Number(pipe.minor_loss_k || 0), 0);
  const fittingLoss = 1 + Number(pipe.bend_count || 0) * 0.08 + Number(pipe.valve_count || 0) * 0.12 + minorLoss * 0.18;
  const effectiveDelta = Math.max(Math.abs(headDelta), 0);
  const qM3s = effectiveDelta === 0 ? 0 : Math.pow((effectiveDelta * Math.pow(roughness, 1.852) * Math.pow(diameterM, 4.871)) / (10.67 * length * fittingLoss), 1 / 1.852);
  const area = Math.PI * Math.pow(diameterM / 2, 2);
  return {
    flow_lps: qM3s * 1000,
    direction,
    velocityMps: area > 0 ? qM3s / area : 0,
    headDeltaM: headDelta,
    fromHead,
    toHead,
  };
}

function leakPenaltyAtNode(nodeId, leakDemands = activeLeakDemands()) {
  let penalty = 0;
  for (const [pipeId, demand] of leakDemands) {
    if (pipeTouches(pipeId, nodeId)) penalty += Number(demand || 0) * 1.55;
  }
  return penalty;
}

function nodeDemandAt(minute) {
  const profileId = $("demand-profile")?.value || state.demandProfile || "metro";
  if (demandProfiles[profileId]) return genericNodeDemandAt(minute, profileId);
  if (!state.demandByMinute.size) {
    return new Map(state.nodes.map((node) => [node.node_id, node.base_demand_lps || 0]));
  }
  const available = [...state.demandByMinute.keys()].sort((a, b) => a - b);
  const nearest = available.reduce((best, candidate) => {
    const bestDistance = circularMinuteDistance(best, minute);
    const candidateDistance = circularMinuteDistance(candidate, minute);
    return candidateDistance < bestDistance ? candidate : best;
  }, available[0]);
  return state.demandByMinute.get(nearest) || new Map();
}

function genericNodeDemandAt(minute, profileId) {
  const factor = demandProfileFactor(minute, profileId);
  return new Map(
    state.nodes.map((node) => [
      node.node_id,
      node.node_type === "reservoir" ? 0 : Number(node.base_demand_lps || 0.8) * factor,
    ]),
  );
}

function demandProfileFactor(minute, profileId) {
  const profile = demandProfiles[profileId] || demandProfiles.metro;
  const wrapped = ((minute % 1440) + 1440) % 1440;
  const hour = Math.floor(wrapped / 60);
  const nextHour = (hour + 1) % 24;
  const ratio = (wrapped % 60) / 60;
  const current = profile.multipliers[hour] ?? 1;
  const next = profile.multipliers[nextHour] ?? current;
  return current + (next - current) * ratio;
}

function weightedDistances(source) {
  const graph = new Map();
  const add = (from, to, weight) => {
    if (!graph.has(from)) graph.set(from, []);
    graph.get(from).push([to, weight]);
  };

  for (const pipe of state.pipes) {
    const design = pipeDesign(pipe);
    const age = state.aging.get(pipe.pipe_id) || 0;
    const valvePenalty = state.valves.some((valve) => valve.pipe_id === pipe.pipe_id && String(valve.status).toLowerCase() !== "open") ? 2 : 1;
    const roughnessPenalty = 100 / Math.max(design.roughness_c, 1);
    const minorLossPenalty = 1 + design.minor_loss_k * 0.16;
    const fittingPenalty = 1 + Number(design.bend_count || 0) * 0.05 + Number(design.valve_count || 0) * 0.08 + (Number(design.bend_angle_deg || 0) / 180) * 0.08;
    const weight =
      (design.length_m / Math.max(design.diameter_mm, 1)) *
      (1 + age * 2.2) *
      valvePenalty *
      roughnessPenalty *
      minorLossPenalty *
      fittingPenalty;
    add(pipe.from_node, pipe.to_node, weight);
    add(pipe.to_node, pipe.from_node, weight);
  }

  const distances = new Map([[source, 0]]);
  const queue = [[0, source]];
  while (queue.length) {
    queue.sort((a, b) => a[0] - b[0]);
    const [distance, node] = queue.shift();
    if (distance > distances.get(node)) continue;
    for (const [next, weight] of graph.get(node) || []) {
      const candidate = distance + weight;
      if (!distances.has(next) || candidate < distances.get(next)) {
        distances.set(next, candidate);
        queue.push([candidate, next]);
      }
    }
  }
  return distances;
}

function renderMap(snapshot) {
  const svg = $("network-map");
  const width = 1120;
  const height = 650;
  state.mapFrame = getMapFrame(snapshot.nodes, width, height);
  applyMapViewBox(svg, width, height);
  const project = (node) => projectNode(node, state.mapFrame);

  const nodeById = new Map(snapshot.nodes.map((node) => [node.node_id, node]));
  const selectedKind = state.selected?.split(":")[0];
  const selectedId = state.selected?.split(":")[1];
  const multiNodes = state.multiSelectedNodes || new Set();
  const multiPipes = state.multiSelectedPipes || new Set();
  $("pipe-tool").classList.toggle("active", selectedKind === "pipe");
  $("junction-tool").classList.toggle("active", selectedKind === "node");

  const pipeMarkup = snapshot.pipes
    .map((pipe) => {
      const from = project(nodeById.get(pipe.from_node));
      const to = endpointForPipe(pipe, from, project(nodeById.get(pipe.to_node)));
      const pathPoints = pipeProjectedPath(pipe, from, to, project);
      const flowPath = pipe.flowDirection === "reverse" ? [...pathPoints].reverse() : pathPoints;
      const flowPoint = pointAlongPolyline(flowPath, 0.58);
      const flowAngle = tangentAngleAtPolyline(flowPath, 0.58);
      const selected = selectedKind === "pipe" && selectedId === pipe.pipe_id;
      const multiSelected = multiPipes.has(pipe.pipe_id);
      const isLeak = Number(pipe.leakDemand || 0) > 0 || pipe.status === "leak";
      const strokeColor = isLeak ? PIPE_COLORS.leak : PIPE_COLORS[pipe.status];
      const flowWidth = flowStrokeWidth(pipe.flow_lps, pipe.diameter_mm);
      const strokeWidth = isLeak ? Math.max(12, flowWidth) : flowWidth;
      const mid = pointAlongPolyline(pathPoints, 0.5);
      const pathD = svgPathFromPoints(pathPoints);
      const leakLabel = isLeak ? ` · leak ${Number(pipe.leakDemand || 0).toFixed(2)} L/s` : "";
      const overpressure = pipe.pressureSafety?.overpressure;
      const pressureWarning = pipe.pressureSafety?.warning;
      const pressureLabel = overpressure
        ? ` · over ${Math.round(pipe.pressureSafety.utilization * 100)}%`
        : pressureWarning
          ? ` · ${Math.round(pipe.pressureSafety.utilization * 100)}%`
          : "";
      return `<g>
        ${isLeak ? `<path class="pipe-leak-halo" d="${pathD}" />` : ""}
        ${overpressure ? `<path class="pipe-overpressure-halo" d="${pathD}" />` : ""}
        <path class="pipe ${isLeak ? "leak-pipe-line" : ""} ${overpressure ? "overpressure-pipe-line" : ""} ${pressureWarning ? "pressure-warning-pipe-line" : ""} ${selected ? "selected-pipe-line" : ""} ${multiSelected ? "multi-selected-pipe-line" : ""}" d="${pathD}" stroke="${strokeColor}" stroke-width="${strokeWidth}" data-pipe="${pipe.pipe_id}" />
        ${pipe.flow_lps > 0.02 ? `<g class="flow-arrow" transform="translate(${flowPoint.x} ${flowPoint.y}) rotate(${flowAngle})">
          <path d="M-9 -5 L4 0 L-9 5 Z" />
        </g>` : ""}
        ${selected ? `<circle class="selected-ring" cx="${mid.x}" cy="${mid.y}" r="24" />` : ""}
        <text class="pipe-label ${isLeak ? "leak-pipe-label" : ""} ${overpressure ? "overpressure-pipe-label" : ""}" x="${mid.x}" y="${mid.y - 16}">${pipe.pipe_id} · ${pipe.flow_lps.toFixed(1)} L/s · D${Math.round(pipe.diameter_mm)}${leakLabel}${pressureLabel}</text>
      </g>`;
    })
    .join("");

  const previewMarkup = drawPreviewMarkup(project) + pipePreviewMarkup(project, snapshot) + sourcePreviewMarkup(project, snapshot);

  const nodeMarkup = snapshot.nodes
    .map((node) => {
      const point = project(node);
      const selected = selectedKind === "node" && selectedId === node.node_id;
      const multiSelected = multiNodes.has(node.node_id);
      const color = node.status === "low" ? "#dc2626" : node.status === "marginal" ? "#d97706" : node.node_type === "reservoir" ? "#0f766e" : "#247a5a";
      const radius = node.node_type === "reservoir" ? 13 : 10;
      const pressure = node.node_type === "reservoir" ? "SRC" : `${node.pressure.toFixed(1)}m`;
      return `<g class="junction-icon" data-node="${node.node_id}" transform="translate(${point.x} ${point.y})">
        ${selected ? `<circle class="selected-ring" r="18" />` : ""}
        ${multiSelected ? `<circle class="multi-selected-ring" r="${radius + 9}" />` : ""}
        <circle class="junction-body" r="${radius}" fill="${color}" />
        <path d="M0 -6v12M-6 0h12" />
        <text class="node-label" x="13" y="-8">${node.node_id}</text>
        <text class="pressure-label" x="13" y="5">${pressure}</text>
      </g>`;
    })
    .join("");

  const selectionBoxMarkup = selectionBoxOverlayMarkup();
  svg.innerHTML = `${pipeMarkup}${previewMarkup}${selectionBoxMarkup}${nodeMarkup}`;
  svg.onmousemove = (event) => {
    if (state.selectionBox?.active) {
      updateMapSelectionBox(event);
      return;
    }
    trackDrawingPreview(event);
  };
  svg.onmousedown = (event) => {
    if (event.button !== 0 || event.target.closest("[data-node], [data-pipe]")) return;
    startMapSelectionBox(event);
  };
  svg.onclick = (event) => {
    if (state.selectionMoved) {
      state.selectionMoved = false;
      return;
    }
    if (!state.addMode && !state.pipeDrawMode && !state.sourceDrawMode && bulkSelectionCount() > 0) {
      clearMapObjectSelection();
      render();
      return;
    }
    handleMapClick(event);
  };
  svg.onwheel = (event) => {
    event.preventDefault();
    zoomMap(event.deltaY < 0 ? 1.12 : 0.88, eventToSvgPoint(event));
  };
  svg.onmouseup = (event) => {
    if (state.selectionBox?.active) {
      finishMapSelectionBox(event, snapshot, project);
      return;
    }
    stopNodeDrag();
    stopBulkMove();
  };
  svg.onmouseleave = () => {
    stopNodeDrag();
    stopBulkMove();
    if (state.selectionBox?.active) {
      state.selectionBox = null;
      render();
      return;
    }
    if (state.addMode && !state.pendingJunction?.locked) {
      state.pendingJunction = null;
      updateDrawReadout();
      render();
    }
    if (state.pipeDrawMode && !state.pendingPipe?.locked) {
      state.pendingPipe = null;
      updateDrawReadout();
      render();
    }
  };
  svg.querySelectorAll("[data-pipe]").forEach((el) =>
    el.addEventListener("click", (event) => {
      if (state.addMode || state.pipeDrawMode || state.sourceDrawMode) return;
      event.stopPropagation();
      if (event.shiftKey) {
        toggleMultiPipe(el.dataset.pipe);
        return;
      }
      if (bulkSelectionCount() > 0) {
        addMultiPipe(el.dataset.pipe);
        return;
      }
      selectPipe(el.dataset.pipe);
    }),
  );
  svg.querySelectorAll("[data-node]").forEach((el) =>
    el.addEventListener("click", (event) => {
      if (state.pipeDrawMode) {
        event.stopPropagation();
        lockPendingPipeToNode(el.dataset.node);
        return;
      }
      if (state.addMode || state.sourceDrawMode) return;
      event.stopPropagation();
      if (event.shiftKey) {
        toggleMultiNode(el.dataset.node);
        return;
      }
      selectNode(el.dataset.node);
    }),
  );
  svg.querySelectorAll("[data-node]").forEach((el) =>
    el.addEventListener("mousedown", (event) => {
      if (state.addMode || state.pipeDrawMode || state.sourceDrawMode) return;
      event.stopPropagation();
      startNodeDrag(el.dataset.node, event);
    }),
  );
  refreshSelectedDetail(snapshot);
}

function getMapFrame(nodes, width, height) {
  const allNodes = nodes;
  const xs = allNodes.map((node) => Number(node.x || 0));
  const ys = allNodes.map((node) => Number(node.y || 0));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return { width, height, minX, maxX, minY, maxY, pad: 64 };
}

function applyMapViewBox(svg, width = 1120, height = 650) {
  const zoom = clamp(state.mapZoom || 1, 0.6, 5);
  state.mapZoom = zoom;
  const viewWidth = width / zoom;
  const viewHeight = height / zoom;
  const center = clampMapCenter(state.mapCenter || { x: width / 2, y: height / 2 }, viewWidth, viewHeight, width, height);
  state.mapCenter = center;
  state.mapViewBox = {
    x: center.x - viewWidth / 2,
    y: center.y - viewHeight / 2,
    width: viewWidth,
    height: viewHeight,
  };
  svg.setAttribute("viewBox", `${state.mapViewBox.x} ${state.mapViewBox.y} ${state.mapViewBox.width} ${state.mapViewBox.height}`);
  $("map-zoom-label").textContent = `${Math.round(zoom * 100)}%`;
}

function selectionBoxOverlayMarkup() {
  const box = normalizedSelectionBox();
  if (!box) return "";
  return `<rect class="selection-box ${box.mode}" x="${box.x}" y="${box.y}" width="${box.width}" height="${box.height}" />`;
}

function startMapSelectionBox(event) {
  if (state.addMode || state.pipeDrawMode || state.sourceDrawMode || state.bulkMove) return;
  const point = eventToSvgPoint(event);
  state.selectionBox = { active: true, start: point, current: point };
  state.selectionMoved = false;
}

function updateMapSelectionBox(event) {
  if (!state.selectionBox?.active) return;
  state.selectionBox.current = eventToSvgPoint(event);
  const distance = Math.hypot(
    state.selectionBox.current.x - state.selectionBox.start.x,
    state.selectionBox.current.y - state.selectionBox.start.y,
  );
  state.selectionMoved = distance > 3;
  render();
}

function finishMapSelectionBox(event, snapshot, project) {
  if (!state.selectionBox?.active) return;
  state.selectionBox.current = eventToSvgPoint(event);
  const box = normalizedSelectionBox();
  state.selectionBox = null;
  if (!box || Math.min(box.width, box.height) < 4) {
    render();
    return;
  }
  selectObjectsInBox(box, snapshot, project);
  render();
}

function normalizedSelectionBox() {
  const box = state.selectionBox;
  if (!box?.start || !box?.current) return null;
  const x = Math.min(box.start.x, box.current.x);
  const y = Math.min(box.start.y, box.current.y);
  const width = Math.abs(box.current.x - box.start.x);
  const height = Math.abs(box.current.y - box.start.y);
  return {
    x,
    y,
    width,
    height,
    x2: x + width,
    y2: y + height,
    mode: box.current.x >= box.start.x ? "inside" : "crossing",
  };
}

function selectObjectsInBox(box, snapshot, project) {
  state.multiSelectedNodes = new Set();
  state.multiSelectedPipes = new Set();
  const nodeById = new Map(snapshot.nodes.map((node) => [node.node_id, node]));
  for (const node of snapshot.nodes) {
    if (node.node_type === "reservoir") continue;
    const point = project(node);
    if (pointInRect(point, box)) state.multiSelectedNodes.add(node.node_id);
  }
  for (const pipe of snapshot.pipes) {
    const fromNode = nodeById.get(pipe.from_node);
    const toNode = nodeById.get(pipe.to_node);
    if (!fromNode || !toNode) continue;
    const from = project(fromNode);
    const to = endpointForPipe(pipe, from, project(toNode));
    const points = pipeProjectedPath(pipe, from, to, project);
    const selected = box.mode === "inside" ? polylineInsideRect(points, box) : polylineTouchesRect(points, box);
    if (selected) state.multiSelectedPipes.add(pipe.pipe_id);
  }
  const firstNode = [...state.multiSelectedNodes][0];
  const firstPipe = [...state.multiSelectedPipes][0];
  state.selected = firstPipe ? `pipe:${firstPipe}` : firstNode ? `node:${firstNode}` : state.selected;
  if (firstPipe && $("selected-pipe").querySelector(`option[value="${firstPipe}"]`)) $("selected-pipe").value = firstPipe;
  if (firstNode && $("selected-junction").querySelector(`option[value="${firstNode}"]`)) $("selected-junction").value = firstNode;
  updateBulkSelectionControls();
}

function pointInRect(point, rect) {
  return point && point.x >= rect.x && point.x <= rect.x2 && point.y >= rect.y && point.y <= rect.y2;
}

function polylineInsideRect(points, rect) {
  return points.length > 1 && points.every((point) => pointInRect(point, rect));
}

function polylineTouchesRect(points, rect) {
  if (points.some((point) => pointInRect(point, rect))) return true;
  for (let index = 1; index < points.length; index += 1) {
    if (segmentIntersectsRect(points[index - 1], points[index], rect)) return true;
  }
  return false;
}

function segmentIntersectsRect(a, b, rect) {
  const corners = [
    { x: rect.x, y: rect.y },
    { x: rect.x2, y: rect.y },
    { x: rect.x2, y: rect.y2 },
    { x: rect.x, y: rect.y2 },
  ];
  return corners.some((corner, index) => segmentsIntersect(a, b, corner, corners[(index + 1) % corners.length]));
}

function segmentsIntersect(a, b, c, d) {
  const cross = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  const overlaps = (p, q, r) =>
    Math.min(p.x, q.x) <= r.x + 0.001 &&
    r.x <= Math.max(p.x, q.x) + 0.001 &&
    Math.min(p.y, q.y) <= r.y + 0.001 &&
    r.y <= Math.max(p.y, q.y) + 0.001;
  const ab1 = cross(a, b, c);
  const ab2 = cross(a, b, d);
  const cd1 = cross(c, d, a);
  const cd2 = cross(c, d, b);
  if (Math.abs(ab1) < 0.001 && overlaps(a, b, c)) return true;
  if (Math.abs(ab2) < 0.001 && overlaps(a, b, d)) return true;
  if (Math.abs(cd1) < 0.001 && overlaps(c, d, a)) return true;
  if (Math.abs(cd2) < 0.001 && overlaps(c, d, b)) return true;
  return ab1 * ab2 <= 0 && cd1 * cd2 <= 0;
}

function clampMapCenter(center, viewWidth, viewHeight, width, height) {
  if (viewWidth >= width || viewHeight >= height) return { x: width / 2, y: height / 2 };
  return {
    x: Math.max(viewWidth / 2, Math.min(width - viewWidth / 2, center.x)),
    y: Math.max(viewHeight / 2, Math.min(height - viewHeight / 2, center.y)),
  };
}

function zoomMap(factor, anchorPoint = null) {
  const oldZoom = state.mapZoom || 1;
  const nextZoom = clamp(oldZoom * factor, 0.6, 5);
  if (anchorPoint && oldZoom !== nextZoom) {
    const oldView = state.mapViewBox;
    const relX = (anchorPoint.x - oldView.x) / oldView.width;
    const relY = (anchorPoint.y - oldView.y) / oldView.height;
    const nextWidth = state.mapFrame.width / nextZoom;
    const nextHeight = state.mapFrame.height / nextZoom;
    state.mapCenter = {
      x: anchorPoint.x + (0.5 - relX) * nextWidth,
      y: anchorPoint.y + (0.5 - relY) * nextHeight,
    };
  }
  state.mapZoom = nextZoom;
  render();
}

function resetMapZoom() {
  state.mapZoom = 1;
  state.mapCenter = { x: 560, y: 325 };
  render();
}

function toggleMultiPipe(pipeId) {
  state.multiSelectedPipes = state.multiSelectedPipes || new Set();
  if (state.multiSelectedPipes.has(pipeId)) state.multiSelectedPipes.delete(pipeId);
  else state.multiSelectedPipes.add(pipeId);
  state.selected = `pipe:${pipeId}`;
  if ($("selected-pipe").querySelector(`option[value="${pipeId}"]`)) $("selected-pipe").value = pipeId;
  updateBulkSelectionControls();
  render();
}

function addMultiPipe(pipeId) {
  if (!state.pipes.some((pipe) => pipe.pipe_id === pipeId)) return;
  state.multiSelectedPipes = state.multiSelectedPipes || new Set();
  state.multiSelectedPipes.add(pipeId);
  state.selected = `pipe:${pipeId}`;
  if ($("selected-pipe").querySelector(`option[value="${pipeId}"]`)) $("selected-pipe").value = pipeId;
  updateBulkSelectionControls();
  render();
}

function toggleMultiNode(nodeId) {
  const node = state.nodes.find((item) => item.node_id === nodeId);
  if (!node || node.node_type === "reservoir") return;
  state.multiSelectedNodes = state.multiSelectedNodes || new Set();
  if (state.multiSelectedNodes.has(nodeId)) state.multiSelectedNodes.delete(nodeId);
  else state.multiSelectedNodes.add(nodeId);
  state.selected = `node:${nodeId}`;
  updateBulkSelectionControls();
  render();
}

function clearBulkSelection() {
  state.multiSelectedNodes = new Set();
  state.multiSelectedPipes = new Set();
  state.selectionBox = null;
  state.bulkMove = null;
  updateBulkSelectionControls();
}

function clearMapObjectSelection() {
  clearBulkSelection();
  state.selected = null;
  const detail = $("selection-detail");
  if (detail) {
    detail.innerHTML = `<strong>선택 없음</strong><span>지도에서 Pipe 또는 Junction을 선택하세요.</span>`;
  }
}

function bulkSelectionCount() {
  return (state.multiSelectedNodes?.size || 0) + (state.multiSelectedPipes?.size || 0);
}

function updateBulkSelectionControls() {
  const nodeCount = state.multiSelectedNodes?.size || 0;
  const pipeCount = state.multiSelectedPipes?.size || 0;
  if ($("bulk-selection-count")) $("bulk-selection-count").textContent = `선택 ${nodeCount + pipeCount}개`;
  if ($("bulk-selection-mode")) $("bulk-selection-mode").textContent = `Junction ${nodeCount}개 · Pipe ${pipeCount}개`;
}

function nodesInBulkMove() {
  const ids = new Set(state.multiSelectedNodes || []);
  for (const pipeId of state.multiSelectedPipes || []) {
    const pipe = state.pipes.find((item) => item.pipe_id === pipeId);
    if (!pipe) continue;
    ids.add(pipe.from_node);
    ids.add(pipe.to_node);
  }
  return [...ids].filter((nodeId) => state.nodes.some((node) => node.node_id === nodeId));
}

function projectNode(node, frame = state.mapFrame) {
  return {
    x: frame.pad + ((Number(node.x || 0) - frame.minX) / (frame.maxX - frame.minX || 1)) * (frame.width - frame.pad * 2),
    y: frame.height - frame.pad - ((Number(node.y || 0) - frame.minY) / (frame.maxY - frame.minY || 1)) * (frame.height - frame.pad * 2),
  };
}

function unprojectPoint(point, frame = state.mapFrame) {
  return {
    x: frame.minX + ((point.x - frame.pad) / (frame.width - frame.pad * 2)) * (frame.maxX - frame.minX || 1),
    y: frame.minY + ((frame.height - frame.pad - point.y) / (frame.height - frame.pad * 2)) * (frame.maxY - frame.minY || 1),
  };
}

function drawPreviewMarkup(project) {
  if (!state.addMode || !state.pendingJunction) return "";
  const source = state.nodes.find((node) => node.node_id === $("source-junction").value);
  if (!source) return "";
  const from = project(source);
  const to = project(state.pendingJunction);
  const distance = distanceBetween(source, state.pendingJunction);
  const angle = angleBetween(source, state.pendingJunction);
  const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
  const strokeWidth = Math.max(4, Math.min(12, Number($("pipe-diameter").value || 150) / 48));
  return `<g class="draw-preview">
    <line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke-width="${strokeWidth}" />
    <circle cx="${to.x}" cy="${to.y}" r="12" />
    <text x="${mid.x}" y="${mid.y - 18}">${distance.toFixed(1)} m · ${angle.toFixed(0)}°</text>
    <text x="${to.x + 16}" y="${to.y - 13}">${$("new-junction-id").value || nextJunctionId()}</text>
  </g>`;
}

function pipePreviewMarkup(project, snapshot) {
  if (!state.pipeDrawMode || !state.pendingPipe) return "";
  const source = state.nodes.find((node) => node.node_id === $("source-junction").value);
  if (!source) return "";
  const from = project(source);
  const toNode = state.pendingPipe.to_node ? snapshot.nodes.find((node) => node.node_id === state.pendingPipe.to_node) : null;
  const target = toNode || state.pendingPipe;
  const to = project(target);
  const distance = distanceBetween(source, target);
  const angle = angleBetween(source, target);
  const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
  const strokeWidth = Math.max(4, Math.min(12, Number($("pipe-diameter").value || 150) / 48));
  const targetLabel = state.pendingPipe.to_node || "끝점 선택";
  return `<g class="draw-preview pipe-draw-preview">
    <line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke-width="${strokeWidth}" />
    <circle cx="${to.x}" cy="${to.y}" r="10" />
    <text x="${mid.x}" y="${mid.y - 18}">${distance.toFixed(1)} m · ${angle.toFixed(0)}° · ${targetLabel}</text>
  </g>`;
}

function sourcePreviewMarkup(project, snapshot) {
  if (!state.sourceDrawMode || !state.pendingSource) return "";
  const target = snapshot.nodes.find((node) => node.node_id === $("source-connect-junction").value);
  if (!target) return "";
  const from = project(target);
  const to = project(state.pendingSource);
  const distance = distanceBetween(target, state.pendingSource);
  const angle = angleBetween(target, state.pendingSource);
  const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
  return `<g class="draw-preview source-draw-preview">
    <line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke-width="7" />
    <circle cx="${to.x}" cy="${to.y}" r="13" />
    <text x="${mid.x}" y="${mid.y - 18}">${distance.toFixed(1)} m · ${angle.toFixed(0)}° · ${$("new-source-id").value || nextSourceId()}</text>
  </g>`;
}

function trackDrawingPreview(event) {
  if (state.bulkMove) {
    dragBulkSelection(event);
    return;
  }
  if (state.draggingNodeId) {
    dragSelectedNode(event);
    return;
  }
  if (state.sourceDrawMode) {
    trackPendingSource(event);
    return;
  }
  if (state.pipeDrawMode) {
    trackPendingPipe(event);
    return;
  }
  trackPendingJunction(event);
}

function startNodeDrag(nodeId, event = null) {
  const node = state.nodes.find((item) => item.node_id === nodeId);
  if (!node) return;
  if (bulkSelectionCount() > 1 && nodesInBulkMove().includes(nodeId)) {
    startBulkMove(event);
    return;
  }
  state.draggingNodeId = nodeId;
  state.selected = `node:${nodeId}`;
  if ($("selected-junction").querySelector(`option[value="${nodeId}"]`)) $("selected-junction").value = nodeId;
  if ($("selected-source").querySelector(`option[value="${nodeId}"]`)) $("selected-source").value = nodeId;
}

function dragSelectedNode(event) {
  const node = state.nodes.find((item) => item.node_id === state.draggingNodeId);
  if (!node || !state.mapFrame) return;
  const point = unprojectPoint(eventToSvgPoint(event));
  node.x = point.x;
  node.y = point.y;
  state.baseNodeGeometry.set(node.node_id, baseNodeState(node));
  if (node.node_type === "reservoir") syncSourceEditor();
  else syncJunctionEditor();
  render();
}

function stopNodeDrag() {
  state.draggingNodeId = "";
}

function startBulkMove(event) {
  if (!event || !state.mapFrame) return;
  const nodeIds = nodesInBulkMove();
  if (!nodeIds.length) return;
  state.bulkMove = {
    startPoint: unprojectPoint(eventToSvgPoint(event)),
    originals: new Map(
      nodeIds
        .map((nodeId) => state.nodes.find((node) => node.node_id === nodeId))
        .filter(Boolean)
        .map((node) => [node.node_id, { x: Number(node.x || 0), y: Number(node.y || 0) }]),
    ),
  };
}

function dragBulkSelection(event) {
  if (!state.bulkMove) return;
  state.selectionMoved = true;
  const point = unprojectPoint(eventToSvgPoint(event));
  const dx = point.x - state.bulkMove.startPoint.x;
  const dy = point.y - state.bulkMove.startPoint.y;
  for (const [nodeId, original] of state.bulkMove.originals) {
    const node = state.nodes.find((item) => item.node_id === nodeId);
    if (!node) continue;
    node.x = original.x + dx;
    node.y = original.y + dy;
    state.baseNodeGeometry.set(node.node_id, baseNodeState(node));
  }
  render();
}

function stopBulkMove() {
  state.bulkMove = null;
}

function trackPendingJunction(event) {
  if (!state.addMode || state.pendingJunction?.locked || !state.mapFrame) return;
  const point = eventToSvgPoint(event);
  const networkPoint = unprojectPoint(point);
  state.pendingJunction = buildPendingJunction(networkPoint, false);
  updateDrawReadout();
  render();
}

function trackPendingPipe(event) {
  if (!state.pipeDrawMode || state.pendingPipe?.locked || !state.mapFrame) return;
  const point = eventToSvgPoint(event);
  const networkPoint = unprojectPoint(point);
  state.pendingPipe = { ...networkPoint, locked: false, to_node: "" };
  updateDrawReadout();
  render();
}

function trackPendingSource(event) {
  if (!state.sourceDrawMode || state.pendingSource?.locked || !state.mapFrame) return;
  const networkPoint = unprojectPoint(eventToSvgPoint(event));
  state.pendingSource = buildPendingSource(networkPoint, false);
  syncSourceDraftControls();
  render();
}

function lockPendingPipeToNode(nodeId) {
  if (!state.pipeDrawMode || nodeId === $("source-junction").value) return;
  const target = state.nodes.find((node) => node.node_id === nodeId && node.node_type !== "reservoir");
  if (!target) return;
  state.pendingPipe = { x: target.x, y: target.y, locked: true, to_node: nodeId };
  updateDrawReadout();
  render();
}

function sourcePipeFor(sourceId) {
  return state.pipes.find((pipe) => pipe.from_node === sourceId || pipe.to_node === sourceId);
}

function sourcePumpFor(sourceId) {
  return state.pumps.find((pump) => pump.from_node === sourceId || pump.to_node === sourceId);
}

function sourceTargetFor(sourceId) {
  const pipe = sourcePipeFor(sourceId);
  if (!pipe) return null;
  const targetId = pipe.from_node === sourceId ? pipe.to_node : pipe.from_node;
  return state.nodes.find((node) => node.node_id === targetId && node.node_type !== "reservoir") || null;
}

function lockPendingJunction(event) {
  if (!state.addMode || !state.mapFrame) return;
  const point = eventToSvgPoint(event);
  const networkPoint = unprojectPoint(point);
  state.pendingJunction = buildPendingJunction(networkPoint, true);
  updateDrawReadout();
  render();
}

function lockPendingSource(event) {
  if (!state.sourceDrawMode || !state.mapFrame) return;
  const networkPoint = unprojectPoint(eventToSvgPoint(event));
  state.pendingSource = buildPendingSource(networkPoint, true);
  syncSourceDraftControls();
  $("source-readout").textContent = "Source/Pump 위치가 선택되었습니다. Source/Pump 추가 버튼을 다시 눌러 확정하세요.";
  render();
}

function handleMapClick(event) {
  if (state.sourceDrawMode) {
    lockPendingSource(event);
    return;
  }
  lockPendingJunction(event);
}

function eventToSvgPoint(event) {
  const svg = $("network-map");
  const rect = svg.getBoundingClientRect();
  const viewBox = state.mapViewBox || { x: 0, y: 0, width: state.mapFrame.width, height: state.mapFrame.height };
  return {
    x: viewBox.x + ((event.clientX - rect.left) / rect.width) * viewBox.width,
    y: viewBox.y + ((event.clientY - rect.top) / rect.height) * viewBox.height,
  };
}

function buildPendingJunction(point, locked) {
  const source = state.nodes.find((node) => node.node_id === $("source-junction").value);
  return {
    node_id: $("new-junction-id").value.trim() || nextJunctionId(),
    x: point.x,
    y: point.y,
    elevation_m: source ? Number(source.elevation_m || 0) : 30,
    base_demand_lps: 0.8,
    node_type: "junction",
    dma_id: source?.dma_id || "NEW",
    locked,
  };
}

function buildPendingSource(point, locked) {
  return {
    node_id: $("new-source-id").value.trim() || nextSourceId(),
    x: point.x,
    y: point.y,
    elevation_m: 35,
    base_demand_lps: 0,
    node_type: "reservoir",
    dma_id: "SOURCE",
    locked,
  };
}

function syncDrawWorkflow() {
  $("add-junction-mode").classList.toggle("active", state.addMode);
  $("draw-pipe-mode").classList.toggle("active", state.pipeDrawMode);
  $("add-source-pump").classList.toggle("active", state.sourceDrawMode);
  $("confirm-junction").disabled = !state.addMode || !state.pendingJunction?.locked;
  $("confirm-pipe").disabled = !state.pipeDrawMode || !state.pendingPipe?.locked;
  $("add-source-pump").textContent = state.sourceDrawMode && state.pendingSource?.locked ? "Source/Pump 확정" : state.sourceDrawMode ? "위치 선택 중" : "Source/Pump 추가";
  if (!state.addMode && !state.pipeDrawMode) return;
  updateDrawReadout();
}

function enterAddJunctionMode() {
  state.addMode = true;
  state.pipeDrawMode = false;
  state.sourceDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
  state.pendingSource = null;
  state.editorTab = "junction";
  $("new-junction-id").value = nextJunctionId();
  updateDrawReadout();
  render();
}

function enterPipeDrawMode() {
  state.pipeDrawMode = true;
  state.addMode = false;
  state.sourceDrawMode = false;
  state.pendingPipe = null;
  state.pendingJunction = null;
  state.pendingSource = null;
  state.editorTab = "junction";
  updateDrawReadout();
  render();
}

function cancelAddJunctionMode() {
  state.addMode = false;
  state.pipeDrawMode = false;
  state.sourceDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
  state.pendingSource = null;
  state.editorTab = "leak";
  updateDrawReadout();
  render();
}

function confirmPendingJunction() {
  if (!state.addMode || !state.pendingJunction?.locked) return;
  const sourceId = $("source-junction").value;
  const source = state.nodes.find((node) => node.node_id === sourceId);
  if (!source) return;
  const nodeId = uniqueNodeId(state.pendingJunction.node_id);
  const newNode = { ...state.pendingJunction, node_id: nodeId };
  delete newNode.locked;
  const pipeId = nextPipeId();
  const pipe = {
    pipe_id: pipeId,
    from_node: sourceId,
    to_node: nodeId,
    length_m: distanceBetween(source, newNode),
    diameter_mm: Number($("pipe-diameter").value || 150),
    material: $("pipe-material").value || "PVC",
    service_type: $("pipe-service-type").value || "distribution",
    install_year: CURRENT_YEAR,
    repair_count: 0,
    leak_history_count: 0,
    bend_count: 0,
    valve_count: 0,
    bend_angle_deg: 0,
    soil_ph: 7,
    soil_resistivity_ohm_cm: 3000,
    traffic_load_index: 0.2,
    editable_geometry: true,
  };
  state.nodes.push(newNode);
  state.baseNodeGeometry.set(nodeId, baseNodeState(newNode));
  state.originalNodeGeometry.set(nodeId, baseNodeState(newNode));
  state.pipes.push(pipe);
  state.pipeEdits.set(pipeId, {
    angle_deg: angleBetween(source, newNode),
    length_m: pipe.length_m,
    diameter_mm: pipe.diameter_mm,
    roughness_c: Number($("pipe-roughness").value || 100),
    minor_loss_k: Number($("pipe-minor-loss").value || 0),
    bend_angle_deg: pipe.bend_angle_deg,
    bend_count: pipe.bend_count,
    valve_count: pipe.valve_count,
    material: pipe.material,
    service_type: pipe.service_type,
  });
  state.aging.set(pipeId, agingScore(pipe));
  state.addMode = false;
  state.pendingJunction = null;
  refreshAssetOptions();
  $("selected-pipe").value = pipeId;
  $("selected-junction").value = nodeId;
  state.selected = `pipe:${pipeId}`;
  syncPipeEditor();
  updateDrawReadout(`추가 완료: ${sourceId} → ${nodeId}, Pipe ${pipeId}`);
  render();
}

function confirmPendingPipe() {
  if (!state.pipeDrawMode || !state.pendingPipe?.locked || !state.pendingPipe.to_node) return;
  const sourceId = $("source-junction").value;
  const targetId = state.pendingPipe.to_node;
  if (sourceId === targetId) return;
  const source = state.nodes.find((node) => node.node_id === sourceId);
  const target = state.nodes.find((node) => node.node_id === targetId);
  if (!source || !target) return;
  const pipeId = nextPipeId();
  const pipe = makePipe(pipeId, sourceId, targetId, source, target);
  state.pipes.push(pipe);
  state.pipeEdits.set(pipeId, pipeEditFromControls(source, target));
  state.aging.set(pipeId, agingScore(pipe));
  state.pipeDrawMode = false;
  state.pendingPipe = null;
  refreshAssetOptions();
  $("selected-pipe").value = pipeId;
  state.selected = `pipe:${pipeId}`;
  syncPipeEditor();
  updateDrawReadout(`Pipe 추가 완료: ${sourceId} → ${targetId}, ${pipeId}`);
  render();
}

function deleteSelectedPipe() {
  const pipeId = selectedPipeId();
  if (!pipeId) return;
  const pipeIndex = state.pipes.findIndex((pipe) => pipe.pipe_id === pipeId);
  if (pipeIndex < 0) return;
  state.pipes.splice(pipeIndex, 1);
  state.pipeEdits.delete(pipeId);
  state.aging.delete(pipeId);
  state.leakDemands.delete(pipeId);
  state.valves = state.valves.filter((valve) => valve.pipe_id !== pipeId);
  reflowNetworkGeometry();
  refreshAssetOptions();
  state.selected = state.pipes[0] ? `pipe:${state.pipes[0].pipe_id}` : `node:${firstJunctionId()}`;
  updateDrawReadout(`삭제 완료: ${pipeId}`);
  render();
}

function deleteSelectedJunction() {
  const node = selectedJunction();
  if (!node || node.node_type === "reservoir") return;
  const junctions = state.nodes.filter((item) => item.node_type !== "reservoir");
  if (junctions.length <= 1) {
    updateDrawReadout("마지막 Junction은 삭제할 수 없습니다. 새 Junction을 먼저 추가하세요.");
    return;
  }

  const connectedPipes = state.pipes.filter((pipe) => pipe.from_node === node.node_id || pipe.to_node === node.node_id);
  const connectedPipeIds = new Set(connectedPipes.map((pipe) => pipe.pipe_id));
  const message = connectedPipes.length
    ? `${node.node_id}와 연결된 Pipe ${connectedPipes.length}개도 함께 삭제됩니다. 계속할까요?`
    : `${node.node_id} Junction을 삭제할까요?`;
  if (!window.confirm(message)) return;

  state.nodes = state.nodes.filter((item) => item.node_id !== node.node_id);
  state.pipes = state.pipes.filter((pipe) => !connectedPipeIds.has(pipe.pipe_id));
  state.valves = state.valves.filter((valve) => !connectedPipeIds.has(valve.pipe_id));
  state.households = state.households.filter((household) => household.node_id !== node.node_id);
  state.baseNodeGeometry.delete(node.node_id);
  state.originalNodeGeometry.delete(node.node_id);
  for (const pipeId of connectedPipeIds) {
    state.pipeEdits.delete(pipeId);
    state.aging.delete(pipeId);
    state.leakDemands.delete(pipeId);
  }

  state.addMode = false;
  state.pipeDrawMode = false;
  state.sourceDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
  state.pendingSource = null;
  reflowNetworkGeometry();
  refreshAssetOptions();
  const nextNodeId = firstJunctionId();
  const nextPipeId = state.pipes[0]?.pipe_id || "";
  state.selected = nextNodeId ? `node:${nextNodeId}` : nextPipeId ? `pipe:${nextPipeId}` : null;
  if (nextNodeId) {
    $("selected-junction").value = nextNodeId;
    $("source-junction").value = nextNodeId;
  }
  if (nextPipeId) $("selected-pipe").value = nextPipeId;
  state.editorTab = "junction";
  updateDrawReadout(`삭제 완료: ${node.node_id} · 연결 Pipe ${connectedPipeIds.size}개 정리`);
  render();
}

function deleteBulkSelection() {
  const selectedNodes = new Set(state.multiSelectedNodes || []);
  const selectedPipes = new Set(state.multiSelectedPipes || []);
  if (!selectedNodes.size && !selectedPipes.size) {
    $("selection-detail").innerHTML = `<strong>다중 선택 없음</strong><span>지도에서 드래그하거나 Shift+클릭으로 객체를 선택하세요.</span>`;
    return;
  }
  const sourceIds = new Set(state.nodes.filter((node) => node.node_type === "reservoir").map((node) => node.node_id));
  const junctionIds = new Set(state.nodes.filter((node) => node.node_type !== "reservoir").map((node) => node.node_id));
  const removingSources = [...selectedNodes].filter((id) => sourceIds.has(id));
  const removingJunctions = [...selectedNodes].filter((id) => junctionIds.has(id));
  if (removingSources.length >= sourceIds.size && sourceIds.size > 0) {
    window.alert("Source/Pump가 하나만 있습니다.");
    return;
  }
  if (removingJunctions.length >= junctionIds.size && junctionIds.size > 0) {
    window.alert("마지막 Junction은 삭제할 수 없습니다.");
    return;
  }
  const connectedPipeIds = new Set(
    state.pipes
      .filter((pipe) => selectedNodes.has(pipe.from_node) || selectedNodes.has(pipe.to_node))
      .map((pipe) => pipe.pipe_id),
  );
  for (const pipeId of selectedPipes) connectedPipeIds.add(pipeId);
  const message = `선택 Junction ${selectedNodes.size}개와 Pipe ${connectedPipeIds.size}개를 삭제할까요?`;
  if (!window.confirm(message)) return;

  state.nodes = state.nodes.filter((node) => !selectedNodes.has(node.node_id));
  state.reservoirs = state.reservoirs.filter((reservoir) => !selectedNodes.has(reservoir.node_id));
  state.pumps = state.pumps.filter((pump) => !selectedNodes.has(pump.from_node) && !selectedNodes.has(pump.to_node));
  state.pipes = state.pipes.filter((pipe) => !connectedPipeIds.has(pipe.pipe_id));
  state.valves = state.valves.filter((valve) => !connectedPipeIds.has(valve.pipe_id));
  for (const nodeId of selectedNodes) {
    state.baseNodeGeometry.delete(nodeId);
    state.originalNodeGeometry.delete(nodeId);
  }
  for (const pipeId of connectedPipeIds) {
    state.pipeEdits.delete(pipeId);
    state.aging.delete(pipeId);
    state.leakDemands.delete(pipeId);
  }
  clearBulkSelection();
  refreshAssetOptions();
  state.selected = state.pipes[0] ? `pipe:${state.pipes[0].pipe_id}` : `node:${firstJunctionId()}`;
  render();
}

function applyBulkPipeProperties() {
  const pipeIds = [...(state.multiSelectedPipes || [])].filter((pipeId) => state.pipes.some((pipe) => pipe.pipe_id === pipeId));
  if (!pipeIds.length) return;
  const diameter = Number($("bulk-pipe-diameter").value || 150);
  const material = $("bulk-pipe-material").value || "PVC";
  for (const pipeId of pipeIds) {
    const pipe = state.pipes.find((item) => item.pipe_id === pipeId);
    const current = pipe ? pipeDesign(pipe) : {};
    state.pipeEdits.set(pipeId, {
      ...current,
      diameter_mm: diameter,
      material,
    });
  }
  render();
  $("selection-detail").innerHTML = `<strong>선택 Pipe 일괄 변경</strong><span>${pipeIds.length}개 Pipe에 D${diameter} · ${material}을 적용했습니다.</span>`;
}

function applyBulkJunctionProperties() {
  const nodeIds = [...(state.multiSelectedNodes || [])].filter((nodeId) =>
    state.nodes.some((node) => node.node_id === nodeId && node.node_type !== "reservoir"),
  );
  if (!nodeIds.length) return;
  const elevation = Number($("bulk-junction-elevation").value || 30);
  const demand = Number($("bulk-junction-demand").value || 0.8);
  const dma = $("bulk-junction-dma").value.trim() || "IMG_IMPORT";
  for (const nodeId of nodeIds) {
    const node = state.nodes.find((item) => item.node_id === nodeId);
    if (!node) continue;
    node.elevation_m = elevation;
    node.base_demand_lps = demand;
    node.dma_id = dma;
    state.baseNodeGeometry.set(node.node_id, baseNodeState(node));
  }
  render();
  $("selection-detail").innerHTML = `<strong>선택 Junction 일괄 변경</strong><span>${nodeIds.length}개 Junction에 표고 ${elevation.toFixed(1)} m · 수요 ${demand.toFixed(2)} L/s · ${dma}를 적용했습니다.</span>`;
}

function analyzeBulkSelection() {
  const snapshot = computeSnapshot();
  const nodeIds = new Set(state.multiSelectedNodes || []);
  const pipeIds = new Set(state.multiSelectedPipes || []);
  const nodes = snapshot.nodes.filter((node) => nodeIds.has(node.node_id));
  const pipes = snapshot.pipes.filter((pipe) => pipeIds.has(pipe.pipe_id));
  if (!nodes.length && !pipes.length) {
    $("selection-detail").innerHTML = `<strong>선택 구역 없음</strong><span>분석할 Junction 또는 Pipe를 먼저 선택하세요.</span>`;
    return;
  }
  const lowNodes = nodes.filter((node) => node.node_type !== "reservoir" && node.pressure < MIN_PRESSURE);
  const avgPressure = nodes.length ? nodes.reduce((sum, node) => sum + Number(node.pressure || 0), 0) / nodes.length : 0;
  const highRiskPipe = pipes
    .map((pipe) => ({ pipe, score: state.aging.get(pipe.pipe_id) || 0 }))
    .sort((a, b) => b.score - a.score)[0];
  $("selection-detail").innerHTML = `<strong>선택 구역 분석</strong>
    <span>Junction ${nodes.length}개 · Pipe ${pipes.length}개</span>
    <span>평균 압력 ${avgPressure.toFixed(1)} m · 저압 Junction ${lowNodes.length}개</span>
    <span>최고 위험 Pipe ${highRiskPipe ? `${highRiskPipe.pipe.pipe_id} (${highRiskPipe.score.toFixed(2)})` : "없음"}</span>`;
}

function addSourcePumpImmediateLegacy() {
  const targetId = $("source-connect-junction").value || firstJunctionId();
  const target = state.nodes.find((node) => node.node_id === targetId && node.node_type !== "reservoir");
  if (!target) {
    $("source-readout").textContent = "연결할 Junction을 먼저 선택하세요.";
    return;
  }
  const sourceId = uniqueSourceId($("new-source-id").value.trim() || nextSourceId());
  const sourceNode = {
    node_id: sourceId,
    x: Number($("source-x").value || target.x - 120),
    y: Number($("source-y").value || target.y),
    elevation_m: Math.max(Number(target.elevation_m || 30) + 5, 0),
    base_demand_lps: 0,
    node_type: "reservoir",
    dma_id: "SOURCE",
  };
  const reservoir = {
    node_id: sourceId,
    head_m: Number($("source-design-head").value || 58),
  };
  const pipeId = nextPipeId();
  const pipe = {
    pipe_id: pipeId,
    from_node: sourceId,
    to_node: targetId,
    length_m: distanceBetween(sourceNode, target),
    diameter_mm: Number($("source-pipe-diameter").value || 300),
    material: "ductile_iron",
    service_type: "transmission",
    install_year: CURRENT_YEAR,
    repair_count: 0,
    leak_history_count: 0,
    bend_count: 0,
    valve_count: 0,
    bend_angle_deg: 0,
    soil_ph: 7,
    soil_resistivity_ohm_cm: 3000,
    traffic_load_index: 0.2,
    burst_history_count: 0,
    editable_geometry: true,
  };
  const pump = {
    pump_id: `PU_${sourceId}`,
    from_node: sourceId,
    to_node: targetId,
    base_head_gain_m: Number($("source-pump-gain").value || 0),
    speed_multiplier: 1,
    status: "on",
  };

  state.nodes.unshift(sourceNode);
  state.reservoirs.unshift(reservoir);
  state.pumps.unshift(pump);
  state.pipes.unshift(pipe);
  state.baseNodeGeometry.set(sourceId, baseNodeState(sourceNode));
  state.originalNodeGeometry.set(sourceId, baseNodeState(sourceNode));
  state.pipeEdits.set(pipeId, {
    angle_deg: angleBetween(sourceNode, target),
    length_m: pipe.length_m,
    diameter_mm: pipe.diameter_mm,
    roughness_c: Number($("pipe-roughness").value || 100),
    minor_loss_k: 0,
    bend_angle_deg: 0,
    bend_count: 0,
    valve_count: 0,
    material: pipe.material,
    service_type: pipe.service_type,
  });
  state.aging.set(pipeId, agingScore(pipe));
  $("source-head").value = reservoir.head_m;
  $("pump-head").value = pump.base_head_gain_m;
  $("new-source-id").value = nextSourceId();
  state.selected = `pipe:${pipeId}`;
  state.editorTab = "pipe";
  refreshAssetOptions();
  $("selected-pipe").value = pipeId;
  $("source-readout").textContent = `${sourceId} Source/Pump 추가 완료 · ${sourceId} → ${targetId} · Pipe ${pipeId}`;
  render();
}

function addSourcePump() {
  if (!state.sourceDrawMode) {
    enterSourceDrawMode();
    return;
  }
  if (!state.pendingSource?.locked) {
    $("source-readout").textContent = "Click the map to fix the Source/Pump location, then press Source/Pump again.";
    return;
  }
  confirmPendingSourcePump();
}

function enterSourceDrawMode() {
  const targetId = $("source-connect-junction").value || firstJunctionId();
  const target = state.nodes.find((node) => node.node_id === targetId && node.node_type !== "reservoir");
  if (!target) {
    $("source-readout").textContent = "Select a target Junction before adding Source/Pump.";
    return;
  }
  state.sourceDrawMode = true;
  state.addMode = false;
  state.pipeDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
  state.editorTab = "source";
  const point = {
    x: Number($("source-x").value || target.x - Number($("source-pipe-length").value || 120)),
    y: Number($("source-y").value || target.y),
  };
  state.pendingSource = buildPendingSource(point, false);
  syncSourceDraftControls();
  $("source-readout").textContent = "Move on the map and click where the Source/Pump should be placed.";
  render();
}

function confirmPendingSourcePump() {
  const targetId = $("source-connect-junction").value || firstJunctionId();
  const target = state.nodes.find((node) => node.node_id === targetId && node.node_type !== "reservoir");
  if (!target || !state.pendingSource) return;
  const sourceId = uniqueSourceId($("new-source-id").value.trim() || nextSourceId());
  const sourceNode = {
    ...state.pendingSource,
    node_id: sourceId,
    elevation_m: Math.max(Number(target.elevation_m || 30) + 5, 0),
    base_demand_lps: 0,
    node_type: "reservoir",
    dma_id: "SOURCE",
  };
  delete sourceNode.locked;
  const reservoir = {
    node_id: sourceId,
    head_m: Number($("source-design-head").value || 58),
  };
  const pipeId = nextPipeId();
  const pipe = {
    pipe_id: pipeId,
    from_node: sourceId,
    to_node: targetId,
    length_m: distanceBetween(sourceNode, target),
    diameter_mm: Number($("source-pipe-diameter").value || 300),
    material: "ductile_iron",
    service_type: "transmission",
    install_year: CURRENT_YEAR,
    repair_count: 0,
    leak_history_count: 0,
    bend_count: 0,
    valve_count: 0,
    bend_angle_deg: 0,
    soil_ph: 7,
    soil_resistivity_ohm_cm: 3000,
    traffic_load_index: 0.2,
    burst_history_count: 0,
    editable_geometry: true,
  };
  const pump = {
    pump_id: `PU_${sourceId}`,
    from_node: sourceId,
    to_node: targetId,
    base_head_gain_m: Number($("source-pump-gain").value || 0),
    speed_multiplier: 1,
    status: "on",
  };

  state.nodes.unshift(sourceNode);
  state.reservoirs.unshift(reservoir);
  state.pumps.unshift(pump);
  state.pipes.unshift(pipe);
  state.baseNodeGeometry.set(sourceId, baseNodeState(sourceNode));
  state.originalNodeGeometry.set(sourceId, baseNodeState(sourceNode));
  state.pipeEdits.set(pipeId, {
    angle_deg: angleBetween(sourceNode, target),
    length_m: pipe.length_m,
    diameter_mm: pipe.diameter_mm,
    roughness_c: Number($("source-pipe-roughness").value || 100),
    minor_loss_k: 0,
    bend_angle_deg: 0,
    bend_count: 0,
    valve_count: 0,
    material: pipe.material,
    service_type: pipe.service_type,
  });
  state.aging.set(pipeId, agingScore(pipe));
  state.sourceDrawMode = false;
  state.pendingSource = null;
  $("source-head").value = reservoir.head_m;
  $("pump-head").value = pump.base_head_gain_m;
  $("new-source-id").value = nextSourceId();
  state.selected = `node:${sourceId}`;
  state.editorTab = "source";
  refreshAssetOptions();
  $("selected-source").value = sourceId;
  $("selected-pipe").value = pipeId;
  syncSourceEditor();
  $("source-readout").textContent = `${sourceId} Source/Pump added with pipe ${pipeId} to ${targetId}.`;
  render();
}

function deleteSelectedSourcePump() {
  const sourceId = $("selected-source").value || (state.selected?.startsWith("node:") ? state.selected.split(":")[1] : "");
  const sourceNode = state.nodes.find((node) => node.node_id === sourceId && node.node_type === "reservoir");
  if (!sourceNode) {
    $("source-readout").textContent = "삭제할 Source/Pump를 선택하세요.";
    return;
  }
  const sources = state.nodes.filter((node) => node.node_type === "reservoir");
  if (sources.length <= 1) {
    window.alert("Source/Pump가 하나만 있습니다.");
    $("source-readout").textContent = "Source/Pump가 하나만 있습니다. 새 Source/Pump를 먼저 추가하세요.";
    return;
  }
  const connectedPipes = state.pipes.filter((pipe) => pipe.from_node === sourceId || pipe.to_node === sourceId);
  const connectedPipeIds = new Set(connectedPipes.map((pipe) => pipe.pipe_id));
  const connectedPump = sourcePumpFor(sourceId);
  const message = connectedPipes.length
    ? `${sourceId} Source/Pump와 연결된 Pipe ${connectedPipes.length}개도 함께 삭제됩니다.\n${connectedPump ? "Pump도 같이 삭제됩니다.\n" : ""}계속할까요?`
    : `${sourceId} Source/Pump를 삭제할까요?${connectedPump ? "\nPump도 같이 삭제됩니다." : ""}`;
  if (!window.confirm(message)) return;

  state.nodes = state.nodes.filter((node) => node.node_id !== sourceId);
  state.reservoirs = state.reservoirs.filter((reservoir) => reservoir.node_id !== sourceId);
  state.pumps = state.pumps.filter((pump) => pump.from_node !== sourceId && pump.to_node !== sourceId);
  state.pipes = state.pipes.filter((pipe) => !connectedPipeIds.has(pipe.pipe_id));
  state.valves = state.valves.filter((valve) => !connectedPipeIds.has(valve.pipe_id));
  state.baseNodeGeometry.delete(sourceId);
  state.originalNodeGeometry.delete(sourceId);
  for (const pipeId of connectedPipeIds) {
    state.pipeEdits.delete(pipeId);
    state.aging.delete(pipeId);
    state.leakDemands.delete(pipeId);
  }

  state.selected = `node:${firstSourceId()}`;
  state.editorTab = "source";
  refreshAssetOptions();
  const nextSource = firstSourceId();
  if (nextSource) $("selected-source").value = nextSource;
  $("source-head").value = Number(state.reservoirs[0]?.head_m || 58);
  const pump = state.pumps.find((item) => String(item.status || "on").toLowerCase() !== "off");
  $("pump-head").value = pump ? Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1) : 0;
  $("source-readout").textContent = `삭제 완료: ${sourceId} · 연결 Pipe ${connectedPipeIds.size}개 정리`;
  render();
}

function makePipe(pipeId, fromNode, toNode, source, target) {
  return {
    pipe_id: pipeId,
    from_node: fromNode,
    to_node: toNode,
    length_m: distanceBetween(source, target),
    diameter_mm: Number($("pipe-diameter").value || 150),
    material: $("pipe-material").value || "PVC",
    service_type: $("pipe-service-type").value || "distribution",
    install_year: CURRENT_YEAR,
    repair_count: 0,
    leak_history_count: 0,
    bend_count: Number($("pipe-bend-count").value || 0),
    bend_angle_deg: Number($("pipe-bend-angle").value || 0),
    valve_count: Number($("pipe-valve-count").value || 0),
    soil_ph: 7,
    soil_resistivity_ohm_cm: 3000,
    traffic_load_index: 0.2,
  };
}

function pipeEditFromControls(source, target) {
  return {
    angle_deg: angleBetween(source, target),
    length_m: distanceBetween(source, target),
    diameter_mm: Number($("pipe-diameter").value || 150),
    roughness_c: Number($("pipe-roughness").value || 100),
    minor_loss_k: Number($("pipe-minor-loss").value || 0),
    bend_angle_deg: Number($("pipe-bend-angle").value || 0),
    bend_count: Number($("pipe-bend-count").value || 0),
    valve_count: Number($("pipe-valve-count").value || 0),
    material: $("pipe-material").value || "PVC",
    service_type: $("pipe-service-type").value || "distribution",
  };
}

function updateDrawReadout(message = "") {
  if (message) {
    $("draw-readout").textContent = message;
    return;
  }
  if (!state.addMode) {
    if (state.pipeDrawMode) {
      const source = state.nodes.find((node) => node.node_id === $("source-junction").value);
      if (!source || !state.pendingPipe) {
        $("draw-readout").textContent = "Pipe 그리기 중입니다. 시작 Junction을 선택하고, 지도에서 끝 Junction을 클릭하세요.";
        $("confirm-pipe").disabled = true;
        return;
      }
      const target = state.pendingPipe.to_node ? state.nodes.find((node) => node.node_id === state.pendingPipe.to_node) : state.pendingPipe;
      const distance = distanceBetween(source, target);
      const angle = angleBetween(source, target);
      if (!state.pendingPipe.locked) {
        $("pipe-length").value = Math.max(40, Math.min(620, Math.round(distance / 5) * 5));
        $("pipe-angle").value = normalizeAngle(Math.round(angle / 5) * 5);
        syncPipeControlLabels();
      }
      const stateText = state.pendingPipe.locked ? "끝 Junction 고정" : "마우스 추적 중";
      $("draw-readout").textContent = `${stateText} · ${source.node_id} → ${state.pendingPipe.to_node || "미지정"} · 거리 ${distance.toFixed(1)} m · 각도 ${angle.toFixed(0)}°`;
      $("confirm-pipe").disabled = !state.pendingPipe.locked;
      return;
    }
    $("draw-readout").textContent = "Junction 추가 또는 Pipe 그리기를 누른 뒤 지도 위에서 작업하세요.";
    $("confirm-junction").disabled = true;
    $("confirm-pipe").disabled = true;
    return;
  }
  const source = state.nodes.find((node) => node.node_id === $("source-junction").value);
  if (!source || !state.pendingJunction) {
    $("draw-readout").textContent = "기준 Junction을 선택한 뒤 지도 위로 마우스를 이동하세요.";
    $("confirm-junction").disabled = true;
    return;
  }
  const distance = distanceBetween(source, state.pendingJunction);
  const angle = angleBetween(source, state.pendingJunction);
  if (!state.pendingJunction.locked) {
    $("pipe-length").value = Math.max(40, Math.min(620, Math.round(distance / 5) * 5));
    $("pipe-angle").value = normalizeAngle(Math.round(angle / 5) * 5);
    syncPipeControlLabels();
  }
  const stateText = state.pendingJunction.locked ? "위치 고정" : "마우스 추적 중";
  $("draw-readout").textContent = `${stateText} · ${source.node_id} → ${state.pendingJunction.node_id} · 거리 ${distance.toFixed(1)} m · 각도 ${angle.toFixed(0)}°`;
  $("confirm-junction").disabled = !state.pendingJunction.locked;
}

function endpointForPipe(pipe, from, originalTo) {
  return originalTo;
}

function refreshSelectedDetail(snapshot) {
  if (bulkSelectionCount() > 1) {
    const nodeCount = state.multiSelectedNodes?.size || 0;
    const pipeCount = state.multiSelectedPipes?.size || 0;
    $("selection-detail").innerHTML = `<strong>다중 선택</strong>
      <span>Junction ${nodeCount}개 · Pipe ${pipeCount}개</span>
      <span>선택된 Junction을 드래그하면 연결된 선택 객체를 함께 이동합니다.</span>`;
    return;
  }
  if (!state.selected) return;
  const [kind, id] = state.selected.split(":");
  if (kind === "pipe") showPipeDetail(id, snapshot);
  if (kind === "node") showNodeDetail(id, snapshot);
}

function showPipeDetail(pipeId, snapshot) {
  const pipe = snapshot.pipes.find((item) => item.pipe_id === pipeId);
  if (!pipe) return;
  const score = state.aging.get(pipeId) || 0;
  const recommendation =
    pipe.status === "leak"
      ? "누수 복구와 격리 밸브 확인"
      : pipe.status === "overpressure"
        ? "감압 밸브, Pump 가압, 공급 수두 조정 검토"
      : pipe.status === "low"
        ? "Pump 가압 상향 또는 관경 확대 검토"
        : score > 0.68
          ? "노후도 기반 정밀 점검 우선"
          : "정상 감시";
  $("selection-detail").innerHTML = `<strong>Pipe ${pipeId}</strong>
    <span>${pipe.from_node} → ${pipe.to_node} · ${statusLabel(pipe.status)} · 말단 최소압 ${pipe.endpointPressure.toFixed(1)} m</span>
    <span>길이 ${pipe.length_m.toFixed(0)} m · 관경 ${pipe.diameter_mm.toFixed(0)} mm · 각도 ${pipe.angle_deg.toFixed(0)}°</span>
    <span>재질 ${pipe.material} · 설비 ${serviceLabel(pipe.service_type)} · 조도 C ${pipe.roughness_c.toFixed(0)} · 손실 K ${pipe.minor_loss_k.toFixed(1)}</span>
    <span>Bend/Elbow ${Number(pipe.bend_count || 0)}개 · Bend 각도 ${Number(pipe.bend_angle_deg || 0).toFixed(0)}° · 밸브 ${Number(pipe.valve_count || 0)}개</span>
    <span>누수량 ${Number(pipe.leakDemand || 0).toFixed(2)} L/s</span>
    <span>작용수두 ${pipe.pressureSafety.appliedHead.toFixed(1)} m · 허용수두 ${pipe.pressureSafety.allowableHead.toFixed(1)} m · 사용률 ${Math.round(pipe.pressureSafety.utilization * 100)}%</span>
    <span>추정 유량 ${pipe.flow_lps.toFixed(2)} L/s · 유속 ${pipe.flowVelocityMps.toFixed(2)} m/s · 수리수두차 ${pipe.headDeltaM.toFixed(2)} m</span>
    <span>HGL ${pipe.from_node} ${pipe.fromHead.toFixed(1)} m / ${pipe.to_node} ${pipe.toHead.toFixed(1)} m</span>
    <span>노후점수 ${score.toFixed(2)}</span>
    <strong>추천 조치</strong>
    <span>${recommendation}</span>`;
}

function showNodeDetail(nodeId, snapshot) {
  const node = snapshot.nodes.find((item) => item.node_id === nodeId);
  if (!node) return;
  $("selection-detail").innerHTML = `<strong>Junction ${nodeId}</strong>
    <span>압력 ${node.pressure.toFixed(1)} m · 기준 15 m ${node.compliant ? "충족" : "미달"}</span>
    <span>수요 ${node.localDemand.toFixed(2)} L/s · 표고 ${Number(node.elevation_m || 0).toFixed(1)} m · ${statusLabel(node.status)}</span>
    <span>좌표 X ${Number(node.x || 0).toFixed(1)} · Y ${Number(node.y || 0).toFixed(1)} · DMA ${node.dma_id}</span>`;
}

function renderPressureBars(snapshot) {
  const lowFirst = [...snapshot.nodes]
    .filter((node) => node.node_type !== "reservoir")
    .sort((a, b) => a.pressure - b.pressure)
    .slice(0, 9);
  $("pressure-bars").innerHTML = lowFirst
    .map((node) => barRow(node.node_id, clamp(node.pressure / 35), `${node.pressure.toFixed(1)} m`, statusColor(node.status)))
    .join("");
}

function renderReplacementRanking(snapshot) {
  const ranking = computeReplacementRanking(snapshot).slice(0, 8);
  const header = `<div class="ranking-row header"><span>#</span><span>Pipe</span><span>판단 근거</span><span>점수</span><span>상태</span></div>`;
  const rows = ranking
    .map((pipe, index) => {
      const reason = `노후 ${pipe.aging.toFixed(2)} · 누수이력 ${pipe.leak_history_count || 0} · 말단압 ${pipe.endpointPressure.toFixed(1)}m`;
      return `<div class="ranking-row">
        <strong>${index + 1}</strong>
        <strong>${pipe.pipe_id}</strong>
        <span>${reason}</span>
        <span>${Math.round(pipe.priorityScore * 100)}</span>
        <span>${statusLabel(pipe.status)}</span>
      </div>`;
    })
    .join("");
  $("replacement-ranking").innerHTML = header + rows;
}

function computeReplacementRanking(snapshot) {
  const nodeById = new Map(snapshot.nodes.map((node) => [node.node_id, node]));
  const degree = new Map();
  state.pipes.forEach((pipe) => {
    degree.set(pipe.from_node, (degree.get(pipe.from_node) || 0) + 1);
    degree.set(pipe.to_node, (degree.get(pipe.to_node) || 0) + 1);
  });
  const maxDegree = Math.max(...degree.values(), 1);
  const maxDemand = Math.max(...snapshot.nodes.map((node) => node.localDemand || 0), 1);

  return snapshot.pipes
    .map((pipe) => {
      const from = nodeById.get(pipe.from_node);
      const to = nodeById.get(pipe.to_node);
      const aging = state.aging.get(pipe.pipe_id) || 0;
      const leakHistory = clamp((pipe.leak_history_count || 0) / 3);
      const pressureVulnerability = clamp((MARGINAL_PRESSURE - pipe.endpointPressure) / MARGINAL_PRESSURE);
      const overpressureVulnerability = clamp((pipe.pressureSafety?.utilization || 0) - 0.75, 0, 0.45) / 0.45;
      const connectivity = clamp(((degree.get(pipe.from_node) || 0) + (degree.get(pipe.to_node) || 0)) / (maxDegree * 2));
      const demandImpact = clamp(((from?.localDemand || 0) + (to?.localDemand || 0)) / (maxDemand * 2));
      const hydraulicPenalty = clamp((pipe.length_m / Math.max(pipe.diameter_mm, 1)) / 2);
      const fittingPenalty = clamp(((pipe.bend_count || 0) + (pipe.valve_count || 0) + Number(pipe.bend_angle_deg || 0) / 45) / 10);
      const score =
        aging * 0.28 +
        leakHistory * 0.16 +
        Math.max(pressureVulnerability, overpressureVulnerability) * 0.23 +
        connectivity * 0.11 +
        demandImpact * 0.1 +
        hydraulicPenalty * 0.08 +
        fittingPenalty * 0.04;
      return { ...pipe, aging, priorityScore: clamp(score) };
    })
    .sort((a, b) => b.priorityScore - a.priorityScore);
}

function renderRecommendations(snapshot) {
  const recommendations = [];
  const lowNodes = snapshot.nodes.filter((node) => node.node_type !== "reservoir" && node.status === "low");
  const leakPipes = snapshot.pipes.filter((pipe) => pipe.status === "leak");
  const overpressurePipes = snapshot.pipes.filter((pipe) => pipe.pressureSafety?.overpressure);
  const topRisk = computeReplacementRanking(snapshot)[0];

  if (lowNodes.length) {
    recommendations.push(`저압 Junction ${lowNodes.length}개 발생. Pump 가압을 0.5~1.5 m 올려 압력 회복 민감도를 확인하세요.`);
  }
  if (leakPipes.length) {
    const names = leakPipes.map((pipe) => `${pipe.pipe_id} ${Number(pipe.leakDemand || 0).toFixed(2)} L/s`).join(", ");
    recommendations.push(`다중 누수 시나리오 활성: ${names}. 각 누수 지점의 인접 Junction 압력과 격리 밸브 상태를 우선 확인하세요.`);
  }
  if (overpressurePipes.length) {
    const names = overpressurePipes.map((pipe) => `${pipe.pipe_id} ${Math.round(pipe.pressureSafety.utilization * 100)}%`).join(", ");
    recommendations.push(`과압 위험 Pipe: ${names}. 수요 저하 시간대에는 공급 수두 또는 Pump 가압을 낮추는 제어를 검토하세요.`);
  }
  if (topRisk) {
    recommendations.push(`${topRisk.pipe_id}는 노후도와 압력 취약도가 동시에 높습니다. 관경 확대 또는 조도 개선 후보로 검토하세요.`);
  }
  recommendations.push("Pipe 설계 패널의 길이·관경·조도·손실계수는 EPANET의 Pipes 입력값으로 바로 매핑됩니다.");

  $("recommendations").innerHTML = recommendations.map((item) => `<li>${item}</li>`).join("");
}

function renderAlerts(snapshot) {
  const alerts = [];
  const lowNodes = snapshot.nodes.filter((node) => node.node_type !== "reservoir" && node.status === "low");
  const leakPipes = snapshot.pipes.filter((pipe) => pipe.status === "leak");
  const overpressurePipes = snapshot.pipes.filter((pipe) => pipe.pressureSafety?.overpressure);
  const pressureWarningPipes = snapshot.pipes.filter((pipe) => pipe.pressureSafety?.warning);
  const highVelocityPipes = snapshot.pipes.filter((pipe) => Number(pipe.flowVelocityMps || 0) > 2.5);
  const selectedPipe = snapshot.pipes.find((pipe) => state.selected === `pipe:${pipe.pipe_id}`);

  if (lowNodes.length) {
    const worst = [...lowNodes].sort((a, b) => a.pressure - b.pressure)[0];
    alerts.push(["high", "저압 발생", `${lowNodes.length}개 Junction이 15 m 미만입니다. 최저 지점은 ${worst.node_id}입니다.`]);
  }
  if (leakPipes.length) {
    const totalLeak = leakPipes.reduce((sum, pipe) => sum + Number(pipe.leakDemand || 0), 0);
    alerts.push(["medium", "다중 누수 시나리오", `${leakPipes.length}개 Pipe에서 총 ${totalLeak.toFixed(2)} L/s 누수를 반영했습니다.`]);
  }
  if (overpressurePipes.length) {
    const worst = [...overpressurePipes].sort((a, b) => b.pressureSafety.utilization - a.pressureSafety.utilization)[0];
    alerts.push(["high", "Pipe 과압 위험", `${worst.pipe_id} 작용수두 ${worst.pressureSafety.appliedHead.toFixed(1)} m / 허용수두 ${worst.pressureSafety.allowableHead.toFixed(1)} m (${Math.round(worst.pressureSafety.utilization * 100)}%).`]);
  } else if (pressureWarningPipes.length) {
    const worst = [...pressureWarningPipes].sort((a, b) => b.pressureSafety.utilization - a.pressureSafety.utilization)[0];
    alerts.push(["medium", "Pipe 허용수두 근접", `${worst.pipe_id}가 허용수두의 ${Math.round(worst.pressureSafety.utilization * 100)}% 수준입니다.`]);
  }
  if (highVelocityPipes.length) {
    const fastest = [...highVelocityPipes].sort((a, b) => b.flowVelocityMps - a.flowVelocityMps)[0];
    alerts.push(["medium", "고유속 Pipe", `${fastest.pipe_id} 추정 유속 ${fastest.flowVelocityMps.toFixed(2)} m/s입니다. 관경 확대 또는 밸브 손실을 확인하세요.`]);
  }
  if (selectedPipe) {
    alerts.push(["info", "EPANET 입력값", `${selectedPipe.pipe_id}: Length ${selectedPipe.length_m.toFixed(0)} m, Diameter ${selectedPipe.diameter_mm.toFixed(0)} mm, Roughness ${selectedPipe.roughness_c.toFixed(0)}.`]);
  }

  $("alerts").innerHTML = alerts.map(([level, title, body]) => `<div class="alert-card ${level}"><strong>${title}</strong><span>${body}</span></div>`).join("");
}

function renderLeakList() {
  const leaks = [...state.leakDemands].filter(([, demand]) => Number(demand) > 0);
  if (!leaks.length) {
    $("leak-list").innerHTML = `<div class="empty-row">활성 누수 지점이 없습니다. Pipe를 선택하고 누수를 추가하세요.</div>`;
    return;
  }
  $("leak-list").innerHTML = leaks
    .map(
      ([pipeId, demand]) => `<div class="leak-row">
        <strong>${pipeId}</strong>
        <input data-leak-pipe="${pipeId}" type="range" min="0" max="8" step="0.25" value="${Number(demand).toFixed(2)}" />
        <span>${Number(demand).toFixed(2)} L/s</span>
        <button class="text-button danger-button" data-remove-leak="${pipeId}" type="button">제거</button>
      </div>`,
    )
    .join("");
  $("leak-list").querySelectorAll("[data-leak-pipe]").forEach((input) => {
    input.addEventListener("input", () => updateLeakDemand(input.dataset.leakPipe, Number(input.value || 0)));
  });
  $("leak-list").querySelectorAll("[data-remove-leak]").forEach((button) => {
    button.addEventListener("click", () => removeLeakPipe(button.dataset.removeLeak));
  });
}

function addLeakPipe(pipeId, demand = 0) {
  if (!pipeId) return;
  state.leakDemands.set(pipeId, Math.max(Number(demand || 0), 0.25));
  state.editorTab = "leak";
  state.selected = `pipe:${pipeId}`;
  if ($("selected-pipe").querySelector(`option[value="${pipeId}"]`)) $("selected-pipe").value = pipeId;
  render();
}

function updateLeakDemand(pipeId, demand) {
  if (!pipeId) return;
  if (demand <= 0) {
    state.leakDemands.delete(pipeId);
  } else {
    state.leakDemands.set(pipeId, demand);
  }
  render();
}

function removeLeakPipe(pipeId) {
  state.leakDemands.delete(pipeId);
  render();
}

function renderDemandChart() {
  const svg = $("demand-chart");
  const width = 520;
  const height = 230;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const points = state.timeline.map((minute) => {
    const demand = [...nodeDemandAt(minute).values()].reduce((sum, value) => sum + Number(value || 0), 0) * Number($("demand-scale").value || 1);
    return { minute, demand };
  });
  const maxDemand = Math.max(...points.map((point) => point.demand), 1);
  const x = (minute) => 32 + (minute / 1430) * (width - 58);
  const y = (demand) => height - 30 - (demand / maxDemand) * (height - 58);
  const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(point.minute).toFixed(1)} ${y(point.demand).toFixed(1)}`).join(" ");
  const currentX = x(currentMinute());

  svg.innerHTML = `
    <path class="chart-grid" d="M32 20V200H500" />
    <path class="demand-line" d="${line}" />
    <line class="time-cursor" x1="${currentX}" x2="${currentX}" y1="22" y2="200" />
    <text class="chart-label" x="32" y="218">00:00</text>
    <text class="chart-label" x="242" y="218">12:00</text>
    <text class="chart-label" x="462" y="218">24:00</text>
  `;
}

function updatePipeEditFromControls() {
  if (state.addMode || state.pipeDrawMode) {
    if (state.pendingJunction?.locked) {
      const source = state.nodes.find((node) => node.node_id === $("source-junction").value);
      if (source) {
        state.pendingJunction = {
          ...state.pendingJunction,
          ...pointFromPolar(source, Number($("pipe-length").value || 0), Number($("pipe-angle").value || 0)),
        };
      }
    }
    if (state.pendingPipe?.locked) {
      const source = state.nodes.find((node) => node.node_id === $("source-junction").value);
      if (source) {
        state.pendingPipe = {
          ...state.pendingPipe,
          ...pointFromPolar(source, Number($("pipe-length").value || 0), Number($("pipe-angle").value || 0)),
        };
      }
    }
    syncPipeControlLabels();
    updateDrawReadout();
    render();
    return;
  }
  const pipeId = selectedPipeId();
  const pipe = state.pipes.find((item) => item.pipe_id === pipeId);
  if (!pipe) return;
  const edit = {
    angle_deg: Number($("pipe-angle").value),
    length_m: Number($("pipe-length").value),
    diameter_mm: Number($("pipe-diameter").value),
    roughness_c: Number($("pipe-roughness").value),
    minor_loss_k: Number($("pipe-minor-loss").value),
    bend_angle_deg: Number($("pipe-bend-angle").value),
    bend_count: Number($("pipe-bend-count").value),
    valve_count: Number($("pipe-valve-count").value),
    material: $("pipe-material").value,
    service_type: $("pipe-service-type").value,
  };
  state.pipeEdits.set(pipeId, edit);
  reflowNetworkGeometry();
  render();
}

function syncPipeEditor() {
  if (state.addMode || state.pipeDrawMode) {
    syncPipeControlLabels();
    return;
  }
  const pipeId = selectedPipeId();
  const pipe = state.pipes.find((item) => item.pipe_id === pipeId);
  if (!pipe) return;
  const design = pipeDesign(pipe);
  setControlValue("pipe-angle", design.angle_deg);
  setControlValue("pipe-length", design.length_m);
  setControlValue("pipe-diameter", design.diameter_mm);
  setControlValue("pipe-roughness", design.roughness_c);
  setControlValue("pipe-minor-loss", design.minor_loss_k);
  setControlValue("pipe-bend-angle", design.bend_angle_deg);
  setControlValue("pipe-bend-count", design.bend_count);
  setControlValue("pipe-valve-count", design.valve_count);
  $("pipe-material").value = design.material;
  $("pipe-service-type").value = design.service_type;
  syncPipeControlLabels();
}

function syncPipeControlLabels() {
  $("pipe-angle-value").textContent = `${Math.round(Number($("pipe-angle").value || 0))}°`;
  $("pipe-length-value").textContent = `${Math.round(Number($("pipe-length").value || 0))} m`;
  $("pipe-diameter-value").textContent = `${Math.round(Number($("pipe-diameter").value || 0))} mm`;
  $("pipe-roughness-value").textContent = `${Math.round(Number($("pipe-roughness").value || 0))}`;
  $("pipe-minor-loss-value").textContent = `${Number($("pipe-minor-loss").value || 0).toFixed(1)}`;
  $("pipe-bend-angle-value").textContent = `${Math.round(Number($("pipe-bend-angle").value || 0))}°`;
  $("pipe-bend-count-value").textContent = `${Math.round(Number($("pipe-bend-count").value || 0))}`;
  $("pipe-valve-count-value").textContent = `${Math.round(Number($("pipe-valve-count").value || 0))}`;
}

function syncJunctionEditor() {
  const node = selectedJunction();
  if (!node || node.node_type === "reservoir") return;
  setControlValue("junction-x", Number(node.x || 0));
  setControlValue("junction-y", Number(node.y || 0));
  setControlValue("junction-elevation", Number(node.elevation_m || 0));
  setControlValue("junction-demand", Number(node.base_demand_lps || 0));
  $("junction-dma").value = node.dma_id || "";
  syncJunctionControlLabels();
}

function syncSourceEditor() {
  const sourceId = $("selected-source").value || (state.selected?.startsWith("node:") ? state.selected.split(":")[1] : "");
  const source = state.nodes.find((node) => node.node_id === sourceId && node.node_type === "reservoir");
  if (!source) return;
  const reservoir = state.reservoirs.find((item) => item.node_id === source.node_id);
  const pump = sourcePumpFor(source.node_id);
  const pipe = sourcePipeFor(source.node_id);
  const target = sourceTargetFor(source.node_id);
  setControlValue("source-x", Math.round(Number(source.x || 0)));
  setControlValue("source-y", Math.round(Number(source.y || 0)));
  if (target && $("source-connect-junction").querySelector(`option[value="${target.node_id}"]`)) {
    $("source-connect-junction").value = target.node_id;
    setControlValue("source-pipe-length", Math.round(distanceBetween(source, target)));
  }
  if (reservoir) setControlValue("source-design-head", Number(reservoir.head_m || 58));
  if (pump) setControlValue("source-pump-gain", Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1));
  if (pipe) {
    const design = pipeDesign(pipe);
    setControlValue("source-pipe-diameter", Number(design.diameter_mm || pipe.diameter_mm || 300));
    setControlValue("source-pipe-roughness", Number(design.roughness_c || 100));
  }
  syncSourceControlLabels();
}

function syncJunctionControlLabels() {
  $("junction-x-value").textContent = `${Number($("junction-x").value || 0).toFixed(0)}`;
  $("junction-y-value").textContent = `${Number($("junction-y").value || 0).toFixed(0)}`;
  $("junction-elevation-value").textContent = `${Number($("junction-elevation").value || 0).toFixed(1)} m`;
  $("junction-demand-value").textContent = `${Number($("junction-demand").value || 0).toFixed(2)} L/s`;
}

function syncSourceControlLabels() {
  $("source-design-head-value").textContent = `${Number($("source-design-head").value || 0).toFixed(1)} m`;
  $("source-pump-gain-value").textContent = `${Number($("source-pump-gain").value || 0).toFixed(1)} m`;
  $("source-pipe-diameter-value").textContent = `${Math.round(Number($("source-pipe-diameter").value || 0))} mm`;
  $("source-pipe-length-value").textContent = `${Math.round(Number($("source-pipe-length").value || 0))} m`;
  $("source-pipe-roughness-value").textContent = `${Math.round(Number($("source-pipe-roughness").value || 0))}`;
}

function suggestSourcePumpPosition() {
  const target = state.nodes.find((node) => node.node_id === $("source-connect-junction").value);
  if (!target) return;
  const length = Number($("source-pipe-length").value || 120);
  const point = pointFromPolar(target, length, 180);
  $("source-x").value = Math.round(point.x);
  $("source-y").value = Math.round(point.y);
  $("new-source-id").value = nextSourceId();
  if (state.sourceDrawMode) {
    state.pendingSource = buildPendingSource(point, false);
    syncSourceDraftControls();
    render();
    return;
  }
  syncSourceControlLabels();
  $("source-readout").textContent = `${target.node_id}에 연결할 Source/Pump 위치를 제안했습니다. 필요하면 X/Y를 직접 조정하세요.`;
}

function syncSourceDraftControls() {
  if (!state.pendingSource) return;
  const target = state.nodes.find((node) => node.node_id === $("source-connect-junction").value);
  setControlValue("source-x", Math.round(Number(state.pendingSource.x || 0)));
  setControlValue("source-y", Math.round(Number(state.pendingSource.y || 0)));
  if (target) setControlValue("source-pipe-length", Math.round(distanceBetween(target, state.pendingSource)));
  syncSourceControlLabels();
}

function updateSourceEditFromControls(event = null) {
  updateSourcePositionFromControls(event);
  syncSourceControlLabels();
}

function updateSourcePositionFromControls(event = null) {
  const targetId = $("source-connect-junction").value || firstJunctionId();
  const target = state.nodes.find((node) => node.node_id === targetId && node.node_type !== "reservoir");
  const sourceId = $("selected-source").value || (state.selected?.startsWith("node:") ? state.selected.split(":")[1] : "");
  const source = state.nodes.find((node) => node.node_id === sourceId && node.node_type === "reservoir");
  const length = Number($("source-pipe-length").value || 120);
  const inputId = event?.target?.id || "";

  let point = {
    x: Number($("source-x").value || source?.x || target?.x || 0),
    y: Number($("source-y").value || source?.y || target?.y || 0),
  };
  if (inputId === "source-pipe-length" && target) {
    const angle = state.pendingSource
      ? angleBetween(target, state.pendingSource)
      : source
        ? angleBetween(target, source)
        : 180;
    point = pointFromPolar(target, length, angle);
  }

  if (state.sourceDrawMode) {
    state.pendingSource = buildPendingSource(point, Boolean(state.pendingSource?.locked));
    syncSourceDraftControls();
    render();
    return;
  }

  if (!source) return;
  Object.assign(source, point);
  state.baseNodeGeometry.set(source.node_id, baseNodeState(source));
  const reservoir = state.reservoirs.find((item) => item.node_id === source.node_id);
  if (reservoir) reservoir.head_m = Number($("source-design-head").value || reservoir.head_m || 58);
  const pump = sourcePumpFor(source.node_id);
  if (pump) {
    pump.base_head_gain_m = Number($("source-pump-gain").value || 0);
    pump.speed_multiplier = 1;
  }
  const pipe = sourcePipeFor(source.node_id);
  const connectedTarget = sourceTargetFor(source.node_id) || target;
  if (pipe && connectedTarget) {
    const design = {
      ...pipeDesign(pipe),
      angle_deg: angleBetween(source, connectedTarget),
      length_m: distanceBetween(source, connectedTarget),
      diameter_mm: Number($("source-pipe-diameter").value || pipe.diameter_mm || 300),
      roughness_c: Number($("source-pipe-roughness").value || 100),
      material: pipe.material || "ductile_iron",
      service_type: pipe.service_type || "transmission",
    };
    Object.assign(pipe, {
      length_m: design.length_m,
      diameter_mm: design.diameter_mm,
      material: design.material,
      service_type: design.service_type,
    });
    state.pipeEdits.set(pipe.pipe_id, design);
  }
  setControlValue("source-x", Math.round(Number(source.x || 0)));
  setControlValue("source-y", Math.round(Number(source.y || 0)));
  if (connectedTarget) setControlValue("source-pipe-length", Math.round(distanceBetween(source, connectedTarget)));
  $("source-head").value = reservoir?.head_m ?? $("source-design-head").value;
  $("pump-head").value = pump ? Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1) : $("source-pump-gain").value;
  render();
}

function updateJunctionEditFromControls() {
  const node = selectedJunction();
  if (!node || node.node_type === "reservoir") return;
  Object.assign(node, {
    x: Number($("junction-x").value),
    y: Number($("junction-y").value),
    elevation_m: Number($("junction-elevation").value),
    base_demand_lps: Number($("junction-demand").value),
    dma_id: $("junction-dma").value.trim() || node.dma_id,
  });
  state.baseNodeGeometry.set(node.node_id, baseNodeState(node));
  syncJunctionControlLabels();
  refreshAssetOptions();
  $("selected-junction").value = node.node_id;
  render();
}

function resetSelectedJunctionEdit() {
  const node = selectedJunction();
  if (!node) return;
  const original = state.originalNodeGeometry.get(node.node_id);
  if (!original) return;
  Object.assign(node, original);
  state.baseNodeGeometry.set(node.node_id, baseNodeState(node));
  syncJunctionEditor();
  render();
}

function selectedJunction() {
  const [kind, id] = (state.selected || "").split(":");
  const nodeId = kind === "node" ? id : $("selected-junction").value;
  return state.nodes.find((node) => node.node_id === nodeId);
}

function setControlValue(id, value) {
  if (Number($(id).value) !== Number(value)) $(id).value = value;
}

function applyPipeEditToRuntimeAsset(pipe, edit) {
  Object.assign(pipe, {
    length_m: edit.length_m,
    diameter_mm: edit.diameter_mm,
    material: edit.material,
    service_type: edit.service_type,
    bend_angle_deg: edit.bend_angle_deg,
    bend_count: edit.bend_count,
    valve_count: edit.valve_count,
  });
  const source = state.nodes.find((node) => node.node_id === pipe.from_node);
  const target = state.nodes.find((node) => node.node_id === pipe.to_node);
  if (!source || !target || target.node_type === "reservoir") return;
  Object.assign(target, pointFromPolar(source, edit.length_m, edit.angle_deg));
}

function reflowNetworkGeometry() {
  for (const node of state.nodes) {
    const base = state.baseNodeGeometry.get(node.node_id);
    if (base) Object.assign(node, base);
  }
  for (const [pipeId, edit] of state.pipeEdits) {
    const pipe = state.pipes.find((item) => item.pipe_id === pipeId);
    if (pipe) applyPipeEditToRuntimeAsset(pipe, edit);
  }
}

function pipeDesign(pipe) {
  const from = state.nodes.find((node) => node.node_id === pipe.from_node);
  const to = state.nodes.find((node) => node.node_id === pipe.to_node);
  const baseAngle = from && to ? angleBetween(from, to) : 0;
  const defaults = {
    angle_deg: baseAngle,
    length_m: Number(pipe.length_m || 100),
    diameter_mm: Number(pipe.diameter_mm || 150),
    roughness_c: 100,
    minor_loss_k: 0,
    bend_angle_deg: Number(pipe.bend_angle_deg || 0),
    bend_count: Number(pipe.bend_count || 0),
    valve_count: Number(pipe.valve_count || 0),
    material: pipe.material || "PVC",
    service_type: pipe.service_type || "distribution",
  };
  return { ...defaults, ...(state.pipeEdits.get(pipe.pipe_id) || {}) };
}

function resetSelectedPipeEdit() {
  state.pipeEdits.delete(selectedPipeId());
  reflowNetworkGeometry();
  render();
}

function selectPipe(pipeId) {
  clearBulkSelection();
  state.selected = `pipe:${pipeId}`;
  state.editorTab = "pipe";
  $("selected-pipe").value = pipeId;
  syncPipeEditor();
  render();
}

function selectNode(nodeId) {
  clearBulkSelection();
  const node = state.nodes.find((item) => item.node_id === nodeId);
  if (node?.node_type === "reservoir") {
    state.selected = `node:${nodeId}`;
    state.editorTab = "source";
    if ($("selected-source").querySelector(`option[value="${nodeId}"]`)) $("selected-source").value = nodeId;
    syncSourceEditor();
    $("source-readout").textContent = `${nodeId} Source가 선택되었습니다. 새 Source/Pump를 추가하려면 연결 Junction을 선택하세요.`;
    render();
    return;
  }
  state.selected = `node:${nodeId}`;
  state.editorTab = "junction";
  if ($("selected-junction").querySelector(`option[value="${nodeId}"]`)) $("selected-junction").value = nodeId;
  render();
}

function selectSourcePump(sourceId) {
  if (!sourceId) return;
  state.selected = `node:${sourceId}`;
  state.editorTab = "source";
  $("selected-source").value = sourceId;
  const reservoir = state.reservoirs.find((item) => item.node_id === sourceId);
  const pump = state.pumps.find((item) => item.from_node === sourceId || item.to_node === sourceId);
  if (reservoir) $("source-design-head").value = Number(reservoir.head_m || 58);
  if (pump) $("source-pump-gain").value = Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1);
  syncSourceEditor();
  $("source-readout").textContent = `${sourceId} Source/Pump가 선택되었습니다. 삭제하거나 새 Source/Pump를 추가할 수 있습니다.`;
  render();
}

function selectedPipeId() {
  const [kind, id] = (state.selected || "").split(":");
  return kind === "pipe" ? id : $("selected-pipe").value;
}

function togglePlayback() {
  if (state.playbackTimer) {
    stopPlayback();
    return;
  }
  $("play-toggle").textContent = "Ⅱ";
  state.playbackTimer = setInterval(() => {
    const slider = $("time-slider");
    slider.value = (Number(slider.value) + 1) % state.timeline.length;
    render();
  }, Math.max(80, 900 / state.playbackSpeed));
}

function stopPlayback() {
  clearInterval(state.playbackTimer);
  state.playbackTimer = null;
  $("play-toggle").textContent = "▶";
}

function setPlaybackSpeed(speed) {
  state.playbackSpeed = speed;
  document.querySelectorAll(".speed-button").forEach((button) => button.classList.toggle("active", Number(button.dataset.speed) === speed));
  if (state.playbackTimer) {
    stopPlayback();
    togglePlayback();
  }
}

function resetScenario() {
  $("time-slider").value = Math.min(42, state.timeline.length - 1);
  $("demand-scale").value = 1;
  $("demand-profile").value = state.demandProfile || "metro";
  $("source-head").value = Number(state.reservoirs[0]?.head_m || 58);
  const pump = state.pumps.find((item) => String(item.status || "on").toLowerCase() !== "off");
  $("pump-head").value = pump ? Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1) : 0;
  $("leak-pipe").value = state.pipes.some((pipe) => pipe.pipe_id === "P14") ? "P14" : state.pipes[0]?.pipe_id || "";
  $("leak-demand").value = 2;
  state.leakDemands.clear();
  render();
}

function currentMinute() {
  return state.timeline[Number($("time-slider").value || 0)] || 0;
}

function minuteOfDay(timestamp) {
  const match = String(timestamp).match(/(\d{2}):(\d{2})/);
  if (!match) return 0;
  return Number(match[1]) * 60 + Number(match[2]);
}

function formatMinute(minute) {
  const wrapped = ((minute % 1440) + 1440) % 1440;
  const hour = Math.floor(wrapped / 60);
  const min = wrapped % 60;
  return `${String(hour).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
}

function circularMinuteDistance(a, b) {
  const distance = Math.abs(a - b);
  return Math.min(distance, 1440 - distance);
}

function normalizeAngle(angle) {
  return ((angle % 360) + 360) % 360;
}

function distanceBetween(from, to) {
  return Math.hypot(Number(to.x || 0) - Number(from.x || 0), Number(to.y || 0) - Number(from.y || 0));
}

function angleBetween(from, to) {
  return normalizeAngle((Math.atan2(Number(to.y || 0) - Number(from.y || 0), Number(to.x || 0) - Number(from.x || 0)) * 180) / Math.PI);
}

function pointFromPolar(source, length, angle) {
  const radians = (normalizeAngle(angle) * Math.PI) / 180;
  return {
    x: Number(source.x || 0) + Math.cos(radians) * length,
    y: Number(source.y || 0) + Math.sin(radians) * length,
  };
}

function baseNodeState(node) {
  return {
    x: Number(node.x || 0),
    y: Number(node.y || 0),
    elevation_m: Number(node.elevation_m || 0),
    base_demand_lps: Number(node.base_demand_lps || 0),
    dma_id: node.dma_id || "",
  };
}

function nextJunctionId() {
  let index = state.nodes.filter((node) => String(node.node_id).startsWith("J_NEW_")).length + 1;
  while (state.nodes.some((node) => node.node_id === `J_NEW_${index}`)) index += 1;
  return `J_NEW_${index}`;
}

function nextPipeId() {
  let index = state.pipes.filter((pipe) => String(pipe.pipe_id).startsWith("P_NEW_")).length + 1;
  while (state.pipes.some((pipe) => pipe.pipe_id === `P_NEW_${index}`)) index += 1;
  return `P_NEW_${index}`;
}

function nextSourceId() {
  let index = state.nodes.filter((node) => String(node.node_id).startsWith("R_NEW_")).length + 1;
  while (state.nodes.some((node) => node.node_id === `R_NEW_${index}`)) index += 1;
  return `R_NEW_${index}`;
}

function uniqueNodeId(preferredId) {
  const base = preferredId || nextJunctionId();
  if (!state.nodes.some((node) => node.node_id === base)) return base;
  let index = 2;
  while (state.nodes.some((node) => node.node_id === `${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

function uniqueSourceId(preferredId) {
  const base = preferredId || nextSourceId();
  if (!state.nodes.some((node) => node.node_id === base)) return base;
  let index = 2;
  while (state.nodes.some((node) => node.node_id === `${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

function serviceLabel(serviceType) {
  return {
    distribution: "배수관",
    transmission: "송수관",
    service: "급수관",
    bypass: "우회관",
  }[serviceType] || "배수관";
}

function pipeTouches(pipeId, nodeId) {
  const pipe = state.pipes.find((item) => item.pipe_id === pipeId);
  return pipe && (pipe.from_node === nodeId || pipe.to_node === nodeId);
}

function agingScore(pipe) {
  const mat = pipe.material || "unknown";
  const age = clamp((CURRENT_YEAR - pipe.install_year) / (designLife[mat] || designLife.unknown));
  const material = clamp(materialRisk[mat] ?? materialRisk.unknown);
  const repair = clamp((pipe.repair_count || 0) / 5);
  const leakHistory = clamp((pipe.leak_history_count || 0) / 3);
  const geometry = clamp(((pipe.bend_count || 0) + (pipe.valve_count || 0)) / 8);
  const soil = soilRisk(pipe);
  const traffic = clamp(pipe.traffic_load_index || 0);
  return clamp(
    weights.age * age +
      weights.material * material +
      weights.repair * repair +
      weights.leak_history * leakHistory +
      weights.geometry * geometry +
      weights.soil * soil +
      weights.traffic * traffic,
  );
}

function soilRisk(pipe) {
  const ph = pipe.soil_ph || 7;
  const resistivity = pipe.soil_resistivity_ohm_cm || 3000;
  const phRisk = ph < 6 ? 1 : ph < 6.5 ? 0.75 : ph < 7.5 ? 0.35 : 0.45;
  const resRisk = resistivity < 1000 ? 1 : resistivity < 2000 ? 0.75 : resistivity < 5000 ? 0.4 : 0.2;
  return clamp((phRisk + resRisk) / 2);
}

function barRow(label, value, text, color) {
  return `<div class="bar-row"><span>${label}</span><div class="bar-track"><div class="bar-fill" style="width:${clamp(value) * 100}%;background:${color}"></div></div><span>${text}</span></div>`;
}

function statusColor(status) {
  return status === "overpressure" ? "#111827" : status === "low" ? "#dc2626" : status === "marginal" ? "#d97706" : "#247a5a";
}

function statusLabel(status) {
  return status === "overpressure" ? "과압" : status === "low" ? "저압" : status === "marginal" ? "주의" : status === "leak" ? "누수" : "정상";
}

function clamp(value, min = 0, max = 1) {
  return Math.max(min, Math.min(max, Number(value) || 0));
}

function fallbackData() {
  return {
    "nodes.csv": [
      { node_id: "R1", x: -120, y: 0, elevation_m: 38, base_demand_lps: 0, node_type: "reservoir", dma_id: "SOURCE" },
      { node_id: "J1", x: 0, y: 0, elevation_m: 32.8, base_demand_lps: 0.9, node_type: "junction", dma_id: "DMA_A" },
      { node_id: "J2", x: 120, y: 0, elevation_m: 33, base_demand_lps: 1.1, node_type: "junction", dma_id: "DMA_A" },
      { node_id: "J3", x: 240, y: 40, elevation_m: 34, base_demand_lps: 1.4, node_type: "junction", dma_id: "DMA_B" },
      { node_id: "J4", x: 360, y: 20, elevation_m: 34.5, base_demand_lps: 1.3, node_type: "junction", dma_id: "DMA_B" },
    ],
    "pipes.csv": [
      { pipe_id: "P1", from_node: "R1", to_node: "J1", length_m: 140, diameter_mm: 250, material: "ductile_iron", install_year: 1998 },
      { pipe_id: "P2", from_node: "J1", to_node: "J2", length_m: 120, diameter_mm: 180, material: "steel", install_year: 1988 },
      { pipe_id: "P3", from_node: "J2", to_node: "J3", length_m: 150, diameter_mm: 150, material: "cast_iron", install_year: 1982 },
      { pipe_id: "P4", from_node: "J3", to_node: "J4", length_m: 130, diameter_mm: 120, material: "PVC", install_year: 2010 },
    ],
    "reservoirs.csv": [{ node_id: "R1", head_m: 58 }],
    "pumps.csv": [{ pump_id: "PU1", from_node: "R1", to_node: "J1", base_head_gain_m: 3, speed_multiplier: 1, status: "on" }],
    "valves.csv": [],
    "households.csv": [],
    "household_demand_timeseries.csv": [],
  };
}
