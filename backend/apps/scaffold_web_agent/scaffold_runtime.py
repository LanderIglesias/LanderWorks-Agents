from __future__ import annotations

from .chat_service import ChatApplicationService
from .mailer import Mailer
from .runtime import RuntimeResult
from .tenants import Tenant


class ScaffoldAgentRuntime:
    agent_name = "scaffold_web_agent"

    def __init__(self, chat_service: ChatApplicationService) -> None:
        self._chat_service = chat_service

    def process_chat(
        self,
        *,
        tenant: Tenant,
        client_ip: str,
        session_id: str,
        message: str,
        mailer: Mailer,
    ) -> RuntimeResult:
        result = self._chat_service.process_chat(
            tenant=tenant,
            client_ip=client_ip,
            session_id=session_id,
            message=message,
            mailer=mailer,
        )

        return RuntimeResult(
            reply=result.reply,
            step=result.step,
            is_done=result.is_done,
        )
