import json

import numpy as np
import pytest

from aging_water_network.vision.drawing_recognition import (
    _parse_json_response,
    analyze_drawing_image,
    build_dashboard_assets_from_recognition,
    call_gemini_vision,
)


def test_parse_json_response_removes_markdown_fence():
    parsed = _parse_json_response('```json\n{"drawing_type":"water_network_drawing"}\n```')

    assert parsed == {"drawing_type": "water_network_drawing"}


def test_gemini_without_api_key_returns_configuration_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    result = call_gemini_vision(b"not-real-image", "image/png", api_key=None)

    assert result.error
    assert "GEMINI_API_KEY" in result.error


def test_analyze_drawing_image_extracts_synthetic_pipe_candidates():
    cv2 = pytest.importorskip("cv2")
    canvas = np.full((220, 320, 3), 255, dtype=np.uint8)
    cv2.line(canvas, (40, 60), (260, 60), (0, 0, 0), 4)
    cv2.line(canvas, (260, 60), (260, 170), (0, 0, 0), 4)
    cv2.circle(canvas, (40, 60), 9, (0, 0, 0), 2)
    cv2.circle(canvas, (260, 60), 9, (0, 0, 0), 2)
    cv2.circle(canvas, (260, 170), 9, (0, 0, 0), 2)
    ok, encoded = cv2.imencode(".png", canvas)
    assert ok

    result = analyze_drawing_image(encoded.tobytes(), "image/png", min_line_length=25)
    payload = json.loads(result.binary_payload.decode("utf-8"))

    assert result.width == 320
    assert result.height == 220
    assert len(result.line_segments) >= 2
    assert len(result.pipe_candidates) >= 2
    assert payload["image"]["mime_type"] == "image/png"
    assert payload["pipes"]


def test_recognition_result_exports_dashboard_assets():
    cv2 = pytest.importorskip("cv2")
    canvas = np.full((180, 280, 3), 255, dtype=np.uint8)
    cv2.line(canvas, (35, 70), (220, 70), (0, 0, 0), 4)
    cv2.circle(canvas, (35, 70), 8, (0, 0, 0), 2)
    cv2.circle(canvas, (220, 70), 8, (0, 0, 0), 2)
    ok, encoded = cv2.imencode(".png", canvas)
    assert ok

    result = analyze_drawing_image(encoded.tobytes(), "image/png", min_line_length=25)
    assets = build_dashboard_assets_from_recognition(result, scale_m_per_px=0.5)

    assert assets.nodes
    assert assets.pipes
    assert {"node_id", "x", "y", "node_type"}.issubset(assets.nodes[0])
    assert {"pipe_id", "from_node", "to_node", "length_m", "diameter_mm"}.issubset(assets.pipes[0])
    assert assets.reservoirs
