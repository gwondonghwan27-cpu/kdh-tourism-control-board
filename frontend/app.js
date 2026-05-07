const DATA_DIR = "../data/mock";
const MIN_PRESSURE = 15;
const MARGINAL_PRESSURE = 20;
const CURRENT_YEAR = 2026;

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
  pendingJunction: null,
  pendingPipe: null,
  mapFrame: null,
  mapZoom: 1,
  mapCenter: { x: 560, y: 325 },
  mapViewBox: { x: 0, y: 0, width: 1120, height: 650 },
  draggingNodeId: "",
  playbackTimer: null,
  playbackSpeed: 1,
  drawingFile: null,
  drawingImage: null,
  drawingAssets: null,
  drawingRecognition: null,
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
  ["source-design-head", "source-pump-gain", "source-pipe-diameter"].forEach((id) => {
    $(id).addEventListener("input", syncSourceControlLabels);
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
      if (state.drawingRecognition) renderDrawingRecognition();
    });
  });
  $("analyze-drawing").addEventListener("click", analyzeDrawingImage);
  $("reset-drawing").addEventListener("click", resetDrawingRecognition);
  $("download-assets-json").addEventListener("click", () => downloadRecognitionAsset("json"));
  $("download-nodes-csv").addEventListener("click", () => downloadRecognitionAsset("nodes"));
  $("download-pipes-csv").addEventListener("click", () => downloadRecognitionAsset("pipes"));
  $("download-reservoirs-csv").addEventListener("click", () => downloadRecognitionAsset("reservoirs"));
}

function handleDrawingFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const image = new Image();
  image.onload = () => {
    state.drawingFile = file;
    state.drawingImage = image;
    state.drawingRecognition = null;
    state.drawingAssets = null;
    drawRecognitionCanvas();
    updateRecognitionStatus("image loaded", "0 pipes / 0 nodes");
    $("recognized-image-size").textContent = `${image.naturalWidth} x ${image.naturalHeight}`;
    $("recognized-export-state").textContent = "대기";
    toggleRecognitionDownloads(false);
  };
  image.src = URL.createObjectURL(file);
}

function resetDrawingRecognition() {
  state.drawingFile = null;
  state.drawingImage = null;
  state.drawingRecognition = null;
  state.drawingAssets = null;
  restoreInitialDashboardNetwork();
  $("drawing-file").value = "";
  $("recognized-pipe-count").textContent = 0;
  $("recognized-node-count").textContent = 0;
  $("recognized-image-size").textContent = "--";
  $("recognized-export-state").textContent = "reset";
  renderRecognitionTable("recognized-nodes-table", [], ["node_id", "x", "y", "node_type", "dma_id"]);
  renderRecognitionTable("recognized-pipes-table", [], ["pipe_id", "from_node", "to_node", "length_m", "diameter_mm", "material"]);
  toggleRecognitionDownloads(false);
  updateRecognitionStatus("image waiting", "0 pipes / 0 nodes");
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
  state.baseNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.originalNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.aging = new Map(state.pipes.map((pipe) => [pipe.pipe_id, agingScore(pipe)]));
  state.addMode = false;
  state.pipeDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
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
  if (!image) {
    $("drawing-empty-state").style.display = "grid";
    return;
  }
  $("drawing-empty-state").style.display = "none";
  const scale = Math.min(canvas.width / image.naturalWidth, canvas.height / image.naturalHeight);
  const width = image.naturalWidth * scale;
  const height = image.naturalHeight * scale;
  const offsetX = (canvas.width - width) / 2;
  const offsetY = (canvas.height - height) / 2;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, offsetX, offsetY, width, height);
  ctx.lineCap = "round";
  ctx.lineWidth = 3;
  ctx.strokeStyle = "#2563eb";
  for (const segment of segments) {
    ctx.beginPath();
    ctx.moveTo(offsetX + segment.x1 * scale, offsetY + segment.y1 * scale);
    ctx.lineTo(offsetX + segment.x2 * scale, offsetY + segment.y2 * scale);
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
}

async function analyzeDrawingImage() {
  if (!state.drawingImage || !state.drawingFile) {
    updateRecognitionStatus("image required", "0 pipes / 0 nodes");
    return;
  }
  updateRecognitionStatus("analyzing", "OpenCV + Gemini");
  $("analyze-drawing").disabled = true;
  try {
    const serverResult = await recognizeDrawingGeometryWithApi(state.drawingFile);
    state.drawingRecognition = serverResult.recognition;
    renderDrawingRecognition(serverResult.assets);
  } catch (error) {
    console.warn("Server recognition failed, using browser fallback.", error);
    state.drawingRecognition = recognizeDrawingGeometry(state.drawingImage);
    renderDrawingRecognition();
    updateRecognitionStatus("browser fallback", `${state.drawingAssets.pipes.length} pipes / ${state.drawingAssets.nodes.length} nodes`);
  } finally {
    $("analyze-drawing").disabled = false;
  }
}

function renderDrawingRecognition(prebuiltAssets = null) {
  if (!state.drawingRecognition) return;
  const assets = prebuiltAssets || dashboardAssetsFromRecognition(state.drawingRecognition);
  state.drawingAssets = assets;
  drawRecognitionCanvas(state.drawingRecognition.segments, state.drawingRecognition.nodes);
  $("recognized-pipe-count").textContent = assets.pipes.length;
  $("recognized-node-count").textContent = Math.max(assets.nodes.length - assets.reservoirs.length, 0);
  $("recognized-image-size").textContent = `${state.drawingRecognition.width} x ${state.drawingRecognition.height}`;
  $("recognized-export-state").textContent = assets.pipes.length ? "준비" : "확인";
  updateRecognitionStatus("analysis ready", `${assets.pipes.length} pipes / ${assets.nodes.length} nodes`);
  renderRecognitionTable("recognized-nodes-table", assets.nodes, ["node_id", "x", "y", "node_type", "dma_id"]);
  renderRecognitionTable("recognized-pipes-table", assets.pipes, ["pipe_id", "from_node", "to_node", "length_m", "diameter_mm", "material"]);
  toggleRecognitionDownloads(Boolean(assets.nodes.length && assets.pipes.length));
  applyRecognitionAssetsToDashboard(assets);
}

async function recognizeDrawingGeometryWithApi(file) {
  const imageBase64 = await fileToBase64(file);
  const response = await fetch("/api/recognize-drawing", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      image_base64: imageBase64,
      mime_type: file.type || "image/png",
      min_line_length: Number($("drawing-min-line").value || 45),
      merge_tolerance_px: Number($("drawing-merge-tolerance").value || 18),
      scale_m_per_px: Number($("drawing-scale").value || 1),
      default_diameter_mm: Number($("drawing-diameter").value || 150),
      default_material: $("drawing-material").value || "PVC",
      use_gemini: true,
    }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "recognition API failed");
  if (!payload.recognition || !payload.assets) throw new Error("recognition API returned an incomplete payload");
  return payload;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",")[1] || "");
    reader.onerror = () => reject(reader.error || new Error("file read failed"));
    reader.readAsDataURL(file);
  });
}

function recognizeDrawingGeometry(image) {
  const maxWidth = 900;
  const scale = Math.min(1, maxWidth / image.naturalWidth);
  const width = Math.max(1, Math.round(image.naturalWidth * scale));
  const height = Math.max(1, Math.round(image.naturalHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(image, 0, 0, width, height);
  const { data } = ctx.getImageData(0, 0, width, height);
  const dark = (x, y) => {
    const index = (y * width + x) * 4;
    const avg = (data[index] + data[index + 1] + data[index + 2]) / 3;
    return data[index + 3] > 0 && avg < 165;
  };
  const minLine = Number($("drawing-min-line").value || 45);
  const tolerance = Number($("drawing-merge-tolerance").value || 18);
  const segments = [
    ...scanDarkRuns(width, height, dark, "h", minLine),
    ...scanDarkRuns(width, height, dark, "v", minLine),
  ];
  const mergedSegments = mergeSimilarSegments(segments, tolerance);
  const nodes = mergeSegmentEndpoints(mergedSegments, tolerance);
  return { width, height, segments: mergedSegments, nodes };
}

function scanDarkRuns(width, height, dark, axis, minLength) {
  const segments = [];
  const step = 4;
  if (axis === "h") {
    for (let y = 0; y < height; y += step) {
      let start = -1;
      for (let x = 0; x < width; x += 1) {
        if (dark(x, y)) {
          if (start < 0) start = x;
        } else if (start >= 0) {
          if (x - start >= minLength) segments.push({ x1: start, y1: y, x2: x - 1, y2: y, axis });
          start = -1;
        }
      }
      if (start >= 0 && width - start >= minLength) segments.push({ x1: start, y1: y, x2: width - 1, y2: y, axis });
    }
  } else {
    for (let x = 0; x < width; x += step) {
      let start = -1;
      for (let y = 0; y < height; y += 1) {
        if (dark(x, y)) {
          if (start < 0) start = y;
        } else if (start >= 0) {
          if (y - start >= minLength) segments.push({ x1: x, y1: start, x2: x, y2: y - 1, axis });
          start = -1;
        }
      }
      if (start >= 0 && height - start >= minLength) segments.push({ x1: x, y1: start, x2: x, y2: height - 1, axis });
    }
  }
  return segments;
}

function mergeSimilarSegments(segments, tolerance) {
  const merged = [];
  const sorted = [...segments].sort((a, b) => segmentLength(b) - segmentLength(a));
  for (const segment of sorted) {
    if (merged.some((item) => similarSegment(item, segment, tolerance))) continue;
    merged.push({ ...segment, id: `L_IMG_${merged.length + 1}`, length_px: segmentLength(segment), angle_deg: segment.axis === "h" ? 0 : 90 });
    if (merged.length >= 240) break;
  }
  return merged;
}

function similarSegment(a, b, tolerance) {
  if (a.axis !== b.axis) return false;
  if (a.axis === "h") return Math.abs(a.y1 - b.y1) <= tolerance && rangesOverlap(a.x1, a.x2, b.x1, b.x2, tolerance);
  return Math.abs(a.x1 - b.x1) <= tolerance && rangesOverlap(a.y1, a.y2, b.y1, b.y2, tolerance);
}

function rangesOverlap(a1, a2, b1, b2, tolerance) {
  return Math.max(Math.min(a1, a2), Math.min(b1, b2)) <= Math.min(Math.max(a1, a2), Math.max(b1, b2)) + tolerance;
}

function segmentLength(segment) {
  return Math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1);
}

function mergeSegmentEndpoints(segments, tolerance) {
  const nodes = [];
  for (const segment of segments) {
    for (const point of [
      { x: segment.x1, y: segment.y1 },
      { x: segment.x2, y: segment.y2 },
    ]) {
      const match = nodes.find((node) => Math.hypot(node.x - point.x, node.y - point.y) <= tolerance);
      if (match) {
        match.x = (match.x * match.hits + point.x) / (match.hits + 1);
        match.y = (match.y * match.hits + point.y) / (match.hits + 1);
        match.hits += 1;
      } else {
        nodes.push({ id: `N_IMG_${nodes.length + 1}`, x: point.x, y: point.y, hits: 1 });
      }
    }
  }
  return nodes.map((node) => ({ ...node, x: Number(node.x.toFixed(1)), y: Number(node.y.toFixed(1)) }));
}

function dashboardAssetsFromRecognition(recognition) {
  const scale = Math.max(Number($("drawing-scale").value || 1), 0.01);
  const diameter = Number($("drawing-diameter").value || 150);
  const material = $("drawing-material").value || "PVC";
  const nodeIdById = new Map(recognition.nodes.map((node, index) => [node.id, `J_IMG_${index + 1}`]));
  const nodes = recognition.nodes.map((node, index) => ({
    node_id: `J_IMG_${index + 1}`,
    x: Number((node.x * scale).toFixed(2)),
    y: Number((node.y * scale).toFixed(2)),
    elevation_m: 30,
    base_demand_lps: 0.8,
    node_type: "junction",
    dma_id: "IMG_IMPORT",
  }));
  const pipes = [];
  for (const segment of recognition.segments) {
    const start = nearestRecognitionNode(recognition.nodes, segment.x1, segment.y1);
    const end = nearestRecognitionNode(recognition.nodes, segment.x2, segment.y2);
    if (!start || !end || start.id === end.id) continue;
    pipes.push({
      pipe_id: `P_IMG_${pipes.length + 1}`,
      from_node: nodeIdById.get(start.id),
      to_node: nodeIdById.get(end.id),
      length_m: Number((segment.length_px * scale).toFixed(2)),
      diameter_mm: diameter,
      material,
      install_year: CURRENT_YEAR,
      bend_count: 0,
      valve_count: 0,
      repair_count: 0,
      leak_history_count: 0,
      soil_ph: 7,
      soil_resistivity_ohm_cm: 3000,
      traffic_load_index: 0.3,
      burst_history_count: 0,
    });
  }
  const reservoirs = [];
  if (nodes.length) {
    const source = [...nodes].sort((a, b) => a.x - b.x)[0];
    nodes.unshift({ node_id: "R_IMG_1", x: Number((source.x - 80 * scale).toFixed(2)), y: source.y, elevation_m: 35, base_demand_lps: 0, node_type: "reservoir", dma_id: "SOURCE" });
    reservoirs.push({ node_id: "R_IMG_1", head_m: 58 });
    pipes.unshift({ pipe_id: "P_IMG_SOURCE", from_node: "R_IMG_1", to_node: source.node_id, length_m: Number((80 * scale).toFixed(2)), diameter_mm: Math.max(diameter, 250), material: "ductile_iron", install_year: CURRENT_YEAR, bend_count: 0, valve_count: 0, repair_count: 0, leak_history_count: 0, soil_ph: 7, soil_resistivity_ohm_cm: 3000, traffic_load_index: 0.2, burst_history_count: 0 });
  }
  return { nodes, pipes, reservoirs };
}

function applyRecognitionAssetsToDashboard(assets) {
  if (!assets.nodes.length || !assets.pipes.length) return;
  state.nodes = assets.nodes.map((node) => ({ ...node }));
  state.pipes = assets.pipes.map((pipe) => ({ ...pipe }));
  state.reservoirs = assets.reservoirs.map((reservoir) => ({ ...reservoir }));
  state.pumps = [];
  state.valves = [];
  state.households = [];
  state.demandByMinute = new Map();
  state.pipeEdits = new Map();
  state.leakDemands = new Map();
  state.baseNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.originalNodeGeometry = new Map(state.nodes.map((node) => [node.node_id, baseNodeState(node)]));
  state.aging = new Map(state.pipes.map((pipe) => [pipe.pipe_id, agingScore(pipe)]));
  state.addMode = false;
  state.pipeDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
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
  renderRecognitionTable("recognized-nodes-table", assets.nodes || [], ["node_id", "x", "y", "node_type", "dma_id"]);
  renderRecognitionTable("recognized-pipes-table", assets.pipes || [], ["pipe_id", "from_node", "to_node", "length_m", "diameter_mm", "material"]);
  $("recognized-pipe-count").textContent = assets.pipes?.length || 0;
  $("recognized-node-count").textContent = Math.max((assets.nodes?.length || 0) - (assets.reservoirs?.length || 0), 0);
  $("recognized-export-state").textContent = "Streamlit 반영";
  updateRecognitionStatus("streamlit analysis ready", `${assets.pipes?.length || 0} pipes / ${assets.nodes?.length || 0} nodes`);
  toggleRecognitionDownloads(Boolean(assets.nodes?.length && assets.pipes?.length));
  applyRecognitionAssetsToDashboard(assets);
  setAppView("dashboard");
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
  state.mapCenter = { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
  state.mapZoom = clamp(Math.min(1120 / (width + 180), 650 / (height + 160)), 0.45, 2.8);
}

function nearestRecognitionNode(nodes, x, y) {
  return [...nodes].sort((a, b) => Math.hypot(a.x - x, a.y - y) - Math.hypot(b.x - x, b.y - y))[0];
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
  $("pipe-tool").classList.toggle("active", selectedKind === "pipe");
  $("junction-tool").classList.toggle("active", selectedKind === "node");

  const pipeMarkup = snapshot.pipes
    .map((pipe) => {
      const from = project(nodeById.get(pipe.from_node));
      const to = endpointForPipe(pipe, from, project(nodeById.get(pipe.to_node)));
      const flowStart = pipe.flowDirection === "reverse" ? to : from;
      const flowEnd = pipe.flowDirection === "reverse" ? from : to;
      const flowPoint = pointAlong(flowStart, flowEnd, 0.58);
      const flowAngle = Math.atan2(flowEnd.y - flowStart.y, flowEnd.x - flowStart.x) * (180 / Math.PI);
      const selected = selectedKind === "pipe" && selectedId === pipe.pipe_id;
      const isLeak = Number(pipe.leakDemand || 0) > 0 || pipe.status === "leak";
      const strokeColor = isLeak ? PIPE_COLORS.leak : PIPE_COLORS[pipe.status];
      const flowWidth = flowStrokeWidth(pipe.flow_lps, pipe.diameter_mm);
      const strokeWidth = isLeak ? Math.max(12, flowWidth) : flowWidth;
      const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
      const leakLabel = isLeak ? ` · leak ${Number(pipe.leakDemand || 0).toFixed(2)} L/s` : "";
      const overpressure = pipe.pressureSafety?.overpressure;
      const pressureWarning = pipe.pressureSafety?.warning;
      const pressureLabel = overpressure
        ? ` · over ${Math.round(pipe.pressureSafety.utilization * 100)}%`
        : pressureWarning
          ? ` · ${Math.round(pipe.pressureSafety.utilization * 100)}%`
          : "";
      return `<g>
        ${isLeak ? `<line class="pipe-leak-halo" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" />` : ""}
        ${overpressure ? `<line class="pipe-overpressure-halo" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" />` : ""}
        <line class="pipe ${isLeak ? "leak-pipe-line" : ""} ${overpressure ? "overpressure-pipe-line" : ""} ${pressureWarning ? "pressure-warning-pipe-line" : ""} ${selected ? "selected-pipe-line" : ""}" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="${strokeColor}" stroke-width="${strokeWidth}" data-pipe="${pipe.pipe_id}" />
        ${pipe.flow_lps > 0.02 ? `<g class="flow-arrow" transform="translate(${flowPoint.x} ${flowPoint.y}) rotate(${flowAngle})">
          <path d="M-9 -5 L4 0 L-9 5 Z" />
        </g>` : ""}
        ${selected ? `<circle class="selected-ring" cx="${mid.x}" cy="${mid.y}" r="24" />` : ""}
        <text class="pipe-label ${isLeak ? "leak-pipe-label" : ""} ${overpressure ? "overpressure-pipe-label" : ""}" x="${mid.x}" y="${mid.y - 16}">${pipe.pipe_id} · ${pipe.flow_lps.toFixed(1)} L/s · D${Math.round(pipe.diameter_mm)}${leakLabel}${pressureLabel}</text>
      </g>`;
    })
    .join("");

  const previewMarkup = drawPreviewMarkup(project) + pipePreviewMarkup(project, snapshot);

  const nodeMarkup = snapshot.nodes
    .map((node) => {
      const point = project(node);
      const selected = selectedKind === "node" && selectedId === node.node_id;
      const color = node.status === "low" ? "#dc2626" : node.status === "marginal" ? "#d97706" : node.node_type === "reservoir" ? "#0f766e" : "#247a5a";
      const radius = node.node_type === "reservoir" ? 13 : 10;
      const pressure = node.node_type === "reservoir" ? "SRC" : `${node.pressure.toFixed(1)}m`;
      return `<g class="junction-icon" data-node="${node.node_id}" transform="translate(${point.x} ${point.y})">
        ${selected ? `<circle class="selected-ring" r="18" />` : ""}
        <circle class="junction-body" r="${radius}" fill="${color}" />
        <path d="M0 -6v12M-6 0h12" />
        <text class="node-label" x="13" y="-8">${node.node_id}</text>
        <text class="pressure-label" x="13" y="5">${pressure}</text>
      </g>`;
    })
    .join("");

  svg.innerHTML = `${pipeMarkup}${previewMarkup}${nodeMarkup}`;
  svg.onmousemove = (event) => trackDrawingPreview(event);
  svg.onclick = (event) => lockPendingJunction(event);
  svg.onwheel = (event) => {
    event.preventDefault();
    zoomMap(event.deltaY < 0 ? 1.12 : 0.88, eventToSvgPoint(event));
  };
  svg.onmouseup = () => stopNodeDrag();
  svg.onmouseleave = () => {
    stopNodeDrag();
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
      if (state.addMode || state.pipeDrawMode) return;
      event.stopPropagation();
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
      if (state.addMode) return;
      event.stopPropagation();
      selectNode(el.dataset.node);
    }),
  );
  svg.querySelectorAll("[data-node]").forEach((el) =>
    el.addEventListener("mousedown", (event) => {
      if (state.addMode || state.pipeDrawMode) return;
      event.stopPropagation();
      startNodeDrag(el.dataset.node);
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
  const zoom = clamp(state.mapZoom, 0.6, 5);
  state.mapZoom = zoom;
  const viewWidth = width / zoom;
  const viewHeight = height / zoom;
  const center = clampMapCenter(state.mapCenter, viewWidth, viewHeight, width, height);
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

function clampMapCenter(center, viewWidth, viewHeight, width, height) {
  if (viewWidth >= width || viewHeight >= height) return { x: width / 2, y: height / 2 };
  return {
    x: Math.max(viewWidth / 2, Math.min(width - viewWidth / 2, center.x)),
    y: Math.max(viewHeight / 2, Math.min(height - viewHeight / 2, center.y)),
  };
}

function zoomMap(factor, anchorPoint = null) {
  const oldZoom = state.mapZoom;
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

function trackDrawingPreview(event) {
  if (state.draggingNodeId) {
    dragSelectedNode(event);
    return;
  }
  if (state.pipeDrawMode) {
    trackPendingPipe(event);
    return;
  }
  trackPendingJunction(event);
}

function startNodeDrag(nodeId) {
  const node = state.nodes.find((item) => item.node_id === nodeId);
  if (!node || node.node_type === "reservoir") return;
  state.draggingNodeId = nodeId;
  state.selected = `node:${nodeId}`;
  if ($("selected-junction").querySelector(`option[value="${nodeId}"]`)) $("selected-junction").value = nodeId;
}

function dragSelectedNode(event) {
  const node = state.nodes.find((item) => item.node_id === state.draggingNodeId);
  if (!node || !state.mapFrame) return;
  const point = unprojectPoint(eventToSvgPoint(event));
  node.x = point.x;
  node.y = point.y;
  state.baseNodeGeometry.set(node.node_id, baseNodeState(node));
  syncJunctionEditor();
  render();
}

function stopNodeDrag() {
  state.draggingNodeId = "";
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

function lockPendingPipeToNode(nodeId) {
  if (!state.pipeDrawMode || nodeId === $("source-junction").value) return;
  const target = state.nodes.find((node) => node.node_id === nodeId && node.node_type !== "reservoir");
  if (!target) return;
  state.pendingPipe = { x: target.x, y: target.y, locked: true, to_node: nodeId };
  updateDrawReadout();
  render();
}

function lockPendingJunction(event) {
  if (!state.addMode || !state.mapFrame) return;
  const point = eventToSvgPoint(event);
  const networkPoint = unprojectPoint(point);
  state.pendingJunction = buildPendingJunction(networkPoint, true);
  updateDrawReadout();
  render();
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

function syncDrawWorkflow() {
  $("add-junction-mode").classList.toggle("active", state.addMode);
  $("draw-pipe-mode").classList.toggle("active", state.pipeDrawMode);
  $("confirm-junction").disabled = !state.addMode || !state.pendingJunction?.locked;
  $("confirm-pipe").disabled = !state.pipeDrawMode || !state.pendingPipe?.locked;
  if (!state.addMode && !state.pipeDrawMode) return;
  updateDrawReadout();
}

function enterAddJunctionMode() {
  state.addMode = true;
  state.pipeDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
  state.editorTab = "junction";
  $("new-junction-id").value = nextJunctionId();
  updateDrawReadout();
  render();
}

function enterPipeDrawMode() {
  state.pipeDrawMode = true;
  state.addMode = false;
  state.pendingPipe = null;
  state.pendingJunction = null;
  state.editorTab = "junction";
  updateDrawReadout();
  render();
}

function cancelAddJunctionMode() {
  state.addMode = false;
  state.pipeDrawMode = false;
  state.pendingJunction = null;
  state.pendingPipe = null;
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
  state.pendingJunction = null;
  state.pendingPipe = null;
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

function addSourcePump() {
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
  fitMapToCurrentNetwork();
  refreshAssetOptions();
  $("selected-pipe").value = pipeId;
  $("source-readout").textContent = `${sourceId} Source/Pump 추가 완료 · ${sourceId} → ${targetId} · Pipe ${pipeId}`;
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
    $("source-readout").textContent = "마지막 Source/Pump는 삭제할 수 없습니다. 새 Source/Pump를 먼저 추가하세요.";
    return;
  }
  const connectedPipes = state.pipes.filter((pipe) => pipe.from_node === sourceId || pipe.to_node === sourceId);
  const connectedPipeIds = new Set(connectedPipes.map((pipe) => pipe.pipe_id));
  const message = connectedPipes.length
    ? `${sourceId} Source/Pump와 연결된 Pipe ${connectedPipes.length}개도 함께 삭제됩니다. 계속할까요?`
    : `${sourceId} Source/Pump를 삭제할까요?`;
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
  fitMapToCurrentNetwork();
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
}

function suggestSourcePumpPosition() {
  const target = state.nodes.find((node) => node.node_id === $("source-connect-junction").value);
  if (!target) return;
  $("source-x").value = Math.round(Number(target.x || 0) - 120);
  $("source-y").value = Math.round(Number(target.y || 0));
  $("new-source-id").value = nextSourceId();
  $("source-readout").textContent = `${target.node_id}에 연결할 Source/Pump 위치를 제안했습니다. 필요하면 X/Y를 직접 조정하세요.`;
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
  state.selected = `pipe:${pipeId}`;
  state.editorTab = "pipe";
  $("selected-pipe").value = pipeId;
  syncPipeEditor();
  render();
}

function selectNode(nodeId) {
  const node = state.nodes.find((item) => item.node_id === nodeId);
  if (node?.node_type === "reservoir") {
    state.selected = `node:${nodeId}`;
    state.editorTab = "source";
    if ($("selected-source").querySelector(`option[value="${nodeId}"]`)) $("selected-source").value = nodeId;
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
  syncSourceControlLabels();
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
