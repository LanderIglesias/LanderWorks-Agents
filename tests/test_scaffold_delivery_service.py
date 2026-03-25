from backend.apps.scaffold_web_agent.delivery_service import DeliveryService
from backend.apps.scaffold_web_agent.tenants import Tenant


class DummyMailer:
    def __init__(self):
        self.sent = None

    def send(self, to_email: str, subject: str, body: str) -> None:
        self.sent = {
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }


def test_delivery_service_deliver_lead_uses_category_value():
    service = DeliveryService()
    mailer = DummyMailer()
    tenant = Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Scaffold]",
        allowed_origins=["http://localhost"],
    )

    service.deliver_lead(
        tenant=tenant,
        category_value="pricing",
        summary="Lead summary",
        mailer=mailer,
    )

    assert mailer.sent == {
        "to_email": "hello@example.com",
        "subject": "[Scaffold] pricing",
        "body": "Lead summary",
    }


def test_delivery_service_deliver_lead_falls_back_to_inquiry():
    service = DeliveryService()
    mailer = DummyMailer()
    tenant = Tenant(
        tenant_id="tenant-a",
        widget_token="tok_123",
        inbox_email="hello@example.com",
        subject_prefix="[Scaffold]",
        allowed_origins=["http://localhost"],
    )

    service.deliver_lead(
        tenant=tenant,
        category_value=None,
        summary="Lead summary",
        mailer=mailer,
    )

    assert mailer.sent == {
        "to_email": "hello@example.com",
        "subject": "[Scaffold] inquiry",
        "body": "Lead summary",
    }
