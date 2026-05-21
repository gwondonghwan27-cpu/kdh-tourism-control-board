"""Serve the interactive HTML dashboard inside Streamlit Cloud."""

from __future__ import annotations

import html
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
SRC_DIR = REPO_ROOT / "src"


STREAMLIT_DASHBOARD_HEIGHT = 4200
DASHBOARD_API_VERSION = "2026-05-21-source-id-alignment"


def main() -> None:
    import streamlit as st
    import streamlit.components.v1 as components

    ensure_src_path()
    st.set_page_config(
        page_title="Water Network Digital Twin",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(
        """
        <style>
          .stApp { background: #f6f9fc; }
          .stAppViewContainer,
          .main,
          section[data-testid="stMain"],
          div[data-testid="stMainBlockContainer"],
          div[data-testid="stVerticalBlock"],
          div[data-testid="stElementContainer"] {
            width: 100% !important;
            max-width: none !important;
          }
          .block-container {
            padding: 0 !important;
            max-width: none !important;
            width: 100% !important;
          }
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
            width: 100% !important;
            max-width: none !important;
            min-height: 100vh;
            border: 0;
          }
          footer { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    recognized_assets = render_streamlit_recognition_controls(st)
    recognition_api_base = ensure_local_recognition_api(st)
    components.html(
        build_dashboard_html(recognized_assets=recognized_assets, recognition_api_base=recognition_api_base),
        height=STREAMLIT_DASHBOARD_HEIGHT,
        scrolling=True,
    )


def ensure_src_path() -> None:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))


def render_streamlit_recognition_controls(st: Any) -> dict[str, Any] | None:
    st.sidebar.header("상수도 관망 도면 .inp 업로드")
    st.sidebar.caption("상단의 도면 .inp 업로드 화면에서 EPANET 관망 파일을 불러오고, 관망 적용 후 GIS 대시보드에서 확인합니다.")
    st.session_state.pop("streamlit_recognized_assets", None)
    st.session_state.pop("streamlit_recognition_summary", None)
    return None


def ensure_local_recognition_api(st: Any) -> str | None:
    """Start the local dashboard API used by the embedded HTML dashboard."""

    configured_api_base = configured_recognition_api_base(st)
    if configured_api_base:
        if is_recognition_api_ready(configured_api_base):
            st.sidebar.caption(f"관망 계산 API: {configured_api_base}")
            return configured_api_base
        st.sidebar.warning("설정된 관망 계산 API에 연결할 수 없습니다. Streamlit 내장 fallback 계산으로 동작합니다.")
        return None

    st.sidebar.caption("관망 계산 API: Streamlit 동일 서버 /api/simulate-network")
    return None

    for port in range(5181, 5200):
        api_base = f"http://127.0.0.1:{port}"
        if is_recognition_api_ready(api_base):
            st.sidebar.caption(f"관망 계산 API: {api_base}")
            return api_base
        if not is_port_available("127.0.0.1", port):
            continue
        process = subprocess.Popen(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "dashboard_server.py"),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        st.session_state.streamlit_recognition_api_process = process.pid
        for _ in range(80):
            if is_recognition_api_ready(api_base):
                st.sidebar.caption(f"관망 계산 API: {api_base}")
                return api_base
            if process.poll() is not None:
                break
            time.sleep(0.1)
    st.sidebar.warning("관망 계산 API를 시작하지 못했습니다. 정밀 해석 기능만 제한될 수 있습니다.")
    return None


def configured_recognition_api_base(st: Any) -> str | None:
    """Return an externally reachable API base for hosted Streamlit deployments."""

    candidates: list[Any] = [
        os.environ.get("DASHBOARD_API_BASE_URL"),
        os.environ.get("DRAWING_RECOGNITION_API_BASE"),
    ]
    try:
        candidates.extend(
            [
                st.secrets.get("DASHBOARD_API_BASE_URL"),
                st.secrets.get("DRAWING_RECOGNITION_API_BASE"),
            ],
        )
    except Exception:
        pass
    for candidate in candidates:
        api_base = str(candidate or "").strip().rstrip("/")
        if api_base:
            return api_base
    return None


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def is_recognition_api_ready(api_base: str) -> bool:
    try:
        with urllib.request.urlopen(f"{api_base}/api/health", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return (
                response.status == 200
                and payload.get("ok") is True
                and payload.get("service") == "drawing-recognition-api"
                and payload.get("dashboard_api_version") == DASHBOARD_API_VERSION
                and payload.get("supports_cors") is True
            )
    except (OSError, json.JSONDecodeError):
        return False


def build_dashboard_html(
    recognized_assets: dict[str, Any] | None = None,
    recognition_api_base: str | None = None,
) -> str:
    index_html = read_text(FRONTEND_DIR / "index.html")
    css = read_text(FRONTEND_DIR / "styles.css")
    app_js = read_text(FRONTEND_DIR / "app.js")

    body = extract_body(index_html)
    body = remove_stylesheet_links(body)
    body = remove_script_tags(body)

    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Water Network Digital Twin</title>
    <style>
      html, body {{
        margin: 0;
        min-height: 100%;
        overflow-x: hidden;
        overflow-y: auto;
      }}
      {css}
    </style>
  </head>
  <body>
    {body}
    <script>
      window.__STREAMLIT_RECOGNIZED_ASSETS__ = {json.dumps(recognized_assets, ensure_ascii=False)};
      window.__DRAWING_RECOGNITION_API_BASE__ = {json.dumps(recognition_api_base or "", ensure_ascii=False)};
      const __streamlitOriginalFetch = window.fetch ? window.fetch.bind(window) : null;
      window.fetch = async function(resource, options) {{
        const url = typeof resource === "string" ? resource : resource?.url || "";
        const route = decodeURIComponent(String(url).split("?")[0]);
        if (route.endsWith("/api/simulate-network") && window.__DRAWING_RECOGNITION_API_BASE__) {{
          const apiBase = String(window.__DRAWING_RECOGNITION_API_BASE__).replace(/\\/$/, "");
          const isLoopbackApi = /^(https?:\\/\\/)?(127\\.0\\.0\\.1|localhost)(:|\\/|$)/i.test(apiBase);
          const hostContext = `${{window.location.hostname || ""}} ${{document.referrer || ""}}`;
          const isLocalStreamlit = /(^|\\/\\/)(localhost|127\\.0\\.0\\.1)(:|\\/|$)/i.test(hostContext);
          if (isLoopbackApi && !isLocalStreamlit) {{
            return new Response(JSON.stringify({{
              error: "Loopback API is not reachable from hosted Streamlit iframe."
            }}), {{
              status: 501,
              headers: {{ "Content-Type": "application/json;charset=utf-8" }},
            }});
          }}
          if (__streamlitOriginalFetch) return __streamlitOriginalFetch(`${{apiBase}}/api/simulate-network`, options);
        }}
        if (route.endsWith("/api/simulate-network")) {{
          if (__streamlitOriginalFetch) return __streamlitOriginalFetch(resource, options);
          return new Response(JSON.stringify({{
            error: "Streamlit simulation API is not available for this operation."
          }}), {{
            status: 501,
            headers: {{ "Content-Type": "application/json;charset=utf-8" }},
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
