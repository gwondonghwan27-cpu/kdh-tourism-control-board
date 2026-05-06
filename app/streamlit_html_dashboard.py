"""Serve the interactive HTML dashboard inside Streamlit.

This app intentionally reuses the static frontend files instead of rebuilding the
dashboard with Streamlit widgets. That keeps the Streamlit deployment visually
and behaviorally aligned with ``frontend/index.html``.
"""

from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
MOCK_DATA_DIR = REPO_ROOT / "data" / "mock"


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
          }
          footer { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    components.html(build_dashboard_html(), height=2500, scrolling=True)


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
