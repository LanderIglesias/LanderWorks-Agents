from fastapi.testclient import TestClient

from backend.main import app


def test_demo_page_served():
    client = TestClient(app)
    r = client.get("/scaffold-agent/demo?token=tok_test_123")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Scaffold Agent Demo" in r.text
    assert "tok_test_123" in r.text
    assert "/scaffold-agent/widget.js?token=tok_test_123" in r.text
