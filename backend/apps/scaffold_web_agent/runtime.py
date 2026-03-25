from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .mailer import Mailer
from .tenants import Tenant


@dataclass(frozen=True)
class RuntimeResult:
    reply: str
    step: str
    is_done: bool


class AgentRuntime(Protocol):
    agent_name: str

    def process_chat(
        self,
        *,
        tenant: Tenant,
        client_ip: str,
        session_id: str,
        message: str,
        mailer: Mailer,
    ) -> RuntimeResult: ...
