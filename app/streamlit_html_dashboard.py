"""Serve the interactive HTML dashboard inside Streamlit."""

from __future__ import annotations

import html
import json
import re
import socket
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
MOCK_DATA_DIR = REPO_ROOT / "data" / "mock"
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 5173
DASHBOARD_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/frontend/index.html"
HEALTH_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/api/health"


CSV_FILES = [
    "nodes.csv",
    "pipes.csv",
    "reservoirs.csv",
    "pumps.csv",
    "valves.csv",
    "households.csv",
    "household_demand_timeseries.csv",
]


def main() -> None:
    import streamlit as st
    import streamlit.components.v1 as components

    st.set_page_config(
        page_title="상수관망 디지털 트윈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(
        """
        <style>
          html,
          body,
          .stApp,
          [data-testid="stAppViewContainer"],
          [data-testid="stMain"],
          .block-container {
            height: 100vh;
            overflow: hidden;
          }
          .stApp { background: #f6f9fc; }
          .block-container { padding: 0; max-width: 100%; }
          header[data-testid="stHeader"] { display: none; }
          [data-testid="stToolbar"],
          [data-testid="stDecoration"],
          [data-testid="stStatusWidget"],
          #MainMenu {
            visibility: hidden;
            height: 0;
          }
          iframe {
            display: block;
            width: 100%;
            height: 100vh !important;
          }
          footer { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    server_ready = ensure_dashboard_server()
    if server_ready:
        components.iframe(DASHBOARD_URL, height=1000, scrolling=True)
    else:
        st.error("Could not start the local dashboard/API server.")
        st.caption(f"Try running: {sys.executable} scripts/dashboard_server.py")


@lru_cache(maxsize=1)
def ensure_dashboard_server() -> bool:
    if _healthcheck():
        return True
    if _port_is_busy(DASHBOARD_HOST, DASHBOARD_PORT):
        return False
    subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "dashboard_server.py"),
            "--host",
            DASHBOARD_HOST,
            "--port",
            str(DASHBOARD_PORT),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_creation_flags(),
    )
    for _ in range(40):
        if _healthcheck():
            return True
        time.sleep(0.1)
    return False


def _healthcheck() -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def _port_is_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


@lru_cache(maxsize=1)
def build_dashboard_html() -> str:
    index_html = read_text(FRONTEND_DIR / "index.html")
    css = read_text(FRONTEND_DIR / "styles.css")
    app_js = read_text(FRONTEND_DIR / "app.js")
    csv_payload = {file_name: read_text(MOCK_DATA_DIR / file_name) for file_name in CSV_FILES}

    body = extract_body(index_html)
    body = remove_stylesheet_links(body)
    body = remove_script_tags(body)

    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>상수관망 디지털 트윈 대시보드</title>
    <style>
      html, body {{
        margin: 0;
        min-height: 100%;
        overflow-x: hidden;
      }}
      {css}
    </style>
  </head>
  <body>
    {body}
    <script>
      window.__STREAMLIT_MOCK_CSV__ = {json.dumps(csv_payload, ensure_ascii=False)};
      const __streamlitOriginalFetch = window.fetch ? window.fetch.bind(window) : null;
      window.fetch = async function(resource, options) {{
        const url = typeof resource === "string" ? resource : resource?.url || "";
        const fileName = decodeURIComponent(String(url).split("?")[0].split("/").pop());
        if (Object.prototype.hasOwnProperty.call(window.__STREAMLIT_MOCK_CSV__, fileName)) {{
          return new Response(window.__STREAMLIT_MOCK_CSV__[fileName], {{
            status: 200,
            headers: {{ "Content-Type": "text/csv;charset=utf-8" }},
          }});
        }}
        if (__streamlitOriginalFetch) return __streamlitOriginalFetch(resource, options);
        return new Response("", {{ status: 404 }});
      }};
    </script>
    <script>
      {app_js}
    </script>
  </body>
</html>"""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def extract_body(index_html: str) -> str:
    match = re.search(r"<body[^>]*>(?P<body>.*?)</body>", index_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        escaped = html.escape(index_html)
        raise RuntimeError(f"Could not find <body> in frontend/index.html: {escaped[:120]}")
    return match.group("body")


def remove_stylesheet_links(body: str) -> str:
    return re.sub(r"<link\b[^>]*rel=[\"']stylesheet[\"'][^>]*>", "", body, flags=re.IGNORECASE)


def remove_script_tags(body: str) -> str:
    return re.sub(r"<script\b[^>]*>.*?</script>", "", body, flags=re.IGNORECASE | re.DOTALL)


if __name__ == "__main__":
    main()
