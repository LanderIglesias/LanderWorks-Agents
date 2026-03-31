from fastapi.testclient import TestClient

from backend.main import app


def test_widget_js_served():
    client = TestClient(app)
    r = client.get("/scaffold-agent/widget.js")
    assert r.status_code == 200
    assert "application/javascript" in r.headers.get("content-type", "")
    assert "X-Widget-Token" in r.text
