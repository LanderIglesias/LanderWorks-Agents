from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from .delivery_service import DeliveryService
from .domain import Status, Step
from .engine import handle_user_message
from .event_service import EventService
from .lead_service import LeadService
from .mailer import Mailer
from .rate_limit import is_rate_limited
from .session_service import SessionService
from .tenants import Tenant


@dataclass(frozen=True)
class ChatResult:
    reply: str
    step: str
    is_done: bool


class ChatApplicationService:
    def __init__(
        self,
        session_service: SessionService,
        lead_service: LeadService,
        delivery_service: DeliveryService,
        event_service: EventService,
    ) -> None:
        self._session_service = session_service
        self._lead_service = lead_service
        self._delivery_service = delivery_service
        self._event_service = event_service

    def process_chat(
        self,
        *,
        tenant: Tenant,
        client_ip: str,
        session_id: str,
        message: str,
        mailer: Mailer,
    ) -> ChatResult:
        if is_rate_limited(tenant.tenant_id, client_ip):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        self._event_service.record(
            tenant_id=tenant.tenant_id,
            session_id=session_id,
            event_type="chat_requested",
            event_payload={
                "client_ip": client_ip,
                "message_length": len(message),
            },
        )

        state = self._session_service.get_state(tenant.tenant_id, session_id)
        context_message = message

        if tenant.knowledge_text:
            context_message = (
                f"[CLIENT KNOWLEDGE]\n{tenant.knowledge_text}\n\n" f"[USER MESSAGE]\n{message}"
            )

        new_state, reply = handle_user_message(state, context_message)

        self._event_service.record(
            tenant_id=tenant.tenant_id,
            session_id=session_id,
            event_type="chat_replied",
            event_payload={
                "step": new_state.step.value,
                "is_done": new_state.step == Step.DONE,
            },
        )

        if new_state.step == Step.SEND:
            if not new_state.data.summary or new_state.data.status.value != "ready_to_send":
                raise HTTPException(
                    status_code=500,
                    detail="Invariant violated: tried to send without ready summary.",
                )

            self._event_service.record(
                tenant_id=tenant.tenant_id,
                session_id=session_id,
                event_type="lead_delivery_requested",
                event_payload={
                    "category": new_state.data.category.value if new_state.data.category else None,
                    "has_email": bool(new_state.data.email),
                    "has_topic": bool(new_state.data.topic),
                },
            )

            self._delivery_service.deliver_lead(
                tenant=tenant,
                category_value=new_state.data.category.value if new_state.data.category else None,
                summary=new_state.data.summary,
                mailer=mailer,
            )

            self._lead_service.create_lead(
                tenant_id=tenant.tenant_id,
                session_id=session_id,
                email=new_state.data.email,
                topic=new_state.data.topic,
                summary=new_state.data.summary,
            )

            self._event_service.record(
                tenant_id=tenant.tenant_id,
                session_id=session_id,
                event_type="lead_created",
                event_payload={
                    "has_email": bool(new_state.data.email),
                    "has_topic": bool(new_state.data.topic),
                },
            )

            new_state.step = Step.DONE
            new_state.data.status = Status.SENT

            self._event_service.record(
                tenant_id=tenant.tenant_id,
                session_id=session_id,
                event_type="lead_delivery_completed",
                event_payload={
                    "final_step": new_state.step.value,
                    "status": new_state.data.status.value,
                },
            )

        self._session_service.save_state(tenant.tenant_id, session_id, new_state)

        return ChatResult(
            reply=reply,
            step=new_state.step.value,
            is_done=(new_state.step == Step.DONE),
        )
