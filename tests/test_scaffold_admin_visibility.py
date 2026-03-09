from fastapi.testclient import TestClient

from backend.apps.scaffold_web_agent.tenants import Tenant, upsert_tenant
from backend.main import app


def test_admin_list_tenants(monkeypatch, tmp_path):
    import backend.apps.scaffold_web_agent.sqlite_store as ss

    monkeypatch.setattr(ss, "_db_path", lambda: tmp_path / "scaffold_test.db")

    monkeypatch.setenv("ADMIN_TOKEN", "admintest")

    upsert_tenant(
        Tenant(
            tenant_id="t1",
            widget_token="tok_test",
            inbox_email="inbox@test.com",
            subject_prefix="[Test]",
            allowed_origins=["https://client.example"],
        )
    )

    client = TestClient(app)

    r = client.get(
        "/scaffold-agent/admin/tenants",
        headers={"X-Admin-Token": "admintest"},
    )

    assert r.status_code == 200
    data = r.json()

    assert len(data["tenants"]) == 1
    assert data["tenants"][0]["tenant_id"] == "t1"
