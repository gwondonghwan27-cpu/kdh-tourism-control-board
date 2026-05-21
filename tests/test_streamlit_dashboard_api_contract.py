from app.streamlit_html_dashboard import build_dashboard_html, is_loopback_api_base


def test_streamlit_embedded_dashboard_requires_backend_hydraulic_api() -> None:
    html = build_dashboard_html()

    assert "window.__STREAMLIT_EMBEDDED__ = true" in html
    assert "window.__REQUIRE_BACKEND_HYDRAULIC_API__ = true" in html
    assert "window.__ALLOW_FRONTEND_HYDRAULIC_FALLBACK__ = false" in html
    assert 'window.__DRAWING_RECOGNITION_API_BASE__ = ""' in html
    assert "Loopback API is not reachable from hosted Streamlit iframe" not in html


def test_loopback_api_base_is_never_treated_as_hosted_api() -> None:
    assert is_loopback_api_base("http://127.0.0.1:5181")
    assert is_loopback_api_base("http://localhost:5181")
    assert not is_loopback_api_base("https://example.com")
