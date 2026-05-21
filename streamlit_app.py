"""Streamlit Cloud entrypoint with the same calculation API as the HTML app."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from streamlit.starlette import App


REPO_ROOT = Path(__file__).resolve().parent
APP_DIR = REPO_ROOT / "app"
SRC_DIR = REPO_ROOT / "src"

for path in (APP_DIR, SRC_DIR, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.dashboard_server import _health_payload, _simulate_network  # noqa: E402


API_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-private-network": "true",
    "access-control-allow-methods": "GET,HEAD,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
}


async def health(_: Request) -> JSONResponse:
    return JSONResponse(_health_payload(), headers=API_HEADERS)


async def simulate_network(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=API_HEADERS)
    try:
        payload: dict[str, Any] = await request.json()
        result = _simulate_network(payload)
        return JSONResponse(result, headers=API_HEADERS)
    except Exception as error:
        return JSONResponse({"error": str(error)}, status_code=500, headers=API_HEADERS)


app = App(
    APP_DIR / "streamlit_html_dashboard.py",
    routes=[
        Route("/api/health", health, methods=["GET", "HEAD"]),
        Route("/api/health/", health, methods=["GET", "HEAD"]),
        Route("/api/simulate-network", simulate_network, methods=["POST", "OPTIONS"]),
        Route("/api/simulate-network/", simulate_network, methods=["POST", "OPTIONS"]),
    ],
)
