"""Default Streamlit Cloud entrypoint for the HTML dashboard."""

from __future__ import annotations

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from streamlit_html_dashboard import main  # noqa: E402


if __name__ == "__main__":
    main()
