"""JSON stdin/stdout bridge for browser drawing recognition."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aging_water_network.vision import (  # noqa: E402
    analyze_drawing_image,
    build_dashboard_assets_from_recognition,
    call_gemini_vision,
)


def main() -> None:
    request = json.loads(sys.stdin.read() or "{}")
    image_bytes = base64.b64decode(request["image_base64"])
    mime_type = str(request.get("mime_type") or "image/png")
    min_line_length = int(float(request.get("min_line_length") or 45))
    merge_tolerance_px = float(request.get("merge_tolerance_px") or 18)

    opencv_result = analyze_drawing_image(
        image_bytes,
        mime_type,
        min_line_length=min_line_length,
        merge_tolerance_px=merge_tolerance_px,
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
    response: dict[str, Any] = {
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
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


def _gemini_to_dict(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "model": result.model,
        "parsed_json": result.parsed_json,
        "raw_text": result.raw_text,
        "error": result.error,
    }


if __name__ == "__main__":
    main()
