from __future__ import annotations

from .mailer import Mailer
from .tenants import Tenant


class DeliveryService:
    def deliver_lead(
        self,
        *,
        tenant: Tenant,
        category_value: str | None,
        summary: str,
        mailer: Mailer,
    ) -> None:
        subject = f"{tenant.subject_prefix} {category_value or 'inquiry'}"
        mailer.send(tenant.inbox_email, subject, summary)
