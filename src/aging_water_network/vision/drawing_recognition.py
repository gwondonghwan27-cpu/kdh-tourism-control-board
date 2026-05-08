"""Recognize water-network drawing features from image, PDF, and CAD files.

The recognizer first routes each upload by file type. Image files use Gemini
semantic hints plus deterministic geometry candidates, vector PDFs/CAD files
prefer native geometry extraction, and scanned PDFs can fall back to the image
route when a PDF renderer is available.
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
SUPPORTED_PDF_MIME_TYPES = {"application/pdf"}
SUPPORTED_CAD_MIME_TYPES = {
    "application/acad",
    "application/autocad",
    "application/dwg",
    "application/x-acad",
    "application/x-autocad",
    "application/x-dwg",
    "image/vnd.dwg",
}
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_CAD_EXTENSIONS = {".dwg", ".dxf"}


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
class CadRecognitionResult:
    width: int
    height: int
    line_segments: list[dict[str, float]]
    node_candidates: list[dict[str, float]]
    pipe_candidates: list[dict[str, Any]]
    binary_payload: bytes
    cad_format: str
    warnings: list[str] = field(default_factory=list)

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
class PdfRecognitionResult:
    width: int
    height: int
    line_segments: list[dict[str, float]]
    node_candidates: list[dict[str, float]]
    pipe_candidates: list[dict[str, Any]]
    binary_payload: bytes
    pdf_mode: str
    warnings: list[str] = field(default_factory=list)

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
    pipe_mask = _detect_colored_pipe_mask(cv2, image)
    color_node_candidates = _detect_colored_node_candidates(cv2, image)
    use_color_recognition = int(np.count_nonzero(pipe_mask)) > max(100, int(width * height * 0.002))

    if use_color_recognition:
        edges = cv2.Canny(pipe_mask, 40, 120, apertureSize=3)
        raw_lines = cv2.HoughLinesP(
            pipe_mask,
            rho=1,
            theta=np.pi / 180,
            threshold=35,
            minLineLength=max(15, min_line_length),
            maxLineGap=24,
        )
        line_segments = _dedupe_line_segments(_normalize_lines(raw_lines), merge_tolerance_px)
        node_candidates = color_node_candidates or _detect_node_candidates(cv2, threshold)
        merged_nodes = _merge_symbol_nodes_and_pipe_endpoints(
            node_candidates,
            line_segments,
            tolerance_px=merge_tolerance_px,
            min_endpoint_line_length=max(float(min_line_length) * 3.0, 110.0),
        )
        pipe_candidates = _pipes_from_colored_mask(
            pipe_mask,
            merged_nodes,
            max_pair_distance_px=max(width, height) * 0.45,
        )
        if pipe_candidates:
            line_segments = _line_segments_from_pipe_candidates(pipe_candidates, merged_nodes)
        if not pipe_candidates:
            merged_nodes = _merge_line_endpoints(line_segments, merge_tolerance_px)
            pipe_candidates = _pipes_from_lines(line_segments, merged_nodes)
    else:
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


def detect_drawing_file_type(
    file_bytes: bytes,
    *,
    filename: str = "",
    mime_type: str = "",
) -> str:
    """Classify an uploaded drawing before selecting an image or CAD route."""

    suffix = _file_suffix(filename)
    normalized_mime = (mime_type or "").split(";")[0].strip().lower()
    header = file_bytes[:16]

    if suffix in SUPPORTED_IMAGE_EXTENSIONS or normalized_mime in SUPPORTED_IMAGE_MIME_TYPES:
        return "image"
    if suffix in SUPPORTED_PDF_EXTENSIONS or normalized_mime in SUPPORTED_PDF_MIME_TYPES:
        return "pdf"
    if suffix in SUPPORTED_CAD_EXTENSIONS or normalized_mime in SUPPORTED_CAD_MIME_TYPES:
        return "cad"
    if header.startswith(b"\xff\xd8\xff") or header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if header.startswith(b"%PDF"):
        return "pdf"
    if header.startswith(b"AC10") or b"SECTION" in file_bytes[:512].upper():
        return "cad"
    return "unknown"


def analyze_drawing_cad(
    cad_bytes: bytes,
    *,
    filename: str = "",
    mime_type: str = "",
    merge_tolerance_px: float = 16.0,
) -> CadRecognitionResult:
    """Route CAD drawings through vector extraction instead of image masks."""

    suffix = _file_suffix(filename)
    warnings: list[str] = []
    if suffix == ".dxf" or _looks_like_ascii_dxf(cad_bytes):
        line_segments, width, height, warnings = _parse_ascii_dxf_lines(cad_bytes)
        nodes = _merge_line_endpoints(line_segments, merge_tolerance_px)
        pipes = _pipes_from_lines(line_segments, nodes)
        cad_format = "dxf"
    elif suffix == ".dwg" or cad_bytes.startswith(b"AC10"):
        cad_format = "dwg"
        line_segments = []
        nodes = []
        pipes = []
        width = 0
        height = 0
        warnings.append(
            "DWG file was routed to the CAD recognizer, but binary DWG geometry "
            "extraction needs an external CAD converter or parser. Export DXF for "
            "the current vector route."
        )
    else:
        cad_format = suffix.lstrip(".") or (mime_type or "unknown")
        line_segments = []
        nodes = []
        pipes = []
        width = 0
        height = 0
        warnings.append("The upload was routed as CAD, but no supported CAD extractor matched it.")

    dashboard_assets = build_dashboard_assets_from_candidates(
        nodes,
        pipes,
        image_width=max(width, 1),
        image_height=max(height, 1),
    )
    binary_payload = json.dumps(
        {
            "file": {
                "filename": filename,
                "mime_type": mime_type,
                "drawing_file_type": "cad",
                "cad_format": cad_format,
            },
            "image": {"width": width, "height": height, "mime_type": mime_type},
            "nodes": nodes,
            "pipes": pipes,
            "cad_warnings": warnings,
            "dashboard_assets": dashboard_assets.to_dict(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return CadRecognitionResult(
        width=width,
        height=height,
        line_segments=line_segments,
        node_candidates=nodes,
        pipe_candidates=pipes,
        binary_payload=binary_payload,
        cad_format=cad_format,
        warnings=warnings,
    )


def analyze_drawing_pdf(
    pdf_bytes: bytes,
    *,
    filename: str = "",
    mime_type: str = "application/pdf",
    min_line_length: int = 35,
    merge_tolerance_px: float = 16.0,
) -> PdfRecognitionResult:
    """Route PDF drawings through vector extraction before scanned-image fallback."""

    warnings: list[str] = []
    line_segments, width, height, fitz_warnings = _extract_pdf_vectors_with_pymupdf(pdf_bytes)
    warnings.extend(fitz_warnings)
    pdf_mode = "vector"

    if not line_segments:
        fallback_segments, fallback_width, fallback_height, fallback_warnings = _parse_uncompressed_pdf_vector_lines(pdf_bytes)
        warnings.extend(fallback_warnings)
        line_segments = fallback_segments
        width = fallback_width
        height = fallback_height
        if line_segments:
            pdf_mode = "vector_uncompressed"

    if not line_segments:
        rendered = _render_pdf_first_page_to_image_route(
            pdf_bytes,
            min_line_length=min_line_length,
            merge_tolerance_px=merge_tolerance_px,
        )
        if rendered:
            rendered_result, render_warnings = rendered
            warnings.extend(render_warnings)
            payload = json.loads(rendered_result.binary_payload.decode("utf-8"))
            assets = build_dashboard_assets_from_recognition(rendered_result)
            binary_payload = json.dumps(
                {
                    "file": {
                        "filename": filename,
                        "mime_type": mime_type,
                        "drawing_file_type": "pdf",
                        "pdf_mode": "scanned_image",
                    },
                    "image": {"width": rendered_result.width, "height": rendered_result.height, "mime_type": "image/png"},
                    "nodes": payload.get("nodes", []),
                    "pipes": payload.get("pipes", []),
                    "pdf_warnings": warnings,
                    "dashboard_assets": assets.to_dict(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            return PdfRecognitionResult(
                width=rendered_result.width,
                height=rendered_result.height,
                line_segments=rendered_result.line_segments,
                node_candidates=payload.get("nodes", []),
                pipe_candidates=rendered_result.pipe_candidates,
                binary_payload=binary_payload,
                pdf_mode="scanned_image",
                warnings=warnings,
            )
        pdf_mode = "unresolved"

    nodes = _merge_line_endpoints(line_segments, merge_tolerance_px)
    pipes = _pipes_from_lines(line_segments, nodes)
    if not line_segments:
        warnings.append(
            "PDF file was routed correctly, but no vector geometry could be extracted. "
            "Install PyMuPDF to enable scanned PDF rendering fallback."
        )

    assets = build_dashboard_assets_from_candidates(
        nodes,
        pipes,
        image_width=max(width, 1),
        image_height=max(height, 1),
    )
    binary_payload = json.dumps(
        {
            "file": {
                "filename": filename,
                "mime_type": mime_type,
                "drawing_file_type": "pdf",
                "pdf_mode": pdf_mode,
            },
            "image": {"width": width, "height": height, "mime_type": mime_type},
            "nodes": nodes,
            "pipes": pipes,
            "pdf_warnings": warnings,
            "dashboard_assets": assets.to_dict(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return PdfRecognitionResult(
        width=width,
        height=height,
        line_segments=line_segments,
        node_candidates=nodes,
        pipe_candidates=pipes,
        binary_payload=binary_payload,
        pdf_mode=pdf_mode,
        warnings=warnings,
    )


def recognize_drawing_file(
    file_bytes: bytes,
    *,
    filename: str = "",
    mime_type: str = "",
    min_line_length: int = 35,
    merge_tolerance_px: float = 16.0,
) -> tuple[str, OpenCVRecognitionResult | PdfRecognitionResult | CadRecognitionResult]:
    """Recognize an uploaded drawing through the route selected by file type."""

    drawing_file_type = detect_drawing_file_type(file_bytes, filename=filename, mime_type=mime_type)
    if drawing_file_type == "image":
        image_mime_type = _normalize_image_mime_type(filename, mime_type)
        return drawing_file_type, analyze_drawing_image(
            file_bytes,
            image_mime_type,
            min_line_length=min_line_length,
            merge_tolerance_px=merge_tolerance_px,
        )
    if drawing_file_type == "pdf":
        return drawing_file_type, analyze_drawing_pdf(
            file_bytes,
            filename=filename,
            mime_type=mime_type or "application/pdf",
            min_line_length=min_line_length,
            merge_tolerance_px=merge_tolerance_px,
        )
    if drawing_file_type == "cad":
        return drawing_file_type, analyze_drawing_cad(
            file_bytes,
            filename=filename,
            mime_type=mime_type,
            merge_tolerance_px=merge_tolerance_px,
        )
    raise ValueError("Unsupported drawing file type. Use JPG, PNG, PDF, DWG, or DXF.")


def build_dashboard_assets_from_recognition(
    result: OpenCVRecognitionResult | PdfRecognitionResult | CadRecognitionResult,
    *,
    scale_m_per_px: float = 1.0,
    default_diameter_mm: float = 150.0,
    default_material: str = "PVC",
    default_elevation_m: float = 30.0,
    default_demand_lps: float = 0.8,
    include_virtual_reservoir: bool = True,
) -> DashboardAssetExport:
    """Convert a recognition result into dashboard-compatible assets."""

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

    source_candidate_id = _select_source_candidate_id(nodes, pipes)
    reservoirs: list[dict[str, Any]] = []
    if include_virtual_reservoir and dashboard_nodes:
        source_node = next(
            (
                node
                for node in dashboard_nodes
                if node["node_id"] == node_id_by_candidate.get(str(source_candidate_id))
            ),
            min(dashboard_nodes, key=lambda node: float(node["x"])),
        )
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
        warnings.append("No dashboard nodes were created from the drawing.")
    if not dashboard_pipes:
        warnings.append("No dashboard pipes were created from the drawing.")

    return DashboardAssetExport(
        nodes=dashboard_nodes,
        pipes=dashboard_pipes,
        reservoirs=reservoirs,
        warnings=warnings,
    )


def _select_source_candidate_id(
    nodes: list[dict[str, Any]],
    pipes: list[dict[str, Any]],
) -> str | None:
    if not nodes:
        return None
    degree: dict[str, int] = {}
    for pipe in pipes:
        for key in ["from_node", "to_node"]:
            node_id = str(pipe.get(key, ""))
            if node_id:
                degree[node_id] = degree.get(node_id, 0) + 1

    valid_nodes = [node for node in nodes if "id" in node and "x" in node and "y" in node]
    if not valid_nodes:
        return None

    def source_rank(node: dict[str, Any]) -> tuple[int, float, float]:
        node_id = str(node["id"])
        is_terminal = degree.get(node_id, 0) <= 1
        return (0 if is_terminal else 1, float(node["y"]), float(node["x"]))

    return str(min(valid_nodes, key=source_rank)["id"])


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
Analyze this water distribution network drawing as a machine-readable recognition aid.
Return only JSON with this schema:
{
  "drawing_type": "water_network_drawing|unknown",
  "pipe_style": {
    "main_pipe_colors": [string],
    "secondary_pipe_colors": [string],
    "existing_pipe_style": string,
    "background_or_road_style": string
  },
  "detected_assets": {
    "reservoirs": [{"label": string, "box_2d": [number, number, number, number], "confidence": number}],
    "junctions": [{"label": string, "box_2d": [number, number, number, number], "confidence": number}],
    "valves": [{"label": string, "box_2d": [number, number, number, number], "confidence": number}],
    "pumps": [{"label": string, "box_2d": [number, number, number, number], "confidence": number}]
  },
  "text_labels": [{"text": string, "meaning": "node_id|pipe_diameter|pipe_name|legend|unknown", "near": string, "confidence": number}],
  "connection_hints": [{"from": string, "to": string, "evidence": string, "confidence": number}],
  "legend": [{"symbol": string, "meaning": string}],
  "risks_or_ambiguities": [string],
  "recommended_next_step": string
}
Use normalized Gemini box_2d coordinates in the 0-1000 range when possible.
Prefer visible labels and visual evidence over guesses. Use Korean for free-text descriptions.
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


def _file_suffix(filename: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]+)$", filename or "")
    return match.group(1).lower() if match else ""


def _normalize_image_mime_type(filename: str, mime_type: str) -> str:
    normalized_mime = (mime_type or "").split(";")[0].strip().lower()
    if normalized_mime in SUPPORTED_IMAGE_MIME_TYPES:
        return normalized_mime
    suffix = _file_suffix(filename)
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return "image/png"


def _extract_pdf_vectors_with_pymupdf(pdf_bytes: bytes) -> tuple[list[dict[str, float]], int, int, list[str]]:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return [], 0, 0, ["PyMuPDF is not installed, so native vector PDF extraction was skipped."]

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        if not document.page_count:
            return [], 0, 0, ["PDF has no pages."]
        page = document[0]
        page_rect = page.rect
        raw_segments: list[tuple[float, float, float, float]] = []
        for drawing in page.get_drawings():
            for item in drawing.get("items", []):
                if not item or item[0] != "l":
                    continue
                start = item[1]
                end = item[2]
                raw_segments.append((float(start.x), float(start.y), float(end.x), float(end.y)))
        if not raw_segments:
            return [], int(page_rect.width), int(page_rect.height), ["No vector line drawings were found on the first PDF page."]
        segments, width, height = _normalize_cad_segments(raw_segments)
        return segments, width, height, []
    except Exception as exc:  # pragma: no cover - depends on optional package/runtime PDFs
        return [], 0, 0, [f"Vector PDF extraction failed: {exc}"]


def _render_pdf_first_page_to_image_route(
    pdf_bytes: bytes,
    *,
    min_line_length: int,
    merge_tolerance_px: float,
) -> tuple[OpenCVRecognitionResult, list[str]] | None:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return None

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        if not document.page_count:
            return None
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image_bytes = pixmap.tobytes("png")
        result = analyze_drawing_image(
            image_bytes,
            "image/png",
            min_line_length=min_line_length,
            merge_tolerance_px=merge_tolerance_px,
        )
        return result, ["Scanned PDF fallback rendered the first page to PNG and used the image route."]
    except Exception:
        return None


def _parse_uncompressed_pdf_vector_lines(pdf_bytes: bytes) -> tuple[list[dict[str, float]], int, int, list[str]]:
    text = pdf_bytes.decode("latin1", errors="ignore")
    token_pattern = re.compile(r"[-+]?(?:\d+\.\d+|\d+|\.\d+)|[A-Za-z*]+")
    tokens = token_pattern.findall(text)
    stack: list[float] = []
    current: tuple[float, float] | None = None
    raw_segments: list[tuple[float, float, float, float]] = []

    for token in tokens:
        try:
            stack.append(float(token))
            continue
        except ValueError:
            pass

        if token == "m" and len(stack) >= 2:
            current = (stack[-2], stack[-1])
            stack.clear()
        elif token == "l" and len(stack) >= 2 and current is not None:
            target = (stack[-2], stack[-1])
            raw_segments.append((current[0], current[1], target[0], target[1]))
            current = target
            stack.clear()
        elif token == "re" and len(stack) >= 4:
            x, y, width, height = stack[-4], stack[-3], stack[-2], stack[-1]
            raw_segments.extend(
                [
                    (x, y, x + width, y),
                    (x + width, y, x + width, y + height),
                    (x + width, y + height, x, y + height),
                    (x, y + height, x, y),
                ]
            )
            stack.clear()
        elif token in {"S", "s", "f", "F", "n", "h", "q", "Q", "cm", "w", "rg", "RG"}:
            if token != "h":
                stack.clear()

    if not raw_segments:
        return [], 0, 0, ["No uncompressed PDF path line commands were found."]
    segments, width, height = _normalize_cad_segments(raw_segments)
    return segments, width, height, []


def _looks_like_ascii_dxf(cad_bytes: bytes) -> bool:
    sample = cad_bytes[:2048].decode("utf-8", errors="ignore").upper()
    return "SECTION" in sample and "ENTITIES" in sample


def _parse_ascii_dxf_lines(cad_bytes: bytes) -> tuple[list[dict[str, float]], int, int, list[str]]:
    text = cad_bytes.decode("utf-8", errors="ignore")
    raw_pairs = [line.strip() for line in text.splitlines()]
    pairs: list[tuple[str, str]] = []
    for index in range(0, len(raw_pairs) - 1, 2):
        pairs.append((raw_pairs[index], raw_pairs[index + 1]))

    raw_segments: list[tuple[float, float, float, float]] = []
    cursor = 0
    while cursor < len(pairs):
        code, value = pairs[cursor]
        if code == "0" and value == "LINE":
            segment, cursor = _read_dxf_line_entity(pairs, cursor + 1)
            if segment:
                raw_segments.append(segment)
            continue
        if code == "0" and value == "LWPOLYLINE":
            segments, cursor = _read_dxf_lwpolyline_entity(pairs, cursor + 1)
            raw_segments.extend(segments)
            continue
        cursor += 1

    warnings: list[str] = []
    if not raw_segments:
        warnings.append("No LINE or LWPOLYLINE entities were extracted from the CAD drawing.")
        return [], 0, 0, warnings

    normalized_segments, width, height = _normalize_cad_segments(raw_segments)
    return normalized_segments, width, height, warnings


def _read_dxf_line_entity(
    pairs: list[tuple[str, str]],
    cursor: int,
) -> tuple[tuple[float, float, float, float] | None, int]:
    values: dict[str, float] = {}
    while cursor < len(pairs):
        code, value = pairs[cursor]
        if code == "0":
            break
        if code in {"10", "20", "11", "21"}:
            try:
                values[code] = float(value)
            except ValueError:
                pass
        cursor += 1
    if {"10", "20", "11", "21"}.issubset(values):
        return (values["10"], values["20"], values["11"], values["21"]), cursor
    return None, cursor


def _read_dxf_lwpolyline_entity(
    pairs: list[tuple[str, str]],
    cursor: int,
) -> tuple[list[tuple[float, float, float, float]], int]:
    points: list[tuple[float, float]] = []
    pending_x: float | None = None
    closed = False
    while cursor < len(pairs):
        code, value = pairs[cursor]
        if code == "0":
            break
        if code == "70":
            try:
                closed = bool(int(float(value)) & 1)
            except ValueError:
                closed = False
        elif code == "10":
            try:
                pending_x = float(value)
            except ValueError:
                pending_x = None
        elif code == "20" and pending_x is not None:
            try:
                points.append((pending_x, float(value)))
            except ValueError:
                pass
            pending_x = None
        cursor += 1

    segments = [
        (points[index][0], points[index][1], points[index + 1][0], points[index + 1][1])
        for index in range(len(points) - 1)
    ]
    if closed and len(points) > 2:
        segments.append((points[-1][0], points[-1][1], points[0][0], points[0][1]))
    return segments, cursor


def _normalize_cad_segments(
    raw_segments: list[tuple[float, float, float, float]],
) -> tuple[list[dict[str, float]], int, int]:
    xs = [value for x1, _, x2, _ in raw_segments for value in (x1, x2)]
    ys = [value for _, y1, _, y2 in raw_segments for value in (y1, y2)]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    margin = 20.0
    width = int(math.ceil(max(max_x - min_x + margin * 2, 1)))
    height = int(math.ceil(max(max_y - min_y + margin * 2, 1)))

    line_segments: list[dict[str, float]] = []
    for raw_index, (x1, y1, x2, y2) in enumerate(raw_segments):
        nx1 = x1 - min_x + margin
        nx2 = x2 - min_x + margin
        ny1 = max_y - y1 + margin
        ny2 = max_y - y2 + margin
        length = math.hypot(nx2 - nx1, ny2 - ny1)
        if length <= 0:
            continue
        line_segments.append(
            {
                "id": f"L_CAD_{len(line_segments) + 1}",
                "x1": round(nx1, 2),
                "y1": round(ny1, 2),
                "x2": round(nx2, 2),
                "y2": round(ny2, 2),
                "length_px": round(length, 2),
                "angle_deg": round(math.degrees(math.atan2(ny2 - ny1, nx2 - nx1)), 2),
                "source_entity": f"DXF_{raw_index + 1}",
            }
        )
    return line_segments, width, height


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


def _detect_colored_pipe_mask(cv2: Any, image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([85, 45, 35]), np.array([130, 255, 255]))
    cyan = cv2.inRange(hsv, np.array([75, 35, 60]), np.array([100, 255, 255]))
    mask = cv2.bitwise_or(blue, cyan)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    return mask


def _detect_colored_node_candidates(cv2: Any, image: np.ndarray) -> list[dict[str, float]]:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35, 35, 45]), np.array([90, 255, 255]))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    green = cv2.dilate(green, kernel, iterations=1)
    contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[dict[str, float]] = []
    image_area = float(image.shape[0] * image.shape[1])
    min_marker_area = max(120.0, image_area * 0.00018)
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_marker_area or area > 2500:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        circularity = 4 * math.pi * area / (perimeter * perimeter)
        x, y, w, h = [float(value) for value in cv2.boundingRect(contour)]
        aspect = w / max(h, 1)
        if w < 18 or h < 18:
            continue
        if circularity < 0.25 or not (0.45 <= aspect <= 2.2):
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
    return sorted(candidates, key=lambda row: (row["y"], row["x"]))[:150]


def _nodes_from_candidates(candidates: list[dict[str, float]]) -> list[dict[str, float]]:
    return [
        {
            "id": f"N{index + 1}",
            "x": float(candidate["x"]),
            "y": float(candidate["y"]),
            "hits": 1,
        }
        for index, candidate in enumerate(candidates)
        if "x" in candidate and "y" in candidate
    ]


def _merge_symbol_nodes_and_pipe_endpoints(
    candidates: list[dict[str, float]],
    line_segments: list[dict[str, float]],
    *,
    tolerance_px: float,
    min_endpoint_line_length: float,
) -> list[dict[str, float]]:
    nodes = _nodes_from_candidates(candidates)
    for line in line_segments:
        if float(line.get("length_px", 0.0)) < min_endpoint_line_length:
            continue
        for x_key, y_key in [("x1", "y1"), ("x2", "y2")]:
            x = float(line[x_key])
            y = float(line[y_key])
            match = _nearest_node(nodes, x, y, tolerance_px * 2.8)
            if match is None:
                nodes.append({"id": f"N{len(nodes) + 1}", "x": x, "y": y, "hits": 1})
            else:
                match["hits"] = int(float(match["hits"]) + 1)
    return [
        {"id": f"N{index + 1}", "x": round(float(node["x"]), 2), "y": round(float(node["y"]), 2), "hits": int(node.get("hits", 1))}
        for index, node in enumerate(nodes)
    ]


def _dedupe_line_segments(
    line_segments: list[dict[str, float]],
    tolerance_px: float,
) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for segment in sorted(line_segments, key=lambda row: row["length_px"], reverse=True):
        if any(_similar_line_segment(existing, segment, tolerance_px) for existing in merged):
            continue
        copied = dict(segment)
        copied["id"] = f"L{len(merged) + 1}"
        merged.append(copied)
        if len(merged) >= 300:
            break
    return merged


def _similar_line_segment(a: dict[str, float], b: dict[str, float], tolerance_px: float) -> bool:
    angle_delta = abs(((float(a["angle_deg"]) - float(b["angle_deg"]) + 90) % 180) - 90)
    if angle_delta > 8:
        return False
    ax1, ay1, ax2, ay2 = float(a["x1"]), float(a["y1"]), float(a["x2"]), float(a["y2"])
    bx1, by1, bx2, by2 = float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])
    distance = _point_to_line_distance((bx1 + bx2) / 2, (by1 + by2) / 2, ax1, ay1, ax2, ay2)
    if distance > max(tolerance_px, 10):
        return False
    return _projected_ranges_overlap((ax1, ay1), (ax2, ay2), (bx1, by1), (bx2, by2), tolerance_px)


def _projected_ranges_overlap(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
    tolerance_px: float,
) -> bool:
    dx = a2[0] - a1[0]
    dy = a2[1] - a1[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return False
    ux, uy = dx / length, dy / length
    a_range = sorted([0.0, length])
    b_range = sorted([
        (b1[0] - a1[0]) * ux + (b1[1] - a1[1]) * uy,
        (b2[0] - a1[0]) * ux + (b2[1] - a1[1]) * uy,
    ])
    return max(a_range[0], b_range[0]) <= min(a_range[1], b_range[1]) + tolerance_px


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


def _pipes_from_colored_mask(
    pipe_mask: np.ndarray,
    nodes: list[dict[str, float]],
    *,
    max_pair_distance_px: float,
) -> list[dict[str, Any]]:
    pipes: list[dict[str, Any]] = []
    if len(nodes) < 2:
        return pipes
    ordered_nodes = sorted(nodes, key=lambda node: (float(node["y"]), float(node["x"])))
    for index, start in enumerate(ordered_nodes):
        for end in ordered_nodes[index + 1 :]:
            distance = math.hypot(float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"]))
            if distance < 20 or distance > max_pair_distance_px:
                continue
            if _has_intermediate_node(start, end, ordered_nodes):
                continue
            coverage = _mask_line_coverage(pipe_mask, start, end)
            if coverage < 0.52:
                continue
            angle = math.degrees(math.atan2(float(end["y"]) - float(start["y"]), float(end["x"]) - float(start["x"])))
            pipes.append(
                {
                    "id": f"P_IMG_{len(pipes) + 1}",
                    "from_node": start["id"],
                    "to_node": end["id"],
                    "source_line": f"COLOR_{len(pipes) + 1}",
                    "length_px": round(distance, 2),
                    "angle_deg": round(angle, 2),
                }
            )
    return pipes


def _line_segments_from_pipe_candidates(
    pipe_candidates: list[dict[str, Any]],
    nodes: list[dict[str, float]],
) -> list[dict[str, float]]:
    node_by_id = {str(node["id"]): node for node in nodes}
    line_segments: list[dict[str, float]] = []
    for pipe in pipe_candidates:
        start = node_by_id.get(str(pipe.get("from_node", "")))
        end = node_by_id.get(str(pipe.get("to_node", "")))
        if not start or not end:
            continue
        x1, y1 = float(start["x"]), float(start["y"])
        x2, y2 = float(end["x"]), float(end["y"])
        line_segments.append(
            {
                "id": str(pipe.get("source_line") or f"COLOR_{len(line_segments) + 1}"),
                "x1": round(x1, 2),
                "y1": round(y1, 2),
                "x2": round(x2, 2),
                "y2": round(y2, 2),
                "length_px": float(pipe.get("length_px", math.hypot(x2 - x1, y2 - y1))),
                "angle_deg": float(pipe.get("angle_deg", math.degrees(math.atan2(y2 - y1, x2 - x1)))),
            }
        )
    return line_segments


def _has_intermediate_node(
    start: dict[str, float],
    end: dict[str, float],
    nodes: list[dict[str, float]],
) -> bool:
    sx, sy = float(start["x"]), float(start["y"])
    ex, ey = float(end["x"]), float(end["y"])
    length = math.hypot(ex - sx, ey - sy)
    if length <= 0:
        return False
    for node in nodes:
        if node["id"] in {start["id"], end["id"]}:
            continue
        nx, ny = float(node["x"]), float(node["y"])
        projection = ((nx - sx) * (ex - sx) + (ny - sy) * (ey - sy)) / (length * length)
        if not (0.12 <= projection <= 0.88):
            continue
        if _point_to_line_distance(nx, ny, sx, sy, ex, ey) <= 32:
            return True
    return False


def _mask_line_coverage(
    pipe_mask: np.ndarray,
    start: dict[str, float],
    end: dict[str, float],
    *,
    corridor_px: int = 8,
) -> float:
    height, width = pipe_mask.shape[:2]
    sx, sy = float(start["x"]), float(start["y"])
    ex, ey = float(end["x"]), float(end["y"])
    sample_count = max(24, int(math.hypot(ex - sx, ey - sy) / 3))
    hits = 0
    checked = 0
    for index in range(sample_count + 1):
        t = index / sample_count
        x = int(round(sx + (ex - sx) * t))
        y = int(round(sy + (ey - sy) * t))
        if not (0 <= x < width and 0 <= y < height):
            continue
        checked += 1
        x1, x2 = max(0, x - corridor_px), min(width, x + corridor_px + 1)
        y1, y2 = max(0, y - corridor_px), min(height, y + corridor_px + 1)
        if np.any(pipe_mask[y1:y2, x1:x2] > 0):
            hits += 1
    return hits / max(checked, 1)


def _point_to_line_distance(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 0:
        return math.hypot(px - x1, py - y1)
    return abs((y2 - y1) * px - (x2 - x1) * py + x2 * y1 - y2 * x1) / length


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
