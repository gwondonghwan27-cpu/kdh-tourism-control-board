"""Recognize water-network drawing features from image, PDF, and CAD files.

The recognizer first routes each upload by file type. Image files use Gemini
semantic hints plus deterministic geometry candidates, vector PDFs/CAD files
prefer native geometry extraction, and scanned PDFs can fall back to the image
route when a PDF renderer is available.
"""

from __future__ import annotations

import json
import heapq
import math
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


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
MAX_USER_PIPE_SAMPLES = 100
MAX_USER_JUNCTION_ANCHORS = 100
LOW_CONFIDENCE_THRESHOLD = 0.55


class RecognitionBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x1: float
    y1: float
    x2: float
    y2: float


class EvidenceField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    bbox: RecognitionBBox | None = None
    source_text: str | None = None
    is_inferred: bool = False
    needs_review: bool = False


class SemanticAssetHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    asset_type: Literal["junction", "pipe", "valve", "pump", "reservoir", "label", "unknown"] = "unknown"
    bbox: RecognitionBBox | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_text: str | None = None
    is_inferred: bool = False
    needs_review: bool = False


class SemanticPipeHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    from_label: str | None = None
    to_label: str | None = None
    bbox: RecognitionBBox | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_text: str | None = None
    is_inferred: bool = False
    needs_review: bool = False


class WaterNetworkExtraction(BaseModel):
    """Structured Gemini output for water-network drawing hints."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["water_network_extract_v1"] = "water_network_extract_v1"
    drawing_type: Literal["water_network", "unknown"] = "unknown"
    scale: EvidenceField = Field(default_factory=EvidenceField)
    unit: EvidenceField = Field(default_factory=EvidenceField)
    junctions: list[SemanticAssetHint] = Field(default_factory=list)
    pipes: list[SemanticPipeHint] = Field(default_factory=list)
    valves: list[SemanticAssetHint] = Field(default_factory=list)
    pumps: list[SemanticAssetHint] = Field(default_factory=list)
    reservoirs: list[SemanticAssetHint] = Field(default_factory=list)
    labels: list[SemanticAssetHint] = Field(default_factory=list)
    legend: list[EvidenceField] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


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
    pumps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "pipes": self.pipes,
            "reservoirs": self.reservoirs,
            "pumps": self.pumps,
            "warnings": self.warnings,
        }


def analyze_drawing_image(
    image_bytes: bytes,
    mime_type: str,
    *,
    min_line_length: int = 35,
    merge_tolerance_px: float = 16.0,
    pipe_style_samples: list[dict[str, float]] | None = None,
    pipe_candidate_samples: list[dict[str, float]] | None = None,
    junction_anchor_samples: list[dict[str, float]] | None = None,
    source_pump_candidate_samples: list[dict[str, float]] | None = None,
) -> OpenCVRecognitionResult:
    """Decode a JPG/PNG drawing through a pipe-style mask and skeleton graph route."""

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
    text_mask = _detect_text_like_mask(cv2, gray, threshold)
    grid_mask = _detect_light_grid_mask(cv2, gray)
    base_nuisance_mask = cv2.bitwise_or(text_mask, grid_mask)
    pipe_style = _estimate_pipe_style(
        cv2,
        image,
        gray,
        threshold,
        base_nuisance_mask,
        [],
    )
    road_mask = (
        _detect_background_band_mask(cv2, image, gray)
        if str(pipe_style.get("mode", "")).startswith(("sample_color", "auto_color"))
        else np.zeros_like(gray, dtype=np.uint8)
    )
    nuisance_mask = cv2.bitwise_or(base_nuisance_mask, road_mask)
    pipe_mask = _build_pipe_style_mask(
        cv2,
        image,
        gray,
        threshold,
        nuisance_mask,
        pipe_style,
        min_line_length=max(10, min_line_length),
    )
    edges = _skeletonize_mask(cv2, pipe_mask)
    color_node_candidates = _detect_colored_node_candidates(cv2, image)
    generic_node_candidates = _detect_node_candidates(cv2, cv2.bitwise_and(threshold, cv2.bitwise_not(nuisance_mask)))
    symbol_candidates = color_node_candidates if len(color_node_candidates) >= 3 else generic_node_candidates
    junction_anchors = _normalize_junction_anchor_samples(junction_anchor_samples or [], width, height)
    pipe_guides = _normalize_pipe_candidate_samples(pipe_candidate_samples or pipe_style_samples or [], width, height)
    if len(junction_anchors) >= 2:
        line_segments, merged_nodes, pipe_candidates = _anchor_graph_from_junction_samples(
            cv2,
            pipe_mask,
            junction_anchors,
            min_line_length=max(10, min_line_length),
            merge_tolerance_px=merge_tolerance_px,
        )
    else:
        line_segments, merged_nodes, pipe_candidates = _style_mask_graph_from_mask(
            cv2,
            pipe_mask,
            symbol_candidates,
            min_line_length=max(10, min_line_length),
            merge_tolerance_px=merge_tolerance_px,
            text_mask=text_mask,
        )
    pipe_candidates = _reinforce_pipes_from_pipe_candidates(
        cv2,
        pipe_mask,
        merged_nodes,
        pipe_candidates,
        pipe_guides,
        min_line_length=max(10, min_line_length),
        merge_tolerance_px=merge_tolerance_px,
    )
    if pipe_guides:
        merged_nodes = _mark_pipe_endpoint_hits(merged_nodes, pipe_candidates)
        line_segments = _line_segments_from_pipe_candidates(pipe_candidates, merged_nodes)
    node_candidates = symbol_candidates if symbol_candidates else merged_nodes
    overlay = _draw_overlay(cv2, image, line_segments, node_candidates, pipe_candidates)
    dashboard_assets = build_dashboard_assets_from_candidates(
        merged_nodes,
        pipe_candidates,
        image_width=width,
        image_height=height,
        source_pump_candidate_samples=source_pump_candidate_samples,
    )
    quality_report = validate_recognition_quality(
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
            "low_confidence_pipes": [
                pipe for pipe in pipe_candidates if float(pipe.get("confidence", 1.0)) < LOW_CONFIDENCE_THRESHOLD
            ],
            "quality_report": quality_report,
            "text_regions": _contours_to_regions(cv2, text_mask),
            "style_regions": {
                "pipe_style": pipe_style,
                "pipe_samples": pipe_guides,
                "pipe_candidate_samples": pipe_guides,
                "junction_samples": junction_anchors,
                "source_pump_samples": _normalize_source_pump_candidate_samples(source_pump_candidate_samples or [], width, height),
                "grid_regions": _contours_to_regions(cv2, grid_mask)[:80],
                "road_regions": _contours_to_regions(cv2, road_mask)[:80],
            },
            "semantic_hints": {
                "source": "gemini_pending",
                "items": [],
                "pipeline": "junction_anchor_pipe_path_graph" if len(junction_anchors) >= 2 else "pipe_style_mask_centerline_graph",
                "pipe_style": pipe_style,
                "junction_anchor_count": len(junction_anchors),
                "pipe_candidate_count": len(pipe_guides),
            },
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
            "quality_report": validate_recognition_quality(
                nodes,
                pipes,
                image_width=max(width, 1),
                image_height=max(height, 1),
            ),
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
    source_pump_candidate_samples: list[dict[str, float]] | None = None,
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
            source_pump_candidate_samples=source_pump_candidate_samples,
        )
        if rendered:
            rendered_result, render_warnings = rendered
            warnings.extend(render_warnings)
            payload = json.loads(rendered_result.binary_payload.decode("utf-8"))
            assets = build_dashboard_assets_from_recognition(
                rendered_result,
                source_pump_candidate_samples=source_pump_candidate_samples,
            )
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
                    "quality_report": payload.get("quality_report")
                    or validate_recognition_quality(
                        payload.get("nodes", []),
                        payload.get("pipes", []),
                        image_width=rendered_result.width,
                        image_height=rendered_result.height,
                    ),
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
        source_pump_candidate_samples=source_pump_candidate_samples,
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
            "quality_report": validate_recognition_quality(
                nodes,
                pipes,
                image_width=max(width, 1),
                image_height=max(height, 1),
            ),
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
    pipe_style_samples: list[dict[str, float]] | None = None,
    pipe_candidate_samples: list[dict[str, float]] | None = None,
    junction_anchor_samples: list[dict[str, float]] | None = None,
    source_pump_candidate_samples: list[dict[str, float]] | None = None,
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
            pipe_style_samples=pipe_style_samples,
            pipe_candidate_samples=pipe_candidate_samples,
            junction_anchor_samples=junction_anchor_samples,
            source_pump_candidate_samples=source_pump_candidate_samples,
        )
    if drawing_file_type == "pdf":
        return drawing_file_type, analyze_drawing_pdf(
            file_bytes,
            filename=filename,
            mime_type=mime_type or "application/pdf",
            min_line_length=min_line_length,
            merge_tolerance_px=merge_tolerance_px,
            source_pump_candidate_samples=source_pump_candidate_samples,
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
    source_pump_candidate_samples: list[dict[str, float]] | None = None,
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
        source_pump_candidate_samples=source_pump_candidate_samples
        or payload.get("style_regions", {}).get("source_pump_samples", []),
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
    source_pump_candidate_samples: list[dict[str, float]] | None = None,
) -> DashboardAssetExport:
    """Build the CSV-shaped node/pipe records used by the HTML dashboard."""

    safe_scale = max(float(scale_m_per_px), 0.001)
    export_pipes = [pipe for pipe in pipes if float(pipe.get("confidence", 1.0)) >= LOW_CONFIDENCE_THRESHOLD]
    used_node_ids = {
        str(pipe.get(key, ""))
        for pipe in export_pipes
        for key in ["from_node", "to_node"]
        if pipe.get(key)
    }
    export_nodes = [node for node in nodes if str(node.get("id", "")) in used_node_ids] if used_node_ids else list(nodes)
    node_id_by_candidate = {str(node["id"]): f"J_IMG_{index + 1}" for index, node in enumerate(export_nodes)}
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
        for node in export_nodes
        if "id" in node and "x" in node and "y" in node
    ]

    warnings: list[str] = []
    dashboard_pipes: list[dict[str, Any]] = []
    for pipe in pipes:
        if float(pipe.get("confidence", 1.0)) < LOW_CONFIDENCE_THRESHOLD:
            warnings.append(f"{pipe.get('id', 'unknown')} is a low-confidence pipe candidate and was not auto-exported.")
            continue
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
                "geometry_type": str(pipe.get("geometry_type", "straight")),
                "geometry_m": _dashboard_pipe_geometry(pipe, image_height=image_height, scale_m_per_px=safe_scale),
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

    source_samples = _normalize_source_pump_candidate_samples(
        source_pump_candidate_samples or [],
        image_width,
        image_height,
    )
    source_sample = source_samples[0] if source_samples else None
    source_candidate_id = (
        _nearest_node_id_to_sample(export_nodes, source_sample)
        if source_sample
        else _select_source_candidate_id(export_nodes, export_pipes)
    )
    reservoirs: list[dict[str, Any]] = []
    pumps: list[dict[str, Any]] = []
    if include_virtual_reservoir and dashboard_nodes:
        source_node = next(
            (
                node
                for node in dashboard_nodes
                if node["node_id"] == node_id_by_candidate.get(str(source_candidate_id))
            ),
            min(dashboard_nodes, key=lambda node: float(node["x"])),
        )
        reservoir_x = (
            round(float(source_sample["x"]) * safe_scale, 2)
            if source_sample
            else round(float(source_node["x"]) - 80 * safe_scale, 2)
        )
        reservoir_y = (
            round((float(image_height) - float(source_sample["y"])) * safe_scale, 2)
            if source_sample
            else source_node["y"]
        )
        reservoir_node = {
            "node_id": "R_IMG_1",
            "x": reservoir_x,
            "y": reservoir_y,
            "elevation_m": float(default_elevation_m) + 5.0,
            "base_demand_lps": 0.0,
            "node_type": "reservoir",
            "dma_id": "SOURCE",
        }
        dashboard_nodes.insert(0, reservoir_node)
        reservoirs.append({"node_id": "R_IMG_1", "head_m": 58.0})
        pumps.append(
            {
                "pump_id": "PU_IMG_1",
                "from_node": "R_IMG_1",
                "to_node": source_node["node_id"],
                "base_head_gain_m": 3.0,
                "speed_multiplier": 1.0,
                "status": "on",
            }
        )
        dashboard_pipes.insert(
            0,
            {
                "pipe_id": "P_IMG_SOURCE",
                "from_node": "R_IMG_1",
                "to_node": source_node["node_id"],
                "length_m": round(_dashboard_node_distance(reservoir_node, source_node), 2),
                "geometry_type": "straight",
                "geometry_m": [],
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
        if source_sample:
            warnings.append("A user-selected Source/Pump candidate was used for the source location.")
        else:
            warnings.append("A virtual reservoir and source pipe were added for dashboard preview.")

    if not dashboard_nodes:
        warnings.append("No dashboard nodes were created from the drawing.")
    if not dashboard_pipes:
        warnings.append("No dashboard pipes were created from the drawing.")

    return DashboardAssetExport(
        nodes=dashboard_nodes,
        pipes=dashboard_pipes,
        reservoirs=reservoirs,
        pumps=pumps,
        warnings=warnings,
    )


def _dashboard_pipe_geometry(
    pipe: dict[str, Any],
    *,
    image_height: int,
    scale_m_per_px: float,
) -> list[dict[str, float]]:
    points = [
        point
        for point in pipe.get("polyline_px", [])
        if isinstance(point, dict) and "x" in point and "y" in point
    ]
    if len(points) < 2:
        return []
    return [
        {
            "x": round(float(point["x"]) * scale_m_per_px, 2),
            "y": round((float(image_height) - float(point["y"])) * scale_m_per_px, 2),
        }
        for point in points
    ]


def validate_recognition_quality(
    nodes: list[dict[str, Any]],
    pipes: list[dict[str, Any]],
    *,
    image_width: int,
    image_height: int,
    semantic_hints: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic review flags for recognized water-network topology."""

    review_items: list[dict[str, Any]] = []
    warnings: list[str] = []
    node_ids = {str(node.get("id", "")) for node in nodes if node.get("id")}
    used_node_ids: set[str] = set()
    pipe_pairs: set[tuple[str, str]] = set()
    confidence_values: list[float] = []

    if not nodes:
        warnings.append("No junction/node candidates were recognized.")
        review_items.append({"kind": "topology", "target": "nodes", "reason": "no_nodes"})
    if not pipes:
        warnings.append("No pipe candidates were recognized.")
        review_items.append({"kind": "topology", "target": "pipes", "reason": "no_pipes"})

    for node in nodes:
        node_id = str(node.get("id", "unknown"))
        try:
            x = float(node.get("x"))
            y = float(node.get("y"))
        except (TypeError, ValueError):
            review_items.append({"kind": "node", "target": node_id, "reason": "invalid_coordinate"})
            continue
        if not (0 <= x <= image_width and 0 <= y <= image_height):
            review_items.append({"kind": "node", "target": node_id, "reason": "coordinate_out_of_bounds"})

    for pipe in pipes:
        pipe_id = str(pipe.get("id", "unknown"))
        start = str(pipe.get("from_node", ""))
        end = str(pipe.get("to_node", ""))
        if start:
            used_node_ids.add(start)
        if end:
            used_node_ids.add(end)
        try:
            confidence = float(pipe.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence_values.append(confidence)

        if confidence < LOW_CONFIDENCE_THRESHOLD:
            review_items.append(
                {
                    "kind": "pipe",
                    "target": pipe_id,
                    "reason": "low_confidence",
                    "confidence": round(confidence, 3),
                }
            )
        if not start or not end or start == end:
            review_items.append({"kind": "pipe", "target": pipe_id, "reason": "invalid_endpoint"})
        elif start not in node_ids or end not in node_ids:
            review_items.append({"kind": "pipe", "target": pipe_id, "reason": "endpoint_missing_node"})
        pair = tuple(sorted((start, end)))
        if start and end and pair in pipe_pairs:
            review_items.append({"kind": "pipe", "target": pipe_id, "reason": "duplicate_connection"})
        pipe_pairs.add(pair)
        try:
            if float(pipe.get("length_px", 0.0)) <= 8.0:
                review_items.append({"kind": "pipe", "target": pipe_id, "reason": "too_short"})
        except (TypeError, ValueError):
            review_items.append({"kind": "pipe", "target": pipe_id, "reason": "invalid_length"})

    isolated_nodes = sorted(node_ids - used_node_ids)
    for node_id in isolated_nodes[:25]:
        review_items.append({"kind": "node", "target": node_id, "reason": "isolated_node"})
    if len(isolated_nodes) > 25:
        review_items.append(
            {
                "kind": "node",
                "target": "isolated_nodes",
                "reason": "many_isolated_nodes",
                "count": len(isolated_nodes),
            }
        )

    semantic_review_count = _semantic_needs_review_count(semantic_hints)
    if semantic_review_count:
        review_items.append(
            {
                "kind": "semantic",
                "target": "gemini",
                "reason": "semantic_hints_need_review",
                "count": semantic_review_count,
            }
        )

    warning_reasons = {str(item["reason"]) for item in review_items}
    if "low_confidence" in warning_reasons:
        warnings.append("Some pipe candidates are below the auto-export confidence threshold.")
    if "isolated_node" in warning_reasons or "many_isolated_nodes" in warning_reasons:
        warnings.append("Some recognized nodes are not connected to any exported pipe.")
    if "endpoint_missing_node" in warning_reasons:
        warnings.append("Some pipe endpoints do not map back to recognized nodes.")

    low_confidence_count = sum(1 for value in confidence_values if value < LOW_CONFIDENCE_THRESHOLD)
    auto_pipe_count = len(confidence_values) - low_confidence_count
    hard_error_reasons = {"endpoint_missing_node", "invalid_endpoint", "invalid_coordinate"}
    return {
        "schema_version": "recognition_quality_v1",
        "image": {"width": image_width, "height": image_height},
        "counts": {
            "nodes": len(nodes),
            "pipes": len(pipes),
            "auto_pipes": auto_pipe_count,
            "review_pipes": low_confidence_count,
            "review_items": len(review_items),
        },
        "confidence": {
            "min": round(min(confidence_values), 3) if confidence_values else None,
            "avg": round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None,
            "threshold": LOW_CONFIDENCE_THRESHOLD,
        },
        "can_auto_apply": bool(
            nodes
            and auto_pipe_count
            and not any(item["reason"] in hard_error_reasons for item in review_items)
        ),
        "review_items": review_items,
        "warnings": warnings,
    }


def semantic_samples_from_gemini(
    parsed_json: dict[str, Any] | list[Any] | None,
    *,
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """Convert structured Gemini bbox hints into OpenCV anchor/sample inputs."""

    if not isinstance(parsed_json, dict):
        return {"junction_anchor_samples": [], "pipe_candidate_samples": [], "source_pump_candidate_samples": [], "review_regions": []}

    normalized = _normalize_water_network_extraction(parsed_json)
    if normalized is None:
        normalized = _legacy_gemini_hints_to_water_network(parsed_json)
    if normalized is None:
        return {"junction_anchor_samples": [], "pipe_candidate_samples": [], "source_pump_candidate_samples": [], "review_regions": []}

    junction_samples = [
        sample
        for item in normalized.get("junctions", [])
        if (sample := _sample_from_semantic_bbox(item, image_width=image_width, image_height=image_height)) is not None
        and float(item.get("confidence", 0.0)) >= 0.45
    ][:MAX_USER_JUNCTION_ANCHORS]
    pipe_samples = [
        sample
        for item in normalized.get("pipes", [])
        if (sample := _sample_from_semantic_bbox(item, image_width=image_width, image_height=image_height)) is not None
        and float(item.get("confidence", 0.0)) >= 0.35
    ][:MAX_USER_PIPE_SAMPLES]
    source_samples = [
        sample
        for item in [*normalized.get("reservoirs", []), *normalized.get("pumps", [])]
        if (sample := _sample_from_semantic_bbox(item, image_width=image_width, image_height=image_height)) is not None
        and float(item.get("confidence", 0.0)) >= 0.35
    ][:MAX_USER_PIPE_SAMPLES]
    review_regions = [
        {
            "asset_type": str(item.get("asset_type", "pipe")),
            "label": item.get("label"),
            "bbox": item.get("bbox"),
            "confidence": item.get("confidence", 0.0),
            "reason": "semantic_needs_review" if item.get("needs_review") else "low_semantic_confidence",
        }
        for item in [
            *normalized.get("junctions", []),
            *normalized.get("pipes", []),
            *normalized.get("valves", []),
            *normalized.get("pumps", []),
            *normalized.get("reservoirs", []),
        ]
        if item.get("needs_review") or float(item.get("confidence", 0.0)) < 0.5
    ][:80]
    return {
        "junction_anchor_samples": junction_samples,
        "pipe_candidate_samples": pipe_samples,
        "source_pump_candidate_samples": source_samples,
        "review_regions": review_regions,
        "normalized_schema": normalized,
    }


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


def _normalize_source_pump_candidate_samples(
    samples: list[dict[str, float]],
    width: int,
    height: int,
) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for index, sample in enumerate(_normalize_pipe_style_samples(samples, width, height), 1):
        candidate = dict(sample)
        candidate["id"] = f"SP{index}"
        candidate["source"] = str(sample.get("source", "user_source_pump_candidate"))
        normalized.append(candidate)
    return normalized


def _nearest_node_id_to_sample(nodes: list[dict[str, Any]], sample: dict[str, float] | None) -> str | None:
    if not nodes or sample is None:
        return None
    sx, sy = float(sample["x"]), float(sample["y"])
    nearest = min(
        nodes,
        key=lambda node: math.hypot(float(node.get("x", 0.0)) - sx, float(node.get("y", 0.0)) - sy),
    )
    return str(nearest.get("id")) if nearest.get("id") else None


def _dashboard_node_distance(first: dict[str, Any], second: dict[str, Any]) -> float:
    return math.hypot(
        float(first.get("x", 0.0)) - float(second.get("x", 0.0)),
        float(first.get("y", 0.0)) - float(second.get("y", 0.0)),
    )


def call_gemini_vision(
    image_bytes: bytes,
    mime_type: str,
    *,
    api_key: str | None = None,
    model: str = "gemini-3-flash-preview",
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

Rules:
- Return only JSON that matches the provided schema.
- Do not guess missing values.
- Use null when a value is unreadable.
- Every visible asset should include confidence and bbox evidence.
- bbox coordinates must use image pixel coordinates when possible.
- Mark needs_review=true when an item is blurred, partially hidden, inferred, or ambiguous.
- Prefer visible labels and visual evidence over assumptions.
"""
    try:
        client = genai.Client(api_key=api_key)
        config = _gemini_structured_config(types)
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt or default_prompt,
            ],
            config=config,
        )
        raw_text = str(getattr(response, "text", "") or "")
        parsed = _parse_json_response(raw_text)
        normalized = _normalize_water_network_extraction(parsed) if isinstance(parsed, dict) else None
        return GeminiVisionResult(
            model=model,
            raw_text=raw_text,
            parsed_json=normalized or parsed,
        )
    except Exception as exc:  # pragma: no cover - network/API runtime path
        return GeminiVisionResult(model=model, raw_text="", error=str(exc))


def _gemini_structured_config(types: Any) -> Any:
    schema = WaterNetworkExtraction.model_json_schema()
    kwargs: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_json_schema": schema,
    }
    media_resolution = getattr(types, "MediaResolution", None)
    if media_resolution is not None:
        high_resolution = getattr(media_resolution, "MEDIA_RESOLUTION_HIGH", None)
        if high_resolution is not None:
            kwargs["media_resolution"] = high_resolution
    thinking_config = getattr(types, "ThinkingConfig", None)
    if thinking_config is not None:
        try:
            kwargs["thinking_config"] = thinking_config(thinking_level="medium")
        except TypeError:
            pass
    try:
        return types.GenerateContentConfig(**kwargs)
    except TypeError:
        kwargs.pop("response_json_schema", None)
        return types.GenerateContentConfig(**kwargs)


def _normalize_water_network_extraction(parsed_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(parsed_json, dict):
        return None
    try:
        return WaterNetworkExtraction.model_validate(parsed_json).model_dump(mode="json")
    except Exception:
        return None


def _legacy_gemini_hints_to_water_network(parsed_json: dict[str, Any]) -> dict[str, Any] | None:
    detected_assets = parsed_json.get("detected_assets")
    if not isinstance(detected_assets, dict):
        return None

    def legacy_assets(key: str, asset_type: str) -> list[dict[str, Any]]:
        items = detected_assets.get(key)
        if not isinstance(items, list):
            return []
        converted: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            converted.append(
                {
                    "label": item.get("label"),
                    "asset_type": asset_type,
                    "bbox": _bbox_from_any(item.get("bbox") or item.get("box_2d")),
                    "confidence": _clamp_confidence(item.get("confidence", 0.0)),
                    "source_text": item.get("source_text"),
                    "is_inferred": bool(item.get("is_inferred", False)),
                    "needs_review": bool(item.get("needs_review", False)),
                }
            )
        return converted

    pipes = []
    connection_hints = parsed_json.get("connection_hints", [])
    if isinstance(connection_hints, list):
        for item in connection_hints:
            if not isinstance(item, dict):
                continue
            pipes.append(
                {
                    "label": item.get("label"),
                    "from_label": item.get("from"),
                    "to_label": item.get("to"),
                    "bbox": _bbox_from_any(item.get("bbox") or item.get("box_2d")),
                    "confidence": _clamp_confidence(item.get("confidence", 0.0)),
                    "source_text": item.get("evidence"),
                    "is_inferred": bool(item.get("is_inferred", True)),
                    "needs_review": bool(item.get("needs_review", True)),
                }
            )

    return {
        "schema_version": "water_network_extract_v1",
        "drawing_type": "water_network"
        if parsed_json.get("drawing_type") in {"water_network", "water_network_drawing"}
        else "unknown",
        "scale": EvidenceField().model_dump(mode="json"),
        "unit": EvidenceField().model_dump(mode="json"),
        "junctions": legacy_assets("junctions", "junction"),
        "pipes": pipes,
        "valves": legacy_assets("valves", "valve"),
        "pumps": legacy_assets("pumps", "pump"),
        "reservoirs": legacy_assets("reservoirs", "reservoir"),
        "labels": legacy_assets("text_labels", "label"),
        "legend": [],
        "ambiguities": [
            str(item)
            for item in parsed_json.get("risks_or_ambiguities", [])
            if isinstance(item, (str, int, float))
        ],
    }


def _sample_from_semantic_bbox(
    item: dict[str, Any],
    *,
    image_width: int,
    image_height: int,
) -> dict[str, float] | None:
    bbox = _bbox_from_any(item.get("bbox") or item.get("box_2d"))
    if bbox is None:
        return None
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
    if max(x1, y1, x2, y2) <= 1000 and (x2 > image_width or y2 > image_height):
        x1, x2 = x1 / 1000.0 * image_width, x2 / 1000.0 * image_width
        y1, y2 = y1 / 1000.0 * image_height, y2 / 1000.0 * image_height
    x = (x1 + x2) / 2
    y = (y1 + y2) / 2
    if not (0 <= x <= image_width and 0 <= y <= image_height):
        return None
    radius = max(8.0, min(32.0, max(abs(x2 - x1), abs(y2 - y1)) / 2.0))
    return {
        "x": round(float(x), 2),
        "y": round(float(y), 2),
        "radius_px": round(float(radius), 2),
        "source": "gemini_semantic_bbox",
        "confidence": round(_clamp_confidence(item.get("confidence", 0.0)), 3),
    }


def _bbox_from_any(value: Any) -> dict[str, float] | None:
    if isinstance(value, RecognitionBBox):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        try:
            return {
                "x1": float(value["x1"]),
                "y1": float(value["y1"]),
                "x2": float(value["x2"]),
                "y2": float(value["y2"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, list) and len(value) == 4:
        try:
            x1, y1, x2, y2 = [float(item) for item in value]
        except (TypeError, ValueError):
            return None
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
    return None


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.0
    return min(1.0, max(0.0, confidence))


def _semantic_needs_review_count(semantic_hints: dict[str, Any] | list[Any] | None) -> int:
    if not isinstance(semantic_hints, dict):
        return 0
    normalized = _normalize_water_network_extraction(semantic_hints)
    if normalized is None:
        normalized = _legacy_gemini_hints_to_water_network(semantic_hints)
    if normalized is None:
        return 0
    count = 0
    for key in ["junctions", "pipes", "valves", "pumps", "reservoirs", "labels"]:
        for item in normalized.get(key, []):
            if item.get("needs_review") or float(item.get("confidence", 0.0)) < 0.5:
                count += 1
    return count


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
        raw_segments: list[dict[str, Any]] = []
        for drawing in page.get_drawings():
            layer = str(drawing.get("layer") or "").strip()
            for item in drawing.get("items", []):
                if not item or item[0] != "l":
                    continue
                start = item[1]
                end = item[2]
                raw_segments.append(
                    {
                        "x1": float(start.x),
                        "y1": float(start.y),
                        "x2": float(end.x),
                        "y2": float(end.y),
                        "layer": layer,
                        "source_entity": "PDF_VECTOR",
                    }
                )
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
    source_pump_candidate_samples: list[dict[str, float]] | None = None,
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
            source_pump_candidate_samples=source_pump_candidate_samples,
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


def _detect_text_like_mask(cv2: Any, gray: np.ndarray, threshold: np.ndarray) -> np.ndarray:
    """Find compact text-like regions so labels do not become pipe geometry."""

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 3))
    text_blobs = cv2.morphologyEx(threshold, cv2.MORPH_CLOSE, horizontal_kernel, iterations=1)
    contours, _ = cv2.findContours(text_blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(gray, dtype=np.uint8)
    image_area = float(gray.shape[0] * gray.shape[1])
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = float(w * h)
        if area < 40 or area > image_area * 0.04:
            continue
        aspect = w / max(h, 1)
        if h <= 42 and aspect >= 1.2:
            cv2.rectangle(mask, (max(0, x - 3), max(0, y - 3)), (x + w + 3, y + h + 3), 255, -1)
    return mask


def _detect_light_grid_mask(cv2: Any, gray: np.ndarray) -> np.ndarray:
    """Remove faint drafting grids without touching darker pipe ink."""

    light_ink = cv2.inRange(gray, 176, 246)
    horizontal = cv2.morphologyEx(light_ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (38, 1)), iterations=1)
    vertical = cv2.morphologyEx(light_ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 38)), iterations=1)
    grid = cv2.bitwise_or(horizontal, vertical)
    return cv2.dilate(grid, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)


def _detect_background_band_mask(cv2: Any, image: np.ndarray, gray: np.ndarray) -> np.ndarray:
    """Mask broad roads/background bands that otherwise look like thick pipes."""

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    low_saturation = cv2.inRange(hsv[:, :, 1], 0, 58)
    mid_lightness = cv2.inRange(gray, 132, 244)
    broad_ink = cv2.bitwise_and(low_saturation, mid_lightness)
    broad_ink = cv2.morphologyEx(broad_ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)), iterations=1)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(broad_ink, 8)
    mask = np.zeros_like(gray, dtype=np.uint8)
    image_area = float(gray.shape[0] * gray.shape[1])
    for label in range(1, component_count):
        x, y, w, h, area = [float(value) for value in stats[label]]
        if area < image_area * 0.0015:
            continue
        if max(w, h) < 90 or min(w, h) < 8:
            continue
        mask[labels == label] = 255
    return cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)), iterations=1)


def _normalize_pipe_style_samples(samples: list[dict[str, float]], width: int, height: int) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for sample in samples[:MAX_USER_PIPE_SAMPLES]:
        try:
            x = float(sample.get("x", 0))
            y = float(sample.get("y", 0))
        except (TypeError, ValueError, AttributeError):
            continue
        if not (0 <= x < width and 0 <= y < height):
            continue
        normalized.append({"x": round(x, 2), "y": round(y, 2), "radius_px": float(sample.get("radius_px", 10) or 10)})
    return normalized


def _normalize_pipe_candidate_samples(samples: list[dict[str, float]], width: int, height: int) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for index, sample in enumerate(_normalize_pipe_style_samples(samples, width, height), 1):
        candidate = dict(sample)
        candidate["id"] = f"PC{index}"
        normalized.append(candidate)
    return normalized


def _normalize_junction_anchor_samples(samples: list[dict[str, float]], width: int, height: int) -> list[dict[str, float]]:
    """Normalize user-clicked Junction anchors, capped to keep pair inference bounded."""

    normalized: list[dict[str, float]] = []
    for sample in samples[:MAX_USER_JUNCTION_ANCHORS]:
        try:
            x = float(sample.get("x", 0))
            y = float(sample.get("y", 0))
        except (TypeError, ValueError, AttributeError):
            continue
        if not (0 <= x < width and 0 <= y < height):
            continue
        if any(math.hypot(float(existing["x"]) - x, float(existing["y"]) - y) < 5.0 for existing in normalized):
            continue
        normalized.append(
            {
                "id": f"N{len(normalized) + 1}",
                "x": round(x, 2),
                "y": round(y, 2),
                "hits": 1,
                "confidence": 0.92,
                "candidate_state": "auto",
                "source": "user_junction_anchor",
                "locked": True,
            }
        )
    return normalized


def _estimate_pipe_style(
    cv2: Any,
    image: np.ndarray,
    gray: np.ndarray,
    threshold: np.ndarray,
    nuisance_mask: np.ndarray,
    samples: list[dict[str, float]],
) -> dict[str, Any]:
    """Estimate the drawing's pipe ink before extracting geometry."""

    normalized_samples = _normalize_pipe_style_samples(samples, image.shape[1], image.shape[0])
    sampled = _sampled_pipe_style(cv2, image, gray, nuisance_mask, normalized_samples)
    if sampled:
        return sampled
    color_style = _auto_color_pipe_style(cv2, image, nuisance_mask)
    if color_style:
        return color_style
    return _auto_dark_pipe_style(cv2, gray, threshold, nuisance_mask)


def _sampled_pipe_style(
    cv2: Any,
    image: np.ndarray,
    gray: np.ndarray,
    nuisance_mask: np.ndarray,
    samples: list[dict[str, float]],
) -> dict[str, Any] | None:
    if not samples:
        return None
    sample_mask = np.zeros(gray.shape, dtype=np.uint8)
    for sample in samples:
        cv2.circle(sample_mask, (int(round(sample["x"])), int(round(sample["y"]))), int(max(4, sample.get("radius_px", 10))), 255, -1)
    sample_mask = cv2.bitwise_and(sample_mask, cv2.bitwise_not(nuisance_mask))
    ys, xs = np.where(sample_mask > 0)
    if len(xs) < 20:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hsv_pixels = hsv[ys, xs].astype(float)
    gray_pixels = gray[ys, xs].astype(float)
    median_saturation = float(np.median(hsv_pixels[:, 1]))
    median_value = float(np.median(hsv_pixels[:, 2]))
    stroke_width = _estimate_stroke_width_from_mask(cv2, sample_mask)
    if median_saturation >= 32:
        hue = float(np.median(hsv_pixels[:, 0]))
        return {
            "mode": "sample_color",
            "hue": round(hue, 2),
            "hue_tolerance": 14.0,
            "saturation_min": round(max(22.0, median_saturation - 75.0), 2),
            "value_min": round(max(20.0, median_value - 95.0), 2),
            "value_max": round(min(255.0, median_value + 95.0), 2),
            "stroke_width_px": stroke_width,
            "sample_count": len(samples),
        }
    return {
        "mode": "sample_dark",
        "gray_center": round(float(np.median(gray_pixels)), 2),
        "gray_tolerance": 58.0,
        "stroke_width_px": stroke_width,
        "sample_count": len(samples),
    }


def _auto_color_pipe_style(cv2: Any, image: np.ndarray, nuisance_mask: np.ndarray) -> dict[str, Any] | None:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturated = cv2.inRange(hsv[:, :, 1], 38, 255)
    not_too_bright = cv2.inRange(hsv[:, :, 2], 28, 252)
    candidate_mask = cv2.bitwise_and(cv2.bitwise_and(saturated, not_too_bright), cv2.bitwise_not(nuisance_mask))
    candidate_mask = cv2.morphologyEx(candidate_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)), iterations=1)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate_mask, 8)
    best_score = 0.0
    best_pixels: tuple[np.ndarray, np.ndarray] | None = None
    image_area = float(image.shape[0] * image.shape[1])
    for label in range(1, component_count):
        x, y, w, h, area = [float(value) for value in stats[label]]
        if area < max(42.0, image_area * 0.00004) or area > image_area * 0.08:
            continue
        long_axis = max(w, h)
        short_axis = max(1.0, min(w, h))
        if long_axis < 35 or long_axis / short_axis < 1.55:
            continue
        ys, xs = np.where(labels == label)
        median_saturation = float(np.median(hsv[ys, xs, 1]))
        score = long_axis * math.sqrt(area) * max(median_saturation, 1.0)
        if score > best_score:
            best_score = score
            best_pixels = (ys, xs)
    if best_pixels is None:
        return None
    ys, xs = best_pixels
    hue = float(np.median(hsv[ys, xs, 0]))
    saturation = float(np.median(hsv[ys, xs, 1]))
    value = float(np.median(hsv[ys, xs, 2]))
    local_mask = np.zeros(image.shape[:2], dtype=np.uint8)
    local_mask[ys, xs] = 255
    return {
        "mode": "auto_color",
        "hue": round(hue, 2),
        "hue_tolerance": 16.0,
        "saturation_min": round(max(28.0, saturation - 85.0), 2),
        "value_min": round(max(18.0, value - 105.0), 2),
        "value_max": round(min(255.0, value + 105.0), 2),
        "stroke_width_px": _estimate_stroke_width_from_mask(cv2, local_mask),
        "sample_count": 0,
    }


def _auto_dark_pipe_style(cv2: Any, gray: np.ndarray, threshold: np.ndarray, nuisance_mask: np.ndarray) -> dict[str, Any]:
    dark_mask = cv2.bitwise_and(threshold, cv2.bitwise_not(nuisance_mask))
    dark_mask = _filter_pipe_like_components(cv2, dark_mask, min_line_length=24)
    ys, xs = np.where(dark_mask > 0)
    gray_center = float(np.percentile(gray[ys, xs], 35)) if len(xs) else 80.0
    return {
        "mode": "auto_dark",
        "gray_center": round(gray_center, 2),
        "gray_tolerance": 70.0,
        "stroke_width_px": _estimate_stroke_width_from_mask(cv2, dark_mask),
        "sample_count": 0,
    }


def _build_pipe_style_mask(
    cv2: Any,
    image: np.ndarray,
    gray: np.ndarray,
    threshold: np.ndarray,
    nuisance_mask: np.ndarray,
    pipe_style: dict[str, Any],
    *,
    min_line_length: int,
) -> np.ndarray:
    mode = str(pipe_style.get("mode", "auto_dark"))
    if mode.endswith("color"):
        mask = _hsv_style_mask(cv2, image, pipe_style)
    else:
        center = float(pipe_style.get("gray_center", 80.0))
        tolerance = float(pipe_style.get("gray_tolerance", 70.0))
        lower = max(0, int(center - tolerance))
        upper = min(255, int(center + tolerance))
        mask = cv2.inRange(gray, lower, upper)
        mask = cv2.bitwise_or(mask, threshold)
    mask = cv2.bitwise_and(mask, cv2.bitwise_not(nuisance_mask))
    return _postprocess_pipe_mask(cv2, mask, pipe_style, min_line_length=min_line_length)


def _hsv_style_mask(cv2: Any, image: np.ndarray, pipe_style: dict[str, Any]) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue = float(pipe_style.get("hue", 105.0))
    hue_tolerance = float(pipe_style.get("hue_tolerance", 16.0))
    saturation_min = int(max(0, min(255, float(pipe_style.get("saturation_min", 32.0)))))
    value_min = int(max(0, min(255, float(pipe_style.get("value_min", 20.0)))))
    value_max = int(max(value_min, min(255, float(pipe_style.get("value_max", 255.0)))))
    low_hue = hue - hue_tolerance
    high_hue = hue + hue_tolerance
    if low_hue < 0:
        first = cv2.inRange(hsv, np.array([0, saturation_min, value_min]), np.array([int(high_hue), 255, value_max]))
        second = cv2.inRange(hsv, np.array([int(180 + low_hue), saturation_min, value_min]), np.array([179, 255, value_max]))
        return cv2.bitwise_or(first, second)
    if high_hue > 179:
        first = cv2.inRange(hsv, np.array([0, saturation_min, value_min]), np.array([int(high_hue - 180), 255, value_max]))
        second = cv2.inRange(hsv, np.array([int(low_hue), saturation_min, value_min]), np.array([179, 255, value_max]))
        return cv2.bitwise_or(first, second)
    return cv2.inRange(hsv, np.array([int(low_hue), saturation_min, value_min]), np.array([int(high_hue), 255, value_max]))


def _postprocess_pipe_mask(cv2: Any, mask: np.ndarray, pipe_style: dict[str, Any], *, min_line_length: int) -> np.ndarray:
    stroke = max(3, int(round(float(pipe_style.get("stroke_width_px", 7.0)))))
    close_size = max(5, min(17, stroke * 2 + 1))
    clean_size = 3 if stroke <= 7 else 5
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size)), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (clean_size, clean_size)), iterations=1)
    mask = _filter_pipe_like_components(cv2, mask, min_line_length=min_line_length)
    return cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)


def _estimate_stroke_width_from_mask(cv2: Any, mask: np.ndarray) -> float:
    if not np.count_nonzero(mask):
        return 7.0
    distance = cv2.distanceTransform(np.where(mask > 0, 255, 0).astype(np.uint8), cv2.DIST_L2, 3)
    values = distance[distance > 0]
    if values.size == 0:
        return 7.0
    return round(float(np.clip(np.percentile(values, 80) * 2.0, 3.0, 18.0)), 2)


def _contours_to_regions(cv2: Any, mask: np.ndarray) -> list[dict[str, float]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions: list[dict[str, float]] = []
    for contour in contours[:120]:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h <= 0:
            continue
        regions.append({"x": float(x), "y": float(y), "width_px": float(w), "height_px": float(h)})
    return regions


def _skeletonize_mask(cv2: Any, mask: np.ndarray) -> np.ndarray:
    binary = np.where(mask > 0, 255, 0).astype(np.uint8)
    skeleton = np.zeros(binary.shape, dtype=np.uint8)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while np.count_nonzero(binary):
        eroded = cv2.erode(binary, element)
        opened = cv2.dilate(eroded, element)
        residue = cv2.subtract(binary, opened)
        skeleton = cv2.bitwise_or(skeleton, residue)
        binary = eroded
        if np.count_nonzero(binary) > mask.size * 0.85:
            break
    return skeleton


def _filter_pipe_like_components(cv2: Any, mask: np.ndarray, *, min_line_length: int) -> np.ndarray:
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(np.where(mask > 0, 255, 0).astype(np.uint8), 8)
    filtered = np.zeros_like(mask, dtype=np.uint8)
    image_area = float(mask.shape[0] * mask.shape[1])
    for label in range(1, component_count):
        x, y, w, h, area = [float(value) for value in stats[label]]
        if area < max(18.0, min_line_length * 0.7):
            continue
        if area > image_area * 0.18:
            continue
        long_axis = max(w, h)
        short_axis = max(min(w, h), 1.0)
        if long_axis < min_line_length * 0.75:
            continue
        if long_axis / short_axis < 1.15 and area < 450:
            continue
        filtered[labels == label] = 255
    return filtered


def _style_mask_graph_from_mask(
    cv2: Any,
    mask: np.ndarray,
    symbol_candidates: list[dict[str, float]],
    *,
    min_line_length: int,
    merge_tolerance_px: float,
    text_mask: np.ndarray | None = None,
) -> tuple[list[dict[str, float]], list[dict[str, float]], list[dict[str, Any]]]:
    """Convert a pipe-style mask to graph candidates without Hough line guessing."""

    skeleton = _skeletonize_mask(cv2, mask)
    ys, xs = np.where(skeleton > 0)
    skeleton_pixels = {(int(x), int(y)) for x, y in zip(xs, ys)}
    if not skeleton_pixels:
        return [], _nodes_from_candidates(symbol_candidates), []

    line_segments = _trace_skeleton_pipe_paths(skeleton_pixels, mask, min_line_length=min_line_length, text_mask=text_mask)
    line_segments = _dedupe_line_segments(line_segments, merge_tolerance_px)
    line_segments = _split_pipe_candidates_at_intersections(line_segments, tolerance_px=merge_tolerance_px)
    line_segments = _prune_style_line_segments(line_segments, mask, text_mask, min_line_length=min_line_length)
    nodes = _junction_candidates_from_pipe_topology(
        symbol_candidates,
        line_segments,
        tolerance_px=merge_tolerance_px,
        min_endpoint_line_length=max(10.0, min_line_length * 0.65),
    )
    pipes = _pipes_from_lines(line_segments, nodes, max_endpoint_distance=merge_tolerance_px * 3.0)
    if len(pipes) < 2:
        fallback_nodes = _style_mask_fallback_nodes(skeleton_pixels, symbol_candidates, merge_tolerance_px)
        fallback_pipes = _pipes_from_mask_between_nodes(mask, fallback_nodes, min_line_length=max(10.0, min_line_length * 0.65))
        if len(fallback_pipes) > len(pipes):
            nodes = fallback_nodes
            pipes = fallback_pipes
            line_segments = _line_segments_from_pipe_candidates(pipes, nodes)
    nodes = _mark_pipe_endpoint_hits(nodes, pipes)
    for pipe in pipes:
        source_line = next((line for line in line_segments if line["id"] == pipe.get("source_line")), None)
        confidence = float(source_line.get("confidence", 0.62)) if source_line else 0.62
        pipe["confidence"] = confidence
        pipe["candidate_state"] = "auto" if confidence >= 0.6 else "review"
    nodes, pipes = _collapse_pipe_graph_to_topology(nodes, pipes)
    line_segments = _line_segments_from_pipe_candidates(pipes, nodes)
    return line_segments, nodes, pipes


def _anchor_graph_from_junction_samples(
    cv2: Any,
    mask: np.ndarray,
    junction_anchors: list[dict[str, float]],
    *,
    min_line_length: int,
    merge_tolerance_px: float,
) -> tuple[list[dict[str, float]], list[dict[str, float]], list[dict[str, Any]]]:
    """Infer Pipe candidates by tracing likely pipe paths between user-clicked Junction anchors."""

    nodes = [dict(anchor) for anchor in junction_anchors[:MAX_USER_JUNCTION_ANCHORS]]
    skeleton = _skeletonize_mask(cv2, mask)
    ys, xs = np.where(skeleton > 0)
    skeleton_pixels = {(int(x), int(y)) for x, y in zip(xs, ys)}
    if not skeleton_pixels:
        return [], nodes, []

    snap_tolerance = max(24.0, merge_tolerance_px * 3.0)
    snapped: dict[str, tuple[int, int]] = {}
    for node in nodes:
        nearest = _nearest_skeleton_pixel(skeleton_pixels, float(node["x"]), float(node["y"]), snap_tolerance)
        if nearest is not None:
            snapped[str(node["id"])] = nearest

    candidate_pairs = _anchor_candidate_pairs(nodes)
    pipes: list[dict[str, Any]] = []
    for start_index, end_index in candidate_pairs:
        start = nodes[start_index]
        end = nodes[end_index]
        direct_distance = math.hypot(float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"]))
        if direct_distance < min_line_length:
            continue
        start_pixel = snapped.get(str(start["id"]))
        end_pixel = snapped.get(str(end["id"]))
        path: list[tuple[int, int]] = []
        path_length = 0.0
        if start_pixel is not None and end_pixel is not None:
            path = _shortest_skeleton_path(
                skeleton_pixels,
                start_pixel,
                end_pixel,
                max_cost=direct_distance * 2.45 + merge_tolerance_px * 8.0,
            )
            path_length = _polyline_length(path) if path else 0.0
        if path:
            if _path_has_intermediate_anchor(path, start, end, nodes, tolerance_px=max(16.0, merge_tolerance_px * 1.25)):
                continue
            if path_length > direct_distance * 2.25 + merge_tolerance_px * 4.0:
                continue
            coverage = _mask_path_coverage(mask, path)
            confidence = min(0.97, max(0.45, 0.52 + coverage * 0.3 + min(direct_distance / 650.0, 0.1) - max(path_length / max(direct_distance, 1.0) - 1.0, 0.0) * 0.12))
            polyline = [
                {"x": float(start["x"]), "y": float(start["y"])},
                *_simplify_polyline_path(path, min_step_px=16.0),
                {"x": float(end["x"]), "y": float(end["y"])},
            ]
            length = path_length
        else:
            if _has_intermediate_node(start, end, nodes):
                continue
            coverage = _mask_line_coverage(mask, start, end, corridor_px=max(7, int(merge_tolerance_px * 0.65)))
            if coverage < 0.62:
                continue
            confidence = min(0.9, 0.42 + coverage * 0.45)
            polyline = [{"x": float(start["x"]), "y": float(start["y"])}, {"x": float(end["x"]), "y": float(end["y"])}]
            length = direct_distance
        pipes.append(
            {
                "id": f"P_IMG_{len(pipes) + 1}",
                "from_node": start["id"],
                "to_node": end["id"],
                "source_line": f"ANCHOR_{len(pipes) + 1}",
                "length_px": round(float(length), 2),
                "angle_deg": round(math.degrees(math.atan2(float(end["y"]) - float(start["y"]), float(end["x"]) - float(start["x"]))), 2),
                "confidence": round(float(confidence), 3),
                "candidate_state": "auto" if confidence >= 0.62 else "review",
                "polyline_px": polyline,
                "geometry_type": _pipe_geometry_type([(int(round(point["x"])), int(round(point["y"]))) for point in polyline]),
            }
        )

    pipes = _prune_anchor_pipe_candidates(pipes, nodes)
    nodes = _mark_pipe_endpoint_hits(nodes, pipes)
    line_segments = _line_segments_from_pipe_candidates(pipes, nodes)
    return line_segments, nodes, pipes


def _reinforce_pipes_from_pipe_candidates(
    cv2: Any,
    mask: np.ndarray,
    nodes: list[dict[str, float]],
    pipes: list[dict[str, Any]],
    pipe_samples: list[dict[str, float]],
    *,
    min_line_length: int,
    merge_tolerance_px: float,
) -> list[dict[str, Any]]:
    """Use user-clicked Pipe candidate points to add missing pipes without replacing existing recognition."""

    if not pipe_samples or len(nodes) < 2:
        return pipes

    result = [dict(pipe) for pipe in pipes]
    node_by_id = {str(node.get("id")): node for node in nodes if node.get("id") is not None}
    if len(node_by_id) < 2:
        return result

    skeleton = _skeletonize_mask(cv2, mask)
    ys, xs = np.where(skeleton > 0)
    skeleton_pixels = {(int(x), int(y)) for x, y in zip(xs, ys)}
    snap_tolerance = max(24.0, merge_tolerance_px * 3.0)
    snapped: dict[str, tuple[int, int]] = {}
    if skeleton_pixels:
        for node in nodes:
            node_id = str(node.get("id", ""))
            nearest = _nearest_skeleton_pixel(skeleton_pixels, float(node["x"]), float(node["y"]), snap_tolerance)
            if nearest is not None:
                snapped[node_id] = nearest

    for sample in pipe_samples[:MAX_USER_PIPE_SAMPLES]:
        if _pipe_sample_hits_existing_pipe(sample, result, node_by_id, tolerance_px=max(14.0, merge_tolerance_px * 1.2)):
            continue
        candidate = _best_pipe_from_candidate_sample(
            mask,
            skeleton_pixels,
            snapped,
            nodes,
            result,
            sample,
            min_line_length=min_line_length,
            merge_tolerance_px=merge_tolerance_px,
        )
        if candidate is None:
            continue
        result.append(candidate)

    return _dedupe_pipe_candidates_by_pair(result)


def _best_pipe_from_candidate_sample(
    mask: np.ndarray,
    skeleton_pixels: set[tuple[int, int]],
    snapped: dict[str, tuple[int, int]],
    nodes: list[dict[str, float]],
    existing_pipes: list[dict[str, Any]],
    sample: dict[str, float],
    *,
    min_line_length: int,
    merge_tolerance_px: float,
) -> dict[str, Any] | None:
    sample_x = float(sample["x"])
    sample_y = float(sample["y"])
    existing_pairs = {_pipe_pair_key(pipe) for pipe in existing_pipes}
    existing_pairs.discard(None)
    nearest_nodes = sorted(
        nodes,
        key=lambda node: math.hypot(float(node["x"]) - sample_x, float(node["y"]) - sample_y),
    )[: min(14, len(nodes))]
    if len(nearest_nodes) < 2:
        return None

    max_dimension = float(max(mask.shape[:2]))
    line_tolerance = max(18.0, merge_tolerance_px * 1.45)
    best: tuple[float, dict[str, Any]] | None = None
    for start_index, start in enumerate(nearest_nodes):
        for end in nearest_nodes[start_index + 1 :]:
            pair = tuple(sorted((str(start.get("id", "")), str(end.get("id", "")))))
            if pair in existing_pairs or not pair[0] or pair[0] == pair[1]:
                continue
            direct_distance = math.hypot(float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"]))
            if direct_distance < min_line_length or direct_distance > max_dimension * 0.62:
                continue
            direct_sample_distance = _point_to_segment_distance(
                sample_x,
                sample_y,
                float(start["x"]),
                float(start["y"]),
                float(end["x"]),
                float(end["y"]),
            )
            if direct_sample_distance > line_tolerance * 2.2:
                continue
            if _has_intermediate_node(start, end, nodes):
                continue

            path: list[tuple[int, int]] = []
            path_length = 0.0
            start_pixel = snapped.get(str(start.get("id", "")))
            end_pixel = snapped.get(str(end.get("id", "")))
            if skeleton_pixels and start_pixel is not None and end_pixel is not None:
                path = _shortest_skeleton_path(
                    skeleton_pixels,
                    start_pixel,
                    end_pixel,
                    max_cost=direct_distance * 2.45 + merge_tolerance_px * 8.0,
                )
                path_length = _polyline_length(path) if path else 0.0
                if path and (
                    _path_distance_to_point(path, sample_x, sample_y) > line_tolerance
                    or _path_has_intermediate_anchor(path, start, end, nodes, tolerance_px=max(16.0, merge_tolerance_px * 1.25))
                    or path_length > direct_distance * 2.25 + merge_tolerance_px * 4.0
                ):
                    path = []

            if path:
                coverage = _mask_path_coverage(mask, path)
                if coverage < 0.42:
                    path = []
                else:
                    proximity = max(0.0, 1.0 - _path_distance_to_point(path, sample_x, sample_y) / max(line_tolerance, 1.0))
                    confidence = min(
                        0.94,
                        max(
                            0.55,
                            0.5
                            + coverage * 0.32
                            + proximity * 0.12
                            - max(path_length / max(direct_distance, 1.0) - 1.0, 0.0) * 0.1,
                        ),
                    )
                    polyline = [
                        {"x": float(start["x"]), "y": float(start["y"])},
                        *_simplify_polyline_path(path, min_step_px=16.0),
                        {"x": float(end["x"]), "y": float(end["y"])},
                    ]
                    length = path_length
            if not path:
                if direct_sample_distance > line_tolerance:
                    continue
                coverage = _mask_line_coverage(mask, start, end, corridor_px=max(8, int(merge_tolerance_px * 0.75)))
                if coverage < 0.05:
                    continue
                proximity = max(0.0, 1.0 - direct_sample_distance / max(line_tolerance, 1.0))
                confidence = min(0.86, 0.47 + coverage * 0.32 + proximity * 0.12)
                if confidence < 0.55:
                    continue
                polyline = [
                    {"x": round(float(start["x"]), 2), "y": round(float(start["y"]), 2)},
                    {"x": round(float(end["x"]), 2), "y": round(float(end["y"]), 2)},
                ]
                length = direct_distance

            candidate = {
                "id": f"P_IMG_{len(existing_pipes) + 1}",
                "from_node": start["id"],
                "to_node": end["id"],
                "source_line": f"PIPE_CANDIDATE_{str(sample.get('id', len(existing_pipes) + 1))}",
                "length_px": round(float(length), 2),
                "angle_deg": round(math.degrees(math.atan2(float(end["y"]) - float(start["y"]), float(end["x"]) - float(start["x"]))), 2),
                "confidence": round(float(confidence), 3),
                "candidate_state": "auto" if confidence >= 0.6 else "review",
                "polyline_px": polyline,
                "geometry_type": _pipe_geometry_type([(int(round(point["x"])), int(round(point["y"]))) for point in polyline]),
                "source": "user_pipe_candidate",
            }
            score = float(confidence) + min(direct_distance / max(max_dimension, 1.0), 0.18)
            if best is None or score > best[0]:
                best = (score, candidate)
    return best[1] if best else None


def _pipe_pair_key(pipe: dict[str, Any]) -> tuple[str, str] | None:
    start = str(pipe.get("from_node", ""))
    end = str(pipe.get("to_node", ""))
    if not start or not end or start == end:
        return None
    return tuple(sorted((start, end)))


def _dedupe_pipe_candidates_by_pair(pipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    ordered_pairs: list[tuple[str, str]] = []
    for pipe in pipes:
        pair = _pipe_pair_key(pipe)
        if pair is None:
            continue
        existing = by_pair.get(pair)
        if existing is None:
            by_pair[pair] = pipe
            ordered_pairs.append(pair)
            continue
        if float(pipe.get("confidence", 0.0)) > float(existing.get("confidence", 0.0)):
            by_pair[pair] = pipe
    result = [by_pair[pair] for pair in ordered_pairs if pair in by_pair]
    for index, pipe in enumerate(result, 1):
        pipe["id"] = f"P_IMG_{index}"
        if not pipe.get("source_line"):
            pipe["source_line"] = f"P_IMG_{index}"
    return result


def _pipe_sample_hits_existing_pipe(
    sample: dict[str, float],
    pipes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, float]],
    *,
    tolerance_px: float,
) -> bool:
    sample_x = float(sample["x"])
    sample_y = float(sample["y"])
    for pipe in pipes:
        points = _pipe_polyline_points(pipe, node_by_id)
        if len(points) >= 2 and _polyline_distance_to_point(points, sample_x, sample_y) <= tolerance_px:
            return True
    return False


def _pipe_polyline_points(pipe: dict[str, Any], node_by_id: dict[str, dict[str, float]]) -> list[dict[str, float]]:
    points = [
        {"x": float(point["x"]), "y": float(point["y"])}
        for point in pipe.get("polyline_px", [])
        if isinstance(point, dict) and "x" in point and "y" in point
    ]
    if len(points) >= 2:
        return points
    start = node_by_id.get(str(pipe.get("from_node", "")))
    end = node_by_id.get(str(pipe.get("to_node", "")))
    if not start or not end:
        return []
    return [{"x": float(start["x"]), "y": float(start["y"])}, {"x": float(end["x"]), "y": float(end["y"])}]


def _path_distance_to_point(path: list[tuple[int, int]], x: float, y: float) -> float:
    points = [{"x": float(px), "y": float(py)} for px, py in path]
    return _polyline_distance_to_point(points, x, y)


def _polyline_distance_to_point(points: list[dict[str, float]], x: float, y: float) -> float:
    if len(points) < 2:
        return float("inf")
    return min(
        _point_to_segment_distance(
            x,
            y,
            float(start["x"]),
            float(start["y"]),
            float(end["x"]),
            float(end["y"]),
        )
        for start, end in zip(points, points[1:])
    )


def _point_to_segment_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _anchor_candidate_pairs(nodes: list[dict[str, float]]) -> list[tuple[int, int]]:
    if len(nodes) < 2:
        return []
    direct_limit = max(
        90.0,
        min(
            520.0,
            float(np.percentile(
                [
                    math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))
                    for index, a in enumerate(nodes)
                    for b in nodes[index + 1 :]
                ],
                55,
            ))
            * 1.55,
        ),
    )
    pairs: set[tuple[int, int]] = set()
    neighbor_limit = 6 if len(nodes) <= 24 else 4 if len(nodes) > 60 else 5
    for index, node in enumerate(nodes):
        distances = sorted(
            (
                (
                    math.hypot(float(other["x"]) - float(node["x"]), float(other["y"]) - float(node["y"])),
                    other_index,
                )
                for other_index, other in enumerate(nodes)
                if other_index != index
            ),
            key=lambda item: item[0],
        )
        for distance, other_index in distances[:neighbor_limit]:
            if distance <= direct_limit or len(nodes) <= 12:
                pairs.add(tuple(sorted((index, other_index))))
    return sorted(pairs)


def _shortest_skeleton_path(
    skeleton_pixels: set[tuple[int, int]],
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    max_cost: float,
) -> list[tuple[int, int]]:
    if start == end:
        return [start]
    open_heap: list[tuple[float, float, tuple[int, int]]] = []
    heapq.heappush(open_heap, (math.hypot(end[0] - start[0], end[1] - start[1]), 0.0, start))
    best_cost = {start: 0.0}
    parent: dict[tuple[int, int], tuple[int, int]] = {}
    visited: set[tuple[int, int]] = set()
    while open_heap:
        _, cost, pixel = heapq.heappop(open_heap)
        if pixel in visited:
            continue
        visited.add(pixel)
        if pixel == end:
            path = [end]
            while path[-1] != start:
                path.append(parent[path[-1]])
            path.reverse()
            return path
        if cost > max_cost:
            continue
        for neighbor in _pixel_neighbors(pixel, skeleton_pixels):
            step = math.hypot(neighbor[0] - pixel[0], neighbor[1] - pixel[1])
            next_cost = cost + step
            if next_cost > max_cost or next_cost >= best_cost.get(neighbor, float("inf")):
                continue
            best_cost[neighbor] = next_cost
            parent[neighbor] = pixel
            priority = next_cost + math.hypot(end[0] - neighbor[0], end[1] - neighbor[1])
            heapq.heappush(open_heap, (priority, next_cost, neighbor))
    return []


def _path_has_intermediate_anchor(
    path: list[tuple[int, int]],
    start: dict[str, float],
    end: dict[str, float],
    nodes: list[dict[str, float]],
    *,
    tolerance_px: float,
) -> bool:
    if len(path) < 3:
        return False
    start_id = str(start["id"])
    end_id = str(end["id"])
    for node in nodes:
        node_id = str(node["id"])
        if node_id in {start_id, end_id}:
            continue
        best_index = -1
        best_distance = tolerance_px
        for index, pixel in enumerate(path):
            distance = math.hypot(pixel[0] - float(node["x"]), pixel[1] - float(node["y"]))
            if distance <= best_distance:
                best_distance = distance
                best_index = index
        if best_index <= 0:
            continue
        fraction = best_index / max(len(path) - 1, 1)
        if 0.12 <= fraction <= 0.88:
            return True
    return False


def _prune_anchor_pipe_candidates(pipes: list[dict[str, Any]], nodes: list[dict[str, float]]) -> list[dict[str, Any]]:
    if not pipes:
        return []
    kept: list[dict[str, Any]] = []
    degree: dict[str, int] = {}
    for pipe in sorted(pipes, key=lambda item: (float(item.get("confidence", 0.0)), -float(item.get("length_px", 0.0))), reverse=True):
        start = str(pipe.get("from_node", ""))
        end = str(pipe.get("to_node", ""))
        if not start or not end or start == end:
            continue
        if degree.get(start, 0) >= 4 or degree.get(end, 0) >= 4:
            continue
        kept.append(pipe)
        degree[start] = degree.get(start, 0) + 1
        degree[end] = degree.get(end, 0) + 1
    kept.sort(key=lambda item: str(item.get("id", "")))
    for index, pipe in enumerate(kept, 1):
        pipe["id"] = f"P_IMG_{index}"
        pipe["source_line"] = f"ANCHOR_{index}"
    return kept


def _style_mask_fallback_nodes(
    skeleton_pixels: set[tuple[int, int]],
    symbol_candidates: list[dict[str, float]],
    merge_tolerance_px: float,
) -> list[dict[str, float]]:
    nodes = _nodes_from_candidates(symbol_candidates)
    if len(nodes) >= 2:
        return [
            {
                "id": f"N{index + 1}",
                "x": round(float(node["x"]), 2),
                "y": round(float(node["y"]), 2),
                "hits": int(float(node.get("hits", 1))),
                "confidence": round(float(node.get("confidence", 0.74)), 3),
                "candidate_state": "auto",
                "source": str(node.get("source", "symbol")),
                "locked": True,
            }
            for index, node in enumerate(nodes)
        ]
    for x, y, kind in _skeleton_node_points(skeleton_pixels):
        _add_or_merge_junction_node(
            nodes,
            float(x),
            float(y),
            tolerance_px=merge_tolerance_px,
            source=f"skeleton_{kind}",
            confidence=0.66 if kind == "branch" else 0.58,
        )
    return [
        {
            "id": f"N{index + 1}",
            "x": round(float(node["x"]), 2),
            "y": round(float(node["y"]), 2),
            "hits": int(float(node.get("hits", 1))),
            "confidence": round(float(node.get("confidence", 0.6)), 3),
            "candidate_state": "auto" if float(node.get("confidence", 0.6)) >= 0.66 else "review",
            "source": str(node.get("source", "fallback")),
            "locked": bool(node.get("locked", False)),
        }
        for index, node in enumerate(nodes)
    ]


def _mark_pipe_endpoint_hits(nodes: list[dict[str, float]], pipes: list[dict[str, Any]]) -> list[dict[str, float]]:
    endpoint_hits: dict[str, int] = {}
    for pipe in pipes:
        for key in ("from_node", "to_node"):
            node_id = str(pipe.get(key, ""))
            if node_id:
                endpoint_hits[node_id] = endpoint_hits.get(node_id, 0) + 1
    marked: list[dict[str, float]] = []
    for node in nodes:
        copied = dict(node)
        node_id = str(copied.get("id", ""))
        copied["hits"] = max(int(float(copied.get("hits", 1))), endpoint_hits.get(node_id, 1))
        if endpoint_hits.get(node_id, 0) >= 2:
            copied["confidence"] = min(0.96, float(copied.get("confidence", 0.7)) + 0.08)
        marked.append(copied)
    return marked


def _prune_style_line_segments(
    line_segments: list[dict[str, float]],
    mask: np.ndarray,
    text_mask: np.ndarray | None,
    *,
    min_line_length: int,
) -> list[dict[str, float]]:
    pruned: list[dict[str, float]] = []
    image_diagonal = math.hypot(mask.shape[1], mask.shape[0])
    for line in line_segments:
        length = float(line.get("length_px", 0.0))
        if length < min_line_length:
            continue
        points = _line_polyline_points(line)
        path = [(int(round(point["x"])), int(round(point["y"]))) for point in points]
        coverage = _mask_path_coverage(mask, path) if len(path) >= 2 else 0.0
        text_overlap = _mask_path_coverage(text_mask, path) if text_mask is not None and len(path) >= 2 else 0.0
        if coverage < 0.42 or text_overlap > 0.2:
            continue
        if length > image_diagonal * 0.72 and coverage < 0.68:
            continue
        copied = dict(line)
        copied["confidence"] = round(min(0.98, max(0.35, float(copied.get("confidence", 0.45)) + coverage * 0.36 - text_overlap * 0.35)), 3)
        copied["candidate_state"] = "auto" if copied["confidence"] >= 0.6 else "review"
        pruned.append(copied)
    return pruned


def _trace_skeleton_pipe_paths(
    skeleton_pixels: set[tuple[int, int]],
    mask: np.ndarray,
    *,
    min_line_length: int,
    text_mask: np.ndarray | None,
) -> list[dict[str, float]]:
    graph_pixels = {pixel for pixel in skeleton_pixels if len(_pixel_neighbors(pixel, skeleton_pixels)) != 2}
    if not graph_pixels:
        return []

    line_segments: list[dict[str, float]] = []
    seen_edges: set[frozenset[tuple[int, int]]] = set()
    for start_pixel in graph_pixels:
        for neighbor in _pixel_neighbors(start_pixel, skeleton_pixels):
            path = _walk_pixel_path_between_graph_nodes(
                skeleton_pixels,
                graph_pixels,
                start_pixel,
                neighbor,
                max_steps=max(4000, mask.size // 3),
            )
            if len(path) < 2:
                continue
            end_pixel = path[-1]
            if end_pixel not in graph_pixels:
                continue
            edge_key = frozenset((start_pixel, end_pixel))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            length = _polyline_length(path)
            if length < min_line_length:
                continue
            coverage = _mask_path_coverage(mask, path)
            text_overlap = _mask_path_coverage(text_mask, path) if text_mask is not None else 0.0
            if text_overlap > 0.18:
                continue
            direct = math.hypot(end_pixel[0] - start_pixel[0], end_pixel[1] - start_pixel[1])
            tortuosity = length / max(direct, 1.0)
            if tortuosity > 4.2 and direct > min_line_length * 1.5:
                continue
            confidence = min(0.98, max(0.25, 0.45 + coverage * 0.5 + min(length / 450.0, 0.12) - text_overlap * 0.45))
            line_segments.append(
                {
                    "id": f"L_IMG_{len(line_segments) + 1}",
                    "x1": round(float(start_pixel[0]), 2),
                    "y1": round(float(start_pixel[1]), 2),
                    "x2": round(float(end_pixel[0]), 2),
                    "y2": round(float(end_pixel[1]), 2),
                    "length_px": round(length, 2),
                    "angle_deg": round(math.degrees(math.atan2(end_pixel[1] - start_pixel[1], end_pixel[0] - start_pixel[0])), 2),
                    "confidence": round(confidence, 3),
                    "source": "skeleton_path",
                    "points": _simplify_polyline_path(path),
                    "geometry_type": _pipe_geometry_type(path),
                }
            )
    return line_segments


def _walk_pixel_path_between_graph_nodes(
    skeleton_pixels: set[tuple[int, int]],
    graph_pixels: set[tuple[int, int]],
    start: tuple[int, int],
    first: tuple[int, int],
    *,
    max_steps: int,
) -> list[tuple[int, int]]:
    path = [start, first]
    previous = start
    current = first
    for _ in range(max_steps):
        if current in graph_pixels and current != start:
            break
        neighbors = [pixel for pixel in _pixel_neighbors(current, skeleton_pixels) if pixel != previous]
        if not neighbors:
            break
        if len(neighbors) > 1:
            break
        previous, current = current, neighbors[0]
        path.append(current)
    return path


def _split_pipe_candidates_at_intersections(
    line_segments: list[dict[str, float]],
    *,
    tolerance_px: float,
) -> list[dict[str, float]]:
    split_candidates = [line for line in line_segments if line.get("source") != "hough_mask"]
    passthrough = [line for line in line_segments if line.get("source") == "hough_mask"]
    split_points: dict[int, list[dict[str, float]]] = {index: [] for index in range(len(split_candidates))}
    polylines = [_line_polyline_points(line) for line in split_candidates]

    for first_index, first_points in enumerate(polylines):
        for second_index in range(first_index + 1, len(polylines)):
            second_points = polylines[second_index]
            first_nodes = _line_endpoint_keys(split_candidates[first_index], tolerance_px)
            second_nodes = _line_endpoint_keys(split_candidates[second_index], tolerance_px)
            if first_nodes & second_nodes:
                continue
            for a1, a2 in zip(first_points, first_points[1:]):
                for b1, b2 in zip(second_points, second_points[1:]):
                    point = _segment_intersection_point(a1, a2, b1, b2, tolerance_px=tolerance_px)
                    if point is None:
                        continue
                    split_points[first_index].append(point)
                    split_points[second_index].append(point)

    result: list[dict[str, float]] = []
    for index, line in enumerate(split_candidates):
        points = _ordered_polyline_split_points(polylines[index], split_points[index], tolerance_px=tolerance_px)
        if len(points) < 2:
            result.append(line)
            continue
        for start, end in zip(points, points[1:]):
            length = math.hypot(float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"]))
            if length < max(8.0, tolerance_px * 0.6):
                continue
            copied = dict(line)
            copied["id"] = f"L_IMG_{len(result) + 1}"
            copied["x1"] = round(float(start["x"]), 2)
            copied["y1"] = round(float(start["y"]), 2)
            copied["x2"] = round(float(end["x"]), 2)
            copied["y2"] = round(float(end["y"]), 2)
            copied["length_px"] = round(length, 2)
            copied["angle_deg"] = round(math.degrees(math.atan2(float(end["y"]) - float(start["y"]), float(end["x"]) - float(start["x"]))), 2)
            copied["points"] = [start, end]
            copied["geometry_type"] = "straight"
            copied["source"] = f"{line.get('source', 'pipe')}_split"
            result.append(copied)
    return result + passthrough


def _line_polyline_points(line: dict[str, float]) -> list[dict[str, float]]:
    points = [
        {"x": float(point["x"]), "y": float(point["y"])}
        for point in line.get("points", [])
        if isinstance(point, dict) and "x" in point and "y" in point
    ]
    if len(points) >= 2:
        return points
    return [
        {"x": float(line["x1"]), "y": float(line["y1"])},
        {"x": float(line["x2"]), "y": float(line["y2"])},
    ]


def _line_endpoint_keys(line: dict[str, float], tolerance_px: float) -> set[tuple[int, int]]:
    return {
        (round(float(line["x1"]) / tolerance_px), round(float(line["y1"]) / tolerance_px)),
        (round(float(line["x2"]) / tolerance_px), round(float(line["y2"]) / tolerance_px)),
    }


def _segment_intersection_point(
    a1: dict[str, float],
    a2: dict[str, float],
    b1: dict[str, float],
    b2: dict[str, float],
    *,
    tolerance_px: float,
) -> dict[str, float] | None:
    ax, ay = float(a1["x"]), float(a1["y"])
    bx, by = float(a2["x"]), float(a2["y"])
    cx, cy = float(b1["x"]), float(b1["y"])
    dx, dy = float(b2["x"]), float(b2["y"])
    denom = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
    if abs(denom) < 1e-6:
        return None
    t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / denom
    u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / denom
    margin_a = tolerance_px / max(math.hypot(bx - ax, by - ay), 1.0)
    margin_b = tolerance_px / max(math.hypot(dx - cx, dy - cy), 1.0)
    if not (margin_a < t < 1.0 - margin_a and margin_b < u < 1.0 - margin_b):
        return None
    return {"x": round(ax + t * (bx - ax), 2), "y": round(ay + t * (by - ay), 2)}


def _ordered_polyline_split_points(
    points: list[dict[str, float]],
    extra_points: list[dict[str, float]],
    *,
    tolerance_px: float,
) -> list[dict[str, float]]:
    if not points:
        return []
    split_points = [points[0], *extra_points, points[-1]]

    def distance_along(point: dict[str, float]) -> float:
        best_distance = 0.0
        best_offset = float("inf")
        walked = 0.0
        for start, end in zip(points, points[1:]):
            sx, sy = float(start["x"]), float(start["y"])
            ex, ey = float(end["x"]), float(end["y"])
            length = math.hypot(ex - sx, ey - sy)
            if length <= 0:
                continue
            projection = ((float(point["x"]) - sx) * (ex - sx) + (float(point["y"]) - sy) * (ey - sy)) / (length * length)
            clamped = max(0.0, min(1.0, projection))
            px = sx + clamped * (ex - sx)
            py = sy + clamped * (ey - sy)
            offset = math.hypot(float(point["x"]) - px, float(point["y"]) - py)
            if offset < best_offset:
                best_offset = offset
                best_distance = walked + clamped * length
            walked += length
        return best_distance

    ordered: list[dict[str, float]] = []
    for point in sorted(split_points, key=distance_along):
        if ordered and math.hypot(float(point["x"]) - float(ordered[-1]["x"]), float(point["y"]) - float(ordered[-1]["y"])) <= tolerance_px * 0.5:
            continue
        ordered.append({"x": round(float(point["x"]), 2), "y": round(float(point["y"]), 2)})
    return ordered


def _collapse_pipe_graph_to_topology(
    nodes: list[dict[str, float]],
    pipes: list[dict[str, Any]],
) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    """Keep junctions at pipe endpoints/intersections, not at every skeleton pixel turn."""

    node_by_id = {str(node.get("id")): dict(node) for node in nodes if node.get("id")}
    working_pipes = [dict(pipe) for pipe in pipes if pipe.get("from_node") in node_by_id and pipe.get("to_node") in node_by_id]
    if len(node_by_id) < 3 or len(working_pipes) < 2:
        return nodes, pipes

    changed = True
    while changed:
        changed = False
        adjacency = _pipe_adjacency(working_pipes)
        for node_id, incident in list(adjacency.items()):
            if len(incident) != 2:
                continue
            node = node_by_id.get(node_id)
            if node and bool(node.get("locked")):
                continue
            first_index, second_index = incident
            if first_index >= len(working_pipes) or second_index >= len(working_pipes):
                continue
            first = working_pipes[first_index]
            second = working_pipes[second_index]
            other_a = _other_pipe_endpoint(first, node_id)
            other_b = _other_pipe_endpoint(second, node_id)
            if not other_a or not other_b or other_a == other_b:
                continue
            if not _degree_two_node_is_straight(node_by_id, other_a, node_id, other_b, angle_tolerance_deg=30.0):
                continue
            merged = _merge_two_pipe_candidates(first, second, node_by_id, other_a, other_b)
            for index in sorted([first_index, second_index], reverse=True):
                working_pipes.pop(index)
            working_pipes.append(merged)
            node_by_id.pop(node_id, None)
            changed = True
            break

    working_pipes = _dedupe_pipe_candidates_by_pair(working_pipes)
    used_node_ids = {
        str(pipe.get(key, ""))
        for pipe in working_pipes
        for key in ("from_node", "to_node")
        if pipe.get(key)
    }
    ordered_nodes = [node for node in nodes if str(node.get("id", "")) in used_node_ids]
    if not ordered_nodes:
        return nodes, pipes

    remapped_nodes: list[dict[str, float]] = []
    id_map: dict[str, str] = {}
    for index, node in enumerate(ordered_nodes, 1):
        old_id = str(node["id"])
        new_id = f"N{index}"
        id_map[old_id] = new_id
        copied = dict(node)
        copied["id"] = new_id
        remapped_nodes.append(copied)

    remapped_pipes: list[dict[str, Any]] = []
    for pipe in working_pipes:
        from_node = id_map.get(str(pipe.get("from_node", "")))
        to_node = id_map.get(str(pipe.get("to_node", "")))
        if not from_node or not to_node or from_node == to_node:
            continue
        copied = dict(pipe)
        copied["id"] = f"P_IMG_{len(remapped_pipes) + 1}"
        copied["from_node"] = from_node
        copied["to_node"] = to_node
        copied["source_line"] = f"TOPO_{len(remapped_pipes) + 1}"
        remapped_pipes.append(copied)
    return remapped_nodes, remapped_pipes


def _pipe_adjacency(pipes: list[dict[str, Any]]) -> dict[str, list[int]]:
    adjacency: dict[str, list[int]] = {}
    for index, pipe in enumerate(pipes):
        for key in ("from_node", "to_node"):
            node_id = str(pipe.get(key, ""))
            if node_id:
                adjacency.setdefault(node_id, []).append(index)
    return adjacency


def _other_pipe_endpoint(pipe: dict[str, Any], node_id: str) -> str | None:
    start = str(pipe.get("from_node", ""))
    end = str(pipe.get("to_node", ""))
    if start == node_id:
        return end
    if end == node_id:
        return start
    return None


def _merge_two_pipe_candidates(
    first: dict[str, Any],
    second: dict[str, Any],
    node_by_id: dict[str, dict[str, float]],
    from_node: str,
    to_node: str,
) -> dict[str, Any]:
    start = node_by_id[from_node]
    end = node_by_id[to_node]
    middle = _shared_pipe_endpoint(first, second)
    first_points = _oriented_pipe_points(first, node_by_id, from_node, middle or str(first.get("to_node", "")))
    second_points = _oriented_pipe_points(second, node_by_id, middle or str(second.get("from_node", "")), to_node)
    polyline = first_points + second_points[1:] if first_points and second_points else [
        {"x": float(start["x"]), "y": float(start["y"])},
        {"x": float(end["x"]), "y": float(end["y"])},
    ]
    direct_length = math.hypot(float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"]))
    path_length = _polyline_length([(round(point["x"]), round(point["y"])) for point in polyline])
    confidence = min(float(first.get("confidence", 0.7)), float(second.get("confidence", 0.7)))
    angle = math.degrees(math.atan2(float(end["y"]) - float(start["y"]), float(end["x"]) - float(start["x"])))
    return {
        "id": first.get("id", "P_IMG"),
        "from_node": from_node,
        "to_node": to_node,
        "source_line": first.get("source_line", "TOPO"),
        "length_px": round(max(path_length, direct_length), 2),
        "angle_deg": round(angle, 2),
        "confidence": confidence,
        "candidate_state": "auto" if confidence >= 0.55 else "review",
        "polyline_px": polyline,
        "geometry_type": _pipe_geometry_type([(round(point["x"]), round(point["y"])) for point in polyline]),
    }


def _shared_pipe_endpoint(first: dict[str, Any], second: dict[str, Any]) -> str | None:
    first_nodes = {str(first.get("from_node", "")), str(first.get("to_node", ""))}
    second_nodes = {str(second.get("from_node", "")), str(second.get("to_node", ""))}
    shared = [node_id for node_id in first_nodes & second_nodes if node_id]
    return shared[0] if shared else None


def _oriented_pipe_points(
    pipe: dict[str, Any],
    node_by_id: dict[str, dict[str, float]],
    from_node: str,
    to_node: str,
) -> list[dict[str, float]]:
    points = [
        {"x": float(point["x"]), "y": float(point["y"])}
        for point in pipe.get("polyline_px", [])
        if isinstance(point, dict) and "x" in point and "y" in point
    ]
    if not points:
        start = node_by_id.get(from_node)
        end = node_by_id.get(to_node)
        if not start or not end:
            return []
        points = [{"x": float(start["x"]), "y": float(start["y"])}, {"x": float(end["x"]), "y": float(end["y"])}]
    start_node = node_by_id.get(from_node)
    end_node = node_by_id.get(to_node)
    if start_node and end_node:
        start_distance = math.hypot(points[0]["x"] - float(start_node["x"]), points[0]["y"] - float(start_node["y"]))
        end_distance = math.hypot(points[-1]["x"] - float(end_node["x"]), points[-1]["y"] - float(end_node["y"]))
        reversed_start_distance = math.hypot(points[-1]["x"] - float(start_node["x"]), points[-1]["y"] - float(start_node["y"]))
        reversed_end_distance = math.hypot(points[0]["x"] - float(end_node["x"]), points[0]["y"] - float(end_node["y"]))
        if reversed_start_distance + reversed_end_distance < start_distance + end_distance:
            points.reverse()
    return points


def _degree_two_node_is_straight(
    node_by_id: dict[str, dict[str, float]],
    first_id: str,
    middle_id: str,
    second_id: str,
    *,
    angle_tolerance_deg: float = 28.0,
) -> bool:
    first = node_by_id.get(first_id)
    middle = node_by_id.get(middle_id)
    second = node_by_id.get(second_id)
    if not first or not middle or not second:
        return False
    ax = float(first["x"]) - float(middle["x"])
    ay = float(first["y"]) - float(middle["y"])
    bx = float(second["x"]) - float(middle["x"])
    by = float(second["y"]) - float(middle["y"])
    first_length = math.hypot(ax, ay)
    second_length = math.hypot(bx, by)
    if first_length <= 0 or second_length <= 0:
        return False
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / (first_length * second_length)))
    angle = math.degrees(math.acos(cosine))
    return abs(180.0 - angle) <= angle_tolerance_deg


def _dedupe_pipe_candidates_by_pair(pipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for pipe in pipes:
        pair = tuple(sorted([str(pipe.get("from_node", "")), str(pipe.get("to_node", ""))]))
        if not pair[0] or not pair[1] or pair[0] == pair[1]:
            continue
        existing = by_pair.get(pair)
        if existing is None or float(pipe.get("confidence", 0.0)) > float(existing.get("confidence", 0.0)):
            by_pair[pair] = pipe
    return list(by_pair.values())


def _pipes_from_mask_between_nodes(
    mask: np.ndarray,
    nodes: list[dict[str, float]],
    *,
    min_line_length: float,
) -> list[dict[str, Any]]:
    pipes: list[dict[str, Any]] = []
    if len(nodes) < 2:
        return pipes
    ordered_nodes = sorted(nodes, key=lambda node: (float(node["y"]), float(node["x"])))
    neighbor_limit = 4 if len(ordered_nodes) <= 16 else 5
    nearest_by_node: dict[str, set[str]] = {}
    for node in ordered_nodes:
        distances = sorted(
            (
                (math.hypot(float(other["x"]) - float(node["x"]), float(other["y"]) - float(node["y"])), str(other["id"]))
                for other in ordered_nodes
                if other["id"] != node["id"]
            ),
            key=lambda item: item[0],
        )
        nearest_by_node[str(node["id"])] = {node_id for _, node_id in distances[:neighbor_limit]}
    max_pair_distance = max(mask.shape[:2]) * 0.52
    for index, start in enumerate(ordered_nodes):
        for end in ordered_nodes[index + 1 :]:
            distance = math.hypot(float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"]))
            if distance < min_line_length or distance > max_pair_distance:
                continue
            start_id = str(start["id"])
            end_id = str(end["id"])
            if end_id not in nearest_by_node.get(start_id, set()) and start_id not in nearest_by_node.get(end_id, set()):
                continue
            if _has_intermediate_node(start, end, ordered_nodes):
                continue
            coverage = _mask_line_coverage(mask, start, end, corridor_px=10)
            if coverage < 0.56:
                continue
            if distance > max(mask.shape[:2]) * 0.35 and coverage < 0.72:
                continue
            angle = math.degrees(math.atan2(float(end["y"]) - float(start["y"]), float(end["x"]) - float(start["x"])))
            pipes.append(
                {
                    "id": f"P_IMG_{len(pipes) + 1}",
                    "from_node": start["id"],
                    "to_node": end["id"],
                    "source_line": f"MASK_{len(pipes) + 1}",
                    "length_px": round(distance, 2),
                    "angle_deg": round(angle, 2),
                    "confidence": round(min(0.96, 0.35 + coverage * 0.65), 3),
                    "candidate_state": "auto" if coverage >= 0.42 else "review",
                    "polyline_px": [
                        {"x": round(float(start["x"]), 2), "y": round(float(start["y"]), 2)},
                        {"x": round(float(end["x"]), 2), "y": round(float(end["y"]), 2)},
                    ],
                    "geometry_type": "straight",
                }
            )
    return pipes


def _skeleton_node_points(skeleton_pixels: set[tuple[int, int]]) -> list[tuple[int, int, str]]:
    points: list[tuple[int, int, str]] = []
    for pixel in skeleton_pixels:
        degree = len(_pixel_neighbors(pixel, skeleton_pixels))
        if degree == 1:
            points.append((pixel[0], pixel[1], "endpoint"))
        elif degree >= 3:
            points.append((pixel[0], pixel[1], "branch"))
    return _cluster_skeleton_points(points, tolerance=10.0)


def _cluster_skeleton_points(points: list[tuple[int, int, str]], tolerance: float) -> list[tuple[int, int, str]]:
    clusters: list[dict[str, Any]] = []
    for x, y, kind in points:
        match = None
        for cluster in clusters:
            if math.hypot(cluster["x"] - x, cluster["y"] - y) <= tolerance:
                match = cluster
                break
        if match is None:
            clusters.append({"x": float(x), "y": float(y), "count": 1, "kind": kind})
        else:
            count = int(match["count"])
            match["x"] = (match["x"] * count + x) / (count + 1)
            match["y"] = (match["y"] * count + y) / (count + 1)
            match["count"] = count + 1
            if kind == "branch":
                match["kind"] = "branch"
    return [(round(cluster["x"]), round(cluster["y"]), str(cluster["kind"])) for cluster in clusters]


def _nearest_skeleton_pixel(
    skeleton_pixels: set[tuple[int, int]],
    x: float,
    y: float,
    tolerance_px: float,
) -> tuple[int, int] | None:
    nearest = None
    nearest_distance = tolerance_px
    for pixel in skeleton_pixels:
        distance = math.hypot(pixel[0] - x, pixel[1] - y)
        if distance <= nearest_distance:
            nearest = pixel
            nearest_distance = distance
    return nearest


def _pixel_neighbors(pixel: tuple[int, int], skeleton_pixels: set[tuple[int, int]]) -> list[tuple[int, int]]:
    x, y = pixel
    return [
        (x + dx, y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if (dx or dy) and (x + dx, y + dy) in skeleton_pixels
    ]


def _walk_skeleton_path(
    skeleton_pixels: set[tuple[int, int]],
    start: tuple[int, int],
    first: tuple[int, int],
    node_points: list[tuple[int, int, str]],
    *,
    max_steps: int,
) -> list[tuple[int, int]]:
    node_set = {(x, y) for x, y, _ in node_points}
    path = [start, first]
    previous = start
    current = first
    for _ in range(max_steps):
        if current in node_set and current != start:
            break
        neighbors = [pixel for pixel in _pixel_neighbors(current, skeleton_pixels) if pixel != previous]
        if not neighbors:
            break
        if len(neighbors) > 1:
            break
        previous, current = current, neighbors[0]
        path.append(current)
    return path


def _polyline_length(path: list[tuple[int, int]]) -> float:
    return sum(math.hypot(path[index][0] - path[index - 1][0], path[index][1] - path[index - 1][1]) for index in range(1, len(path)))


def _simplify_polyline_path(path: list[tuple[int, int]], *, min_step_px: float = 18.0) -> list[dict[str, float]]:
    if not path:
        return []
    simplified: list[tuple[int, int]] = [path[0]]
    accumulated = 0.0
    for index in range(1, len(path) - 1):
        accumulated += math.hypot(path[index][0] - path[index - 1][0], path[index][1] - path[index - 1][1])
        if accumulated >= min_step_px:
            simplified.append(path[index])
            accumulated = 0.0
    if path[-1] != simplified[-1]:
        simplified.append(path[-1])
    return [{"x": round(float(x), 2), "y": round(float(y), 2)} for x, y in simplified]


def _pipe_geometry_type(path: list[tuple[int, int]]) -> str:
    if len(path) <= 2:
        return "straight"
    start = path[0]
    end = path[-1]
    direct = math.hypot(end[0] - start[0], end[1] - start[1])
    path_length = _polyline_length(path)
    if direct <= 0:
        return "curved"
    return "straight" if path_length / direct <= 1.04 else "curved"


def _mask_path_coverage(mask: np.ndarray, path: list[tuple[int, int]]) -> float:
    if not path:
        return 0.0
    height, width = mask.shape[:2]
    hits = 0
    for x, y in path:
        if 0 <= x < width and 0 <= y < height and mask[y, x] > 0:
            hits += 1
    return hits / max(len(path), 1)


def _looks_like_ascii_dxf(cad_bytes: bytes) -> bool:
    sample = cad_bytes[:2048].decode("utf-8", errors="ignore").upper()
    return "SECTION" in sample and "ENTITIES" in sample


def _parse_ascii_dxf_lines(cad_bytes: bytes) -> tuple[list[dict[str, float]], int, int, list[str]]:
    text = cad_bytes.decode("utf-8", errors="ignore")
    raw_pairs = [line.strip() for line in text.splitlines()]
    pairs: list[tuple[str, str]] = []
    for index in range(0, len(raw_pairs) - 1, 2):
        pairs.append((raw_pairs[index], raw_pairs[index + 1]))

    raw_segments: list[dict[str, Any]] = []
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
    layer_summary = _cad_layer_summary(normalized_segments)
    if layer_summary:
        warnings.append(f"DXF layer hints detected: {layer_summary}.")
    return normalized_segments, width, height, warnings


def _read_dxf_line_entity(
    pairs: list[tuple[str, str]],
    cursor: int,
) -> tuple[dict[str, Any] | None, int]:
    values: dict[str, float] = {}
    layer = ""
    while cursor < len(pairs):
        code, value = pairs[cursor]
        if code == "0":
            break
        if code == "8":
            layer = value.strip()
        if code in {"10", "20", "11", "21"}:
            try:
                values[code] = float(value)
            except ValueError:
                pass
        cursor += 1
    if {"10", "20", "11", "21"}.issubset(values):
        return {
            "x1": values["10"],
            "y1": values["20"],
            "x2": values["11"],
            "y2": values["21"],
            "layer": layer,
        }, cursor
    return None, cursor


def _read_dxf_lwpolyline_entity(
    pairs: list[tuple[str, str]],
    cursor: int,
) -> tuple[list[dict[str, Any]], int]:
    points: list[tuple[float, float]] = []
    pending_x: float | None = None
    closed = False
    layer = ""
    while cursor < len(pairs):
        code, value = pairs[cursor]
        if code == "0":
            break
        if code == "8":
            layer = value.strip()
        elif code == "70":
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
        {
            "x1": points[index][0],
            "y1": points[index][1],
            "x2": points[index + 1][0],
            "y2": points[index + 1][1],
            "layer": layer,
        }
        for index in range(len(points) - 1)
    ]
    if closed and len(points) > 2:
        segments.append(
            {
                "x1": points[-1][0],
                "y1": points[-1][1],
                "x2": points[0][0],
                "y2": points[0][1],
                "layer": layer,
            }
        )
    return segments, cursor


def _normalize_cad_segments(
    raw_segments: list[Any],
) -> tuple[list[dict[str, float]], int, int]:
    normalized_raw: list[dict[str, Any]] = []
    for raw in raw_segments:
        segment = _raw_cad_segment(raw)
        if segment is not None:
            normalized_raw.append(segment)
    if not normalized_raw:
        return [], 0, 0

    xs = [value for segment in normalized_raw for value in (segment["x1"], segment["x2"])]
    ys = [value for segment in normalized_raw for value in (segment["y1"], segment["y2"])]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    margin = 20.0
    width = int(math.ceil(max(max_x - min_x + margin * 2, 1)))
    height = int(math.ceil(max(max_y - min_y + margin * 2, 1)))

    line_segments: list[dict[str, float]] = []
    for raw_index, raw in enumerate(normalized_raw):
        x1 = float(raw["x1"])
        y1 = float(raw["y1"])
        x2 = float(raw["x2"])
        y2 = float(raw["y2"])
        nx1 = x1 - min_x + margin
        nx2 = x2 - min_x + margin
        ny1 = max_y - y1 + margin
        ny2 = max_y - y2 + margin
        length = math.hypot(nx2 - nx1, ny2 - ny1)
        if length <= 0:
            continue
        layer = str(raw.get("layer") or "").strip()
        layer_role = _infer_cad_layer_role(layer)
        line_segments.append(
            {
                "id": f"L_CAD_{len(line_segments) + 1}",
                "x1": round(nx1, 2),
                "y1": round(ny1, 2),
                "x2": round(nx2, 2),
                "y2": round(ny2, 2),
                "length_px": round(length, 2),
                "angle_deg": round(math.degrees(math.atan2(ny2 - ny1, nx2 - nx1)), 2),
                "source_entity": str(raw.get("source_entity") or f"DXF_{raw_index + 1}"),
                "source_layer": layer,
                "layer_role": layer_role,
            }
        )
    return line_segments, width, height


def _raw_cad_segment(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        try:
            return {
                "x1": float(raw["x1"]),
                "y1": float(raw["y1"]),
                "x2": float(raw["x2"]),
                "y2": float(raw["y2"]),
                "layer": str(raw.get("layer") or ""),
                "source_entity": raw.get("source_entity"),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(raw, tuple) and len(raw) == 4:
        try:
            x1, y1, x2, y2 = [float(value) for value in raw]
        except (TypeError, ValueError):
            return None
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "layer": "", "source_entity": None}
    return None


def _infer_cad_layer_role(layer: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "_", layer).lower()
    if not normalized:
        return "unknown"
    if any(keyword in normalized for keyword in ["pipe", "water", "main", "line", "관", "관로", "배관", "상수"]):
        return "pipe"
    if any(keyword in normalized for keyword in ["pump", "펌프"]):
        return "pump"
    if any(keyword in normalized for keyword in ["source", "reservoir", "tank", "수원", "저수", "배수지"]):
        return "source"
    if any(keyword in normalized for keyword in ["valve", "밸브", "제수"]):
        return "valve"
    if any(keyword in normalized for keyword in ["dim", "dimension", "치수"]):
        return "dimension"
    if any(keyword in normalized for keyword in ["text", "anno", "label", "주석", "문자"]):
        return "annotation"
    return "unknown"


def _cad_layer_summary(line_segments: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for segment in line_segments:
        layer = str(segment.get("source_layer") or "").strip()
        role = str(segment.get("layer_role") or "unknown")
        if not layer:
            continue
        key = f"{layer}:{role}"
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(f"{key}={count}" for key, count in sorted(counts.items())[:12])


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - dependency check path
        raise RuntimeError(
            "OpenCV is required for drawing recognition. Install opencv-python-headless."
        ) from exc
    return cv2


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


def _junction_candidates_from_pipe_topology(
    candidates: list[dict[str, float]],
    line_segments: list[dict[str, float]],
    *,
    tolerance_px: float,
    min_endpoint_line_length: float,
) -> list[dict[str, float]]:
    nodes: list[dict[str, float]] = []
    for line in line_segments:
        if float(line.get("length_px", 0.0)) < min_endpoint_line_length:
            continue
        for x_key, y_key in [("x1", "y1"), ("x2", "y2")]:
            _add_or_merge_junction_node(
                nodes,
                float(line[x_key]),
                float(line[y_key]),
                tolerance_px=tolerance_px * 1.6,
                source="pipe_endpoint",
                confidence=0.72,
            )

    for candidate in candidates:
        if "x" not in candidate or "y" not in candidate:
            continue
        match = _nearest_node(nodes, float(candidate["x"]), float(candidate["y"]), tolerance_px * 2.8)
        if match is None:
            continue
        match["symbol_hits"] = int(float(match.get("symbol_hits", 0)) + 1)
        match["locked"] = True
        match["confidence"] = min(0.98, float(match.get("confidence", 0.72)) + 0.16)
        match["source"] = "pipe_endpoint+symbol"

    confirmed = [
        node
        for node in nodes
        if int(float(node.get("hits", 1))) >= 2 or bool(node.get("locked")) or float(node.get("confidence", 0.0)) >= 0.7
    ]
    if not confirmed:
        confirmed = nodes
    return [
        {
            "id": f"N{index + 1}",
            "x": round(float(node["x"]), 2),
            "y": round(float(node["y"]), 2),
            "hits": int(float(node.get("hits", 1))),
            "confidence": round(float(node.get("confidence", 0.72)), 3),
            "candidate_state": "auto" if float(node.get("confidence", 0.72)) >= 0.7 else "review",
            "source": str(node.get("source", "pipe_endpoint")),
            "locked": bool(node.get("locked", False)),
        }
        for index, node in enumerate(confirmed)
    ]


def _add_or_merge_junction_node(
    nodes: list[dict[str, float]],
    x: float,
    y: float,
    *,
    tolerance_px: float,
    source: str,
    confidence: float,
) -> None:
    match = _nearest_node(nodes, x, y, tolerance_px)
    if match is None:
        nodes.append({"id": f"N{len(nodes) + 1}", "x": x, "y": y, "hits": 1, "confidence": confidence, "source": source})
        return
    hits = int(float(match.get("hits", 1)))
    match["x"] = (float(match["x"]) * hits + x) / (hits + 1)
    match["y"] = (float(match["y"]) * hits + y) / (hits + 1)
    match["hits"] = hits + 1
    match["confidence"] = min(0.96, max(float(match.get("confidence", confidence)), confidence) + 0.04)
    if source not in str(match.get("source", "")):
        match["source"] = f"{match.get('source', 'pipe_endpoint')}+{source}"


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
    *,
    max_endpoint_distance: float = 9999.0,
) -> list[dict[str, Any]]:
    pipes: list[dict[str, Any]] = []
    for line in line_segments:
        if line.get("layer_role") in {"annotation", "dimension"}:
            continue
        start = _nearest_node(nodes, float(line["x1"]), float(line["y1"]), max_endpoint_distance)
        end = _nearest_node(nodes, float(line["x2"]), float(line["y2"]), max_endpoint_distance)
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
                "polyline_px": line.get("points", []),
                "geometry_type": line.get("geometry_type", "straight"),
                "source_layer": line.get("source_layer", ""),
                "layer_role": line.get("layer_role", "unknown"),
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
                "points": pipe.get("polyline_px")
                or [
                    {"x": round(x1, 2), "y": round(y1, 2)},
                    {"x": round(x2, 2), "y": round(y2, 2)},
                ],
                "geometry_type": pipe.get("geometry_type", "straight"),
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
            max(4, int(max(float(candidate.get("width_px", 12)), float(candidate.get("height_px", 12))) / 2)),
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
