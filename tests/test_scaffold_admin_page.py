from fastapi.testclient import TestClient

from backend.main import app


def test_admin_page_served():
    client = TestClient(app)
    r = client.get("/scaffold-agent/admin/page")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Scaffold Admin" in r.text
