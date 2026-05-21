const MIN_PRESSURE = 15;
const MARGINAL_PRESSURE = 20;
const CURRENT_YEAR = 2026;
const DRAWING_SAMPLE_LIMIT = 100;
const MAP_ZOOM_MIN = 0.6;
const MAP_ZOOM_MAX = 14;
const MAP_WHEEL_ZOOM_SENSITIVITY = 0.0014;
const HYDRAULIC_BUSY_MIN_MS = 800;

const CONTROL_VALID_MAX = {
  "source-head": 250,
  "pump-head": 150,
  "source-design-head": 250,
  "source-pump-gain": 150,
  "source-pipe-diameter": 3000,
  "pipe-diameter": 3000,
  "bulk-pipe-diameter": 3000,
  "junction-demand": 100,
  "bulk-junction-demand": 100,
  "leak-demand": 100,
  "demand-scale": 5,
};

const PIPE_COLORS = {
  ok: "#2563eb",
  marginal: "#d97706",
  low: "#dc2626",
  leak: "#7c3aed",
  overpressure: "#111827",
};

const WATER_DENSITY_KG_M3 = 1000;
const GRAVITY_M_S2 = 9.80665;
const KINEMATIC_VISCOSITY_M2_S = 1.004e-6;

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
  demandPatterns: [],
  energyOptions: {},
  pumpEnergy: [],
  activeDemandMode: "profile",
  demandProfile: "metro",
  headlossFormula: "H-W",
  initialData: null,
  demandByMinute: new Map(),
  timeline: [],
  pipeEdits: new Map(),
  leakDemands: new Map(),
  baseNodeGeometry: new Map(),
  originalNodeGeometry: new Map(),
  aging: new Map(),
  selected: null,
  dashboardMode: "ops",
  editorTab: "source",
  addMode: false,
  pipeDrawMode: false,
  sourceDrawMode: false,
  pendingJunction: null,
  pendingPipe: null,
  pendingSource: null,
  mapFrame: null,
  mapZoom: 1,
  mapPanEnabled: false,
  mapLayer: "pressure",
  mapCenter: { x: 560, y: 325 },
  mapViewBox: { x: 0, y: 0, width: 1120, height: 650 },
  draggingNodeId: "",
  mapPan: null,
  multiSelectedNodes: new Set(),
  multiSelectedPipes: new Set(),
  selectionBox: null,
  selectionMoved: false,
  bulkMove: null,
  playbackTimer: null,
  playbackSpeed: 1,
  backendSimulation: null,
  backendSimulationSignature: "",
  backendSimulationPending: false,
  backendSimulationStatusMessage: "",
  backendSimulationStatusLevel: "",
  sourcePumpOptimizationPending: false,
  optimizedControlBoostM: 0,
  optimizedControlSignatureBase: "",
  hasUnsavedChanges: false,
  drawingFile: null,
  drawingFileType: null,
  drawingImage: null,
  drawingAssets: null,
  drawingAssetsApplied: false,
  drawingRecognition: null,
  recognitionCandidateStates: new Map(),
  recognitionFilter: "all",
  highlightedRecognitionCandidate: null,
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
  const { nodes, pipes, reservoirs, pumps, valves, households, demandSeries, demandPatterns, energyOptions, pumpEnergy } = emptyDashboardData();
  Object.assign(state, { nodes, pipes, reservoirs, pumps, valves, households, demandSeries, demandPatterns, energyOptions, pumpEnergy });
  state.initialData = {
    nodes: cloneRows(nodes),
    pipes: cloneRows(pipes),
    reservoirs: cloneRows(reservoirs),
    pumps: cloneRows(pumps),
    valves: cloneRows(valves),
    households: cloneRows(households),
    demandSeries: cloneRows(demandSeries),
    demandPatterns: cloneRows(demandPatterns),
    energyOptions: { ...energyOptions },
    pumpEnergy: cloneRows(pumpEnergy),
    activeDemandMode: state.activeDemandMode,
  };
  state.baseNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.originalNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.aging = new Map(state.pipes.map((pipe) => [pipe.pipe_id, agingScore(pipe)]));
  buildDemandIndex();
  initControls();
  render();
  applyInjectedRecognitionAssets();
}

function emptyDashboardData() {
  return {
    nodes: [],
    pipes: [],
    reservoirs: [],
    pumps: [],
    valves: [],
    households: [],
    demandSeries: [],
    demandPatterns: [],
    energyOptions: {},
    pumpEnergy: [],
  };
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
  initDashboardModeTabs();

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

  $("time-slider").addEventListener("input", render);
  ["demand-profile", "demand-scale", "source-head", "pump-head"].forEach((id) => {
    $(id).addEventListener("input", () => {
      clearOptimizedControlBoost();
      render();
    });
  });
  ["leak-pipe", "leak-demand"].forEach((id) => {
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
  document.querySelectorAll("[data-map-layer]").forEach((button) => {
    button.addEventListener("click", () => setMapLayer(button.dataset.mapLayer));
  });

  $("map-zoom-in").addEventListener("click", () => zoomMap(1.2));
  $("map-zoom-out").addEventListener("click", () => zoomMap(1 / 1.2));
  $("map-zoom-reset").addEventListener("click", resetMapZoom);
  $("map-pan-toggle")?.addEventListener("click", toggleMapPanMode);
  $("play-toggle").addEventListener("click", togglePlayback);
  $("reset-scenario").addEventListener("click", resetScenario);
  $("add-leak-pipe").addEventListener("click", () => addLeakPipe($("leak-pipe").value, Number($("leak-demand").value || 0)));
  $("run-backend-simulation")?.addEventListener("click", runBackendSimulation);
  $("optimize-source-pump")?.addEventListener("click", runSourcePumpOptimization);
  $("download-professional-report")?.addEventListener("click", downloadProfessionalReport);
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
  setDashboardMode(state.dashboardMode);
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

function initDashboardModeTabs() {
  document.querySelectorAll("[data-dashboard-mode-target]").forEach((button) => {
    button.addEventListener("click", () => setDashboardMode(button.dataset.dashboardModeTarget || "ops"));
  });
}

function setDashboardMode(mode) {
  const nextMode = ["ops", "scenario", "diagnostics"].includes(mode) ? mode : "ops";
  state.dashboardMode = nextMode;
  const summaries = {
    ops: "관망 상태를 확인하고 지도에서 바로 자산을 선택·편집합니다.",
    scenario: "수요, 누수, Source/Pump 조건을 바꾸고 최적값을 계산합니다.",
    diagnostics: "저압 원인, 위험도, 수질·화재유량 진단과 리포트를 확인합니다.",
  };
  $("dashboard-mode-summary").textContent = summaries[nextMode];
  $("dashboard-view")?.setAttribute("data-dashboard-mode-current", nextMode);

  document.querySelectorAll("[data-dashboard-mode-target]").forEach((button) => {
    const active = button.dataset.dashboardModeTarget === nextMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-dashboard-mode]").forEach((panel) => {
    const modes = String(panel.dataset.dashboardMode || "").split(/\s+/);
    panel.classList.toggle("active", modes.includes(nextMode));
  });
}

function initDrawingRecognition() {
  $("drawing-file").addEventListener("change", handleDrawingFile);
  ["drawing-scale", "drawing-diameter", "drawing-material"].forEach((id) => {
    $(id).addEventListener("input", () => {
      if (state.drawingRecognition && state.drawingAssets) renderDrawingRecognition(state.drawingAssets);
    });
  });
  $("analyze-drawing").addEventListener("click", analyzeDrawingImage);
  $("apply-recognition-assets").addEventListener("click", applyCurrentRecognitionAssets);
  $("download-assets-json").addEventListener("click", () => downloadRecognitionAsset("json"));
  $("download-nodes-csv").addEventListener("click", () => downloadRecognitionAsset("nodes"));
  $("download-pipes-csv").addEventListener("click", () => downloadRecognitionAsset("pipes"));
  $("download-reservoirs-csv").addEventListener("click", () => downloadRecognitionAsset("reservoirs"));
  document.querySelectorAll("[data-recognition-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.recognitionFilter = button.dataset.recognitionFilter || "all";
      renderRecognitionCandidateReview();
    });
  });
}

function handleDrawingFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const fileType = classifyDrawingFile(file);
  state.drawingFile = fileType === "inp" ? file : null;
  state.drawingFileType = fileType;
  state.drawingImage = null;
  state.drawingRecognition = null;
  state.drawingAssets = null;
  state.drawingAssetsApplied = false;
  state.recognitionCandidateStates = new Map();
  state.highlightedRecognitionCandidate = null;
  state.drawingPipeSamples = [];
  state.drawingJunctionSamples = [];
  state.drawingSourceSamples = [];
  state.drawingSampleMode = false;
  state.drawingJunctionMode = false;
  state.drawingSourceMode = false;
  $("recognized-export-state").textContent = "waiting";
  toggleRecognitionDownloads(false);
  toggleRecognitionApply(false);
  drawRecognitionCanvas();
  $("recognized-image-size").textContent = file.name;
  if (fileType !== "inp") {
    updateRecognitionStatus("unsupported file", "EPANET .inp only");
    return;
  }
  updateRecognitionStatus("INP loaded", "ready for EPANET parser");
}

function resetDrawingRecognition() {
  state.drawingFile = null;
  state.drawingFileType = null;
  state.drawingImage = null;
  state.drawingRecognition = null;
  state.drawingAssets = null;
  state.drawingAssetsApplied = false;
  state.recognitionCandidateStates = new Map();
  state.highlightedRecognitionCandidate = null;
  state.drawingPipeSamples = [];
  state.drawingJunctionSamples = [];
  state.drawingSourceSamples = [];
  state.drawingSampleMode = false;
  state.drawingJunctionMode = false;
  state.drawingSourceMode = false;
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
  updateRecognitionStatus("inp waiting", "0 pipes / 0 nodes");
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
  state.demandPatterns = cloneRows(state.initialData.demandPatterns || []);
  state.energyOptions = { ...(state.initialData.energyOptions || {}) };
  state.pumpEnergy = cloneRows(state.initialData.pumpEnergy || []);
  state.activeDemandMode = state.initialData.activeDemandMode || "profile";
  buildDemandIndex();
  state.pipeEdits = new Map();
  state.leakDemands = new Map();
  clearOptimizedControlBoost();
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
  state.selected = state.pipes[0] ? `pipe:${state.pipes[0].pipe_id}` : firstJunctionId() ? `node:${firstJunctionId()}` : null;
  fitMapToCurrentNetwork();
  refreshAssetOptions();
  syncDashboardControlsAfterNetworkRestore();
  updateDrawReadout("INP 가져오기 상태를 초기화했습니다. 새 .inp 파일을 업로드하면 관망지도가 생성됩니다.");
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
  drawRecognitionHighlight(ctx, offsetX, offsetY, scale);
  drawPipeSampleMarkers(ctx, offsetX, offsetY, scale);
  drawJunctionSampleMarkers(ctx, offsetX, offsetY, scale);
  drawSourceSampleMarkers(ctx, offsetX, offsetY, scale);
}

function drawRecognitionHighlight(ctx, offsetX, offsetY, scale) {
  const candidateId = state.highlightedRecognitionCandidate;
  if (!candidateId || !state.drawingRecognition) return;
  const candidate = (state.drawingRecognition.pipe_candidates || []).find((pipe) =>
    [pipe.id, pipe.pipe_id, pipe.source_line].some((value) => String(value || "") === String(candidateId)),
  ) || recognitionCandidateByExportId(candidateId);
  const segment = candidate
    ? (state.drawingRecognition.segments || []).find((line) => String(line.id || "") === String(candidate.source_line || ""))
    : (state.drawingRecognition.segments || []).find((line) => String(line.id || "") === String(candidateId));
  const points = candidate?.polyline_px || segment?.points || (segment ? [{ x: segment.x1, y: segment.y1 }, { x: segment.x2, y: segment.y2 }] : []);
  if (!points.length) return;
  ctx.save();
  ctx.strokeStyle = "#f59e0b";
  ctx.lineWidth = 8;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(offsetX + Number(points[0].x || 0) * scale, offsetY + Number(points[0].y || 0) * scale);
  for (const point of points.slice(1)) {
    ctx.lineTo(offsetX + Number(point.x || 0) * scale, offsetY + Number(point.y || 0) * scale);
  }
  ctx.stroke();
  ctx.restore();
}

function recognitionCandidateByExportId(candidateId) {
  const index = Number(String(candidateId || "").match(/(\d+)$/)?.[1] || 0) - 1;
  return index >= 0 ? (state.drawingRecognition?.pipe_candidates || [])[index] : null;
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
  if (!state.drawingFile || state.drawingFileType !== "inp") {
    updateRecognitionStatus("inp file required", "0 pipes / 0 nodes");
    return;
  }
  analyzeInpFile();
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
  renderInpImportResult(assets);
}

function applyCurrentRecognitionAssets() {
  if (!state.drawingAssets) return;
  applyRecognitionAssetsToDashboard(reviewedRecognitionAssets());
}

function classifyDrawingFile(file) {
  const name = String(file.name || "").toLowerCase();
  if (name.endsWith(".inp")) return "inp";
  return "unknown";
}

function mimeTypeFromFilename(filename) {
  const name = String(filename || "").toLowerCase();
  if (name.endsWith(".inp")) return "text/plain";
  return "application/octet-stream";
}

function recognitionRouteLabel(fileType) {
  if (fileType === "inp") return "EPANET INP parser";
  return "unsupported file";
}

function recognitionReadyLabel(fileType) {
  if (fileType === "inp") return "INP parse ready";
  return "import ready";
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

async function analyzeInpFile() {
  updateRecognitionStatus("parsing inp", "EPANET sections");
  $("analyze-drawing").disabled = true;
  try {
    const text = await state.drawingFile.text();
    const parsed = parseEpanetInp(text, {
      filename: state.drawingFile.name || "network.inp",
      coordinateScale: Number($("drawing-scale").value || 1),
      defaultDiameterMm: Number($("drawing-diameter").value || 150),
      defaultMaterial: $("drawing-material").value || "PVC",
    });
    state.drawingRecognition = parsed.recognition;
    state.drawingFileType = "inp";
    state.recognitionCandidateStates = new Map();
    state.highlightedRecognitionCandidate = null;
    renderDrawingRecognition(parsed.assets);
  } catch (error) {
    console.warn("INP parse failed.", error);
    updateRecognitionStatus("inp parse failed", error.message || "invalid EPANET file");
  } finally {
    $("analyze-drawing").disabled = false;
  }
}

function renderInpImportResult(assets) {
  initializeRecognitionCandidateStates(assets, state.drawingRecognition);
  drawInpPreview(assets);
  $("recognized-pipe-count").textContent = assets.pipes.length;
  $("recognized-node-count").textContent = Math.max((assets.nodes?.length || 0) - (assets.reservoirs?.length || 0), 0);
  $("recognized-image-size").textContent = state.drawingRecognition.filename || state.drawingFile?.name || "--";
  $("recognized-export-state").textContent = assets.pipes.length ? "INP 변환 완료" : "확인 필요";
  updateRecognitionStatus(
    "INP parse ready",
    `${assets.pipes.length} pipes / ${assets.nodes.length} nodes / ${assets.pumps?.length || 0} pumps`,
  );
  renderRecognitionTable("recognized-nodes-table", assets.nodes, ["node_id", "x", "y", "node_type", "elevation_m", "base_demand_lps"]);
  renderRecognitionTable("recognized-pipes-table", assets.pipes, ["pipe_id", "from_node", "to_node", "length_m", "diameter_mm", "roughness_c", "status"]);
  const warnings = state.drawingRecognition.warnings || [];
  $("recognition-review-summary").textContent = warnings.length
    ? `INP 파싱 완료. 검토 필요: ${warnings.join(" / ")}`
    : "INP 파싱 완료. 변환 결과를 확인한 뒤 관망에 적용하세요.";
  toggleRecognitionDownloads(Boolean(assets.nodes.length && assets.pipes.length));
  toggleRecognitionApply(Boolean(assets.nodes.length && assets.pipes.length));
}

function parseEpanetInp(text, options = {}) {
  const sections = epanetSections(text);
  const optionUnits = epanetOptionValue(sections.OPTIONS, "Units") || "GPM";
  const headlossFormula = normalizeEpanetHeadlossFormula(epanetOptionValue(sections.OPTIONS, "Headloss") || "H-W");
  const unit = epanetUnitProfile(optionUnits);
  const coordinateScale = Number(options.coordinateScale || 1);
  const coordinates = parseEpanetCoordinates(sections.COORDINATES, unit, coordinateScale);
  const vertices = parseEpanetVertices(sections.VERTICES, unit, coordinateScale);
  const curves = parseEpanetCurves(sections.CURVES, unit);
  const patternTimestepMinutes = parseEpanetPatternTimestepMinutes(sections.TIMES);
  const demandPatterns = parseEpanetPatterns(sections.PATTERNS, patternTimestepMinutes);
  const energy = parseEpanetEnergy(sections.ENERGY, curves);
  const warnings = [];

  const junctions = (sections.JUNCTIONS || []).map((line, index) => {
    const row = epanetTokens(line);
    const nodeId = String(row[0] || `J_INP_${index + 1}`);
    const point = coordinates.get(nodeId) || fallbackInpPoint(index);
    return {
      reservoir_id: nodeId,
      node_id: nodeId,
      x: point.x,
      y: point.y,
      elevation_m: unit.headToM(numberOr(row[1], 0)),
      base_demand_lps: unit.flowToLps(numberOr(row[2], 0)),
      demand_pattern_id: String(row[3] || ""),
      node_type: "junction",
      dma_id: inferInpDma(point.x, point.y),
      source: "inp",
    };
  });

  const reservoirs = (sections.RESERVOIRS || []).map((line, index) => {
    const row = epanetTokens(line);
    const nodeId = String(row[0] || `R_INP_${index + 1}`);
    const point = coordinates.get(nodeId) || fallbackInpPoint(index + junctions.length, -160);
    return {
      node_id: nodeId,
      x: point.x,
      y: point.y,
      elevation_m: 0,
      base_demand_lps: 0,
      node_type: "reservoir",
      dma_id: "SOURCE",
      head_m: unit.headToM(numberOr(row[1], 58)),
      source: "inp",
    };
  });

  const nodes = [...reservoirs.map(({ head_m, ...node }) => node), ...junctions];
  const nodeIds = new Set(nodes.map((node) => node.node_id));
  const pipeRows = sections.PIPES || [];
  const pipes = pipeRows
    .map((line, index) => {
      const row = epanetTokens(line);
      const fromNode = String(row[1] || "");
      const toNode = String(row[2] || "");
      const pipeId = String(row[0] || `P_INP_${index + 1}`);
      return {
        pipe_id: pipeId,
        from_node: fromNode,
        to_node: toNode,
        length_m: unit.lengthToM(numberOr(row[3], distanceByNodeIds(fromNode, toNode, nodes) || 100)),
        diameter_mm: unit.diameterToMm(numberOr(row[4], options.defaultDiameterMm || 150)),
        roughness_c: numberOr(row[5], 100),
        minor_loss_k: numberOr(row[6], 0),
        status: String(row[7] || "OPEN").toLowerCase(),
        material: String(options.defaultMaterial || "PVC"),
        service_type: "distribution",
        install_year: 2000,
        bend_count: (vertices.get(pipeId) || []).length,
        bend_angle_deg: 0,
        valve_count: 0,
        repair_count: 0,
        leak_history_count: 0,
        burst_history_count: 0,
        soil_ph: 7,
        soil_resistivity_ohm_cm: 3000,
        traffic_load_index: 0.3,
        geometry_type: (vertices.get(pipeId) || []).length ? "polyline" : "straight",
        geometry_m: vertices.get(pipeId) || [],
        source: "inp",
      };
    })
    .filter((pipe) => nodeIds.has(pipe.from_node) && nodeIds.has(pipe.to_node) && pipe.from_node !== pipe.to_node);

  const pumpRows = sections.PUMPS || [];
  const pumpConnectorPipes = [];
  const pumps = pumpRows
    .map((line, index) => {
      const row = epanetTokens(line);
      const pumpId = String(row[0] || `PU_INP_${index + 1}`);
      const fromNode = String(row[1] || "");
      const toNode = String(row[2] || "");
      const pumpCurve = epanetPumpHeadCurve(row, curves);
      const pumpEnergy = energy.pumps.get(pumpId) || {};
      if (nodeIds.has(fromNode) && nodeIds.has(toNode)) {
        pumpConnectorPipes.push(inpPumpConnectorPipe(pumpId, fromNode, toNode, nodes, options.defaultDiameterMm || 300));
      }
      return {
        pump_id: pumpId,
        from_node: fromNode,
        to_node: toNode,
        base_head_gain_m: pumpCurve?.reference_head_m ?? 3,
        pump_curve_id: pumpCurve?.curve_id || "",
        pump_curve_kind: pumpCurve ? "HEAD" : "",
        pump_curve_points: pumpCurve?.points || [],
        curve_reference_head_m: pumpCurve?.reference_head_m ?? null,
        efficiency_percent: pumpEnergy.efficiency_percent ?? energy.options.global_efficiency_percent,
        efficiency_curve_id: pumpEnergy.efficiency_curve_id || "",
        efficiency_curve_points: pumpEnergy.efficiency_curve_points || [],
        energy_price_per_kwh: pumpEnergy.energy_price_per_kwh ?? energy.options.global_price_per_kwh,
        energy_price_pattern_id: pumpEnergy.energy_price_pattern_id || "",
        speed_multiplier: 1,
        status: "on",
        source: "inp",
      };
    })
    .filter((pump) => nodeIds.has(pump.from_node) && nodeIds.has(pump.to_node));

  if (!junctions.length) warnings.push("JUNCTIONS section is empty.");
  if (!pipes.length) warnings.push("PIPES section is empty.");
  if (!coordinates.size) warnings.push("COORDINATES section is empty; automatic layout was used.");
  if (junctions.some((node) => node.demand_pattern_id) && !demandPatterns.length) warnings.push("Junction demand patterns were referenced but [PATTERNS] was empty.");
  const skippedPipes = pipeRows.length - pipes.length;
  if (skippedPipes > 0) warnings.push(`${skippedPipes} pipe(s) had missing endpoints and were skipped.`);

  const assets = {
    nodes,
    pipes: [...pumpConnectorPipes, ...pipes],
    reservoirs: reservoirs.map((reservoir) => ({ reservoir_id: reservoir.reservoir_id || reservoir.node_id, node_id: reservoir.node_id, head_m: reservoir.head_m })),
    pumps,
    demand_patterns: demandPatterns,
    energy_options: energy.options,
    pump_energy: Array.from(energy.pumps.values()),
    options: {
      units: optionUnits,
      headloss: headlossFormula,
      pattern_timestep_minutes: patternTimestepMinutes,
    },
    warnings,
  };
  return {
    recognition: {
      file_type: "inp",
      filename: options.filename || "network.inp",
      units: optionUnits,
      headloss_formula: headlossFormula,
      sections: Object.fromEntries(Object.entries(sections).map(([key, rows]) => [key, rows.length])),
      width: 0,
      height: 0,
      segments: [],
      nodes: [],
      pipe_candidates: [],
      low_confidence_pipes: [],
      quality_report: { counts: { review_items: warnings.length }, warnings },
      warnings,
      summary: () => `${assets.pipes.length} pipes / ${assets.nodes.length} nodes`,
    },
    assets,
  };
}

function parseEpanetCurves(rows = [], unit = epanetUnitProfile("GPM")) {
  const curves = new Map();
  (rows || []).forEach((line) => {
    const row = epanetTokens(line);
    if (row.length < 3) return;
    const curveId = String(row[0] || "");
    const sourceFlow = numberOr(row[1], NaN);
    const sourceHead = numberOr(row[2], NaN);
    if (!curveId || !Number.isFinite(sourceFlow) || !Number.isFinite(sourceHead)) return;
    if (!curves.has(curveId)) curves.set(curveId, []);
    curves.get(curveId).push({
      flow_lps: unit.flowToLps(sourceFlow),
      head_m: unit.headToM(sourceHead),
      source_flow: sourceFlow,
      source_head: sourceHead,
    });
  });
  curves.forEach((points) => points.sort((a, b) => Number(a.flow_lps || 0) - Number(b.flow_lps || 0)));
  return curves;
}

function epanetPumpHeadCurve(tokens, curves) {
  const headIndex = tokens.findIndex((token) => String(token || "").toUpperCase() === "HEAD");
  if (headIndex < 0 || headIndex + 1 >= tokens.length) return null;
  const curveId = String(tokens[headIndex + 1] || "");
  const points = (curves.get(curveId) || []).filter((point) => Number.isFinite(Number(point.head_m)));
  if (!points.length) return null;
  return {
    curve_id: curveId,
    points,
    reference_head_m: representativePumpCurveHead(points),
  };
}

function representativePumpCurveHead(points) {
  const positiveFlowPoints = points.filter((point) => Number(point.flow_lps || 0) > 0);
  const candidates = positiveFlowPoints.length ? positiveFlowPoints : points;
  const middleIndex = Math.floor((candidates.length - 1) / 2);
  return Number(candidates[middleIndex]?.head_m || points[0]?.head_m || 3);
}

function parseEpanetPatterns(rows = [], timestepMinutes = 60) {
  const records = [];
  const counters = new Map();
  for (const line of rows || []) {
    const tokens = epanetTokens(line);
    const patternId = String(tokens[0] || "");
    if (!patternId) continue;
    const start = counters.get(patternId) || 0;
    tokens.slice(1).forEach((token, offset) => {
      const multiplier = numberOr(token, NaN);
      if (!Number.isFinite(multiplier)) return;
      const stepIndex = start + offset;
      records.push({
        pattern_id: patternId,
        step_index: stepIndex,
        hour: (stepIndex * Number(timestepMinutes || 60)) / 60,
        minute: stepIndex * Number(timestepMinutes || 60),
        multiplier,
      });
    });
    counters.set(patternId, start + Math.max(tokens.length - 1, 0));
  }
  return records;
}

function parseEpanetPatternTimestepMinutes(rows = []) {
  for (const line of rows || []) {
    const tokens = epanetTokens(line);
    if (!tokens.length) continue;
    const key = tokens.slice(0, -1).join(" ").toLowerCase();
    if (key === "pattern timestep" || key === "pattern step") {
      return epanetDurationToMinutes(tokens[tokens.length - 1], 60);
    }
  }
  return 60;
}

function epanetDurationToMinutes(value, fallback = 60) {
  const text = String(value || "").trim();
  if (!text) return fallback;
  const clock = text.match(/^(\d+):(\d+)$/);
  if (clock) return Number(clock[1]) * 60 + Number(clock[2]);
  const number = Number(text);
  return Number.isFinite(number) ? number * 60 : fallback;
}

function parseEpanetEnergy(rows = [], curves = new Map()) {
  const options = {
    global_efficiency_percent: 65,
    global_price_per_kwh: 0,
    demand_charge: 0,
  };
  const pumps = new Map();
  const pumpRow = (pumpId) => {
    const id = String(pumpId || "");
    if (!pumps.has(id)) pumps.set(id, { pump_id: id });
    return pumps.get(id);
  };

  for (const line of rows || []) {
    const tokens = epanetTokens(line);
    if (!tokens.length) continue;
    const first = String(tokens[0] || "").toUpperCase();
    if (first === "GLOBAL") {
      const key = String(tokens[1] || "").toUpperCase();
      if (key === "EFFICIENCY") options.global_efficiency_percent = numberOr(tokens[2], options.global_efficiency_percent);
      if (key === "PRICE") options.global_price_per_kwh = numberOr(tokens[2], options.global_price_per_kwh);
      if (key === "PATTERN") options.global_price_pattern_id = String(tokens[2] || "");
      continue;
    }
    if (first === "DEMAND" && String(tokens[1] || "").toUpperCase() === "CHARGE") {
      options.demand_charge = numberOr(tokens[2], options.demand_charge);
      continue;
    }
    if (first !== "PUMP" || tokens.length < 4) continue;
    const pumpId = String(tokens[1] || "");
    const setting = String(tokens[2] || "").toUpperCase();
    const row = pumpRow(pumpId);
    if (setting === "EFFICIENCY") {
      if (String(tokens[3] || "").toUpperCase() === "CURVE" && tokens[4]) {
        row.efficiency_curve_id = String(tokens[4]);
      } else if (Number.isFinite(Number(tokens[3]))) {
        row.efficiency_percent = numberOr(tokens[3], options.global_efficiency_percent);
      } else {
        row.efficiency_curve_id = String(tokens[3] || "");
      }
    }
    if (setting === "PRICE") row.energy_price_per_kwh = numberOr(tokens[3], options.global_price_per_kwh);
    if (setting === "PATTERN") row.energy_price_pattern_id = String(tokens[3] || "");
  }

  for (const row of pumps.values()) {
    const curveId = row.efficiency_curve_id;
    if (!curveId || !curves.has(curveId)) continue;
    row.efficiency_curve_points = (curves.get(curveId) || []).map((point) => ({
      flow_lps: Number(point.flow_lps || 0),
      efficiency_percent: Number(point.source_head || point.head_m || 0),
    }));
  }
  return { options, pumps };
}

function epanetSections(text) {
  const sections = {};
  let current = "";
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const line = rawLine.trim();
    const sectionMatch = line.match(/^\[([^\]]+)\]/);
    if (sectionMatch) {
      current = sectionMatch[1].trim().toUpperCase();
      if (!sections[current]) sections[current] = [];
      continue;
    }
    if (!current || !line || line.startsWith(";")) continue;
    const content = line.split(";")[0].trim();
    if (content) sections[current].push(content);
  }
  return sections;
}

function epanetTokens(line) {
  return String(line || "").trim().split(/\s+/).filter(Boolean);
}

function epanetOptionValue(lines = [], key) {
  const normalized = String(key || "").toLowerCase();
  for (const line of lines) {
    const tokens = epanetTokens(line);
    if (tokens[0]?.toLowerCase() === normalized) return tokens[1] || "";
  }
  return "";
}

function epanetUnitProfile(unitName) {
  const unit = String(unitName || "GPM").toUpperCase();
  const si = ["LPS", "LPM", "MLD", "CMH", "CMD"].includes(unit);
  const flowFactors = {
    CFS: 28.3168466,
    GPM: 0.0630902,
    MGD: 43.812636,
    IMGD: 52.616782,
    AFD: 14.27641,
    LPS: 1,
    LPM: 1 / 60,
    MLD: 11.574074,
    CMH: 0.2777778,
    CMD: 0.0115741,
  };
  return {
    lengthToM: (value) => (si ? value : value * 0.3048),
    headToM: (value) => (si ? value : value * 0.3048),
    diameterToMm: (value) => (si ? value : value * 25.4),
    flowToLps: (value) => value * (flowFactors[unit] || flowFactors.GPM),
    coordinateToM: (value) => (si ? value : value * 0.3048),
  };
}

function parseEpanetCoordinates(lines = [], unit, scale = 1) {
  const coordinates = new Map();
  for (const line of lines) {
    const row = epanetTokens(line);
    if (row.length < 3) continue;
    coordinates.set(String(row[0]), {
      x: unit.coordinateToM(numberOr(row[1], 0)) * scale,
      y: unit.coordinateToM(numberOr(row[2], 0)) * scale,
    });
  }
  return coordinates;
}

function parseEpanetVertices(lines = [], unit, scale = 1) {
  const vertices = new Map();
  for (const line of lines) {
    const row = epanetTokens(line);
    if (row.length < 3) continue;
    const linkId = String(row[0]);
    if (!vertices.has(linkId)) vertices.set(linkId, []);
    vertices.get(linkId).push({
      x: unit.coordinateToM(numberOr(row[1], 0)) * scale,
      y: unit.coordinateToM(numberOr(row[2], 0)) * scale,
    });
  }
  return vertices;
}

function inpPumpConnectorPipe(pumpId, fromNode, toNode, nodes, defaultDiameterMm) {
  return {
    pipe_id: `PUMP_${pumpId}`,
    from_node: fromNode,
    to_node: toNode,
    length_m: Math.max(30, distanceByNodeIds(fromNode, toNode, nodes) || 30),
    diameter_mm: Number(defaultDiameterMm || 300),
    roughness_c: 120,
    minor_loss_k: 0,
    status: "open",
    material: "ductile_iron",
    service_type: "transmission",
    install_year: 2000,
    bend_count: 0,
    bend_angle_deg: 0,
    valve_count: 0,
    repair_count: 0,
    leak_history_count: 0,
    burst_history_count: 0,
    soil_ph: 7,
    soil_resistivity_ohm_cm: 3000,
    traffic_load_index: 0.2,
    geometry_type: "pump_link",
    geometry_m: [],
    source: "inp_pump",
  };
}

function distanceByNodeIds(fromNode, toNode, nodes) {
  const from = nodes.find((node) => node.node_id === fromNode);
  const to = nodes.find((node) => node.node_id === toNode);
  return from && to ? distanceBetween(from, to) : 0;
}

function fallbackInpPoint(index, xOffset = 0) {
  const columns = 6;
  const spacing = 120;
  return {
    x: xOffset + (index % columns) * spacing,
    y: Math.floor(index / columns) * spacing,
  };
}

function inferInpDma(x, y) {
  const col = x < 1100 ? "A" : x < 1700 ? "B" : "C";
  const row = y < 1600 ? "1" : "2";
  return `DMA_${col}${row}`;
}

function numberOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function drawInpPreview(assets) {
  const canvas = $("drawing-canvas");
  const empty = $("drawing-empty-state");
  if (!canvas || !assets?.nodes?.length) return;
  if (empty) empty.style.display = "none";
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#fbfdff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  drawPreviewGrid(ctx, canvas.width, canvas.height);
  const frame = previewProjector(assets.nodes, canvas.width, canvas.height);
  const nodeById = new Map(assets.nodes.map((node) => [node.node_id, node]));
  for (const pipe of assets.pipes || []) {
    const points = [nodeById.get(pipe.from_node), ...(pipe.geometry_m || []), nodeById.get(pipe.to_node)].filter(Boolean).map(frame.project);
    if (points.length < 2) continue;
    ctx.strokeStyle = pipe.source === "inp_pump" ? "#0f766e" : "#2563eb";
    ctx.lineWidth = pipe.source === "inp_pump" ? 5 : 3;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (const point of points.slice(1)) ctx.lineTo(point.x, point.y);
    ctx.stroke();
  }
  for (const node of assets.nodes || []) {
    const point = frame.project(node);
    const isSource = node.node_type === "reservoir";
    ctx.fillStyle = isSource ? "#0f766e" : "#247a5a";
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    if (isSource) {
      ctx.moveTo(point.x, point.y - 9);
      ctx.lineTo(point.x + 9, point.y);
      ctx.lineTo(point.x, point.y + 9);
      ctx.lineTo(point.x - 9, point.y);
      ctx.closePath();
    } else {
      ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#172026";
    ctx.font = "700 10px Inter, sans-serif";
    ctx.fillText(node.node_id, point.x + 9, point.y - 6);
  }
}

function drawPreviewGrid(ctx, width, height) {
  ctx.strokeStyle = "#edf3f6";
  ctx.lineWidth = 1;
  for (let x = 0; x <= width; x += 32) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y <= height; y += 32) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
}

function previewProjector(nodes, width, height) {
  const xs = nodes.map((node) => Number(node.x || 0));
  const ys = nodes.map((node) => Number(node.y || 0));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const pad = 42;
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
  return {
    project: (point) => ({
      x: pad + (Number(point.x || 0) - minX) * scale,
      y: height - pad - (Number(point.y || 0) - minY) * scale,
    }),
  };
}

function applyRecognitionAssetsToDashboard(assets) {
  const normalizedAssets = normalizeDashboardAssetsForEditing(assets);
  if (!normalizedAssets.nodes.length || !normalizedAssets.pipes.length) return;
  state.drawingAssetsApplied = true;
  state.headlossFormula = normalizeEpanetHeadlossFormula(assets?.options?.headloss || state.drawingRecognition?.headloss_formula || state.headlossFormula);
  state.nodes = normalizedAssets.nodes;
  state.pipes = normalizedAssets.pipes;
  state.reservoirs = normalizedAssets.reservoirs;
  state.pumps = normalizedAssets.pumps;
  state.valves = [];
  state.households = [];
  state.demandPatterns = Array.isArray(assets?.demand_patterns) ? cloneRows(assets.demand_patterns) : [];
  state.energyOptions = { ...(assets?.energy_options || {}) };
  state.pumpEnergy = Array.isArray(assets?.pump_energy) ? cloneRows(assets.pump_energy) : [];
  state.activeDemandMode = state.demandPatterns.length ? "inp" : "profile";
  state.demandByMinute = new Map();
  state.pipeEdits = new Map();
  state.leakDemands = new Map();
  state.backendSimulation = null;
  state.backendSimulationSignature = "";
  state.backendSimulationStatusMessage = "";
  state.backendSimulationStatusLevel = "";
  clearOptimizedControlBoost();
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
  const activePump = state.pumps.find((pump) => String(pump.status || "on").toLowerCase() !== "off");
  $("pump-head").value = activePump ? Number(activePump.base_head_gain_m || 0) * Number(activePump.speed_multiplier || 1) : 0;
  syncSourceControlLabels();
  $("recognized-export-state").textContent = "검토 결과 반영";
  updateRecognitionStatus("관망 적용 완료", `${normalizedAssets.pipes.length} pipes / ${normalizedAssets.nodes.length} nodes`);
  updateDrawReadout("INP 관망이 관망맵에 반영되었습니다. Pipe/Junction 패널에서 세부 값을 편집하세요.");
  render();
}

function normalizeDashboardAssetsForEditing(assets) {
  const sourceNodes = Array.isArray(assets?.nodes) ? assets.nodes : [];
  const sourcePipes = Array.isArray(assets?.pipes) ? assets.pipes : [];
  const nodes = sourceNodes
    .map((node, index) => ({
      node_id: String(node.node_id || node.id || `J_IMG_${index + 1}`),
      x: Number(node.x ?? index * 30),
      y: Number(node.y ?? 0),
      elevation_m: Number(node.elevation_m ?? 30),
      base_demand_lps: Number(node.base_demand_lps ?? (node.node_type === "reservoir" ? 0 : 0.8)),
      node_type: node.node_type === "reservoir" ? "reservoir" : "junction",
      dma_id: String(node.dma_id || (node.node_type === "reservoir" ? "SOURCE" : "IMG_IMPORT")),
      demand_pattern_id: String(node.demand_pattern_id || ""),
    }))
    .filter((node) => node.node_id && Number.isFinite(node.x) && Number.isFinite(node.y));
  const nodeIds = new Set(nodes.map((node) => node.node_id));
  const pipes = sourcePipes
    .map((pipe, index) => ({
      ...pipe,
      pipe_id: String(pipe.pipe_id || pipe.id || `P_IMG_${index + 1}`),
      from_node: String(pipe.from_node || ""),
      to_node: String(pipe.to_node || ""),
      length_m: Number(pipe.length_m ?? 100),
      diameter_mm: Number(pipe.diameter_mm ?? 150),
      roughness_c: Number(pipe.roughness_c ?? 100),
      minor_loss_k: Number(pipe.minor_loss_k ?? 0),
      material: String(pipe.material || "PVC"),
      service_type: String(pipe.service_type || "distribution"),
      install_year: Number(pipe.install_year ?? 2026),
      bend_count: Number(pipe.bend_count ?? 0),
      bend_angle_deg: Number(pipe.bend_angle_deg ?? 0),
      valve_count: Number(pipe.valve_count ?? 0),
      repair_count: Number(pipe.repair_count ?? 0),
      leak_history_count: Number(pipe.leak_history_count ?? 0),
      burst_history_count: Number(pipe.burst_history_count ?? 0),
      soil_ph: Number(pipe.soil_ph ?? 7.0),
      soil_resistivity_ohm_cm: Number(pipe.soil_resistivity_ohm_cm ?? 3000),
      traffic_load_index: Number(pipe.traffic_load_index ?? 0.3),
      geometry_type: String(pipe.geometry_type || "straight"),
      geometry_m: Array.isArray(pipe.geometry_m) ? pipe.geometry_m : [],
    }))
    .filter((pipe) => nodeIds.has(pipe.from_node) && nodeIds.has(pipe.to_node) && pipe.from_node !== pipe.to_node);
  let reservoirs = (Array.isArray(assets?.reservoirs) ? assets.reservoirs : [])
    .filter((reservoir) => nodeIds.has(String(reservoir.node_id || "")))
    .map((reservoir) => ({
      node_id: String(reservoir.node_id),
      reservoir_id: String(reservoir.reservoir_id || reservoir.node_id),
      head_m: Number(reservoir.head_m ?? 58),
    }));
  let reservoirNode = nodes.find((node) => node.node_type === "reservoir");
  if (!reservoirNode && nodes.length) {
    const anchor = nodes.find((node) => node.node_type !== "reservoir") || nodes[0];
    reservoirNode = {
      node_id: uniqueAssetId("R_IMG_1", new Set(nodes.map((node) => node.node_id))),
      x: Number(anchor.x || 0) - 80,
      y: Number(anchor.y || 0),
      elevation_m: Number(anchor.elevation_m || 30) + 5,
      base_demand_lps: 0,
      node_type: "reservoir",
      dma_id: "SOURCE",
    };
    nodes.unshift(reservoirNode);
    nodeIds.add(reservoirNode.node_id);
  }
  if (reservoirNode && !reservoirs.some((reservoir) => reservoir.node_id === reservoirNode.node_id)) {
    reservoirs = [{ reservoir_id: reservoirNode.node_id, node_id: reservoirNode.node_id, head_m: 58 }, ...reservoirs];
  }
  const firstJunction = nodes.find((node) => node.node_type !== "reservoir");
  if (reservoirNode && firstJunction && !pipes.some((pipe) => pipe.from_node === reservoirNode.node_id || pipe.to_node === reservoirNode.node_id)) {
    pipes.unshift({
      pipe_id: uniqueAssetId("P_IMG_SOURCE", new Set(pipes.map((pipe) => pipe.pipe_id))),
      from_node: reservoirNode.node_id,
      to_node: firstJunction.node_id,
      length_m: Math.max(40, distanceBetween(reservoirNode, firstJunction)),
      diameter_mm: 300,
      roughness_c: 100,
      minor_loss_k: 0,
      material: "ductile_iron",
      service_type: "transmission",
      install_year: 2026,
      bend_count: 0,
      bend_angle_deg: 0,
      valve_count: 0,
      repair_count: 0,
      leak_history_count: 0,
      burst_history_count: 0,
      soil_ph: 7.0,
      soil_resistivity_ohm_cm: 3000,
      traffic_load_index: 0.2,
      geometry_type: "straight",
      geometry_m: [],
    });
  }
  const pumps = (Array.isArray(assets?.pumps) ? assets.pumps : [])
    .filter((pump) => nodeIds.has(String(pump.from_node || "")) && nodeIds.has(String(pump.to_node || "")))
    .map((pump, index) => ({
      pump_id: String(pump.pump_id || `PU_IMG_${index + 1}`),
      from_node: String(pump.from_node),
      to_node: String(pump.to_node),
      base_head_gain_m: Number(pump.base_head_gain_m ?? 3),
      pump_curve_id: String(pump.pump_curve_id || ""),
      pump_curve_kind: String(pump.pump_curve_kind || ""),
      pump_curve_points: Array.isArray(pump.pump_curve_points) ? pump.pump_curve_points : [],
      curve_reference_head_m: pump.curve_reference_head_m == null ? null : Number(pump.curve_reference_head_m),
      efficiency_percent: pump.efficiency_percent == null ? null : Number(pump.efficiency_percent),
      efficiency_curve_id: String(pump.efficiency_curve_id || ""),
      efficiency_curve_points: Array.isArray(pump.efficiency_curve_points) ? pump.efficiency_curve_points : [],
      energy_price_per_kwh: pump.energy_price_per_kwh == null ? null : Number(pump.energy_price_per_kwh),
      energy_price_pattern_id: String(pump.energy_price_pattern_id || ""),
      speed_multiplier: Number(pump.speed_multiplier ?? 1),
      status: String(pump.status || "on"),
    }));
  if (reservoirNode && firstJunction && !pumps.some((pump) => pump.from_node === reservoirNode.node_id || pump.to_node === reservoirNode.node_id)) {
    pumps.unshift({
      pump_id: uniqueAssetId("PU_IMG_1", new Set(pumps.map((pump) => pump.pump_id))),
      from_node: reservoirNode.node_id,
      to_node: firstJunction.node_id,
      base_head_gain_m: 3,
      efficiency_percent: Number(state.energyOptions?.global_efficiency_percent || 65),
      speed_multiplier: 1,
      status: "on",
    });
  }
  return { nodes, pipes, reservoirs, pumps };
}

function uniqueAssetId(baseId, existingIds) {
  if (!existingIds.has(baseId)) return baseId;
  let index = 2;
  while (existingIds.has(`${baseId}_${index}`)) index += 1;
  return `${baseId}_${index}`;
}

function applyInjectedRecognitionAssets() {
  const assets = window.__STREAMLIT_RECOGNIZED_ASSETS__;
  if (!assets || window.__STREAMLIT_RECOGNIZED_ASSETS_APPLIED__) return;
  window.__STREAMLIT_RECOGNIZED_ASSETS_APPLIED__ = true;
  state.drawingAssets = assets;
  state.drawingAssetsApplied = false;
  initializeRecognitionCandidateStates(assets, state.drawingRecognition);
  renderRecognitionTable("recognized-nodes-table", assets.nodes || [], ["node_id", "x", "y", "node_type", "dma_id"]);
  renderRecognitionCandidateReview();
  $("recognized-pipe-count").textContent = assets.pipes?.length || 0;
  $("recognized-node-count").textContent = Math.max((assets.nodes?.length || 0) - (assets.reservoirs?.length || 0), 0);
  $("recognized-export-state").textContent = "Streamlit 반영";
  updateRecognitionStatus("streamlit analysis ready", `${assets.pipes?.length || 0} pipes / ${assets.nodes?.length || 0} nodes`);
  toggleRecognitionDownloads(Boolean(assets.nodes?.length && assets.pipes?.length));
  toggleRecognitionApply(Boolean(assets.nodes?.length && assets.pipes?.length));
}

function initializeRecognitionCandidateStates(assets, recognition) {
  for (const pipe of assets?.pipes || []) {
    const id = String(pipe.pipe_id || pipe.id || "");
    if (id && !state.recognitionCandidateStates.has(id)) state.recognitionCandidateStates.set(id, "confirmed");
  }
  for (const pipe of recognition?.low_confidence_pipes || []) {
    const id = String(pipe.id || pipe.pipe_id || pipe.source_line || "");
    if (id && !state.recognitionCandidateStates.has(id)) state.recognitionCandidateStates.set(id, "hold");
  }
}

function reviewedRecognitionAssets() {
  const assets = state.drawingAssets || {};
  const confirmedPipes = (assets.pipes || []).filter((pipe) => recognitionCandidateState(pipe.pipe_id || pipe.id) === "confirmed");
  const usedNodeIds = new Set(confirmedPipes.flatMap((pipe) => [String(pipe.from_node || ""), String(pipe.to_node || "")]));
  const sourceNodeIds = new Set((assets.reservoirs || []).map((reservoir) => String(reservoir.node_id || "")));
  const nodes = (assets.nodes || []).filter((node) => usedNodeIds.has(String(node.node_id || node.id || "")) || sourceNodeIds.has(String(node.node_id || node.id || "")));
  const reservoirs = (assets.reservoirs || []).filter((reservoir) => nodes.some((node) => String(node.node_id || node.id || "") === String(reservoir.node_id || "")));
  const pumps = (assets.pumps || []).filter((pump) => usedNodeIds.has(String(pump.from_node || "")) || usedNodeIds.has(String(pump.to_node || "")));
  return { ...assets, nodes, pipes: confirmedPipes, reservoirs, pumps };
}

function recognitionCandidateState(candidateId) {
  return state.recognitionCandidateStates.get(String(candidateId || "")) || "confirmed";
}

function setRecognitionCandidateState(candidateId, candidateState) {
  if (!candidateId) return;
  state.recognitionCandidateStates.set(String(candidateId), candidateState);
  renderRecognitionCandidateReview();
}

function highlightRecognitionCandidate(candidateId) {
  state.highlightedRecognitionCandidate = String(candidateId || "");
  drawRecognitionCanvas(state.drawingRecognition?.segments || [], state.drawingRecognition?.nodes || []);
}

function recognitionPipeCandidateRows(assets, recognition) {
  const lowConfidence = recognition?.low_confidence_pipes || [];
  const highConfidenceRows = (assets.pipes || []).map((pipe) => {
    const confidence = recognitionConfidenceForAssetPipe(pipe, recognition);
    return {
    ...pipe,
    candidate_id: pipe.pipe_id,
    confidence: Number.isFinite(confidence) ? confidence.toFixed(2) : ">= 0.55",
    geometry_type: pipe.geometry_type || "straight",
    candidate_state: recognitionCandidateState(pipe.pipe_id),
    source: "export",
  };
  });
  const reviewRows = lowConfidence.map((pipe) => ({
    candidate_id: pipe.id || pipe.pipe_id || pipe.source_line || "",
    pipe_id: pipe.id || pipe.pipe_id || "",
    from_node: pipe.from_node || "",
    to_node: pipe.to_node || "",
    length_m: pipe.length_px ? `${pipe.length_px} px` : "",
    geometry_type: pipe.geometry_type || "straight",
    confidence: Number.isFinite(Number(pipe.confidence)) ? Number(pipe.confidence).toFixed(2) : "",
    candidate_state: recognitionCandidateState(pipe.id || pipe.pipe_id || pipe.source_line),
    source: "review",
  }));
  return [...highConfidenceRows, ...reviewRows];
}

function recognitionConfidenceForAssetPipe(pipe, recognition) {
  const candidates = recognition?.pipe_candidates || [];
  const index = Number(String(pipe.pipe_id || "").match(/(\d+)$/)?.[1] || 0) - 1;
  const candidate = candidates[index];
  return Number(candidate?.confidence);
}

function filteredRecognitionPipeRows() {
  const rows = recognitionPipeCandidateRows(state.drawingAssets || {}, state.drawingRecognition || {});
  if (state.recognitionFilter === "low") return rows.filter((row) => Number(row.confidence) < 0.55 || row.source === "review");
  if (state.recognitionFilter === "confirmed") return rows.filter((row) => row.candidate_state === "confirmed");
  return rows;
}

function renderRecognitionCandidateReview() {
  document.querySelectorAll("[data-recognition-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.recognitionFilter === state.recognitionFilter);
  });
  const rows = filteredRecognitionPipeRows();
  renderRecognitionTable("recognized-pipes-table", rows, [
    "pipe_id",
    "from_node",
    "to_node",
    "length_m",
    "geometry_type",
    "confidence",
    "candidate_state",
    "review_action",
  ]);
  wireRecognitionCandidateRows();
  updateRecognitionReviewSummary();
  toggleRecognitionApply(Boolean(reviewedRecognitionAssets().nodes.length && reviewedRecognitionAssets().pipes.length));
}

function wireRecognitionCandidateRows() {
  document.querySelectorAll("[data-recognition-candidate]").forEach((row) => {
    row.addEventListener("click", () => highlightRecognitionCandidate(row.dataset.recognitionCandidate));
  });
  document.querySelectorAll("[data-candidate-action]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      setRecognitionCandidateState(button.dataset.candidateId, button.dataset.candidateAction);
    });
  });
}

function updateRecognitionReviewSummary() {
  const rows = recognitionPipeCandidateRows(state.drawingAssets || {}, state.drawingRecognition || {});
  const counts = rows.reduce(
    (acc, row) => {
      acc[row.candidate_state] = (acc[row.candidate_state] || 0) + 1;
      return acc;
    },
    { confirmed: 0, hold: 0, deleted: 0 },
  );
  const summary = $("recognition-review-summary");
  if (summary) {
    summary.textContent = `검토 상태: 확정 ${counts.confirmed || 0}개 · 보류 ${counts.hold || 0}개 · 삭제 ${counts.deleted || 0}개. 확정된 Pipe만 관망맵에 적용됩니다.`;
  }
  if ($("recognized-export-state")) $("recognized-export-state").textContent = counts.confirmed ? "검토 중" : "확정 필요";
}

function fitMapToCurrentNetwork() {
  const points = state.nodes.filter((node) => Number.isFinite(Number(node.x)) && Number.isFinite(Number(node.y)));
  if (!points.length) {
    resetMapZoom();
    return;
  }
  state.mapCenter = { x: 560, y: 325 };
  state.mapZoom = 1;
}

function renderRecognitionTable(id, rows, columns) {
  if (!rows.length) {
    $(id).innerHTML = `<div class="empty-row">후보 없음</div>`;
    return;
  }
  $(id).innerHTML = `<table><thead><tr>${columns.map((col) => `<th>${col}</th>`).join("")}</tr></thead><tbody>${rows
    .slice(0, 80)
    .map((row) => {
      const candidateId = row.candidate_id || "";
      const attrs = candidateId ? ` data-recognition-candidate="${escapeHtml(candidateId)}"` : "";
      return `<tr${attrs}>${columns.map((col) => `<td>${recognitionTableCell(row, col)}</td>`).join("")}</tr>`;
    })
    .join("")}</tbody></table>`;
}

function recognitionTableCell(row, column) {
  if (column === "review_action") {
    const id = escapeHtml(row.candidate_id || row.pipe_id || "");
    const current = row.candidate_state || "confirmed";
    return ["confirmed", "hold", "deleted"]
      .map((action) => `<button class="candidate-state-button ${current === action ? "active" : ""}" data-candidate-id="${id}" data-candidate-action="${action}" type="button">${candidateStateLabel(action)}</button>`)
      .join("");
  }
  if (column === "candidate_state") return `<span class="candidate-state ${escapeHtml(row[column] || "")}">${candidateStateLabel(row[column])}</span>`;
  return escapeHtml(formatTableValue(row[column]));
}

function candidateStateLabel(value) {
  return { confirmed: "확정", hold: "보류", deleted: "삭제" }[String(value || "")] || String(value || "");
}

function formatTableValue(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value) || typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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
  const text = Array.isArray(value) || (value && typeof value === "object") ? JSON.stringify(value) : String(value ?? "");
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
  const minPressure = junctions.length ? Math.min(...junctions.map((node) => node.pressure)) : null;
  const selectedMinute = currentMinute();
  const timeIndex = currentTimeIndex();

  $("time-label").textContent = `${formatMinute(selectedMinute)} #${timeIndex + 1}/${state.timeline.length}`;
  $("timeline-title").textContent = `${formatMinute(selectedMinute)} #${timeIndex + 1} ${demandProfileLabel()} 관망 상태`;
  state.demandProfile = $("demand-profile")?.value || state.demandProfile || "metro";
  $("demand-scale-value").textContent = `${Number($("demand-scale").value).toFixed(2)}x`;
  $("source-head-value").textContent = `${Number($("source-head").value).toFixed(1)} m`;
  $("pump-head-value").textContent =
    snapshot.optimizedControlBoostM > 0
      ? `${(Number($("pump-head").value) + snapshot.optimizedControlBoostM).toFixed(1)} m`
      : `${Number($("pump-head").value).toFixed(1)} m`;
  $("leak-demand-value").textContent = `${Number($("leak-demand").value).toFixed(2)} L/s`;

  $("node-count").textContent = junctions.length;
  $("pipe-count").textContent = state.pipes.length;
  $("min-pressure").textContent = Number.isFinite(minPressure) ? `${minPressure.toFixed(1)} m` : "--";
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
  renderOperationsConsole(snapshot);
  renderProfessionalDiagnostics(snapshot);
  updateDashboardStatus(snapshot);
  renderSourcePumpPrediction(snapshot);
}

function updateDashboardStatus(snapshot) {
  const mode =
    bulkSelectionCount() > 0
      ? "다중 객체 선택"
      : state.addMode
        ? "Junction 생성"
        : state.pipeDrawMode
          ? "Pipe 생성"
          : state.sourceDrawMode
            ? "Source/Pump 생성"
            : state.editorTab === "source"
              ? "Source/Pump 편집"
              : state.editorTab === "junction"
                ? "Junction 편집"
                : state.editorTab === "pipe"
                  ? "Pipe 편집"
                  : "시나리오 편집";
  const backend = snapshot.backendSimulation ? "현재 조건 정밀 계산 반영" : "실시간 관망 계산";
  const dirty = hasNetworkChanged() ? " · 저장되지 않은 변경" : "";
  const optimized = snapshot.optimizedControlBoostM > 0 ? ` / optimized +${snapshot.optimizedControlBoostM.toFixed(2)} m live` : "";
  $("scenario-label").textContent = `${mode} / ${backend}${optimized}${dirty}`;
  const status = $("backend-simulation-status");
  if (status && state.backendSimulationStatusMessage && !state.backendSimulationPending && !snapshot.backendSimulation) {
    status.textContent = state.backendSimulationStatusMessage;
    return;
  }
  if (status && !state.backendSimulationPending && !snapshot.backendSimulation) {
    status.textContent = "현재 화면은 실시간 관망 계산값입니다.";
  }
}

function hasNetworkChanged() {
  if (!state.initialData) return false;
  return (
    state.nodes.length !== state.initialData.nodes.length ||
    state.pipes.length !== state.initialData.pipes.length ||
    state.reservoirs.length !== state.initialData.reservoirs.length ||
    state.pumps.length !== state.initialData.pumps.length ||
    state.leakDemands.size > 0 ||
    state.pipeEdits.size > 0
  );
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

function setMapLayer(layer) {
  state.mapLayer = layer || "pressure";
  document.querySelectorAll("[data-map-layer]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mapLayer === state.mapLayer);
  });
  render();
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
  const backendSimulation = activeBackendSimulation();
  const optimizedControlBoostM = activeOptimizedControlBoost();
  const sourceHead = Number($("source-head").value || 58) + Number($("pump-head").value || 0) + optimizedControlBoostM;
  const demandScale = Number($("demand-scale").value || 1);
  const leakDemands = activeLeakDemands();
  const demandByNode = nodeDemandAt(currentMinute());
  const source = state.reservoirs[0]?.node_id || "R1";
  const distances = weightedDistances(source);
  const localHydraulics = solveEpanetSnapshotHeads({
    sourceHead,
    demandScale,
    demandByNode,
    leakDemands,
  });

  const backendNodeById = new Map((backendSimulation?.node_results || []).map((node) => [String(node.node_id), node]));
  const nodes = state.nodes.map((node) => {
    const localDemand = Number(demandByNode.get(node.node_id) ?? node.base_demand_lps ?? 0) * demandScale;
    const solvedHead = localHydraulics.heads.get(String(node.node_id));
    const pressure = Number.isFinite(solvedHead)
      ? solvedHead - Number(node.elevation_m || 0)
      : sourceHead - Number(node.elevation_m || 0) - (distances.get(node.node_id) || 0) * 0.62;
    const backendNode = backendNodeById.get(String(node.node_id));
    const resolvedPressure = Number.isFinite(Number(backendNode?.pressure_head_m)) ? Number(backendNode.pressure_head_m) : pressure;
    const resolvedHead = Number.isFinite(Number(backendNode?.hydraulic_grade_m)) ? Number(backendNode.hydraulic_grade_m) : resolvedPressure + Number(node.elevation_m || 0);
    return {
      ...node,
      localDemand,
      pressure: resolvedPressure,
      hydraulicHead: resolvedHead,
      status: resolvedPressure < MIN_PRESSURE ? "low" : resolvedPressure < MARGINAL_PRESSURE ? "marginal" : "ok",
      compliant: resolvedPressure >= MIN_PRESSURE,
      backendPressure: Boolean(backendNode),
    };
  });

  const nodeById = new Map(nodes.map((node) => [node.node_id, node]));
  const backendPipeById = new Map((backendSimulation?.pipe_results || []).map((pipe) => [String(pipe.pipe_id), pipe]));
  const pipes = state.pipes.map((pipe) => {
    const design = pipeDesign(pipe);
    const from = nodeById.get(pipe.from_node);
    const to = nodeById.get(pipe.to_node);
    const endpointPressure = Math.min(from?.pressure ?? 999, to?.pressure ?? 999);
    const maxEndpointPressure = Math.max(from?.pressure ?? 0, to?.pressure ?? 0);
    const solvedFlow = localHydraulics.flows.get(String(pipe.pipe_id));
    const flow = Number.isFinite(solvedFlow)
      ? pipeFlowFromSolvedHead({ ...pipe, ...design }, from, to, solvedFlow)
      : estimatePipeFlow({ ...pipe, ...design }, from, to);
    const backendPipe = backendPipeById.get(String(pipe.pipe_id));
    const resolvedFlow = Number.isFinite(Number(backendPipe?.flow_lps)) ? Math.abs(Number(backendPipe.flow_lps)) : flow.flow_lps;
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
      flow_lps: resolvedFlow,
      flowDirection: flow.direction,
      flowVelocityMps: flow.velocityMps,
      headDeltaM: Number.isFinite(Number(backendPipe?.headloss_m)) ? Math.abs(Number(backendPipe.headloss_m)) : flow.headDeltaM,
      fromHead: flow.fromHead,
      toHead: flow.toHead,
      fromPressure: from?.pressure,
      toPressure: to?.pressure,
      leakDemand,
      backendFlow: Boolean(backendPipe),
    };
  });

  return { nodes, pipes, leakDemands, sourceHead, backendSimulation, optimizedControlBoostM };
}

function activeLeakDemands() {
  return new Map([...state.leakDemands].filter(([, demand]) => Number(demand) > 0));
}

function activeBackendSimulation() {
  if (!state.backendSimulation || !state.backendSimulationSignature) return null;
  return state.backendSimulationSignature === liveHydraulicStateSignature() ? state.backendSimulation : null;
}

function activeOptimizedControlBoost() {
  const boost = Number(state.optimizedControlBoostM || 0);
  if (!boost || !Number.isFinite(boost)) return 0;
  return state.optimizedControlSignatureBase === hydraulicControlBaseSignature() ? boost : 0;
}

function setOptimizedControlBoost(boostM) {
  const boost = Math.max(Number(boostM || 0), 0);
  state.optimizedControlBoostM = Number.isFinite(boost) ? boost : 0;
  state.optimizedControlSignatureBase = state.optimizedControlBoostM > 0 ? hydraulicControlBaseSignature() : "";
}

function clearOptimizedControlBoost() {
  state.optimizedControlBoostM = 0;
  state.optimizedControlSignatureBase = "";
}

async function runBackendSimulation() {
  return runHydraulicSimulationRequest("analysis");
}

async function runSourcePumpOptimization() {
  return runHydraulicSimulationRequest("optimization");
}

async function runHydraulicSimulationRequest(mode = "analysis") {
  if (state.backendSimulationPending) {
    const status = $("backend-simulation-status");
    if (status) status.textContent = "이미 계산 중입니다. 현재 계산이 끝난 뒤 다시 실행하세요.";
    return;
  }
  const analysisButton = $("run-backend-simulation");
  const optimizeButton = $("optimize-source-pump");
  const button = mode === "optimization" ? optimizeButton : analysisButton;
  const status = $("backend-simulation-status");
  const apiBase = String(window.__DRAWING_RECOGNITION_API_BASE__ || "").replace(/\/$/, "");
  if (mode === "optimization") clearOptimizedControlBoost();
  const requestPayload = networkSimulationPayload();
  if (!requestPayload.tables.nodes.length || !requestPayload.tables.pipes.length) {
    if (status) status.textContent = "EPANET .inp 관망을 먼저 적용한 뒤 계산할 수 있습니다.";
    return;
  }
  const requestSignature = liveHydraulicStateSignature(requestPayload);
  const startedAt = performance.now();
  state.backendSimulationPending = true;
  state.sourcePumpOptimizationPending = mode === "optimization";
  setHydraulicActionBusy(mode === "optimization");
  state.backendSimulationStatusMessage = "";
  state.backendSimulationStatusLevel = "";
  if (status) status.textContent = mode === "optimization" ? "Source/Pump 최적화 계산 중..." : "현재 조건 정밀 계산 요청 중...";
  render();
  try {
    const response = await fetch(`${apiBase}/api/simulate-network`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
    const payload = await readJsonResponse(response);
    if (!response.ok) throw new Error(payload.error || `simulation API failed (${response.status})`);
    validateHydraulicSimulationPayload(payload);
    const prediction = payload.source_pump_prediction;
    const boost = Number(prediction?.recommended_boost_m || 0);
    if (mode === "optimization") {
      setOptimizedControlBoost(boost);
      state.backendSimulation = simulationWithOptimizedControlBoost(payload, boost);
      state.backendSimulationSignature = liveHydraulicStateSignature(networkSimulationPayload());
    } else {
      state.backendSimulation = payload;
      state.backendSimulationSignature = requestSignature;
    }
    const predictedMin = Number(prediction?.predicted_min_pressure_m || 0);
    const lowAfter = prediction?.low_pressure_nodes_after?.length || 0;
    if (status) {
      status.textContent =
        mode === "optimization"
          ? `Source/Pump 최적화 완료 · 권장 추가 가압 ${boost.toFixed(2)} m · 예측 최저압 ${predictedMin.toFixed(2)} m · 잔여 저압 ${lowAfter}개`
          : `${payload.engine || "backend"} 결과 반영 · ${payload.node_results?.length || 0} nodes / ${payload.pipe_results?.length || 0} pipes · 권장 가압 ${boost.toFixed(2)} m`;
    }
  } catch (error) {
    console.warn("Backend simulation failed.", error);
    const fallback = mode === "optimization" ? frontendSourcePumpFallback(requestPayload, { reason: error.message || "API unavailable" }) : null;
    if (fallback) {
      setOptimizedControlBoost(fallback.source_pump_prediction?.recommended_boost_m || 0);
      state.backendSimulation = fallback;
      state.backendSimulationSignature = liveHydraulicStateSignature(networkSimulationPayload());
      state.backendSimulationStatusMessage = "";
      state.backendSimulationStatusLevel = "";
      const prediction = fallback.source_pump_prediction;
      if (status) {
        status.textContent = `Source/Pump 최적화 완료 · 브라우저 수리계산 · 권장 추가 가압 ${Number(prediction.recommended_boost_m || 0).toFixed(2)} m · 예측 최저압 ${Number(prediction.predicted_min_pressure_m || 0).toFixed(2)} m · 잔여 저압 ${prediction.low_pressure_nodes_after?.length || 0}개`;
      }
    } else {
      state.backendSimulation = null;
      state.backendSimulationSignature = "";
      state.backendSimulationStatusLevel = "error";
      state.backendSimulationStatusMessage = `${mode === "optimization" ? "Source/Pump 최적화" : "현재 조건 정밀 계산"} 실패: ${error.message || "server error"}`;
      if (status) status.textContent = `${mode === "optimization" ? "Source/Pump 최적화" : "현재 조건 정밀 계산"} 실패: ${error.message || "server error"}`;
    }
  } finally {
    const elapsed = performance.now() - startedAt;
    if (elapsed < HYDRAULIC_BUSY_MIN_MS) await delay(HYDRAULIC_BUSY_MIN_MS - elapsed);
    state.backendSimulationPending = false;
    state.sourcePumpOptimizationPending = false;
    setHydraulicActionBusy(false);
    if (button) button.blur();
    render();
  }
}

function setHydraulicActionBusy(isBusy) {
  document.body.classList.toggle("hydraulic-calculation-active", Boolean(isBusy));
  const controlBand = document.querySelector(".control-band");
  if (controlBand) {
    controlBand.classList.toggle("is-hydraulic-busy", Boolean(isBusy));
    if (isBusy) controlBand.dataset.busyLabel = "Source/Pump 최적화 계산 중... 입력을 잠시 잠급니다.";
    else delete controlBand.dataset.busyLabel;
  }
  $("source-pump-prediction")?.classList.toggle("is-hydraulic-busy", Boolean(isBusy));
  ["run-backend-simulation", "optimize-source-pump"].forEach((id) => {
    const button = $(id);
    if (!button) return;
    button.classList.toggle("hydraulic-action-busy", Boolean(isBusy));
    button.setAttribute("aria-busy", String(Boolean(isBusy)));
  });
  setHydraulicControlsLocked(Boolean(isBusy));
}

function setHydraulicControlsLocked(isLocked) {
  document.querySelectorAll(".control-band input, .control-band select, .control-band button").forEach((control) => {
    if (isLocked) {
      if (!Object.prototype.hasOwnProperty.call(control.dataset, "hydraulicPreviousDisabled")) {
        control.dataset.hydraulicPreviousDisabled = String(control.disabled);
      }
      control.disabled = true;
      return;
    }
    if (Object.prototype.hasOwnProperty.call(control.dataset, "hydraulicPreviousDisabled")) {
      control.disabled = control.dataset.hydraulicPreviousDisabled === "true";
      delete control.dataset.hydraulicPreviousDisabled;
    }
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
}

function simulationWithOptimizedControlBoost(payload, boostM) {
  const boost = Math.max(Number(boostM || 0), 0);
  const clone = JSON.parse(JSON.stringify(payload || {}));
  clone.summary = { ...(clone.summary || {}) };
  if (!boost || clone.summary.optimized_control_applied_to_map) return clone;
  const reservoirIds = new Set(state.nodes.filter((node) => node.node_type === "reservoir").map((node) => String(node.node_id)));
  clone.node_results = (clone.node_results || []).map((node) => {
    const nodeId = String(node.node_id || "");
    if (reservoirIds.has(nodeId)) return node;
    const pressure = Number(node.pressure_head_m);
    const grade = Number(node.hydraulic_grade_m);
    return {
      ...node,
      pressure_head_m: Number.isFinite(pressure) ? pressure + boost : node.pressure_head_m,
      hydraulic_grade_m: Number.isFinite(grade) ? grade + boost : node.hydraulic_grade_m,
      optimized_control_boost_m: boost,
    };
  });
  clone.pressure_violations = (clone.pressure_violations || []).filter((node) => Number(node.pressure_head_m || 0) + boost < MIN_PRESSURE);
  clone.summary.optimized_control_applied_to_map = true;
  clone.summary.optimized_control_boost_m = boost;
  return clone;
}

function frontendSourcePumpFallback(requestPayload, options = {}) {
  if (!state.nodes.length || !state.pipes.length) return null;
  const snapshot = computeSnapshot();
  const junctions = snapshot.nodes.filter((node) => node.node_type !== "reservoir");
  if (!junctions.length) return null;
  const minPressure = Math.min(...junctions.map((node) => Number(node.pressure || 0)));
  const requiredBoost = clamp(Math.max(0, MIN_PRESSURE - minPressure + 0.5), 0, 120);
  const predictedMin = minPressure + requiredBoost;
  const lowAfter = junctions.filter((node) => node.pressure + requiredBoost < MIN_PRESSURE).map((node) => ({
    node_id: node.node_id,
    pressure_head_m: Number((node.pressure + requiredBoost).toFixed(3)),
  }));
  const sources = buildFrontendSourceRecommendations(snapshot, requiredBoost);
  const pumps = buildFrontendPumpRecommendations(snapshot, requiredBoost);
  const totalSourceOutflow = sources.reduce((sum, item) => sum + Number(item.predicted_outflow_lps || 0), 0);
  const totalPumpFlow = pumps.reduce((sum, item) => sum + Number(item.predicted_flow_lps || 0), 0);
  const prediction = {
    feasible: lowAfter.length === 0,
    recommended_boost_m: requiredBoost,
    predicted_min_pressure_m: predictedMin,
    total_source_outflow_lps: totalSourceOutflow,
    total_pump_flow_lps: totalPumpFlow,
    low_pressure_nodes_after: lowAfter,
    sources,
    pumps,
    sensitivity_candidates: [],
    control_plan: [...sources, ...pumps].filter((item) => Number(item.recommended_boost_m || 0) > 0),
    epanet_validation_passed: false,
    frontend_validation_passed: lowAfter.length === 0,
    fallback_reason: options.reason || "",
    optimization_method: "frontend_epanet_formula_same_screen_solver",
    hydraulic_simulation_count: 1,
    cache_hit: false,
    warm_start_used: false,
  };
  return {
    engine: "frontend_epanet_formula_solver",
    hydraulic_formula: state.headlossFormula || "H-W",
    node_results: snapshot.nodes.map((node) => ({
      node_id: node.node_id,
      pressure_head_m: node.node_type === "reservoir" ? node.pressure : node.pressure + requiredBoost,
      hydraulic_grade_m: node.hydraulicHead + (node.node_type === "reservoir" ? 0 : requiredBoost),
    })),
    pipe_results: snapshot.pipes.map((pipe) => ({
      pipe_id: pipe.pipe_id,
      flow_lps: pipe.flow_lps,
      headloss_m: pipe.headDeltaM,
    })),
    pressure_violations: lowAfter,
    headloss_alerts: [],
    aged_pressure_stress: [],
    recommendations: [
      {
        action_type: "source_pump_frontend_fallback",
        description: "Streamlit iframe에서 백엔드 API 응답이 없어서 브라우저 계산값으로 Source/Pump 보정안을 표시했습니다.",
        expected_effect: `예측 최저압 ${predictedMin.toFixed(2)} m`,
        score: requiredBoost > 0 ? 0.72 : 0.3,
      },
    ],
    source_pump_prediction: prediction,
    summary: { fallback: true, source: "frontend", optimized_control_applied_to_map: true, optimized_control_boost_m: requiredBoost },
    warnings: [`Backend simulation API was unavailable; frontend hydraulic fallback was used.${options.reason ? ` ${options.reason}` : ""}`],
  };
}

function buildFrontendSourceRecommendations(snapshot, requiredBoost) {
  const sources = state.nodes.filter((node) => node.node_type === "reservoir");
  const sourceCount = Math.max(sources.length, 1);
  const sourceFlows = sourceOutflowLookup(snapshot);
  return sources.map((source) => {
    const reservoir = state.reservoirs.find((item) => item.node_id === source.node_id) || {};
    const currentHead = Number(reservoir.head_m || $("source-head")?.value || 0);
    const flow = Number(sourceFlows.get(source.node_id) || 0);
    return {
      source_id: reservoir.reservoir_id || source.node_id,
      node_id: source.node_id,
      current_head_m: currentHead,
      recommended_head_m: currentHead + requiredBoost / sourceCount,
      recommended_boost_m: requiredBoost / sourceCount,
      predicted_outflow_lps: flow,
      flow_contribution_percent: 0,
      optimization_status: requiredBoost > 0 ? "active" : "not_selected",
    };
  });
}

function buildFrontendPumpRecommendations(snapshot, requiredBoost) {
  const activePumps = state.pumps.filter((pump) => String(pump.status || "on").toLowerCase() !== "off");
  const pumpCount = Math.max(activePumps.length, 1);
  return activePumps.map((pump) => {
    const flow = pumpFlowEstimate(snapshot, pump);
    const currentHead = Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1);
    const boost = activePumps.length ? requiredBoost / pumpCount : 0;
    return {
      pump_id: pump.pump_id,
      current_head_gain_m: currentHead,
      recommended_head_gain_m: currentHead + boost,
      recommended_boost_m: boost,
      predicted_flow_lps: flow,
      flow_contribution_percent: 0,
      estimated_kw: pumpPowerKw(flow, currentHead + boost, pump.efficiency_percent),
      optimization_status: boost > 0 ? "active" : "not_selected",
      curve_points: pump.pump_curve_points || [],
      curve_id: pump.pump_curve_id || "",
      operating_flow_lps: flow,
      curve_head_m: currentHead + boost,
    };
  });
}

function sourceOutflowLookup(snapshot) {
  const outflow = new Map();
  for (const pipe of snapshot.pipes) {
    const from = state.nodes.find((node) => node.node_id === pipe.from_node);
    const to = state.nodes.find((node) => node.node_id === pipe.to_node);
    if (from?.node_type === "reservoir") outflow.set(from.node_id, (outflow.get(from.node_id) || 0) + Math.abs(Number(pipe.flow_lps || 0)));
    if (to?.node_type === "reservoir") outflow.set(to.node_id, (outflow.get(to.node_id) || 0) + Math.abs(Number(pipe.flow_lps || 0)));
  }
  return outflow;
}

function pumpFlowEstimate(snapshot, pump) {
  const matchingPipe = snapshot.pipes.find((pipe) =>
    (pipe.from_node === pump.from_node && pipe.to_node === pump.to_node) ||
    (pipe.from_node === pump.to_node && pipe.to_node === pump.from_node) ||
    pipe.pipe_id === `PUMP_${pump.pump_id}`,
  );
  return Math.abs(Number(matchingPipe?.flow_lps || 0));
}

function pumpPowerKw(flowLps, headM, efficiencyPercent) {
  const efficiency = clamp(Number(efficiencyPercent || 65) / 100, 0.05, 1);
  return (WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * Math.max(Number(flowLps || 0), 0) / 1000 * Math.max(Number(headM || 0), 0)) / efficiency / 1000;
}

async function readJsonResponse(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (error) {
    return { error: text.slice(0, 300) || error.message };
  }
}

function validateHydraulicSimulationPayload(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("simulation API returned an empty payload");
  }
  const hasPrediction = payload.source_pump_prediction && typeof payload.source_pump_prediction === "object";
  const hasNodes = Array.isArray(payload.node_results);
  const hasPipes = Array.isArray(payload.pipe_results);
  if (hasPrediction && hasNodes && hasPipes) return;
  const detail = payload.error ? String(payload.error).slice(0, 180) : "missing source_pump_prediction, node_results, or pipe_results";
  throw new Error(`simulation API returned an invalid payload: ${detail}`);
}

function networkSimulationPayload(options = {}) {
  const includeOptimizedBoost = options.includeOptimizedBoost !== false;
  const optimizedControlBoostM = includeOptimizedBoost ? activeOptimizedControlBoost() : 0;
  const demandByNode = nodeDemandAt(currentMinute());
  return {
    tables: {
      nodes: state.nodes.map((node) => ({
        ...node,
        base_demand_lps: node.node_type === "reservoir" ? 0 : Number(demandByNode.get(node.node_id) ?? node.base_demand_lps ?? 0),
      })),
      pipes: state.pipes.map((pipe) => ({ ...pipe, ...pipeDesign(pipe) })),
      reservoirs: state.reservoirs,
      pumps: state.pumps,
      valves: state.valves,
      demand_patterns: state.demandPatterns,
      energy_options: state.energyOptions ? [state.energyOptions] : [],
      pump_energy: state.pumpEnergy,
      options: [{ headloss: state.headlossFormula || "H-W" }],
    },
    scenario: {
      demand_multiplier: Number($("demand-scale").value || 1),
      source_head_m: Number($("source-head").value || state.reservoirs[0]?.head_m || 58),
      pump_head_m: Number($("pump-head").value || 0) + optimizedControlBoostM,
      optimized_control_boost_m: optimizedControlBoostM,
      time_index: currentTimeIndex(),
      minute_of_day: currentMinute(),
      leaks: [...activeLeakDemands()].map(([pipeId, demand]) => ({ pipe_id: pipeId, demand_lps: Number(demand || 0) })),
    },
  };
}

function liveHydraulicStateSignature(payload = networkSimulationPayload()) {
  return JSON.stringify({
    payload,
    minute: currentMinute(),
    time_index: currentTimeIndex(),
    demand_profile: $("demand-profile")?.value || "",
    active_demand_mode: state.activeDemandMode || "profile",
  });
}

function hydraulicControlBaseSignature() {
  return JSON.stringify({
    source_head_m: Number($("source-head")?.value || state.reservoirs[0]?.head_m || 58),
    pump_head_m: Number($("pump-head")?.value || 0),
    demand_scale: Number($("demand-scale")?.value || 1),
    demand_profile: $("demand-profile")?.value || state.demandProfile || "metro",
    active_demand_mode: state.activeDemandMode || "profile",
    headloss_formula: state.headlossFormula || "H-W",
    leaks: [...activeLeakDemands()].map(([pipeId, demand]) => [pipeId, Number(demand || 0)]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
    nodes: state.nodes.map((node) => [
      node.node_id,
      node.node_type,
      Number(node.elevation_m || 0),
      Number(node.base_demand_lps || 0),
      String(node.demand_pattern_id || ""),
    ]),
    pipes: state.pipes.map((pipe) => {
      const design = pipeDesign(pipe);
      return [
        pipe.pipe_id,
        pipe.from_node,
        pipe.to_node,
        Number(design.length_m || 0),
        Number(design.diameter_mm || 0),
        Number(design.roughness_c || 0),
        Number(design.minor_loss_k || 0),
        String(design.material || ""),
      ];
    }),
  });
}

function renderSourcePumpPrediction(snapshot) {
  const panel = $("source-pump-prediction");
  if (!panel) return;
  const prediction = snapshot.backendSimulation?.source_pump_prediction;
  if (state.sourcePumpOptimizationPending) {
    panel.innerHTML = `
      <div class="source-pump-prediction-header">
        <strong>Source/Pump 운영 최적화</strong>
        <span class="source-pump-badge">계산 중</span>
      </div>
      <div class="source-pump-empty">모든 Source와 Pump 조합을 현재 수요 조건에 맞춰 재계산하고 있습니다.</div>
    `;
    return;
  }
  if (state.backendSimulationStatusLevel === "error") {
    panel.innerHTML = `
      <div class="source-pump-prediction-header">
        <strong>Source/Pump 운영 최적화</strong>
        <span class="source-pump-badge is-warning">계산 실패</span>
      </div>
      <div class="source-pump-empty">${escapeHtml(state.backendSimulationStatusMessage || "Streamlit 계산 API 응답을 확인할 수 없습니다.")}</div>
    `;
    return;
  }
  if (!prediction) {
    panel.innerHTML = `
      <div class="source-pump-prediction-header">
        <strong>Source/Pump 운영 최적화</strong>
        <span class="source-pump-badge is-idle">대기</span>
      </div>
      <div class="source-pump-empty">최적화 버튼을 누르면 저압 해소를 위한 권장 가압, 공급 유량, 펌프 유량을 계산합니다.</div>
    `;
    return;
  }

  const sources = prediction.sources || [];
  const pumps = prediction.pumps || [];
  const lowAfter = prediction.low_pressure_nodes_after?.length || 0;
  const sourceRows = sources.length
    ? sources
        .map(
          (source) => `
            <li>
              <strong>${escapeHtml(source.source_id || "Source")}</strong>
              <span>수두 ${Number(source.current_head_m || 0).toFixed(2)} -> ${Number(source.recommended_head_m || 0).toFixed(2)} m · 추가 ${Number(source.recommended_boost_m || 0).toFixed(2)} m</span>
              <small>${Number(source.predicted_outflow_lps || 0).toFixed(2)} L/s · ${Number(source.flow_contribution_percent || 0).toFixed(1)}% · ${sourcePumpStatusLabel(source.optimization_status)}</small>
            </li>
          `
        )
        .join("")
    : `<li><strong>Source 없음</strong><span>현재 도면에서 Source를 찾지 못했습니다.</span><small>-</small></li>`;
  const pumpRows = pumps.length
    ? pumps
        .map(
          (pump) => `
            <li>
              <strong>${escapeHtml(pump.pump_id || "Pump")}</strong>
              <span>가압 ${Number(pump.current_head_gain_m || 0).toFixed(2)} -> ${Number(pump.recommended_head_gain_m || 0).toFixed(2)} m · 추가 ${Number(pump.recommended_boost_m || 0).toFixed(2)} m</span>
              <small>${Number(pump.predicted_flow_lps || 0).toFixed(2)} L/s · ${Number(pump.flow_contribution_percent || 0).toFixed(1)}% · ${sourcePumpStatusLabel(pump.optimization_status)}</small>
            </li>
          `
        )
        .join("")
    : `<li><strong>Pump 없음</strong><span>활성 Pump가 없으면 Source 수두를 기준으로 보정합니다.</span><small>-</small></li>`;
  const feasibilityText = prediction.feasible ? "저압 해소 가능" : "최대 가압에서도 저압 존재";
  const pumpRowsWithCurves = pumps.length ? renderPumpOperatingRows(pumps) : pumpRows;
  const badgeClass = prediction.feasible ? "is-good" : "is-warning";
  const sensitivityCount = prediction.sensitivity_candidates?.length || 0;
  const controlPlanCount = prediction.control_plan?.length || 0;
  const engineName = String(snapshot.backendSimulation?.engine || "");
  const frontendComputed = engineName.includes("frontend") || prediction.frontend_validation_passed === true;
  const validationText = prediction.epanet_validation_passed ? "EPANET 검증 통과" : frontendComputed ? "브라우저 수리계산 통과" : "EPANET 검증 필요";
  const accelerationText = frontendComputed ? "브라우저 계산" : prediction.cache_hit ? "캐시 재사용" : prediction.warm_start_used ? "Warm-start 적용" : "민감도 최적화";
  const activeControlCount = [...sources, ...pumps].filter((item) => Number(item.recommended_boost_m || 0) > 0).length;

  panel.innerHTML = `
    <div class="source-pump-prediction-header">
      <strong>Source/Pump 운영 최적화</strong>
      <span class="source-pump-badge ${badgeClass}">${feasibilityText}</span>
    </div>
    <div class="source-pump-prediction-grid">
      <span><small>권장 추가 가압</small>${Number(prediction.recommended_boost_m || 0).toFixed(2)} m</span>
      <span><small>예측 최저압</small>${Number(prediction.predicted_min_pressure_m || 0).toFixed(2)} m</span>
      <span><small>총 Source 공급</small>${Number(prediction.total_source_outflow_lps || 0).toFixed(2)} L/s</span>
      <span><small>총 Pump 유량</small>${Number(prediction.total_pump_flow_lps || 0).toFixed(2)} L/s</span>
      <span><small>잔여 저압</small>${lowAfter}개</span>
      <span><small>계산 가속</small>${accelerationText}</span>
      <span><small>후보/제어</small>${sensitivityCount} / ${controlPlanCount}</span>
      <span><small>실제 조정 자산</small>${activeControlCount}개</span>
      <span><small>정밀 검증</small>${validationText}</span>
    </div>
    <div class="source-pump-lists">
      <section>
        <h4>Source 권장 수두</h4>
        <ul>${sourceRows}</ul>
      </section>
      <section>
        <h4>Pump 권장 가압</h4>
        <ul>${pumpRowsWithCurves}</ul>
      </section>
    </div>
  `;
}

function renderPumpOperatingRows(pumps) {
  return pumps
    .map(
      (pump) => `
        <li>
          <strong>${escapeHtml(pump.pump_id || "Pump")}</strong>
          <span>Head ${Number(pump.current_head_gain_m || 0).toFixed(2)} -> ${Number(pump.recommended_head_gain_m || 0).toFixed(2)} m · boost ${Number(pump.recommended_boost_m || 0).toFixed(2)} m</span>
          <small>${Number(pump.predicted_flow_lps || 0).toFixed(2)} L/s · ${Number(pump.flow_contribution_percent || 0).toFixed(1)}% · ${Number(pump.estimated_kw || 0).toFixed(2)} kW · ${sourcePumpStatusLabel(pump.optimization_status)}</small>
          ${renderPumpCurveMiniChart(pump)}
        </li>
      `,
    )
    .join("");
}

function renderPumpCurveMiniChart(pump) {
  const points = Array.isArray(pump.curve_points) ? pump.curve_points : [];
  if (points.length < 2) return "";
  const width = 220;
  const height = 92;
  const pad = 16;
  const flows = points.map((point) => Number(point.flow_lps || 0));
  const heads = points.map((point) => Number(point.head_m || 0));
  const operatingFlow = Math.max(Number(pump.operating_flow_lps || Math.abs(Number(pump.predicted_flow_lps || 0))), 0);
  const operatingHead = Number.isFinite(Number(pump.curve_head_m)) ? Number(pump.curve_head_m) : Number(pump.recommended_head_gain_m || 0);
  const maxFlow = Math.max(...flows, operatingFlow, 1);
  const minHead = Math.min(...heads, operatingHead);
  const maxHead = Math.max(...heads, operatingHead, minHead + 1);
  const x = (flow) => pad + (Number(flow || 0) / maxFlow) * (width - pad * 2);
  const y = (head) => height - pad - ((Number(head || 0) - minHead) / Math.max(maxHead - minHead, 1e-6)) * (height - pad * 2);
  const path = points.map((point, index) => `${index ? "L" : "M"}${x(point.flow_lps).toFixed(1)} ${y(point.head_m).toFixed(1)}`).join(" ");
  const title = `${pump.pump_id || "Pump"} Q=${operatingFlow.toFixed(2)} L/s H=${operatingHead.toFixed(2)} m`;
  return `
    <div class="pump-curve-mini" title="${escapeHtml(title)}">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}">
        <path class="pump-curve-axis" d="M${pad} ${pad}V${height - pad}H${width - pad}" />
        <path class="pump-curve-line" d="${path}" />
        <circle class="pump-curve-point" cx="${x(operatingFlow).toFixed(1)}" cy="${y(operatingHead).toFixed(1)}" r="4.2" />
        <text x="${pad}" y="11">${escapeHtml(pump.curve_id || "curve")}</text>
        <text x="${width - pad}" y="${height - 4}" text-anchor="end">${operatingFlow.toFixed(1)} L/s · ${operatingHead.toFixed(1)} m</text>
      </svg>
    </div>
  `;
}

function sourcePumpStatusLabel(status) {
  return {
    active: "최적화 선택",
    hydraulic_head_only: "유량 기여 낮음",
    not_selected: "미선택",
  }[String(status || "not_selected")] || "미선택";
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
  const points = geometry.map((point) => project({ x: Number(point.x || 0), y: Number(point.y || 0) }));
  points[0] = from;
  points[points.length - 1] = to;
  return points;
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

function normalizeEpanetHeadlossFormula(formula) {
  const value = String(formula || "H-W").trim().toUpperCase().replaceAll("_", "-");
  if (["D-W", "DW", "DARCY-WEISBACH"].includes(value)) return "D-W";
  if (["C-M", "CM", "CHEZY-MANNING"].includes(value)) return "C-M";
  return "H-W";
}

function epanetPipeRoughness(pipe) {
  const formula = normalizeEpanetHeadlossFormula(state.headlossFormula);
  if (formula === "D-W") return Math.max(Number(pipe.roughness_mm || pipe.roughness_c || 0.1), 0.000001);
  if (formula === "C-M") return Math.max(Number(pipe.manning_n || pipe.roughness_n || 0.013), 0.000001);
  return Math.max(Number(pipe.adjusted_roughness_c || pipe.roughness_c || 100), 1);
}

function darcyWeisbachFrictionFactor(flowLps, diameterMm, roughnessMm) {
  const diameterM = Math.max(Number(diameterMm || 0) / 1000, 0.000001);
  const qM3s = Math.abs(Number(flowLps || 0)) / 1000;
  if (qM3s <= 0) return 0;
  const areaM2 = Math.PI * diameterM * diameterM / 4;
  const reynolds = (qM3s / areaM2) * diameterM / KINEMATIC_VISCOSITY_M2_S;
  if (reynolds <= 0) return 0;
  if (reynolds < 2000) return 64 / reynolds;
  const relativeRoughness = Math.max(Number(roughnessMm || 0), 0) / 1000 / diameterM;
  const turbulent = 0.25 / Math.pow(Math.log10(relativeRoughness / 3.7 + 5.74 / Math.pow(Math.max(reynolds, 1), 0.9)), 2);
  if (reynolds >= 4000) return turbulent;
  const laminar = 64 / reynolds;
  const ratio = (reynolds - 2000) / 2000;
  return laminar + ratio * (turbulent - laminar);
}

function epanetPipeResistance(pipe, flowLps = 0) {
  const formula = normalizeEpanetHeadlossFormula(state.headlossFormula);
  const lengthM = Math.max(Number(pipe.length_m || 0), 0);
  const diameterM = Math.max(Number(pipe.diameter_mm || 0) / 1000, 0.000001);
  const roughness = epanetPipeRoughness(pipe);
  if (formula === "D-W") {
    const friction = darcyWeisbachFrictionFactor(flowLps, pipe.diameter_mm, roughness);
    return { resistance: 0.0827 * friction * lengthM / Math.pow(diameterM, 5), exponent: 2 };
  }
  if (formula === "C-M") {
    return { resistance: 10.294 * Math.pow(roughness, 2) * lengthM / Math.pow(diameterM, 5.333), exponent: 2 };
  }
  return { resistance: 10.67 * lengthM / (Math.pow(roughness, 1.852) * Math.pow(diameterM, 4.871)), exponent: 1.852 };
}

function epanetMinorLossResistance(pipe) {
  const diameterM = Math.max(Number(pipe.diameter_mm || 0) / 1000, 0.000001);
  const minorLossK = Math.max(Number(pipe.minor_loss_k || 0), 0);
  return 8 * minorLossK / (GRAVITY_M_S2 * Math.PI * Math.PI * Math.pow(diameterM, 4));
}

function epanetHeadlossM(flowLps, pipe) {
  const flowM3s = Number(flowLps || 0) / 1000;
  if (!Number.isFinite(flowM3s) || flowM3s === 0) return 0;
  const sign = flowM3s >= 0 ? 1 : -1;
  const absFlow = Math.abs(flowM3s);
  const { resistance, exponent } = epanetPipeResistance(pipe, flowLps);
  const minorResistance = epanetMinorLossResistance(pipe);
  return sign * resistance * Math.pow(absFlow, exponent) + sign * minorResistance * absFlow * absFlow;
}

function epanetFlowFromHeadlossLps(headlossM, pipe) {
  const target = Number(headlossM || 0);
  if (!Number.isFinite(target) || Math.abs(target) < 1e-12) return 0;
  const sign = target >= 0 ? 1 : -1;
  const targetAbs = Math.abs(target);
  const formula = normalizeEpanetHeadlossFormula(state.headlossFormula);
  if (formula !== "D-W") {
    const { resistance, exponent } = epanetPipeResistance(pipe, 1);
    const minorResistance = epanetMinorLossResistance(pipe);
    if (minorResistance <= 0) return sign * Math.pow(targetAbs / Math.max(resistance, 1e-30), 1 / exponent) * 1000;
    let qM3s = Math.pow(targetAbs / Math.max(resistance + minorResistance, 1e-30), 1 / Math.max(exponent, 2));
    for (let index = 0; index < 14; index += 1) {
      const value = resistance * Math.pow(qM3s, exponent) + minorResistance * qM3s * qM3s - targetAbs;
      const gradient = exponent * resistance * Math.pow(Math.max(qM3s, 1e-12), exponent - 1) + 2 * minorResistance * qM3s;
      qM3s = Math.max(qM3s - value / Math.max(gradient, 1e-30), 0);
    }
    return sign * qM3s * 1000;
  }
  let low = 0;
  let high = 1;
  while (Math.abs(epanetHeadlossM(sign * high, pipe)) < targetAbs && high < 1_000_000) high *= 2;
  for (let index = 0; index < 72; index += 1) {
    const mid = (low + high) / 2;
    const value = Math.abs(epanetHeadlossM(sign * mid, pipe));
    if (value < targetAbs) low = mid;
    else high = mid;
  }
  return sign * (low + high) / 2;
}

function pumpGainForPipe(pipe) {
  const pump = state.pumps.find((item) => {
    const fromNode = String(item.from_node || "");
    const toNode = String(item.to_node || "");
    return fromNode === String(pipe.from_node || "") && toNode === String(pipe.to_node || "");
  });
  if (!pump || String(pump.status || "on").toLowerCase() === "off") return 0;
  return Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1);
}

function solveEpanetSnapshotHeads({ sourceHead, demandScale, demandByNode, leakDemands }) {
  const fixedHeads = new Map();
  for (const reservoir of state.reservoirs) {
    fixedHeads.set(String(reservoir.node_id), Number(reservoir.head_m || sourceHead));
  }
  if (state.reservoirs[0]) fixedHeads.set(String(state.reservoirs[0].node_id), Number(sourceHead));
  const unknownNodes = state.nodes.filter((node) => !fixedHeads.has(String(node.node_id)));
  const heads = new Map(fixedHeads);
  const flows = new Map();
  if (!unknownNodes.length) return { heads, flows, converged: true };

  const unknownIndex = new Map(unknownNodes.map((node, index) => [String(node.node_id), index]));
  let vector = unknownNodes.map((node) => Number(sourceHead) - Number(node.elevation_m || 0) * 0.05);
  const demand = new Map();
  for (const node of state.nodes) {
    demand.set(String(node.node_id), Number(demandByNode.get(node.node_id) ?? node.base_demand_lps ?? 0) * Number(demandScale || 1));
  }
  for (const [pipeId, value] of leakDemands || new Map()) {
    const pipe = state.pipes.find((item) => String(item.pipe_id) === String(pipeId));
    if (!pipe) continue;
    const leak = Number(value || 0) / 2;
    demand.set(String(pipe.from_node), Number(demand.get(String(pipe.from_node)) || 0) + leak);
    demand.set(String(pipe.to_node), Number(demand.get(String(pipe.to_node)) || 0) + leak);
  }

  const unpack = (values) => {
    const result = new Map(fixedHeads);
    unknownNodes.forEach((node, index) => result.set(String(node.node_id), Number(values[index])));
    return result;
  };

  const residual = (values) => {
    const currentHeads = unpack(values);
    const balance = unknownNodes.map((node) => Number(demand.get(String(node.node_id)) || 0));
    for (const pipe of state.pipes) {
      const design = { ...pipe, ...pipeDesign(pipe) };
      const fromNode = String(pipe.from_node);
      const toNode = String(pipe.to_node);
      const fromHead = Number(currentHeads.get(fromNode) ?? sourceHead);
      const toHead = Number(currentHeads.get(toNode) ?? sourceHead);
      const flow = epanetFlowFromHeadlossLps(fromHead + pumpGainForPipe(pipe) - toHead, design);
      if (unknownIndex.has(fromNode)) balance[unknownIndex.get(fromNode)] += flow;
      if (unknownIndex.has(toNode)) balance[unknownIndex.get(toNode)] -= flow;
    }
    return balance;
  };

  let converged = false;
  for (let iteration = 0; iteration < 32; iteration += 1) {
    const current = residual(vector);
    if (Math.max(...current.map((value) => Math.abs(value))) < 1e-4) {
      converged = true;
      break;
    }
    const jacobian = current.map(() => Array(vector.length).fill(0));
    for (let column = 0; column < vector.length; column += 1) {
      const step = Math.max(Math.abs(vector[column]) * 1e-6, 1e-4);
      const shifted = vector.slice();
      shifted[column] += step;
      const shiftedResidual = residual(shifted);
      for (let row = 0; row < current.length; row += 1) {
        jacobian[row][column] = (shiftedResidual[row] - current[row]) / step;
      }
    }
    const delta = solveLinearSystem(jacobian, current.map((value) => -value));
    if (!delta) break;
    const maxStep = Math.max(...delta.map((value) => Math.abs(value)));
    const scale = maxStep > 20 ? 20 / maxStep : 1;
    vector = vector.map((value, index) => value + delta[index] * scale);
    if (maxStep < 1e-6) {
      converged = true;
      break;
    }
  }

  const solvedHeads = unpack(vector);
  for (const pipe of state.pipes) {
    const design = { ...pipe, ...pipeDesign(pipe) };
    const fromHead = Number(solvedHeads.get(String(pipe.from_node)) ?? sourceHead);
    const toHead = Number(solvedHeads.get(String(pipe.to_node)) ?? sourceHead);
    flows.set(String(pipe.pipe_id), epanetFlowFromHeadlossLps(fromHead + pumpGainForPipe(pipe) - toHead, design));
  }
  return { heads: solvedHeads, flows, converged };
}

function solveLinearSystem(matrix, rhs) {
  const n = rhs.length;
  const a = matrix.map((row, index) => [...row, rhs[index]]);
  for (let pivot = 0; pivot < n; pivot += 1) {
    let maxRow = pivot;
    for (let row = pivot + 1; row < n; row += 1) {
      if (Math.abs(a[row][pivot]) > Math.abs(a[maxRow][pivot])) maxRow = row;
    }
    if (Math.abs(a[maxRow][pivot]) < 1e-12) return null;
    [a[pivot], a[maxRow]] = [a[maxRow], a[pivot]];
    const pivotValue = a[pivot][pivot];
    for (let column = pivot; column <= n; column += 1) a[pivot][column] /= pivotValue;
    for (let row = 0; row < n; row += 1) {
      if (row === pivot) continue;
      const factor = a[row][pivot];
      for (let column = pivot; column <= n; column += 1) a[row][column] -= factor * a[pivot][column];
    }
  }
  return a.map((row) => row[n]);
}

function pipeFlowFromSolvedHead(pipe, from, to, flowLps) {
  const diameterM = Math.max(Number(pipe.diameter_mm || 1) / 1000, 0.000001);
  const qM3s = Math.abs(Number(flowLps || 0)) / 1000;
  const area = Math.PI * Math.pow(diameterM / 2, 2);
  const fromHead = Number(from?.hydraulicHead ?? Number(from?.pressure || 0) + Number(from?.elevation_m || 0));
  const toHead = Number(to?.hydraulicHead ?? Number(to?.pressure || 0) + Number(to?.elevation_m || 0));
  return {
    flow_lps: Math.abs(Number(flowLps || 0)),
    direction: Math.abs(flowLps) < 1e-6 ? "none" : flowLps >= 0 ? "forward" : "reverse",
    velocityMps: area > 0 ? qM3s / area : 0,
    headDeltaM: epanetHeadlossM(flowLps, pipe),
    fromHead,
    toHead,
  };
}

function estimatePipeFlow(pipe, from, to) {
  if (!from || !to) {
    return { flow_lps: 0, direction: "none", velocityMps: 0, headDeltaM: 0 };
  }
  const fromHead = Number(from.hydraulicHead ?? Number(from.pressure || 0) + Number(from.elevation_m || 0));
  const toHead = Number(to.hydraulicHead ?? Number(to.pressure || 0) + Number(to.elevation_m || 0));
  const headDelta = fromHead - toHead;
  const direction = Math.abs(headDelta) < 0.05 ? "none" : headDelta >= 0 ? "forward" : "reverse";
  const flowLps = epanetFlowFromHeadlossLps(headDelta + pumpGainForPipe(pipe), pipe);
  const diameterM = Math.max(Number(pipe.diameter_mm || 1) / 1000, 0.000001);
  const qM3s = Math.abs(flowLps) / 1000;
  const area = Math.PI * Math.pow(diameterM / 2, 2);
  return {
    flow_lps: Math.abs(flowLps),
    direction,
    velocityMps: area > 0 ? qM3s / area : 0,
    headDeltaM: epanetHeadlossM(flowLps, pipe),
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
  const profileId = currentDemandProfileId();
  if (state.activeDemandMode === "inp" && state.demandPatterns.length) return inpPatternNodeDemandAt(minute, profileId);
  if (demandProfiles[profileId]) return genericNodeDemandAt(minute, profileId);
  if (!state.demandByMinute.size) {
    return new Map(state.nodes.map((node) => [node.node_id, cityDemandValue(node, minute, profileId, node.base_demand_lps || 0)]));
  }
  const available = [...state.demandByMinute.keys()].sort((a, b) => a - b);
  const nearest = available.reduce((best, candidate) => {
    const bestDistance = circularMinuteDistance(best, minute);
    const candidateDistance = circularMinuteDistance(candidate, minute);
    return candidateDistance < bestDistance ? candidate : best;
  }, available[0]);
  return scaleDemandMapByProfile(state.demandByMinute.get(nearest) || new Map(), minute, profileId);
}

function currentDemandProfileId() {
  const profileId = $("demand-profile")?.value || state.demandProfile || "metro";
  return demandProfiles[profileId] ? profileId : "metro";
}

function demandProfileLabel(profileId = currentDemandProfileId()) {
  return {
    metro: "대도시",
    midsize: "중소도시",
    rural: "농업도시",
  }[profileId] || "대도시";
}

function inpPatternNodeDemandAt(minute, profileId = currentDemandProfileId()) {
  return new Map(
    state.nodes.map((node) => {
      if (node.node_type === "reservoir") return [node.node_id, 0];
      const patternId = String(node.demand_pattern_id || "");
      const patternMultiplier = patternId ? demandPatternFactor(patternId, minute) : 1;
      return [node.node_id, cityDemandValue(node, minute, profileId, Number(node.base_demand_lps || 0) * patternMultiplier)];
    }),
  );
}

function demandPatternFactor(patternId, minute) {
  const rows = state.demandPatterns
    .filter((row) => String(row.pattern_id || "") === String(patternId || ""))
    .sort((a, b) => Number(a.step_index ?? a.hour ?? 0) - Number(b.step_index ?? b.hour ?? 0));
  if (!rows.length) return 1;
  const timestep = demandPatternTimestepMinutes(rows);
  const wrapped = ((Number(minute || 0) % 1440) + 1440) % 1440;
  const cycleMinutes = Math.max(rows.length * Math.max(timestep, 1), Math.max(timestep, 1));
  const position = (wrapped % cycleMinutes) / Math.max(timestep, 1);
  const step = Math.floor(position) % rows.length;
  const nextStep = (step + 1) % rows.length;
  const ratio = position - Math.floor(position);
  const current = Number(rows[step]?.multiplier ?? 1);
  const next = Number(rows[nextStep]?.multiplier ?? current);
  return current + (next - current) * ratio;
}

function demandPatternTimestepMinutes(rows) {
  const minutes = rows
    .map((row) => Number(row.minute))
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b);
  for (let index = 1; index < minutes.length; index += 1) {
    const delta = minutes[index] - minutes[index - 1];
    if (delta > 0) return delta;
  }
  const hours = rows
    .map((row) => Number(row.hour))
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b);
  for (let index = 1; index < hours.length; index += 1) {
    const delta = hours[index] - hours[index - 1];
    if (delta > 0) return delta * 60;
  }
  return 60;
}

function genericNodeDemandAt(minute, profileId) {
  return new Map(
    state.nodes.map((node) => [
      node.node_id,
      cityDemandValue(node, minute, profileId, Number(node.base_demand_lps || 0.8)),
    ]),
  );
}

function scaleDemandMapByProfile(demandMap, minute, profileId) {
  return new Map(
    state.nodes.map((node) => [
      node.node_id,
      cityDemandValue(node, minute, profileId, Number(demandMap.get(node.node_id) ?? node.base_demand_lps ?? 0)),
    ]),
  );
}

function cityDemandValue(node, minute, profileId, baseDemand) {
  if (node.node_type === "reservoir") return 0;
  return Number(baseDemand || 0) * demandProfileFactor(minute, profileId);
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
    const hydraulic = epanetPipeResistance({ ...pipe, ...design }, Math.max(Number(design.design_flow_lps || 1), 1));
    const weight = Math.max(hydraulic.resistance, 1e-9) * (1 + age * 2.2) * valvePenalty;
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

function renderOperationsConsole(snapshot) {
  const junctions = snapshot.nodes.filter((node) => node.node_type !== "reservoir");
  const lowNodes = junctions.filter((node) => node.status === "low");
  const marginalNodes = junctions.filter((node) => node.status === "marginal");
  const leakPipes = snapshot.pipes.filter((pipe) => Number(pipe.leakDemand || 0) > 0 || pipe.status === "leak");
  const topLeak = topLeakCandidate(snapshot);
  const totalDemand = junctions.reduce((sum, node) => sum + Number(node.localDemand || 0), 0);
  const totalFlow = snapshot.pipes.reduce((sum, pipe) => sum + Number(pipe.flow_lps || 0), 0);
  const minPressure = junctions.length ? Math.min(...junctions.map((node) => Number(node.pressure || 0))) : null;
  const pressureCoverage = clamp((minPressure - 8) / 22);
  const scadaHealth = clamp(1 - (lowNodes.length * 0.18 + marginalNodes.length * 0.06 + leakPipes.length * 0.12));
  const leakProbability = topLeak ? topLeak.leakProbability : 0;
  const twinReadiness = clamp(
    0.42 +
      (state.nodes.length > 0 ? 0.12 : 0) +
      (state.pipes.length > 0 ? 0.12 : 0) +
      (state.timeline.length > 0 ? 0.12 : 0) +
      (state.drawingAssetsApplied ? 0.1 : 0) +
      (snapshot.backendSimulation ? 0.12 : 0),
  );

  setOpsCard(
    "gis",
    junctions.length ? (lowNodes.length ? `저압 ${lowNodes.length}개 감지` : `최소압 ${minPressure.toFixed(1)} m`) : "INP 대기",
    junctions.length ? `${formatMinute(currentMinute())} 기준 압력 Heatmap · 주의 ${marginalNodes.length}개 · 지도 레이어 ${mapLayerLabel(state.mapLayer)}` : ".inp 파일을 업로드하면 관망지도가 생성됩니다.",
    pressureCoverage,
  );
  setOpsCard(
    "scada",
    leakPipes.length ? `경보 ${leakPipes.length}건` : "가상 SCADA 정상",
    `총 수요 ${totalDemand.toFixed(1)} L/s · 추정 관로 유량 합계 ${totalFlow.toFixed(1)} L/s · Pump ${Number($("pump-head").value || 0).toFixed(1)} m`,
    scadaHealth,
  );
  setOpsCard(
    "leak",
    topLeak ? `${topLeak.pipe_id} ${Math.round(leakProbability * 100)}%` : "후보 없음",
    topLeak
      ? `압력 취약도 ${Math.round(topLeak.pressureComponent * 100)}% · 노후도 ${Math.round(topLeak.aging * 100)}% · MNF 가중 ${Math.round(topLeak.nightComponent * 100)}%`
      : "누수량을 추가하거나 야간 시간대로 이동하면 후보 점수가 갱신됩니다.",
    leakProbability,
  );
  setOpsCard(
    "twin",
    snapshot.backendSimulation ? "해석 결과 동기화" : "브라우저 실시간 모델",
    `자산 ${state.pipes.length} pipes/${junctions.length} junctions · 시간 스텝 ${state.timeline.length}개 · ${hasNetworkChanged() ? "편집 반영" : "기본 네트워크"}`,
    twinReadiness,
  );
}

function setOpsCard(kind, status, detail, score) {
  const statusEl = $(`ops-${kind}-status`);
  const detailEl = $(`ops-${kind}-detail`);
  const meterEl = $(`ops-${kind}-meter`);
  if (statusEl) statusEl.textContent = status;
  if (detailEl) detailEl.textContent = detail;
  if (meterEl) meterEl.style.width = `${Math.round(clamp(score) * 100)}%`;
}

function renderProfessionalDiagnostics(snapshot) {
  const grid = $("expert-diagnostics-grid");
  if (!grid) return;
  const diagnostics = buildProfessionalDiagnostics(snapshot);
  grid.innerHTML = diagnostics
    .map(
      (item) => `
        <article class="expert-card ${item.level}">
          <div>
            <span>${escapeHtml(item.category)}</span>
            <strong>${escapeHtml(item.title)}</strong>
          </div>
          <p>${escapeHtml(item.detail)}</p>
          <small>${escapeHtml(item.action)}</small>
        </article>
      `,
    )
    .join("");
}

function buildProfessionalDiagnostics(snapshot) {
  if (!snapshot.nodes.length && !snapshot.pipes.length) {
    return [
      {
        category: "INP",
        title: "관망 데이터 대기",
        detail: ".inp 파일을 업로드하면 압력 원인, Fire Flow, 밸브 격리, DMA 누수, 자산 위험도 진단을 계산합니다.",
        action: "도면 .inp 업로드 후 관망 적용",
        level: "info",
      },
    ];
  }
  return [
    pressureCauseDiagnostic(snapshot),
    fireFlowDiagnostic(snapshot),
    valveIsolationDiagnostic(snapshot),
    tankOperationDiagnostic(snapshot),
    waterQualityDiagnostic(snapshot),
    scadaDiagnostic(snapshot),
    minimumNightFlowDiagnostic(snapshot),
    failureRiskDiagnostic(snapshot),
    reportDiagnostic(snapshot),
    epanetToolkitDiagnostic(snapshot),
  ];
}

function pressureCauseDiagnostic(snapshot) {
  const junctions = snapshot.nodes.filter((node) => node.node_type !== "reservoir");
  const lowNodes = junctions.filter((node) => node.status === "low");
  if (!lowNodes.length) {
    return {
      category: "Pressure",
      title: "저압 원인 없음",
      detail: "현재 시간 조건에서 15m 미만 Junction이 없습니다.",
      action: "피크 수요 시간대와 Fire Flow 조건에서 재확인",
      level: "ok",
    };
  }
  const leakPipes = snapshot.pipes.filter((pipe) => pipe.status === "leak" || Number(pipe.leakDemand || 0) > 0);
  const highDemand = [...junctions].sort((a, b) => Number(b.localDemand || 0) - Number(a.localDemand || 0))[0];
  const bottleneck = [...snapshot.pipes].sort((a, b) => pipeCapacityIndex(a) - pipeCapacityIndex(b))[0];
  const pumpHead = Number($("pump-head")?.value || 0);
  const sourceHead = Number($("source-head")?.value || 0);
  const cause = leakPipes.length
    ? "누수 의심"
    : pumpHead < 5 && sourceHead < 45
      ? "수원/Pump 가압 부족"
      : bottleneck && pipeCapacityIndex(bottleneck) < 0.55
        ? "관경/조도 병목"
        : highDemand && Number(highDemand.localDemand || 0) > 20
          ? "고수요 집중"
          : "수두 손실 누적";
  return {
    category: "Pressure",
    title: `${lowNodes.length}개 저압 · ${cause}`,
    detail: `최저 Junction ${lowNodes.sort((a, b) => a.pressure - b.pressure)[0].node_id}, 병목 후보 ${bottleneck?.pipe_id || "-"}, 최대 수요 ${highDemand?.node_id || "-"} ${Number(highDemand?.localDemand || 0).toFixed(1)} L/s`,
    action: "Source/Pump 최적화 실행 후 병목 Pipe 관경/조도와 누수 시나리오 확인",
    level: "warning",
  };
}

function fireFlowDiagnostic(snapshot) {
  const target = fireFlowTarget(snapshot);
  if (!target) {
    return { category: "Fire Flow", title: "대상 Junction 없음", detail: "화재유량을 적용할 Junction이 없습니다.", action: "INP 관망 적용", level: "info" };
  }
  const extraFlow = 30;
  const simulated = pressureWithExtraDemand(target.node_id, extraFlow);
  const residual = simulated.pressureByNode.get(target.node_id);
  const lowCount = [...simulated.pressureByNode.values()].filter((pressure) => pressure < MIN_PRESSURE).length;
  const pass = Number(residual) >= MIN_PRESSURE && lowCount === 0;
  return {
    category: "Fire Flow",
    title: `${target.node_id} ${extraFlow} L/s ${pass ? "예비 통과" : "압력 부족"}`,
    detail: `화재유량 적용 후 대상 잔압 ${Number(residual || 0).toFixed(1)}m, 저압 Junction ${lowCount}개`,
    action: pass ? "소화전 위치별 반복 검토" : "인근 관경 확대, Pump 가압, 우회 공급 검토",
    level: pass ? "ok" : "risk",
  };
}

function valveIsolationDiagnostic(snapshot) {
  const targetPipe = selectedPipeId() || computeReplacementRanking(snapshot)[0]?.pipe_id || snapshot.pipes[0]?.pipe_id;
  if (!targetPipe) {
    return { category: "Valve Isolation", title: "격리 대상 Pipe 없음", detail: "Pipe가 없어 밸브 격리 분석을 수행할 수 없습니다.", action: "INP 관망 적용", level: "info" };
  }
  const isolated = disconnectedNodesWithoutPipe(snapshot, targetPipe);
  const demandAffected = isolated.reduce((sum, node) => sum + Number(node.localDemand || 0), 0);
  return {
    category: "Valve Isolation",
    title: `${targetPipe} 격리 영향 ${isolated.length}개 Junction`,
    detail: `예상 영향 수요 ${demandAffected.toFixed(1)} L/s. 실제 밸브 데이터가 있으면 차단 밸브 목록까지 자동화 가능합니다.`,
    action: isolated.length ? "우회 공급 가능 Pipe와 밸브 위치 확인" : "격리 시 연결성 영향 낮음",
    level: isolated.length > 3 ? "risk" : isolated.length ? "warning" : "ok",
  };
}

function tankOperationDiagnostic(snapshot) {
  const tankLike = snapshot.nodes.filter((node) => String(node.node_type || "").toLowerCase() === "tank");
  return {
    category: "Tank",
    title: tankLike.length ? `${tankLike.length}개 Tank 운영 검토` : "Tank 데이터 없음",
    detail: tankLike.length ? "Tank 수위와 Pump 스케줄 최적화를 적용할 수 있습니다." : "현재 INP에서 Tank가 인식되지 않아 Source/Pump 중심으로만 운영 최적화합니다.",
    action: tankLike.length ? "시간대별 전기요금과 목표 수위 범위 입력" : "[TANKS] 섹션 포함 INP로 확장",
    level: tankLike.length ? "ok" : "info",
  };
}

function waterQualityDiagnostic(snapshot) {
  const deadEnds = deadEndJunctions(snapshot);
  const lowFlowPipes = snapshot.pipes.filter((pipe) => Number(pipe.flow_lps || 0) < 0.2);
  const risk = deadEnds.length + lowFlowPipes.length;
  return {
    category: "Water Quality",
    title: risk ? `Water Age 위험 후보 ${risk}개` : "Water Age 위험 낮음",
    detail: `말단 Junction ${deadEnds.length}개, 저유량 Pipe ${lowFlowPipes.length}개. 잔류염소 모델은 EPANET Toolkit 연동 시 정밀화 가능합니다.`,
    action: risk ? "말단 배수/순환, 잔류염소 센서 위치 검토" : "수질 시간해석 조건 입력 준비",
    level: risk > 5 ? "warning" : "ok",
  };
}

function scadaDiagnostic(snapshot) {
  const backend = snapshot.backendSimulation;
  return {
    category: "SCADA",
    title: backend ? "모델 결과 동기화됨" : "실측 센서 미연동",
    detail: backend ? "백엔드 해석값과 브라우저 모델을 비교할 준비가 되어 있습니다." : "압력/유량 센서 CSV나 WebSocket을 연결하면 센서 이상, 모델 보정, 실제 누수 의심을 분리할 수 있습니다.",
    action: "sensor_id, node_or_pipe_id, type, timestamp, value 구조의 센서 입력 추가",
    level: backend ? "ok" : "info",
  };
}

function minimumNightFlowDiagnostic(snapshot) {
  const dmas = new Map();
  snapshot.pipes.forEach((pipe) => {
    const key = dmaForPipe(pipe) || "UNKNOWN";
    const current = dmas.get(key) || { leak: 0, flow: 0, count: 0 };
    current.leak += topLeakCandidate({ ...snapshot, pipes: [pipe] })?.leakProbability || 0;
    current.flow += Number(pipe.flow_lps || 0);
    current.count += 1;
    dmas.set(key, current);
  });
  const ranked = [...dmas].map(([dma, item]) => ({ dma, score: item.leak / Math.max(item.count, 1), flow: item.flow })).sort((a, b) => b.score - a.score);
  const top = ranked[0];
  return {
    category: "MNF",
    title: top ? `${top.dma} 야간누수 우선검토` : "DMA 없음",
    detail: top ? `DMA 평균 누수확률 ${Math.round(top.score * 100)}%, 관로 유량 합계 ${top.flow.toFixed(1)} L/s` : "DMA 정보가 없어 야간 최소유량 분석을 묶을 수 없습니다.",
    action: "야간 시간대 SCADA 유량계와 DMA 경계 밸브 정보 연결",
    level: top && top.score > 0.45 ? "warning" : "info",
  };
}

function failureRiskDiagnostic(snapshot) {
  const top = computeReplacementRanking(snapshot)[0];
  if (!top) return { category: "Asset Risk", title: "위험 산정 대상 없음", detail: "Pipe가 없어 파손위험도를 산정할 수 없습니다.", action: "INP 관망 적용", level: "info" };
  return {
    category: "Asset Risk",
    title: `${top.pipe_id} 5년 파손위험 후보`,
    detail: `노후도 ${Number(top.aging || 0).toFixed(2)}, 우선순위 ${Math.round(Number(top.priorityScore || 0) * 100)}점, 상태 ${statusLabel(top.status)}`,
    action: "누수 이력, 토양 부식성, 도로 하중 데이터를 추가하면 확률모델로 확장 가능",
    level: Number(top.priorityScore || 0) > 0.65 ? "risk" : "warning",
  };
}

function reportDiagnostic(snapshot) {
  return {
    category: "Report",
    title: "진단 리포트 생성 가능",
    detail: `현재 ${snapshot.nodes.length} nodes / ${snapshot.pipes.length} pipes 기준 진단/리포트 JSON을 내려받을 수 있습니다.`,
    action: "상단 '진단 리포트 JSON' 버튼 사용",
    level: "ok",
  };
}

function epanetToolkitDiagnostic(snapshot) {
  const backend = snapshot.backendSimulation;
  const toolkitLinked = Boolean(backend && !String(backend.engine || "").includes("fallback"));
  return {
    category: "EPANET",
    title: toolkitLinked ? "Toolkit 엔진 사용" : "EPANET식 로컬 Solver",
    detail: toolkitLinked ? `엔진 ${backend.engine}` : "현재는 EPANET 2.2 수두손실식 기반 로컬 해석입니다. Toolkit 직접 연동 시 신뢰성 표기가 더 강해집니다.",
    action: "WNTR/EPANET Toolkit 실행 경로와 결과 비교 리포트 추가",
    level: toolkitLinked ? "ok" : "info",
  };
}

function topLeakCandidate(snapshot) {
  return snapshot.pipes
    .map((pipe) => {
      const leakDemand = clamp(Number(pipe.leakDemand || 0) / 6);
      const pressureComponent = clamp((MARGINAL_PRESSURE - Number(pipe.endpointPressure || 0)) / MARGINAL_PRESSURE);
      const aging = state.aging.get(pipe.pipe_id) || 0;
      const nightComponent = isNightMinute(currentMinute()) ? clamp(Number(pipe.flow_lps || 0) / 12) : 0;
      const leakProbability = clamp(leakDemand * 0.36 + pressureComponent * 0.28 + aging * 0.24 + nightComponent * 0.12);
      return { ...pipe, leakProbability, pressureComponent, aging, nightComponent };
    })
    .sort((a, b) => b.leakProbability - a.leakProbability)[0];
}

function pipeCapacityIndex(pipe) {
  const diameter = Number(pipe.diameter_mm || 0);
  const roughness = Number(pipe.roughness_c || pipe.roughness_hw || 100);
  const length = Math.max(Number(pipe.length_m || 1), 1);
  return clamp((diameter / 300) * (roughness / 120) / Math.sqrt(length / 150), 0, 2);
}

function fireFlowTarget(snapshot) {
  const [kind, id] = (state.selected || "").split(":");
  if (kind === "node") {
    const selected = snapshot.nodes.find((node) => node.node_id === id && node.node_type !== "reservoir");
    if (selected) return selected;
  }
  return [...snapshot.nodes]
    .filter((node) => node.node_type !== "reservoir")
    .sort((a, b) => Number(a.pressure || 0) - Number(b.pressure || 0))[0];
}

function pressureWithExtraDemand(nodeId, extraLps) {
  const sourceHead = Number($("source-head").value || 58) + Number($("pump-head").value || 0) + activeOptimizedControlBoost();
  const demandScale = Number($("demand-scale").value || 1);
  const demandByNode = nodeDemandAt(currentMinute());
  demandByNode.set(nodeId, Number(demandByNode.get(nodeId) || 0) + Number(extraLps || 0));
  const solved = solveEpanetSnapshotHeads({
    sourceHead,
    demandScale,
    demandByNode,
    leakDemands: activeLeakDemands(),
  });
  const pressureByNode = new Map();
  state.nodes.forEach((node) => {
    if (node.node_type === "reservoir") return;
    const head = solved.heads.get(String(node.node_id));
    pressureByNode.set(node.node_id, Number.isFinite(head) ? head - Number(node.elevation_m || 0) : -Infinity);
  });
  return { pressureByNode, converged: solved.converged };
}

function disconnectedNodesWithoutPipe(snapshot, pipeId) {
  const reservoirs = new Set(snapshot.nodes.filter((node) => node.node_type === "reservoir").map((node) => node.node_id));
  const graph = new Map();
  const add = (a, b) => {
    if (!graph.has(a)) graph.set(a, new Set());
    graph.get(a).add(b);
  };
  snapshot.pipes.forEach((pipe) => {
    if (pipe.pipe_id === pipeId) return;
    add(pipe.from_node, pipe.to_node);
    add(pipe.to_node, pipe.from_node);
  });
  const visited = new Set();
  const queue = [...reservoirs];
  queue.forEach((node) => visited.add(node));
  while (queue.length) {
    const node = queue.shift();
    for (const next of graph.get(node) || []) {
      if (visited.has(next)) continue;
      visited.add(next);
      queue.push(next);
    }
  }
  return snapshot.nodes.filter((node) => node.node_type !== "reservoir" && !visited.has(node.node_id));
}

function deadEndJunctions(snapshot) {
  const degree = new Map();
  snapshot.pipes.forEach((pipe) => {
    degree.set(pipe.from_node, (degree.get(pipe.from_node) || 0) + 1);
    degree.set(pipe.to_node, (degree.get(pipe.to_node) || 0) + 1);
  });
  return snapshot.nodes.filter((node) => node.node_type !== "reservoir" && (degree.get(node.node_id) || 0) <= 1);
}

function dmaForPipe(pipe) {
  const from = state.nodes.find((node) => node.node_id === pipe.from_node);
  const to = state.nodes.find((node) => node.node_id === pipe.to_node);
  return to?.dma_id || from?.dma_id || "";
}

function downloadProfessionalReport() {
  const snapshot = computeSnapshot();
  const report = {
    generated_at: new Date().toISOString(),
    node_count: snapshot.nodes.length,
    pipe_count: snapshot.pipes.length,
    diagnostics: buildProfessionalDiagnostics(snapshot),
    source_pump_prediction: snapshot.backendSimulation?.source_pump_prediction || null,
  };
  downloadBlob("water_network_professional_diagnostics.json", JSON.stringify(report, null, 2), "application/json");
}

function isNightMinute(minute) {
  const hour = Math.floor(((minute % 1440) + 1440) % 1440 / 60);
  return hour < 5 || hour >= 23;
}

function mapLayerLabel(layer) {
  return {
    pressure: "압력",
    leak: "누수 확률",
    dma: "DMA",
    risk: "자산 위험도",
  }[layer] || "압력";
}

function renderMap(snapshot) {
  const svg = $("network-map");
  const width = 1120;
  const height = 650;
  state.mapFrame = getMapFrame(snapshot.nodes, width, height);
  applyMapViewBox(svg, width, height);
  svg.style.setProperty("--map-zoom", String(Math.max(state.mapZoom || 1, 1)));
  syncMapInteractionControls();
  svg.classList.toggle("map-pan-enabled", isMapPanAvailable());
  svg.classList.toggle("map-pannable", isMapPanAvailable());
  svg.classList.toggle("map-panning", Boolean(state.mapPan?.active));
  svg.classList.toggle("node-dragging", Boolean(state.draggingNodeId || state.bulkMove));
  const project = (node) => projectNode(node, state.mapFrame);
  const markerScale = mapScreenScale();
  const labelOffsetX = 16 * markerScale;
  const nodeLabelY = -9 * markerScale;
  const pressureLabelY = 6 * markerScale;
  const pipeLabelOffsetY = 18 * markerScale;

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
      const strokeColor = pipeLayerColor(pipe, snapshot, isLeak);
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
        ${pipe.flow_lps > 0.02 ? `<g class="flow-arrow" transform="translate(${flowPoint.x} ${flowPoint.y}) rotate(${flowAngle}) scale(${markerScale})">
          <path d="M-9 -5 L4 0 L-9 5 Z" />
        </g>` : ""}
        ${selected ? `<circle class="selected-ring" cx="${mid.x}" cy="${mid.y}" r="${24 * markerScale}" />` : ""}
        <text class="pipe-label ${isLeak ? "leak-pipe-label" : ""} ${overpressure ? "overpressure-pipe-label" : ""}" x="${mid.x}" y="${mid.y - pipeLabelOffsetY}">${pipe.pipe_id} · ${pipe.flow_lps.toFixed(1)} L/s · D${Math.round(pipe.diameter_mm)}${leakLabel}${pressureLabel}</text>
      </g>`;
    })
    .join("");

  const previewMarkup = drawPreviewMarkup(project) + pipePreviewMarkup(project, snapshot) + sourcePreviewMarkup(project, snapshot);

  const nodeMarkup = snapshot.nodes
    .map((node) => {
      const point = project(node);
      const selected = selectedKind === "node" && selectedId === node.node_id;
      const multiSelected = multiNodes.has(node.node_id);
      const isSource = node.node_type === "reservoir";
      const color = nodeLayerColor(node);
      const demandRadiusBoost = Math.min(7, Math.sqrt(Math.max(Number(node.localDemand || 0), 0)) * 1.1);
      const radius = node.node_type === "reservoir" ? 13 : 9 + demandRadiusBoost;
      const pressure = node.node_type === "reservoir" ? "SRC" : `${node.pressure.toFixed(1)}m · ${Number(node.localDemand || 0).toFixed(1)}L/s`;
      return `<g class="junction-icon ${isSource ? "source-icon" : ""}" data-node="${node.node_id}" ${isSource ? `data-source="${node.node_id}"` : ""} transform="translate(${point.x} ${point.y})">
        <g class="junction-marker" transform="scale(${markerScale})">
          ${selected ? `<circle class="selected-ring" r="18" />` : ""}
          ${multiSelected ? `<circle class="multi-selected-ring" r="${radius + 9}" />` : ""}
          ${
            isSource
              ? `<path class="source-body" d="M0 -14 L14 0 L0 14 L-14 0 Z" fill="${color}" />`
              : `<circle class="junction-body" r="${radius}" fill="${color}" />`
          }
          <path class="junction-cross" d="M0 -6v12M-6 0h12" />
        </g>
        <text class="node-label" x="${labelOffsetX}" y="${nodeLabelY}">${node.node_id}</text>
        <text class="pressure-label" x="${labelOffsetX}" y="${pressureLabelY}">${pressure}</text>
      </g>`;
    })
    .join("");

  const selectionBoxMarkup = selectionBoxOverlayMarkup();
  const emptyMarkup = !snapshot.nodes.length && !snapshot.pipes.length ? mapEmptyStateMarkup(width, height) : "";
  svg.innerHTML = `${emptyMarkup}${pipeMarkup}${previewMarkup}${selectionBoxMarkup}${nodeMarkup}`;
  svg.onmousemove = (event) => {
    if (state.mapPan?.active) {
      dragMapPan(event);
      return;
    }
    if (state.selectionBox?.active) {
      updateMapSelectionBox(event);
      return;
    }
    trackDrawingPreview(event);
  };
  svg.onmousedown = (event) => {
    if (shouldStartMapPan(event)) {
      startMapPan(event);
      return;
    }
    if (event.target.closest("[data-node]")) return;
    if (event.button !== 0) return;
    startMapSelectionBox(event);
  };
  svg.onclick = (event) => {
    if (state.selectionMoved) {
      state.selectionMoved = false;
      return;
    }
    if (isMapPanMode()) return;
    if (!state.addMode && !state.pipeDrawMode && !state.sourceDrawMode && (bulkSelectionCount() > 0 || state.selected)) {
      clearMapObjectSelection();
      render();
      return;
    }
    handleMapClick(event);
  };
  svg.onwheel = (event) => {
    event.preventDefault();
    zoomMapFromWheel(event);
  };
  svg.onmouseup = (event) => {
    if (state.mapPan?.active) {
      stopMapPan();
      return;
    }
    if (state.selectionBox?.active) {
      finishMapSelectionBox(event, snapshot, project);
      return;
    }
    stopNodeDrag();
    stopBulkMove();
  };
  svg.onmouseleave = () => {
    stopMapPan();
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
      if (isMapPanMode()) return;
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
  svg.querySelectorAll("[data-source]").forEach((el) =>
    el.addEventListener("click", (event) => {
      if (state.addMode || state.pipeDrawMode || state.sourceDrawMode) return;
      event.stopPropagation();
      if (isMapPanMode()) return;
      if (event.shiftKey) {
        toggleMultiNode(el.dataset.source);
        return;
      }
      if (bulkSelectionCount() > 0) {
        addMultiNode(el.dataset.source);
        return;
      }
      selectSourcePump(el.dataset.source);
    }),
  );
  svg.querySelectorAll("[data-node]:not([data-source])").forEach((el) =>
    el.addEventListener("click", (event) => {
      if (state.pipeDrawMode) {
        event.stopPropagation();
        lockPendingPipeToNode(el.dataset.node);
        return;
      }
      if (state.addMode || state.sourceDrawMode) return;
      event.stopPropagation();
      if (isMapPanMode()) return;
      if (event.shiftKey) {
        toggleMultiNode(el.dataset.node);
        return;
      }
      if (bulkSelectionCount() > 0) {
        addMultiNode(el.dataset.node);
        return;
      }
      selectNode(el.dataset.node);
    }),
  );
  svg.querySelectorAll("[data-node]").forEach((el) =>
    el.addEventListener("mousedown", (event) => {
      if (state.addMode || state.pipeDrawMode || state.sourceDrawMode) return;
      if (isMapPanMode()) return;
      event.stopPropagation();
      startNodeDrag(el.dataset.node, event);
    }),
  );
  refreshSelectedDetail(snapshot);
}

function getMapFrame(nodes, width, height) {
  const allNodes = nodes;
  if (!allNodes.length) return { width, height, minX: 0, maxX: width, minY: 0, maxY: height, pad: 64 };
  const xs = allNodes.map((node) => Number(node.x || 0));
  const ys = allNodes.map((node) => Number(node.y || 0));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return { width, height, minX, maxX, minY, maxY, pad: 64 };
}

function mapEmptyStateMarkup(width, height) {
  return `<g class="map-empty-state">
    <rect x="${width / 2 - 220}" y="${height / 2 - 62}" width="440" height="124" rx="8" />
    <text x="${width / 2}" y="${height / 2 - 12}">관망 데이터가 없습니다</text>
    <text class="map-empty-subtitle" x="${width / 2}" y="${height / 2 + 22}">EPANET .inp 파일을 업로드하고 관망 적용을 누르면 지도가 표시됩니다.</text>
  </g>`;
}

function pipeLayerColor(pipe, snapshot, isLeak = false) {
  if (state.mapLayer === "dma") {
    const nodeById = new Map(snapshot.nodes.map((node) => [node.node_id, node]));
    return dmaColor(nodeById.get(pipe.to_node)?.dma_id || nodeById.get(pipe.from_node)?.dma_id || "SOURCE");
  }
  if (state.mapLayer === "risk") {
    return gradientColor(state.aging.get(pipe.pipe_id) || 0, ["#247a5a", "#d97706", "#dc2626"]);
  }
  if (state.mapLayer === "leak") {
    const candidate = topLeakCandidate({ ...snapshot, pipes: [pipe] });
    return gradientColor(candidate?.leakProbability || 0, ["#2563eb", "#f59e0b", "#dc2626"]);
  }
  return isLeak ? PIPE_COLORS.leak : PIPE_COLORS[pipe.status];
}

function nodeLayerColor(node) {
  if (node.node_type === "reservoir") return "#0f766e";
  if (state.mapLayer === "dma") return dmaColor(node.dma_id);
  if (state.mapLayer === "leak") {
    const pressureComponent = clamp((MARGINAL_PRESSURE - Number(node.pressure || 0)) / MARGINAL_PRESSURE);
    return gradientColor(pressureComponent, ["#2563eb", "#f59e0b", "#dc2626"]);
  }
  if (state.mapLayer === "risk") {
    const localPipes = state.pipes.filter((pipe) => pipe.from_node === node.node_id || pipe.to_node === node.node_id);
    const risk = localPipes.length
      ? localPipes.reduce((sum, pipe) => sum + (state.aging.get(pipe.pipe_id) || 0), 0) / localPipes.length
      : 0;
    return gradientColor(risk, ["#247a5a", "#d97706", "#dc2626"]);
  }
  return node.status === "low" ? "#dc2626" : node.status === "marginal" ? "#d97706" : "#247a5a";
}

function dmaColor(dmaId) {
  const palette = ["#2563eb", "#0f766e", "#b45309", "#7c3aed", "#be123c", "#047857", "#4338ca"];
  const text = String(dmaId || "DMA");
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) hash = (hash * 31 + text.charCodeAt(index)) >>> 0;
  return palette[hash % palette.length];
}

function gradientColor(value, colors) {
  const score = clamp(value);
  if (score < 0.5) return mixHex(colors[0], colors[1], score / 0.5);
  return mixHex(colors[1], colors[2], (score - 0.5) / 0.5);
}

function mixHex(from, to, ratio) {
  const a = hexToRgb(from);
  const b = hexToRgb(to);
  const mix = (start, end) => Math.round(start + (end - start) * clamp(ratio));
  return `rgb(${mix(a.r, b.r)}, ${mix(a.g, b.g)}, ${mix(a.b, b.b)})`;
}

function hexToRgb(hex) {
  const value = String(hex).replace("#", "");
  return {
    r: parseInt(value.slice(0, 2), 16),
    g: parseInt(value.slice(2, 4), 16),
    b: parseInt(value.slice(4, 6), 16),
  };
}

function applyMapViewBox(svg, width = 1120, height = 650) {
  const zoom = clamp(state.mapZoom || 1, MAP_ZOOM_MIN, MAP_ZOOM_MAX);
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
  if (isMapPanMode() || state.addMode || state.pipeDrawMode || state.sourceDrawMode || state.bulkMove) return;
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
  if (firstNode) {
    const firstNodeRecord = nodeById.get(firstNode);
    if (firstNodeRecord?.node_type === "reservoir" && $("selected-source").querySelector(`option[value="${firstNode}"]`)) {
      $("selected-source").value = firstNode;
    } else if ($("selected-junction").querySelector(`option[value="${firstNode}"]`)) {
      $("selected-junction").value = firstNode;
    }
  }
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

function zoomMap(factor, anchorClientPoint = null) {
  const oldZoom = state.mapZoom || 1;
  const nextZoom = clamp(oldZoom * factor, MAP_ZOOM_MIN, MAP_ZOOM_MAX);
  if (anchorClientPoint && oldZoom !== nextZoom) {
    state.mapCenter = mapCenterForCursorZoom(nextZoom, anchorClientPoint);
  }
  state.mapZoom = nextZoom;
  render();
}

function zoomMapFromWheel(event) {
  if (!state.mapFrame || !state.mapViewBox) return;
  const deltaModeMultiplier = event.deltaMode === 1 ? 18 : event.deltaMode === 2 ? 240 : 1;
  const normalizedDelta = event.deltaY * deltaModeMultiplier;
  const factor = Math.exp(-normalizedDelta * MAP_WHEEL_ZOOM_SENSITIVITY);
  zoomMap(factor, { x: event.clientX, y: event.clientY });
}

function mapScreenScale() {
  const zoom = Math.max(Number(state.mapZoom || 1), 1);
  return clamp(1 / zoom, 0.09, 1);
}

function isMapPanMode() {
  return Boolean(state.mapPanEnabled) && !state.addMode && !state.pipeDrawMode && !state.sourceDrawMode;
}

function isMapPanAvailable() {
  return isMapPanMode();
}

function shouldStartMapPan(event) {
  return isMapPanAvailable() && (event.button === 0 || event.button === 1);
}

function startMapPan(event) {
  if (!state.mapFrame || !state.mapViewBox || !shouldStartMapPan(event)) return;
  event.preventDefault();
  state.mapPan = {
    active: true,
    startClient: { x: event.clientX, y: event.clientY },
    startCenter: { ...(state.mapCenter || { x: state.mapFrame.width / 2, y: state.mapFrame.height / 2 }) },
    moved: false,
  };
  state.selectionMoved = false;
  render();
}

function toggleMapPanMode() {
  state.mapPanEnabled = !state.mapPanEnabled;
  state.mapPan = null;
  state.selectionBox = null;
  state.selectionMoved = false;
  stopNodeDrag();
  stopBulkMove();
  syncMapInteractionControls();
  render();
}

function syncMapInteractionControls() {
  const button = $("map-pan-toggle");
  const status = $("map-interaction-status");
  const panMode = isMapPanMode();
  if (button) {
    button.classList.toggle("active", Boolean(state.mapPanEnabled));
    button.setAttribute("aria-pressed", state.mapPanEnabled ? "true" : "false");
    button.textContent = state.mapPanEnabled ? "Pan ON" : "Pan OFF";
  }
  if (status) {
    status.textContent = panMode ? "Pan 모드 · 객체 선택 꺼짐" : state.mapPanEnabled ? "편집 중 · Pan 대기" : "객체 선택 모드";
  }
}

function dragMapPan(event) {
  if (!state.mapPan?.active || !state.mapFrame || !state.mapViewBox) return;
  const svg = $("network-map");
  const rect = svg.getBoundingClientRect();
  const dx = ((event.clientX - state.mapPan.startClient.x) / Math.max(rect.width, 1)) * state.mapViewBox.width;
  const dy = ((event.clientY - state.mapPan.startClient.y) / Math.max(rect.height, 1)) * state.mapViewBox.height;
  const nextWidth = state.mapFrame.width / Math.max(state.mapZoom || 1, 1);
  const nextHeight = state.mapFrame.height / Math.max(state.mapZoom || 1, 1);
  state.mapPan.moved = state.mapPan.moved || Math.hypot(dx, dy) > 3;
  state.selectionMoved = state.mapPan.moved;
  state.mapCenter = clampMapCenter(
    {
      x: state.mapPan.startCenter.x - dx,
      y: state.mapPan.startCenter.y - dy,
    },
    nextWidth,
    nextHeight,
    state.mapFrame.width,
    state.mapFrame.height,
  );
  render();
}

function stopMapPan() {
  if (!state.mapPan) return;
  state.selectionMoved = Boolean(state.mapPan.moved);
  state.mapPan = null;
  render();
}

function mapCenterForCursorZoom(nextZoom, clientPoint) {
  const svg = $("network-map");
  const rect = svg.getBoundingClientRect();
  const oldView = state.mapViewBox || { x: 0, y: 0, width: state.mapFrame.width, height: state.mapFrame.height };
  const cursorRatioX = clamp((clientPoint.x - rect.left) / Math.max(rect.width, 1), 0, 1);
  const cursorRatioY = clamp((clientPoint.y - rect.top) / Math.max(rect.height, 1), 0, 1);
  const anchorX = oldView.x + cursorRatioX * oldView.width;
  const anchorY = oldView.y + cursorRatioY * oldView.height;
  const nextWidth = state.mapFrame.width / nextZoom;
  const nextHeight = state.mapFrame.height / nextZoom;
  return clampMapCenter(
    {
      x: anchorX + (0.5 - cursorRatioX) * nextWidth,
      y: anchorY + (0.5 - cursorRatioY) * nextHeight,
    },
    nextWidth,
    nextHeight,
    state.mapFrame.width,
    state.mapFrame.height,
  );
}

function resetMapZoom() {
  state.mapPan = null;
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
  if (!node) return;
  state.multiSelectedNodes = state.multiSelectedNodes || new Set();
  if (state.multiSelectedNodes.has(nodeId)) state.multiSelectedNodes.delete(nodeId);
  else state.multiSelectedNodes.add(nodeId);
  state.selected = `node:${nodeId}`;
  if (node.node_type === "reservoir" && $("selected-source").querySelector(`option[value="${nodeId}"]`)) {
    $("selected-source").value = nodeId;
  } else if ($("selected-junction").querySelector(`option[value="${nodeId}"]`)) {
    $("selected-junction").value = nodeId;
  }
  updateBulkSelectionControls();
  render();
}

function addMultiNode(nodeId) {
  const node = state.nodes.find((item) => item.node_id === nodeId);
  if (!node) return;
  state.multiSelectedNodes = state.multiSelectedNodes || new Set();
  state.multiSelectedNodes.add(nodeId);
  state.selected = `node:${nodeId}`;
  if (node.node_type === "reservoir" && $("selected-source").querySelector(`option[value="${nodeId}"]`)) {
    $("selected-source").value = nodeId;
  } else if ($("selected-junction").querySelector(`option[value="${nodeId}"]`)) {
    $("selected-junction").value = nodeId;
  }
  updateBulkSelectionControls();
  render();
}

function clearBulkSelection() {
  state.multiSelectedNodes = new Set();
  state.multiSelectedPipes = new Set();
  state.selectionBox = null;
  state.bulkMove = null;
  state.mapPan = null;
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
  const sourceCount = [...(state.multiSelectedNodes || [])].filter((nodeId) =>
    state.nodes.some((node) => node.node_id === nodeId && node.node_type === "reservoir"),
  ).length;
  const junctionCount = Math.max(nodeCount - sourceCount, 0);
  if ($("bulk-selection-count")) $("bulk-selection-count").textContent = `선택 ${nodeCount + pipeCount}개`;
  if ($("bulk-selection-mode")) $("bulk-selection-mode").textContent = `Junction ${junctionCount}개 · Source ${sourceCount}개 · Pipe ${pipeCount}개`;
}

function average(values) {
  const safeValues = values.filter((value) => Number.isFinite(value));
  if (!safeValues.length) return 0;
  return safeValues.reduce((sum, value) => sum + value, 0) / safeValues.length;
}

function topCategory(values) {
  const counts = new Map();
  for (const value of values) {
    const label = String(value || "unknown");
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  const [label, count] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0] || ["없음", 0];
  return count > 1 ? `${label} (${count})` : label;
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

function updateConnectedPipeGeometry(nodeId) {
  for (const pipe of state.pipes) {
    if (pipe.from_node !== nodeId && pipe.to_node !== nodeId) continue;
    const from = state.nodes.find((node) => node.node_id === pipe.from_node);
    const to = state.nodes.find((node) => node.node_id === pipe.to_node);
    if (!from || !to) continue;
    const length = distanceBetween(from, to);
    pipe.length_m = length;
    if (Array.isArray(pipe.geometry_m) && pipe.geometry_m.length >= 2) {
      pipe.geometry_m[0] = { x: Number(from.x || 0), y: Number(from.y || 0) };
      pipe.geometry_m[pipe.geometry_m.length - 1] = { x: Number(to.x || 0), y: Number(to.y || 0) };
    }
    if (state.pipeEdits.has(pipe.pipe_id)) {
      state.pipeEdits.set(pipe.pipe_id, {
        ...state.pipeEdits.get(pipe.pipe_id),
        angle_deg: angleBetween(from, to),
        length_m: length,
      });
    }
  }
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
  if (node.node_type === "reservoir") {
    state.editorTab = "source";
    if ($("selected-source").querySelector(`option[value="${nodeId}"]`)) $("selected-source").value = nodeId;
  } else if ($("selected-junction").querySelector(`option[value="${nodeId}"]`)) {
    state.editorTab = "junction";
    $("selected-junction").value = nodeId;
  }
}

function dragSelectedNode(event) {
  const node = state.nodes.find((item) => item.node_id === state.draggingNodeId);
  if (!node || !state.mapFrame) return;
  const point = unprojectPoint(eventToSvgPoint(event));
  state.selectionMoved = true;
  node.x = point.x;
  node.y = point.y;
  state.baseNodeGeometry.set(node.node_id, baseNodeState(node));
  updateConnectedPipeGeometry(node.node_id);
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
  for (const nodeId of state.bulkMove.originals.keys()) updateConnectedPipeGeometry(nodeId);
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
  if (!nodeIds.size && !pipeIds.size && state.selected) {
    const [kind, id] = state.selected.split(":");
    if (kind === "node") nodeIds.add(id);
    if (kind === "pipe") pipeIds.add(id);
  }
  const nodes = snapshot.nodes.filter((node) => nodeIds.has(node.node_id));
  const pipes = snapshot.pipes.filter((pipe) => pipeIds.has(pipe.pipe_id));
  if (!nodes.length && !pipes.length) {
    $("selection-detail").innerHTML = `<strong>선택 구역 없음</strong><span>분석할 Junction 또는 Pipe를 먼저 선택하세요.</span>`;
    return;
  }
  const lowNodes = nodes.filter((node) => node.node_type !== "reservoir" && node.pressure < MIN_PRESSURE);
  const nodePressures = nodes.map((node) => Number(node.pressure || 0));
  const avgPressure = nodePressures.length ? average(nodePressures) : 0;
  const minPressure = nodePressures.length ? Math.min(...nodePressures) : 0;
  const maxPressure = nodePressures.length ? Math.max(...nodePressures) : 0;
  const totalLength = pipes.reduce((sum, pipe) => sum + Number(pipe.length_m || 0), 0);
  const avgFlow = pipes.length ? average(pipes.map((pipe) => Number(pipe.flow_lps || 0))) : 0;
  const leakPipes = pipes.filter((pipe) => Number(pipe.leakDemand || 0) > 0 || pipe.status === "leak");
  const overpressurePipes = pipes.filter((pipe) => pipe.status === "overpressure" || pipe.pressureSafety?.overpressure);
  const warningPipes = pipes.filter((pipe) => pipe.status === "low" || pipe.status === "overpressure" || pipe.pressureSafety?.warning);
  const highRiskPipe = pipes
    .map((pipe) => ({ pipe, score: state.aging.get(pipe.pipe_id) ?? agingScore(pipe) }))
    .sort((a, b) => b.score - a.score)[0];
  const materialSummary = topCategory(pipes.map((pipe) => pipe.material || "unknown"));
  const diameterSummary = topCategory(pipes.map((pipe) => `${Number(pipe.diameter_mm || 0).toFixed(0)} mm`));
  const riskLevel = lowNodes.length || leakPipes.length || overpressurePipes.length ? "주의" : warningPipes.length ? "관찰" : "양호";
  const riskClass = riskLevel === "양호" ? "ok" : riskLevel === "관찰" ? "watch" : "risk";
  $("selection-detail").innerHTML = `<div class="selection-analysis-card">
    <div class="analysis-title-row">
      <div>
        <strong>선택 구역 분석</strong>
        <span>Junction ${nodes.length}개 · Pipe ${pipes.length}개 · 총 연장 ${totalLength.toFixed(0)} m</span>
      </div>
      <b class="risk-badge ${riskClass}">${riskLevel}</b>
    </div>
    <div class="analysis-metric-grid">
      <span><small>평균 압력</small><b>${avgPressure.toFixed(1)} m</b></span>
      <span><small>최소 / 최대</small><b>${minPressure.toFixed(1)} / ${maxPressure.toFixed(1)} m</b></span>
      <span><small>저압 Junction</small><b>${lowNodes.length}개</b></span>
      <span><small>평균 유량</small><b>${avgFlow.toFixed(1)} L/s</b></span>
      <span><small>누수 Pipe</small><b>${leakPipes.length}개</b></span>
      <span><small>과압 Pipe</small><b>${overpressurePipes.length}개</b></span>
    </div>
    <div class="analysis-insight-grid">
      <span><small>대표 관경</small><b>${diameterSummary}</b></span>
      <span><small>대표 재질</small><b>${materialSummary}</b></span>
      <span><small>최고 위험 Pipe</small><b>${highRiskPipe ? `${highRiskPipe.pipe.pipe_id} · ${highRiskPipe.score.toFixed(2)}` : "없음"}</b></span>
    </div>
  </div>`;
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
    reservoir_id: sourceId,
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
    reservoir_id: sourceId,
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
  if (!snapshot.nodes.length && !snapshot.pipes.length) {
    $("selection-detail").innerHTML = `<strong>데이터 없음</strong><span>EPANET .inp 파일을 업로드하면 Pipe/Junction 상세 정보가 표시됩니다.</span>`;
    return;
  }
  if (bulkSelectionCount() > 1) {
    const sourceCount = [...(state.multiSelectedNodes || [])].filter((nodeId) =>
      state.nodes.some((node) => node.node_id === nodeId && node.node_type === "reservoir"),
    ).length;
    const nodeCount = Math.max((state.multiSelectedNodes?.size || 0) - sourceCount, 0);
    const pipeCount = state.multiSelectedPipes?.size || 0;
    $("selection-detail").innerHTML = `<strong>다중 선택</strong>
      <span>Junction ${nodeCount}개 · Source ${sourceCount}개 · Pipe ${pipeCount}개</span>
      <span>선택된 Junction/Source를 드래그하면 연결된 선택 객체를 함께 이동합니다.</span>`;
    return;
  }
  if (!state.selected) return;
  const [kind, id] = state.selected.split(":");
  if (kind === "pipe") showPipeDetail(id, snapshot);
  if (kind === "node") {
    const node = snapshot.nodes.find((item) => item.node_id === id);
    if (node?.node_type === "reservoir") showSourceDetail(id, snapshot);
    else showNodeDetail(id, snapshot);
  }
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

function showSourceDetail(sourceId, snapshot) {
  const source = snapshot.nodes.find((item) => item.node_id === sourceId && item.node_type === "reservoir");
  if (!source) return;
  const reservoir = state.reservoirs.find((item) => item.node_id === sourceId);
  const pump = sourcePumpFor(sourceId);
  const pipe = sourcePipeFor(sourceId);
  const target = sourceTargetFor(sourceId);
  $("selection-detail").innerHTML = `<strong>Source/Pump ${sourceId}</strong>
    <span>공급수두 ${Number(reservoir?.head_m || 0).toFixed(1)} m · Pump 가압 ${Number((pump?.base_head_gain_m || 0) * (pump?.speed_multiplier || 1)).toFixed(1)} m</span>
    <span>연결 Junction ${target?.node_id || "없음"} · 연결 Pipe ${pipe?.pipe_id || "없음"}</span>
    <span>좌표 X ${Number(source.x || 0).toFixed(1)} · Y ${Number(source.y || 0).toFixed(1)} · DMA ${source.dma_id}</span>`;
}

function renderPressureBars(snapshot) {
  const lowFirst = [...snapshot.nodes]
    .filter((node) => node.node_type !== "reservoir")
    .sort((a, b) => a.pressure - b.pressure)
    .slice(0, 9);
  if (!lowFirst.length) {
    $("pressure-bars").innerHTML = `<div class="empty-row">INP 관망을 적용하면 저압 Junction 순위가 표시됩니다.</div>`;
    return;
  }
  $("pressure-bars").innerHTML = lowFirst
    .map((node) => barRow(node.node_id, clamp(node.pressure / 35), `${node.pressure.toFixed(1)} m`, statusColor(node.status)))
    .join("");
}

function renderReplacementRanking(snapshot) {
  const ranking = computeReplacementRanking(snapshot).slice(0, 8);
  const header = `<div class="ranking-row header"><span>#</span><span>Pipe</span><span>판단 근거</span><span>점수</span><span>상태</span></div>`;
  if (!ranking.length) {
    $("replacement-ranking").innerHTML = `${header}<div class="empty-row">INP 관망을 적용하면 Pipe 교체 우선순위가 표시됩니다.</div>`;
    return;
  }
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
  if (!snapshot.nodes.length && !snapshot.pipes.length) {
    $("recommendations").innerHTML = `<li>INP 관망을 적용하면 압력, 누수, 자산 위험도 기반 추천이 표시됩니다.</li>`;
    return;
  }
  if (snapshot.backendSimulation?.recommendations?.length) {
    const prediction = snapshot.backendSimulation.source_pump_prediction;
    const predictionItem = prediction
      ? `<li><strong>source_pump_auto_prediction</strong>: 저압 해소 권장 추가 가압 ${Number(prediction.recommended_boost_m || 0).toFixed(2)} m<br><span>총 Source 공급 ${Number(prediction.total_source_outflow_lps || 0).toFixed(2)} L/s · 예측 최저압 ${Number(prediction.predicted_min_pressure_m || 0).toFixed(2)} m</span></li>`
      : "";
    $("recommendations").innerHTML = predictionItem + snapshot.backendSimulation.recommendations
      .map((item) => `<li><strong>${escapeHtml(item.action_type || item.action_id || "backend")}</strong>: ${escapeHtml(item.description || "")}<br><span>${escapeHtml(item.expected_effect || "")} · score ${Number(item.score || 0).toFixed(2)}</span></li>`)
      .join("");
    return;
  }
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
        <input data-leak-pipe="${pipeId}" type="range" min="0" max="100" step="0.5" value="${Number(demand).toFixed(2)}" />
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
  clearOptimizedControlBoost();
  state.leakDemands.set(pipeId, Math.max(Number(demand || 0), 0.25));
  state.editorTab = "leak";
  state.selected = `pipe:${pipeId}`;
  if ($("selected-pipe").querySelector(`option[value="${pipeId}"]`)) $("selected-pipe").value = pipeId;
  render();
}

function updateLeakDemand(pipeId, demand) {
  if (!pipeId) return;
  clearOptimizedControlBoost();
  if (demand <= 0) {
    state.leakDemands.delete(pipeId);
  } else {
    state.leakDemands.set(pipeId, demand);
  }
  render();
}

function removeLeakPipe(pipeId) {
  clearOptimizedControlBoost();
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
  clearOptimizedControlBoost();
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
  updateSourceLinkSummary(source.node_id);
  syncSourceControlLabels();
}

function updateSourceLinkSummary(sourceId) {
  const pipe = sourcePipeFor(sourceId);
  const pump = sourcePumpFor(sourceId);
  const target = sourceTargetFor(sourceId);
  const summary = $("source-link-summary");
  if (!summary) return;
  summary.textContent = pipe
    ? `연결 묶음: Source ${sourceId} · Pipe ${pipe.pipe_id} → ${target?.node_id || "미연결"} · Pump ${pump?.pump_id || "없음"} · 관경 ${Number(pipe.diameter_mm || 0).toFixed(0)} mm`
    : `연결 묶음: Source ${sourceId}에 연결된 Pipe/Pump가 없습니다.`;
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
  clearOptimizedControlBoost();
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
  clearOptimizedControlBoost();
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
  const input = $(id);
  if (!input) return;
  const number = Number(value);
  const validMax = CONTROL_VALID_MAX[id];
  if (Number.isFinite(number) && Number.isFinite(validMax)) {
    const nextMax = Math.min(validMax, Math.max(Number(input.max || validMax), number));
    input.max = String(nextMax);
    value = Math.min(number, validMax);
  }
  if (Number(input.value) !== Number(value)) input.value = value;
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
  clearBulkSelection();
  state.selected = `node:${sourceId}`;
  state.editorTab = "source";
  $("selected-source").value = sourceId;
  const reservoir = state.reservoirs.find((item) => item.node_id === sourceId);
  const pump = state.pumps.find((item) => item.from_node === sourceId || item.to_node === sourceId);
  if (reservoir) $("source-design-head").value = Number(reservoir.head_m || 58);
  if (pump) $("source-pump-gain").value = Number(pump.base_head_gain_m || 0) * Number(pump.speed_multiplier || 1);
  syncSourceEditor();
  focusMapOnNode(sourceId);
  $("source-readout").textContent = `${sourceId} Source/Pump가 선택되었습니다. 삭제하거나 새 Source/Pump를 추가할 수 있습니다.`;
  render();
}

function focusMapOnNode(nodeId) {
  const node = state.nodes.find((item) => item.node_id === nodeId);
  if (!node || !state.mapFrame) return;
  const point = projectNode(node, state.mapFrame);
  state.mapCenter = clampMapCenter(point, state.mapFrame.width / Math.max(state.mapZoom || 1, 1), state.mapFrame.height / Math.max(state.mapZoom || 1, 1), state.mapFrame.width, state.mapFrame.height);
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
  clearOptimizedControlBoost();
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

function currentTimeIndex() {
  return Number($("time-slider").value || 0);
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
