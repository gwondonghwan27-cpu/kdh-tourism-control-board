from app.streamlit_html_dashboard import build_dashboard_html


def test_streamlit_embedded_dashboard_requires_backend_hydraulic_api() -> None:
    html = build_dashboard_html(recognition_api_base="http://127.0.0.1:5181")

    assert "window.__STREAMLIT_EMBEDDED__ = true" in html
    assert "window.__REQUIRE_BACKEND_HYDRAULIC_API__ = true" in html
    assert "window.__ALLOW_FRONTEND_HYDRAULIC_FALLBACK__ = false" in html
    assert "http://127.0.0.1:5181" in html
