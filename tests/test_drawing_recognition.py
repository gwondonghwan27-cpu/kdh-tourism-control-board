import json

import numpy as np
import pytest

from aging_water_network.vision.drawing_recognition import (
    analyze_drawing_cad,
    analyze_drawing_pdf,
    _parse_json_response,
    analyze_drawing_image,
    build_dashboard_assets_from_recognition,
    call_gemini_vision,
    detect_drawing_file_type,
    recognize_drawing_file,
    semantic_samples_from_gemini,
    validate_recognition_quality,
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


def test_semantic_gemini_hints_convert_to_opencv_samples():
    parsed = {
        "schema_version": "water_network_extract_v1",
        "drawing_type": "water_network",
        "junctions": [
            {
                "label": "J-1",
                "asset_type": "junction",
                "bbox": {"x1": 90, "y1": 40, "x2": 110, "y2": 60},
                "confidence": 0.83,
                "source_text": "J-1",
                "is_inferred": False,
                "needs_review": False,
            }
        ],
        "pipes": [
            {
                "label": "P-1",
                "from_label": "J-1",
                "to_label": "J-2",
                "bbox": {"x1": 120, "y1": 55, "x2": 240, "y2": 75},
                "confidence": 0.7,
                "source_text": "D150",
                "is_inferred": False,
                "needs_review": False,
            }
        ],
    }

    samples = semantic_samples_from_gemini(parsed, image_width=400, image_height=300)

    assert samples["junction_anchor_samples"] == [
        {"x": 100.0, "y": 50.0, "radius_px": 10.0, "source": "gemini_semantic_bbox", "confidence": 0.83}
    ]
    assert samples["pipe_candidate_samples"][0]["x"] == 180.0
    assert samples["pipe_candidate_samples"][0]["source"] == "gemini_semantic_bbox"


def test_validate_recognition_quality_flags_review_risks():
    nodes = [{"id": "N1", "x": 10, "y": 10}, {"id": "N2", "x": 80, "y": 10}, {"id": "N3", "x": 180, "y": 10}]
    pipes = [
        {"id": "P1", "from_node": "N1", "to_node": "N2", "length_px": 70, "confidence": 0.91},
        {"id": "P2", "from_node": "N1", "to_node": "N4", "length_px": 35, "confidence": 0.4},
    ]

    report = validate_recognition_quality(nodes, pipes, image_width=120, image_height=90)
    reasons = {item["reason"] for item in report["review_items"]}

    assert report["counts"]["review_pipes"] == 1
    assert "low_confidence" in reasons
    assert "endpoint_missing_node" in reasons
    assert "coordinate_out_of_bounds" in reasons
    assert report["can_auto_apply"] is False


def test_detect_drawing_file_type_routes_images_and_cad_files():
    assert detect_drawing_file_type(b"\x89PNG\r\n\x1a\n", filename="network.png", mime_type="") == "image"
    assert detect_drawing_file_type(b"%PDF-1.4", filename="network.pdf", mime_type="") == "pdf"
    assert detect_drawing_file_type(b"AC1027\x00\x00", filename="network.dwg", mime_type="application/octet-stream") == "cad"
    assert detect_drawing_file_type(b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", filename="network.dxf", mime_type="") == "cad"
    assert detect_drawing_file_type(b"plain text", filename="network.txt", mime_type="text/plain") == "unknown"


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
    assert result.line_segments
    assert result.pipe_candidates
    assert len(result.pipe_candidates) >= 2
    assert any(node.get("hits", 1) >= 2 for node in payload["nodes"])
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


def test_source_pump_candidate_sets_dashboard_source_location():
    cv2 = pytest.importorskip("cv2")
    canvas = np.full((180, 280, 3), 255, dtype=np.uint8)
    cv2.line(canvas, (80, 70), (220, 70), (0, 0, 0), 4)
    cv2.circle(canvas, (80, 70), 8, (0, 0, 0), 2)
    cv2.circle(canvas, (220, 70), 8, (0, 0, 0), 2)
    ok, encoded = cv2.imencode(".png", canvas)
    assert ok

    result = analyze_drawing_image(
        encoded.tobytes(),
        "image/png",
        min_line_length=25,
        source_pump_candidate_samples=[{"x": 30, "y": 70}],
    )
    assets = build_dashboard_assets_from_recognition(result)
    source_node = next(node for node in assets.nodes if node["node_id"] == "R_IMG_1")

    assert source_node["x"] == 30
    assert source_node["node_type"] == "reservoir"
    assert assets.pumps
    assert assets.pumps[0]["from_node"] == "R_IMG_1"


def test_grayscale_pipe_drawing_uses_color_agnostic_path_extraction():
    cv2 = pytest.importorskip("cv2")
    canvas = np.full((260, 360, 3), 250, dtype=np.uint8)
    pipe_color = (70, 70, 70)
    points = [(50, 80), (170, 80), (280, 120), (220, 210), (90, 200)]
    for start, end in zip(points, points[1:]):
        cv2.line(canvas, start, end, pipe_color, 7)
    for point in points:
        cv2.circle(canvas, point, 8, (40, 40, 40), 2)
    ok, encoded = cv2.imencode(".png", canvas)
    assert ok

    result = analyze_drawing_image(encoded.tobytes(), "image/png", min_line_length=30)
    assets = build_dashboard_assets_from_recognition(result)

    assert len(result.pipe_candidates) >= 2
    assert assets.pipes
    assert any(pipe.get("geometry_type") in {"straight", "curved"} for pipe in result.pipe_candidates)


def test_dxf_cad_route_extracts_vector_lines_into_dashboard_assets():
    dxf = b"""0
SECTION
2
ENTITIES
0
LINE
8
PIPE
10
0
20
0
11
100
21
0
0
LINE
8
PIPE
10
100
20
0
11
100
21
80
0
ENDSEC
0
EOF
"""

    result = analyze_drawing_cad(dxf, filename="network.dxf")
    assets = build_dashboard_assets_from_recognition(result)

    assert result.cad_format == "dxf"
    assert len(result.line_segments) == 2
    assert len(result.pipe_candidates) == 2
    assert assets.nodes
    assert assets.pipes


def test_dxf_layer_roles_keep_annotations_out_of_pipe_candidates():
    dxf = b"""0
SECTION
2
ENTITIES
0
LINE
8
WATER_PIPE
10
0
20
0
11
100
21
0
0
LINE
8
TEXT_LABEL
10
0
20
50
11
100
21
50
0
ENDSEC
0
EOF
"""

    result = analyze_drawing_cad(dxf, filename="network.dxf")

    assert {segment["layer_role"] for segment in result.line_segments} == {"pipe", "annotation"}
    assert len(result.pipe_candidates) == 1
    assert result.pipe_candidates[0]["source_layer"] == "WATER_PIPE"
    assert any("DXF layer hints detected" in warning for warning in result.warnings)


def test_dwg_cad_route_is_detected_without_using_image_decoder():
    drawing_type, result = recognize_drawing_file(b"AC1027 fake dwg bytes", filename="network.dwg", mime_type="application/octet-stream")

    assert drawing_type == "cad"
    assert result.cad_format == "dwg"
    assert result.warnings


def test_uncompressed_pdf_route_extracts_vector_lines_into_dashboard_assets():
    pdf = b"""%PDF-1.4
1 0 obj
<< /Length 34 >>
stream
0 0 m
100 0 l
100 80 l
S
endstream
endobj
%%EOF
"""

    result = analyze_drawing_pdf(pdf, filename="network.pdf")
    assets = build_dashboard_assets_from_recognition(result)

    assert result.pdf_mode == "vector_uncompressed"
    assert len(result.line_segments) == 2
    assert len(result.pipe_candidates) == 2
    assert assets.nodes
    assert assets.pipes


def test_pdf_route_is_selected_without_using_image_decoder():
    drawing_type, result = recognize_drawing_file(b"%PDF-1.4\n%%EOF", filename="network.pdf", mime_type="application/pdf")

    assert drawing_type == "pdf"
    assert result.pdf_mode in {"unresolved", "vector_uncompressed", "vector", "scanned_image"}


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
    assert len(assets.nodes) <= len(nodes) + len(assets.reservoirs) + 5
    assert len(assets.pipes) <= len(pipes) + len(assets.reservoirs) + 2


def test_junction_anchor_samples_drive_pipe_connection_inference():
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
    anchors = [(70, 170), (160, 165), (260, 190), (360, 178), (455, 155), (145, 270), (245, 285), (395, 275)]
    for start, end in pipes:
        cv2.line(canvas, start, end, blue, 8)
        cv2.line(canvas, start, end, (245, 250, 255), 1)
    for point in anchors:
        cv2.circle(canvas, point, 10, (255, 255, 255), -1)
        cv2.circle(canvas, point, 10, (72, 145, 80), 2)
    ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
    assert ok

    result = analyze_drawing_image(
        encoded.tobytes(),
        "image/jpeg",
        min_line_length=30,
        junction_anchor_samples=[{"x": x, "y": y} for x, y in anchors],
    )
    payload = json.loads(result.binary_payload.decode("utf-8"))
    assets = build_dashboard_assets_from_recognition(result)

    assert payload["semantic_hints"]["pipeline"] == "junction_anchor_pipe_path_graph"
    assert len(payload["nodes"]) == len(anchors)
    assert len(result.pipe_candidates) >= len(pipes) - 1
    assert all(node["source"] == "user_junction_anchor" for node in payload["nodes"])
    assert assets.pipes


def test_pipe_candidate_samples_reinforce_missing_anchor_connections_without_replacing_graph():
    cv2 = pytest.importorskip("cv2")
    canvas = np.full((220, 420, 3), 250, dtype=np.uint8)
    blue = (178, 112, 24)
    anchors = [(60, 110), (200, 110), (340, 110)]
    cv2.line(canvas, anchors[0], anchors[1], blue, 8)
    for start_x in range(206, 330, 28):
        cv2.line(canvas, (start_x, 110), (min(start_x + 6, 340), 110), blue, 8)
    for point in anchors:
        cv2.circle(canvas, point, 10, (255, 255, 255), -1)
        cv2.circle(canvas, point, 10, (72, 145, 80), 2)
    ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
    assert ok

    without_pipe_candidate = analyze_drawing_image(
        encoded.tobytes(),
        "image/jpeg",
        min_line_length=25,
        merge_tolerance_px=18,
        junction_anchor_samples=[{"x": x, "y": y} for x, y in anchors],
    )
    with_pipe_candidate = analyze_drawing_image(
        encoded.tobytes(),
        "image/jpeg",
        min_line_length=25,
        merge_tolerance_px=18,
        junction_anchor_samples=[{"x": x, "y": y} for x, y in anchors],
        pipe_candidate_samples=[{"x": 270, "y": 110}],
    )
    payload = json.loads(with_pipe_candidate.binary_payload.decode("utf-8"))

    assert len(with_pipe_candidate.pipe_candidates) >= len(without_pipe_candidate.pipe_candidates)
    assert any(pipe.get("source") == "user_pipe_candidate" for pipe in with_pipe_candidate.pipe_candidates)
    assert payload["semantic_hints"]["pipe_candidate_count"] == 1
