"""Recognize early water-network drawing features from JPG/PNG files.

The OpenCV stage extracts deterministic geometry candidates. The optional
Gemini stage reads the same drawing semantically and returns structured hints
that can be compared against the OpenCV result before creating production
network assets.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png"}


@dataclass(frozen=True)
class OpenCVRecognitionResult:
    width: int
    height: int
    threshold_image: np.ndarray
    edge_image: np.ndarray
    overlay_image: np.ndarray
    line_segments: list[dict[str, float]]
    node_candidates: list[dict[str, float]]
    pipe_candidates: list[dict[str, Any]]
    binary_payload: bytes

    def summary(self) -> dict[str, int]:
        return {
            "width": self.width,
            "height": self.height,
            "line_segments": len(self.line_segments),
            "node_candidates": len(self.node_candidates),
            "pipe_candidates": len(self.pipe_candidates),
            "binary_payload_bytes": len(self.binary_payload),
        }


@dataclass(frozen=True)
class GeminiVisionResult:
    model: str
    raw_text: str
    parsed_json: dict[str, Any] | list[Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class DrawingRecognitionResult:
    opencv: OpenCVRecognitionResult
    gemini: GeminiVisionResult | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, include_images: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "opencv": {
                key: value
                for key, value in asdict(self.opencv).items()
                if include_images or not key.endswith("_image")
            },
            "gemini": asdict(self.gemini) if self.gemini else None,
            "warnings": self.warnings,
        }
        if not include_images:
            payload["opencv"].pop("binary_payload", None)
        return payload


@dataclass(frozen=True)
class DashboardAssetExport:
    nodes: list[dict[str, Any]]
    pipes: list[dict[str, Any]]
    reservoirs: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "pipes": self.pipes,
            "reservoirs": self.reservoirs,
            "warnings": self.warnings,
        }


def analyze_drawing_image(
    image_bytes: bytes,
    mime_type: str,
    *,
    min_line_length: int = 35,
    merge_tolerance_px: float = 16.0,
) -> OpenCVRecognitionResult:
    """Decode a JPG/PNG drawing and extract line, node, and pipe candidates."""

    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError(f"Unsupported image MIME type: {mime_type}")
    cv2 = _import_cv2()

    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image bytes as a JPG/PNG drawing.")

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    threshold = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        8,
    )
    edges = cv2.Canny(denoised, 50, 150, apertureSize=3)
    raw_lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=45,
        minLineLength=max(10, min_line_length),
        maxLineGap=12,
    )

    line_segments = _normalize_lines(raw_lines)
    node_candidates = _detect_node_candidates(cv2, threshold)
    merged_nodes = _merge_line_endpoints(line_segments, merge_tolerance_px)
    pipe_candidates = _pipes_from_lines(line_segments, merged_nodes)
    overlay = _draw_overlay(cv2, image, line_segments, node_candidates, pipe_candidates)
    dashboard_assets = build_dashboard_assets_from_candidates(
        merged_nodes,
        pipe_candidates,
        image_width=width,
        image_height=height,
    )
    binary_payload = json.dumps(
        {
            "image": {"width": width, "height": height, "mime_type": mime_type},
            "nodes": merged_nodes,
            "pipes": pipe_candidates,
            "opencv_nodes": node_candidates,
            "dashboard_assets": dashboard_assets.to_dict(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return OpenCVRecognitionResult(
        width=width,
        height=height,
        threshold_image=threshold,
        edge_image=edges,
        overlay_image=overlay,
        line_segments=line_segments,
        node_candidates=node_candidates,
        pipe_candidates=pipe_candidates,
        binary_payload=binary_payload,
    )


def build_dashboard_assets_from_recognition(
    result: OpenCVRecognitionResult,
    *,
    scale_m_per_px: float = 1.0,
    default_diameter_mm: float = 150.0,
    default_material: str = "PVC",
    default_elevation_m: float = 30.0,
    default_demand_lps: float = 0.8,
    include_virtual_reservoir: bool = True,
) -> DashboardAssetExport:
    """Convert an OpenCV recognition result into dashboard-compatible assets."""

    payload = json.loads(result.binary_payload.decode("utf-8"))
    return build_dashboard_assets_from_candidates(
        payload.get("nodes", []),
        payload.get("pipes", []),
        image_width=int(payload.get("image", {}).get("width", result.width)),
        image_height=int(payload.get("image", {}).get("height", result.height)),
        scale_m_per_px=scale_m_per_px,
        default_diameter_mm=default_diameter_mm,
        default_material=default_material,
        default_elevation_m=default_elevation_m,
        default_demand_lps=default_demand_lps,
        include_virtual_reservoir=include_virtual_reservoir,
    )


def build_dashboard_assets_from_candidates(
    nodes: list[dict[str, Any]],
    pipes: list[dict[str, Any]],
    *,
    image_width: int,
    image_height: int,
    scale_m_per_px: float = 1.0,
    default_diameter_mm: float = 150.0,
    default_material: str = "PVC",
    default_elevation_m: float = 30.0,
    default_demand_lps: float = 0.8,
    include_virtual_reservoir: bool = True,
) -> DashboardAssetExport:
    """Build the CSV-shaped node/pipe records used by the HTML dashboard."""

    safe_scale = max(float(scale_m_per_px), 0.001)
    node_id_by_candidate = {str(node["id"]): f"J_IMG_{index + 1}" for index, node in enumerate(nodes)}
    dashboard_nodes = [
        {
            "node_id": node_id_by_candidate[str(node["id"])],
            "x": round(float(node["x"]) * safe_scale, 2),
            "y": round((float(image_height) - float(node["y"])) * safe_scale, 2),
            "elevation_m": float(default_elevation_m),
            "base_demand_lps": float(default_demand_lps),
            "node_type": "junction",
            "dma_id": "IMG_IMPORT",
        }
        for node in nodes
        if "id" in node and "x" in node and "y" in node
    ]

    warnings: list[str] = []
    dashboard_pipes: list[dict[str, Any]] = []
    for pipe in pipes:
        from_node = node_id_by_candidate.get(str(pipe.get("from_node", "")))
        to_node = node_id_by_candidate.get(str(pipe.get("to_node", "")))
        if not from_node or not to_node:
            warnings.append(f"{pipe.get('id', 'unknown')} endpoint could not be mapped to a node.")
            continue
        dashboard_pipes.append(
            {
                "pipe_id": f"P_IMG_{len(dashboard_pipes) + 1}",
                "from_node": from_node,
                "to_node": to_node,
                "length_m": round(float(pipe.get("length_px", 1.0)) * safe_scale, 2),
                "diameter_mm": float(default_diameter_mm),
                "material": default_material,
                "install_year": 2026,
                "bend_count": 0,
                "valve_count": 0,
                "repair_count": 0,
                "leak_history_count": 0,
                "soil_ph": 7.0,
                "soil_resistivity_ohm_cm": 3000.0,
                "traffic_load_index": 0.3,
                "burst_history_count": 0,
            }
        )

    reservoirs: list[dict[str, Any]] = []
    if include_virtual_reservoir and dashboard_nodes:
        source_node = min(dashboard_nodes, key=lambda node: float(node["x"]))
        reservoir_node = {
            "node_id": "R_IMG_1",
            "x": round(float(source_node["x"]) - 80 * safe_scale, 2),
            "y": source_node["y"],
            "elevation_m": float(default_elevation_m) + 5.0,
            "base_demand_lps": 0.0,
            "node_type": "reservoir",
            "dma_id": "SOURCE",
        }
        dashboard_nodes.insert(0, reservoir_node)
        reservoirs.append({"node_id": "R_IMG_1", "head_m": 58.0})
        dashboard_pipes.insert(
            0,
            {
                "pipe_id": "P_IMG_SOURCE",
                "from_node": "R_IMG_1",
                "to_node": source_node["node_id"],
                "length_m": 80.0 * safe_scale,
                "diameter_mm": max(float(default_diameter_mm), 250.0),
                "material": "ductile_iron",
                "install_year": 2026,
                "bend_count": 0,
                "valve_count": 0,
                "repair_count": 0,
                "leak_history_count": 0,
                "soil_ph": 7.0,
                "soil_resistivity_ohm_cm": 3000.0,
                "traffic_load_index": 0.2,
                "burst_history_count": 0,
            },
        )
        warnings.append("A virtual reservoir and source pipe were added for dashboard preview.")

    if not dashboard_nodes:
        warnings.append("No dashboard nodes were created from the image.")
    if not dashboard_pipes:
        warnings.append("No dashboard pipes were created from the image.")

    return DashboardAssetExport(
        nodes=dashboard_nodes,
        pipes=dashboard_pipes,
        reservoirs=reservoirs,
        warnings=warnings,
    )


def call_gemini_vision(
    image_bytes: bytes,
    mime_type: str,
    *,
    api_key: str | None = None,
    model: str = "gemini-2.5-flash",
    prompt: str | None = None,
) -> GeminiVisionResult:
    """Ask Gemini Vision for structured semantic hints from a drawing image."""

    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError(f"Unsupported image MIME type: {mime_type}")

    api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return GeminiVisionResult(
            model=model,
            raw_text="",
            error="GEMINI_API_KEY or GOOGLE_API_KEY is not configured.",
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - depends on optional package
        return GeminiVisionResult(
            model=model,
            raw_text="",
            error=f"google-genai is not installed: {exc}",
        )

    default_prompt = """
Analyze this water distribution network drawing. Return only JSON with:
{
  "drawing_type": "water_network_drawing|unknown",
  "pipes": [{"label": string, "description": string, "confidence": number}],
  "nodes": [{"label": string, "type": "junction|valve|pump|reservoir|tank|unknown", "confidence": number}],
  "text_labels": [{"text": string, "meaning": string}],
  "legend": [{"symbol": string, "meaning": string}],
  "risks_or_ambiguities": [string],
  "recommended_next_step": string
}
Use Korean for descriptions. Do not invent exact coordinates unless the drawing visibly provides them.
"""
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt or default_prompt,
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        raw_text = str(getattr(response, "text", "") or "")
        return GeminiVisionResult(
            model=model,
            raw_text=raw_text,
            parsed_json=_parse_json_response(raw_text),
        )
    except Exception as exc:  # pragma: no cover - network/API runtime path
        return GeminiVisionResult(model=model, raw_text="", error=str(exc))


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - dependency check path
        raise RuntimeError(
            "OpenCV is required for drawing recognition. Install opencv-python-headless."
        ) from exc
    return cv2


def _normalize_lines(raw_lines: Any) -> list[dict[str, float]]:
    if raw_lines is None:
        return []

    lines: list[dict[str, float]] = []
    for index, line in enumerate(raw_lines):
        x1, y1, x2, y2 = [float(value) for value in line[0]]
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 0:
            continue
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        lines.append(
            {
                "id": f"L{index + 1}",
                "x1": round(x1, 2),
                "y1": round(y1, 2),
                "x2": round(x2, 2),
                "y2": round(y2, 2),
                "length_px": round(length, 2),
                "angle_deg": round(angle, 2),
            }
        )
    return sorted(lines, key=lambda row: row["length_px"], reverse=True)


def _detect_node_candidates(cv2: Any, threshold: np.ndarray) -> list[dict[str, float]]:
    contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[dict[str, float]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < 25 or area > 3000:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        circularity = 4 * math.pi * area / (perimeter * perimeter)
        x, y, w, h = [float(value) for value in cv2.boundingRect(contour)]
        aspect = w / max(h, 1)
        if circularity < 0.35 or not (0.35 <= aspect <= 2.85):
            continue
        candidates.append(
            {
                "id": f"C{len(candidates) + 1}",
                "x": round(x + w / 2, 2),
                "y": round(y + h / 2, 2),
                "width_px": round(w, 2),
                "height_px": round(h, 2),
                "area_px": round(area, 2),
                "circularity": round(circularity, 3),
            }
        )
    return sorted(candidates, key=lambda row: row["area_px"], reverse=True)[:150]


def _merge_line_endpoints(
    line_segments: list[dict[str, float]],
    tolerance_px: float,
) -> list[dict[str, float]]:
    nodes: list[dict[str, float]] = []
    for line in line_segments:
        for x_key, y_key in [("x1", "y1"), ("x2", "y2")]:
            x = float(line[x_key])
            y = float(line[y_key])
            match = _nearest_node(nodes, x, y, tolerance_px)
            if match is None:
                nodes.append({"id": f"N{len(nodes) + 1}", "x": x, "y": y, "hits": 1})
            else:
                hits = float(match["hits"])
                match["x"] = round((float(match["x"]) * hits + x) / (hits + 1), 2)
                match["y"] = round((float(match["y"]) * hits + y) / (hits + 1), 2)
                match["hits"] = int(hits + 1)
    return nodes


def _nearest_node(
    nodes: list[dict[str, float]],
    x: float,
    y: float,
    tolerance_px: float,
) -> dict[str, float] | None:
    nearest: dict[str, float] | None = None
    nearest_distance = tolerance_px
    for node in nodes:
        distance = math.hypot(float(node["x"]) - x, float(node["y"]) - y)
        if distance <= nearest_distance:
            nearest = node
            nearest_distance = distance
    return nearest


def _pipes_from_lines(
    line_segments: list[dict[str, float]],
    nodes: list[dict[str, float]],
) -> list[dict[str, Any]]:
    pipes: list[dict[str, Any]] = []
    for line in line_segments:
        start = _nearest_node(nodes, float(line["x1"]), float(line["y1"]), 9999)
        end = _nearest_node(nodes, float(line["x2"]), float(line["y2"]), 9999)
        if not start or not end or start["id"] == end["id"]:
            continue
        pipes.append(
            {
                "id": f"P_IMG_{len(pipes) + 1}",
                "from_node": start["id"],
                "to_node": end["id"],
                "source_line": line["id"],
                "length_px": line["length_px"],
                "angle_deg": line["angle_deg"],
            }
        )
    return pipes


def _draw_overlay(
    cv2: Any,
    image: np.ndarray,
    line_segments: list[dict[str, float]],
    node_candidates: list[dict[str, float]],
    pipe_candidates: list[dict[str, Any]],
) -> np.ndarray:
    overlay = image.copy()
    line_lookup = {line["id"]: line for line in line_segments}
    for pipe in pipe_candidates[:500]:
        line = line_lookup.get(str(pipe["source_line"]))
        if not line:
            continue
        cv2.line(
            overlay,
            (int(line["x1"]), int(line["y1"])),
            (int(line["x2"]), int(line["y2"])),
            (37, 99, 235),
            2,
        )
    for candidate in node_candidates[:150]:
        cv2.circle(
            overlay,
            (int(candidate["x"]), int(candidate["y"])),
            max(4, int(max(candidate["width_px"], candidate["height_px"]) / 2)),
            (34, 197, 94),
            2,
        )
    return cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)


def _parse_json_response(raw_text: str) -> dict[str, Any] | list[Any] | None:
    text = raw_text.strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None
