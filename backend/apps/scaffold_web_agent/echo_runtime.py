from __future__ import annotations

from .mailer import Mailer
from .runtime import RuntimeResult
from .tenants import Tenant


class EchoAgentRuntime:
    agent_name = "echo_web_agent"

    def process_chat(
        self,
        *,
        tenant: Tenant,
        client_ip: str,
        session_id: str,
        message: str,
        mailer: Mailer,
    ) -> RuntimeResult:
        return RuntimeResult(
            reply=f"[echo:{tenant.tenant_id}] {message}",
            step="done",
            is_done=True,
        )
