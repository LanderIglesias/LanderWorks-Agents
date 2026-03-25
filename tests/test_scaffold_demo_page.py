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


def test_admin_page_shows_agent_type_and_events():
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)

    response = client.get("/scaffold-agent/admin/page")
    html = response.text

    assert response.status_code == 200
    assert "Agent type" in html
    assert "Events" in html


def test_admin_page_shows_knowledge_section():
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)

    response = client.get("/scaffold-agent/admin/page")
    html = response.text

    assert response.status_code == 200
    assert "Knowledge" in html
