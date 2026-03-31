from fastapi.testclient import TestClient

from backend.agents.scaffold_web_agent.tenants import Tenant, upsert_tenant
from backend.main import app


def test_token_rotation(monkeypatch, tmp_path):
    import backend.agents.scaffold_web_agent.sqlite_store as ss

    monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "scaffold_test.db")

    monkeypatch.setenv("ADMIN_TOKEN", "admintest")

    upsert_tenant(
        Tenant(
            tenant_id="t1",
            widget_token="tok_old",
            inbox_email="inbox@scaffold.com",
            subject_prefix="[Scaffold Web Agent]",
            allowed_origins=["https://client.example"],
        )
    )

    client = TestClient(app)

    r = client.post(
        "/scaffold-agent/admin/tenants/t1/rotate-token",
        headers={"X-Admin-Token": "admintest"},
    )

    assert r.status_code == 200
    data = r.json()

    assert data["tenant_id"] == "t1"
    assert data["new_widget_token"].startswith("tok_")
    assert data["new_widget_token"] != "tok_old"
