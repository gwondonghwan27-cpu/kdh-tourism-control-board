"""Streamlit tool for JPG/PNG water-network drawing recognition."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aging_water_network.vision import analyze_drawing_image, call_gemini_vision  # noqa: E402


MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def main() -> None:
    st.set_page_config(page_title="관망 도면 인식", layout="wide")
    st.title("관망 도면 이미지 인식")
    st.caption("JPG/PNG 도면을 OpenCV로 먼저 구조화하고, 필요하면 Gemini Vision으로 의미 해석을 보강합니다.")

    uploaded = st.file_uploader("관망 도면 이미지 업로드", type=["jpg", "jpeg", "png"])
    with st.sidebar:
        st.header("Recognition setup")
        min_line_length = st.slider("최소 선분 길이(px)", 10, 160, 35, 5)
        merge_tolerance = st.slider("끝점 병합 허용치(px)", 4, 40, 16, 1)
        use_gemini = st.checkbox("Gemini Vision 보조 분석 사용", value=False)
        model = st.text_input("Gemini model", value="gemini-2.5-flash")
        api_key = st.text_input("Gemini API key", type="password", help="비워두면 GEMINI_API_KEY/GOOGLE_API_KEY 환경변수를 사용합니다.")

    if uploaded is None:
        render_empty_state()
        return

    image_bytes = uploaded.getvalue()
    suffix = Path(uploaded.name).suffix.lower()
    mime_type = MIME_BY_EXTENSION.get(suffix, uploaded.type or "")
    left, right = st.columns([0.95, 1.05])
    with left:
        st.subheader("입력 도면")
        st.image(image_bytes, caption=uploaded.name, use_container_width=True)

    if st.button("도면 분석 실행", type="primary"):
        with st.spinner("OpenCV로 선분, 노드 후보, pipe 후보를 추출하는 중입니다."):
            opencv_result = analyze_drawing_image(
                image_bytes,
                mime_type,
                min_line_length=min_line_length,
                merge_tolerance_px=float(merge_tolerance),
            )

        gemini_result = None
        if use_gemini:
            with st.spinner("Gemini Vision으로 도면 의미를 보조 해석하는 중입니다."):
                gemini_result = call_gemini_vision(
                    image_bytes,
                    mime_type,
                    api_key=api_key.strip() or None,
                    model=model.strip() or "gemini-2.5-flash",
                )

        st.session_state.drawing_recognition = {
            "opencv": opencv_result,
            "gemini": gemini_result,
        }

    stored = st.session_state.get("drawing_recognition")
    if not stored:
        with right:
            st.info("분석 버튼을 누르면 이 영역에 추출 결과가 표시됩니다.")
        return

    opencv_result = stored["opencv"]
    gemini_result = stored.get("gemini")
    with right:
        st.subheader("OpenCV 추출 오버레이")
        st.image(opencv_result.overlay_image, caption="파란색: pipe 후보, 초록색: node/symbol 후보", use_container_width=True)
        render_summary(opencv_result.summary())

    render_opencv_tables(opencv_result)
    render_binary_payload(opencv_result.binary_payload)
    if gemini_result is not None:
        render_gemini_result(gemini_result)


def render_empty_state() -> None:
    st.info("먼저 `.jpg`, `.jpeg`, `.png` 관망 도면을 올려주세요.")
    st.markdown(
        """
        구현 흐름:
        1. OpenCV가 이미지에서 선분과 원형/기호 후보를 추출합니다.
        2. 선분 끝점을 가까운 것끼리 병합해서 임시 node/pipe 구조를 만듭니다.
        3. Gemini Vision은 텍스트, 범례, 밸브/펌프 같은 의미 해석을 JSON 힌트로 제공합니다.
        4. OpenCV 결과와 Gemini 결과를 검증한 뒤 내부 binary payload로 저장합니다.
        """
    )


def render_summary(summary: dict[str, int]) -> None:
    cols = st.columns(4)
    cols[0].metric("이미지 크기", f"{summary['width']} x {summary['height']}")
    cols[1].metric("선분 후보", summary["line_segments"])
    cols[2].metric("노드/기호 후보", summary["node_candidates"])
    cols[3].metric("Binary bytes", summary["binary_payload_bytes"])


def render_opencv_tables(opencv_result: Any) -> None:
    st.subheader("OpenCV 구조화 결과")
    tabs = st.tabs(["Pipe 후보", "Line 후보", "Node/Symbol 후보", "전처리 이미지"])
    with tabs[0]:
        st.dataframe(pd.DataFrame(opencv_result.pipe_candidates), hide_index=True, use_container_width=True)
    with tabs[1]:
        st.dataframe(pd.DataFrame(opencv_result.line_segments), hide_index=True, use_container_width=True)
    with tabs[2]:
        st.dataframe(pd.DataFrame(opencv_result.node_candidates), hide_index=True, use_container_width=True)
    with tabs[3]:
        st.image(opencv_result.threshold_image, caption="이진화 결과", use_container_width=True)
        st.image(opencv_result.edge_image, caption="Canny edge 결과", use_container_width=True)


def render_binary_payload(binary_payload: bytes) -> None:
    st.subheader("프로그램 내부 binary payload 초안")
    st.caption("현재는 JSON 구조를 UTF-8 bytes로 직렬화한 형태입니다. 다음 단계에서 더 작은 전용 binary 포맷으로 바꿀 수 있습니다.")
    decoded = json.loads(binary_payload.decode("utf-8"))
    st.download_button(
        "binary payload 다운로드",
        data=binary_payload,
        file_name="recognized_network_payload.bin",
        mime="application/octet-stream",
    )
    st.json(decoded, expanded=False)


def render_gemini_result(gemini_result: Any) -> None:
    st.subheader("Gemini Vision 보조 해석")
    if gemini_result.error:
        st.warning(gemini_result.error)
        return
    if gemini_result.parsed_json is not None:
        st.json(gemini_result.parsed_json)
    else:
        st.text_area("Raw Gemini response", gemini_result.raw_text, height=260)


if __name__ == "__main__":
    main()
