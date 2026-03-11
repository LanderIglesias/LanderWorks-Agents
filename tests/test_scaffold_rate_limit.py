from fastapi.testclient import TestClient

from backend.apps.scaffold_web_agent.tenants import Tenant, upsert_tenant
from backend.main import app


def test_rate_limit_blocks_after_threshold(monkeypatch, tmp_path):
    import backend.apps.scaffold_web_agent.sqlite_store as ss

    monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "scaffold_test.db")

    upsert_tenant(
        Tenant(
            tenant_id="t1",
            widget_token="tok_test_123",
            inbox_email="inbox@scaffold.com",
            subject_prefix="[Scaffold Web Agent]",
            allowed_origins=["https://client.example"],
        )
    )

    client = TestClient(app)
    headers = {
        "X-Widget-Token": "tok_test_123",
        "Origin": "https://client.example",
    }

    # 15 requests allowed
    for i in range(15):
        r = client.post(
            "/scaffold-agent/chat",
            json={"session_id": "s1", "message": f"msg-{i}"},
            headers=headers,
        )
        assert r.status_code == 200, r.text

    # 21st request blocked
    r = client.post(
        "/scaffold-agent/chat",
        json={"session_id": "s1", "message": "blocked"},
        headers=headers,
    )
    assert r.status_code == 429, r.text
    assert "Rate limit exceeded" in r.text
