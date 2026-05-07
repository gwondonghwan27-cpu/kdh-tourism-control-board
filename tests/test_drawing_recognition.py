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


def test_blue_jpg_drawing_uses_color_masks_to_avoid_background_noise():
    cv2 = pytest.importorskip("cv2")
    canvas = np.full((360, 520, 3), 250, dtype=np.uint8)
    for x in range(20, 500, 25):
        cv2.line(canvas, (x, 20), (x, 340), (232, 236, 240), 1)
    for y in range(20, 340, 25):
        cv2.line(canvas, (20, y), (500, y), (232, 236, 240), 1)
    cv2.line(canvas, (40, 180), (480, 195), (215, 210, 198), 22)
    blue = (178, 112, 24)
    pipes = [
        ((70, 170), (160, 165)),
        ((160, 165), (260, 190)),
        ((260, 190), (360, 178)),
        ((360, 178), (455, 155)),
        ((160, 165), (145, 270)),
        ((260, 190), (245, 285)),
        ((360, 178), (395, 275)),
    ]
    nodes = [(70, 170), (160, 165), (260, 190), (360, 178), (455, 155), (145, 270), (245, 285), (395, 275)]
    for start, end in pipes:
        cv2.line(canvas, start, end, blue, 8)
        cv2.line(canvas, start, end, (245, 250, 255), 1)
    for index, point in enumerate(nodes, 1):
        cv2.circle(canvas, point, 10, (255, 255, 255), -1)
        cv2.circle(canvas, point, 10, (72, 145, 80), 2)
        cv2.putText(canvas, f"J-{index:02d}", (point[0] + 10, point[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (35, 45, 55), 1)
    cv2.putText(canvas, "D250 MAIN", (210, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50, 90, 125), 1)
    ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
    assert ok

    result = analyze_drawing_image(encoded.tobytes(), "image/jpeg", min_line_length=30)
    assets = build_dashboard_assets_from_recognition(result)

    assert 4 <= len(result.node_candidates) <= len(nodes)
    assert len(result.pipe_candidates) <= len(pipes) + 2
    assert len(assets.nodes) <= len(nodes) + len(assets.reservoirs)
    assert len(assets.pipes) <= len(pipes) + len(assets.reservoirs) + 2
