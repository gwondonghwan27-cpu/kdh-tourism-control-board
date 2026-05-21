"""Streamlit Cloud entrypoint with the same calculation API as the HTML app."""

from __future__ import annotations

import sys
from pathlib import Path

from streamlit.starlette import App


REPO_ROOT = Path(__file__).resolve().parent
APP_DIR = REPO_ROOT / "app"
SRC_DIR = REPO_ROOT / "src"

for path in (APP_DIR, SRC_DIR, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from streamlit_api_routes import STREAMLIT_API_ROUTES  # noqa: E402


app = App(
    APP_DIR / "streamlit_html_dashboard.py",
    routes=STREAMLIT_API_ROUTES,
)
