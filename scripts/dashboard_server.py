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
    analyze_drawing_image,
    build_dashboard_assets_from_recognition,
    call_gemini_vision,
)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "WaterNetworkDashboard/0.1"

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

    def _serve_static(self, route: str) -> None:
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
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json;charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _recognize_drawing(request: dict[str, Any]) -> dict[str, Any]:
    image_bytes = base64.b64decode(request["image_base64"])
    mime_type = str(request.get("mime_type") or "image/png")
    opencv_result = analyze_drawing_image(
        image_bytes,
        mime_type,
        min_line_length=int(float(request.get("min_line_length") or 45)),
        merge_tolerance_px=float(request.get("merge_tolerance_px") or 18),
    )
    assets = build_dashboard_assets_from_recognition(
        opencv_result,
        scale_m_per_px=float(request.get("scale_m_per_px") or 1),
        default_diameter_mm=float(request.get("default_diameter_mm") or 150),
        default_material=str(request.get("default_material") or "PVC"),
        include_virtual_reservoir=True,
    )
    gemini_result = None
    if bool(request.get("use_gemini", True)):
        gemini_result = call_gemini_vision(image_bytes, mime_type)

    payload = json.loads(opencv_result.binary_payload.decode("utf-8"))
    return {
        "recognition": {
            "width": opencv_result.width,
            "height": opencv_result.height,
            "segments": opencv_result.line_segments,
            "nodes": payload.get("nodes", []),
            "node_candidates": opencv_result.node_candidates,
            "pipe_candidates": opencv_result.pipe_candidates,
            "summary": opencv_result.summary(),
            "gemini": _gemini_to_dict(gemini_result),
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
