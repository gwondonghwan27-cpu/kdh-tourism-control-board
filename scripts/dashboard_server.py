"""Serve the HTML dashboard and drawing-recognition API from Python."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aging_water_network.vision import (  # noqa: E402
    build_dashboard_assets_from_recognition,
    call_gemini_vision,
    recognize_drawing_file,
)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "WaterNetworkDashboard/0.1"

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib hook
        route = unquote(urlparse(self.path).path)
        if route == "/api/health":
            self._send_json({"ok": True}, include_body=False)
            return
        self._serve_static(route, include_body=False)

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        route = unquote(urlparse(self.path).path)
        if route == "/api/health":
            self._send_json({"ok": True})
            return
        self._serve_static(route)

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        route = unquote(urlparse(self.path).path)
        if route != "/api/recognize-drawing":
            self.send_error(HTTPStatus.NOT_FOUND, "missing")
            return
        try:
            request = self._read_json_body()
            self._send_json(_recognize_drawing(request))
        except Exception as exc:  # pragma: no cover - runtime protection
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or 0)
        if length > 30 * 1024 * 1024:
            raise ValueError("request body is too large")
        body = self.rfile.read(length).decode("utf-8")
        parsed = json.loads(body or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    def _serve_static(self, route: str, *, include_body: bool = True) -> None:
        if route == "/":
            route = "/frontend/index.html"
        relative_path = Path(route.lstrip("/"))
        file_path = (REPO_ROOT / relative_path).resolve()
        if not file_path.is_file() or not _is_relative_to(file_path, REPO_ROOT):
            self.send_error(HTTPStatus.NOT_FOUND, "missing")
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "text/plain"
        if file_path.suffix.lower() in {".html", ".js", ".css", ".csv", ".json"}:
            content_type = f"{content_type};charset=utf-8"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _send_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
        include_body: bool = True,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json;charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)


def _recognize_drawing(request: dict[str, Any]) -> dict[str, Any]:
    file_bytes = base64.b64decode(request.get("file_base64") or request.get("image_base64") or "")
    mime_type = str(request.get("mime_type") or "")
    filename = str(request.get("filename") or "")
    drawing_file_type, recognition_result = recognize_drawing_file(
        file_bytes,
        filename=filename,
        mime_type=mime_type,
        min_line_length=int(float(request.get("min_line_length") or 45)),
        merge_tolerance_px=float(request.get("merge_tolerance_px") or 18),
        pipe_candidate_samples=request.get("pipe_candidate_samples") if isinstance(request.get("pipe_candidate_samples"), list) else None,
        pipe_style_samples=request.get("pipe_style_samples") if isinstance(request.get("pipe_style_samples"), list) else None,
        junction_anchor_samples=request.get("junction_anchor_samples") if isinstance(request.get("junction_anchor_samples"), list) else None,
    )
    assets = build_dashboard_assets_from_recognition(
        recognition_result,
        scale_m_per_px=float(request.get("scale_m_per_px") or 1),
        default_diameter_mm=float(request.get("default_diameter_mm") or 150),
        default_material=str(request.get("default_material") or "PVC"),
        include_virtual_reservoir=True,
    )
    gemini_result = None
    if drawing_file_type == "image" and bool(request.get("use_gemini", True)):
        gemini_result = call_gemini_vision(file_bytes, _image_mime_for_request(filename, mime_type))

    payload = json.loads(recognition_result.binary_payload.decode("utf-8"))
    semantic_hints = payload.get("semantic_hints") or {}
    if gemini_result is not None:
        semantic_hints = {
            "source": "gemini",
            "parsed_json": gemini_result.parsed_json,
            "error": gemini_result.error,
        }
    return {
        "recognition": {
            "file_type": drawing_file_type,
            "cad_format": getattr(recognition_result, "cad_format", None),
            "pdf_mode": getattr(recognition_result, "pdf_mode", None),
            "filename": filename,
            "mime_type": mime_type,
            "width": recognition_result.width,
            "height": recognition_result.height,
            "segments": recognition_result.line_segments,
            "nodes": payload.get("nodes", []),
            "node_candidates": recognition_result.node_candidates,
            "pipe_candidates": recognition_result.pipe_candidates,
            "low_confidence_pipes": payload.get("low_confidence_pipes", []),
            "semantic_hints": semantic_hints,
            "summary": recognition_result.summary(),
            "gemini": _gemini_to_dict(gemini_result),
            "warnings": payload.get("cad_warnings", []) + payload.get("pdf_warnings", []) + assets.warnings,
        },
        "assets": assets.to_dict(),
    }


def _gemini_to_dict(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "model": result.model,
        "parsed_json": result.parsed_json,
        "raw_text": result.raw_text,
        "error": result.error,
    }


def _image_mime_for_request(filename: str, mime_type: str) -> str:
    normalized_mime = (mime_type or "").split(";")[0].strip().lower()
    if normalized_mime in {"image/jpeg", "image/png"}:
        return normalized_mime
    suffix = Path(filename).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "image/png"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardRequestHandler)
    print(f"Dashboard server running at http://{args.host}:{args.port}/frontend/index.html", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
