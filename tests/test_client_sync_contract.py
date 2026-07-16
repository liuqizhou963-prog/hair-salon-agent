from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_customer_h5_and_miniprogram_read_the_shared_appointment_endpoint():
    h5 = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    miniprogram = (PROJECT_ROOT / "frontend" / "miniprogram" / "app.js").read_text(encoding="utf-8")
    config = (PROJECT_ROOT / "frontend" / "miniprogram" / "config.js").read_text(encoding="utf-8")

    assert 'apiGet("/api/appointments")' in h5
    assert 'this.request("/api/appointments")' in miniprogram
    assert 'apiBase: appConfig.apiBase' in miniprogram
    assert 'apiBase: "http://127.0.0.1:8001"' in config
