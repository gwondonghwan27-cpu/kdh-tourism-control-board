"""Serve the interactive HTML dashboard inside Streamlit Cloud."""

from __future__ import annotations

import html
import json
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
MOCK_DATA_DIR = REPO_ROOT / "data" / "mock"
SRC_DIR = REPO_ROOT / "src"


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
        height=2600,
        scrolling=False,
    )


def ensure_src_path() -> None:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))


def render_streamlit_recognition_controls(st: Any) -> dict[str, Any] | None:
    from aging_water_network.vision import build_dashboard_assets_from_recognition, recognize_drawing_file

    st.sidebar.header("Drawing recognition")
    uploaded = st.sidebar.file_uploader(
        "Water-network drawing file",
        type=["jpg", "jpeg", "png", "pdf", "dwg", "dxf"],
    )
    min_line_length = st.sidebar.slider("Minimum line length (px)", 10, 180, 35, 5)
    merge_tolerance = st.sidebar.slider("Endpoint merge tolerance (px)", 4, 42, 18, 1)
    scale_m_per_px = st.sidebar.number_input("Pixel-to-meter scale", min_value=0.01, max_value=20.0, value=1.0, step=0.05)
    default_diameter_mm = st.sidebar.number_input("Default diameter (mm)", min_value=50.0, max_value=1200.0, value=150.0, step=10.0)
    default_material = st.sidebar.selectbox("Default material", ["PVC", "HDPE", "ductile_iron", "steel", "cast_iron", "concrete"], index=0)
    col_a, col_b = st.sidebar.columns(2)
    analyze = col_a.button("Analyze", type="primary", disabled=uploaded is None)
    reset = col_b.button("Reset")

    if reset:
        st.session_state.pop("streamlit_recognized_assets", None)
        st.session_state.pop("streamlit_recognition_summary", None)
    if analyze and uploaded is not None:
        file_bytes = uploaded.getvalue()
        with st.spinner("Detecting file type and recognizing drawing geometry."):
            drawing_file_type, result = recognize_drawing_file(
                file_bytes,
                filename=uploaded.name,
                mime_type=uploaded.type or mime_type_from_filename(uploaded.name),
                min_line_length=min_line_length,
                merge_tolerance_px=float(merge_tolerance),
            )
            assets = build_dashboard_assets_from_recognition(
                result,
                scale_m_per_px=scale_m_per_px,
                default_diameter_mm=default_diameter_mm,
                default_material=default_material,
                include_virtual_reservoir=True,
            )
        st.session_state.streamlit_recognized_assets = assets.to_dict()
        st.session_state.streamlit_recognition_summary = {
            **result.summary(),
            "file_type": drawing_file_type,
            "cad_format": getattr(result, "cad_format", None),
            "pdf_mode": getattr(result, "pdf_mode", None),
            "warnings": getattr(result, "warnings", []),
        }

    summary = st.session_state.get("streamlit_recognition_summary")
    if summary:
        route = summary.get("file_type", "drawing")
        st.sidebar.caption(
            f"{route} result: {summary['pipe_candidates']} pipes / "
            f"{summary['node_candidates']} node candidates"
        )
        for warning in summary.get("warnings", []):
            st.sidebar.warning(warning)
    return st.session_state.get("streamlit_recognized_assets")


def ensure_local_recognition_api(st: Any) -> str | None:
    """Start the local dashboard API so the embedded canvas can recognize drawings."""

    for port in range(5181, 5190):
        api_base = f"http://127.0.0.1:{port}"
        if is_recognition_api_ready(api_base):
            st.sidebar.caption(f"Canvas recognition API: {api_base}")
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
        for _ in range(20):
            if is_recognition_api_ready(api_base):
                st.sidebar.caption(f"Canvas recognition API: {api_base}")
                return api_base
            if process.poll() is not None:
                break
            time.sleep(0.1)
    st.sidebar.warning("Canvas recognition API could not start. Use the sidebar Analyze button instead.")
    return None


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def is_recognition_api_ready(api_base: str) -> bool:
    try:
        with urllib.request.urlopen(f"{api_base}/api/health", timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return (
                response.status == 200
                and payload.get("ok") is True
                and payload.get("service") == "drawing-recognition-api"
                and payload.get("supports_cors") is True
            )
    except (OSError, json.JSONDecodeError):
        return False


def mime_type_from_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".pdf": "application/pdf",
        ".dwg": "application/x-dwg",
        ".dxf": "application/dxf",
    }.get(suffix, "application/octet-stream")


def build_dashboard_html(
    recognized_assets: dict[str, Any] | None = None,
    recognition_api_base: str | None = None,
) -> str:
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
    <title>Water Network Digital Twin</title>
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
      window.__STREAMLIT_RECOGNIZED_ASSETS__ = {json.dumps(recognized_assets, ensure_ascii=False)};
      window.__STREAMLIT_MOCK_CSV__ = {json.dumps(csv_payload, ensure_ascii=False)};
      window.__DRAWING_RECOGNITION_API_BASE__ = {json.dumps(recognition_api_base or "", ensure_ascii=False)};
      const __streamlitOriginalFetch = window.fetch ? window.fetch.bind(window) : null;
      window.fetch = async function(resource, options) {{
        const url = typeof resource === "string" ? resource : resource?.url || "";
        const route = decodeURIComponent(String(url).split("?")[0]);
        const fileName = route.split("/").pop();
        if (route.endsWith("/api/recognize-drawing") && window.__DRAWING_RECOGNITION_API_BASE__) {{
          const apiBase = String(window.__DRAWING_RECOGNITION_API_BASE__).replace(/\\/$/, "");
          if (__streamlitOriginalFetch) return __streamlitOriginalFetch(`${{apiBase}}/api/recognize-drawing`, options);
        }}
        if (Object.prototype.hasOwnProperty.call(window.__STREAMLIT_MOCK_CSV__, fileName)) {{
          return new Response(window.__STREAMLIT_MOCK_CSV__[fileName], {{
            status: 200,
            headers: {{ "Content-Type": "text/csv;charset=utf-8" }},
          }});
        }}
        if (route.endsWith("/api/recognize-drawing")) {{
          return new Response(JSON.stringify({{
            error: "Use the Streamlit sidebar uploader for cloud drawing recognition."
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
