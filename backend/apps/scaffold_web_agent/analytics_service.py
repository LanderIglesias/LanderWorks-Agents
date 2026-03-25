from __future__ import annotations

from .sqlite_store import list_events_for_tenant, tenant_analytics


class AnalyticsService:
    def tenant_summary(self, tenant_id: str) -> dict:
        base = tenant_analytics(tenant_id)
        events = list_events_for_tenant(tenant_id, limit=10000)

        event_counts = {
            "chat_requested": 0,
            "chat_replied": 0,
            "lead_delivery_requested": 0,
            "lead_created": 0,
            "lead_delivery_completed": 0,
        }

        unique_sessions = {
            "chat_requested": set(),
            "chat_replied": set(),
            "lead_delivery_requested": set(),
            "lead_created": set(),
            "lead_delivery_completed": set(),
        }

        for event in events:
            event_type = event.get("event_type")
            session_id = event.get("session_id")

            if event_type in event_counts:
                event_counts[event_type] += 1
                if session_id:
                    unique_sessions[event_type].add(session_id)

        lead_creation_rate = 0.0
        if event_counts["chat_requested"] > 0:
            lead_creation_rate = event_counts["lead_created"] / event_counts["chat_requested"]

        delivery_completion_rate = 0.0
        if event_counts["lead_delivery_requested"] > 0:
            delivery_completion_rate = (
                event_counts["lead_delivery_completed"] / event_counts["lead_delivery_requested"]
            )

        unique_requested = len(unique_sessions["chat_requested"])
        unique_replied = len(unique_sessions["chat_replied"])
        unique_delivery_requested = len(unique_sessions["lead_delivery_requested"])
        unique_lead_created = len(unique_sessions["lead_created"])
        unique_delivery_completed = len(unique_sessions["lead_delivery_completed"])

        session_reply_rate = 0.0
        if unique_requested > 0:
            session_reply_rate = unique_replied / unique_requested

        session_lead_creation_rate = 0.0
        if unique_requested > 0:
            session_lead_creation_rate = unique_lead_created / unique_requested

        session_delivery_completion_rate = 0.0
        if unique_delivery_requested > 0:
            session_delivery_completion_rate = unique_delivery_completed / unique_delivery_requested

        return {
            **base,
            "total_events": len(events),
            "chat_requested_count": event_counts["chat_requested"],
            "chat_replied_count": event_counts["chat_replied"],
            "lead_delivery_requested_count": event_counts["lead_delivery_requested"],
            "lead_created_count": event_counts["lead_created"],
            "lead_delivery_completed_count": event_counts["lead_delivery_completed"],
            "lead_creation_rate": lead_creation_rate,
            "delivery_completion_rate": delivery_completion_rate,
            "unique_sessions_with_chat_requested": unique_requested,
            "unique_sessions_with_chat_replied": unique_replied,
            "unique_sessions_with_lead_delivery_requested": unique_delivery_requested,
            "unique_sessions_with_lead_created": unique_lead_created,
            "unique_sessions_with_lead_delivery_completed": unique_delivery_completed,
            "session_reply_rate": session_reply_rate,
            "session_lead_creation_rate": session_lead_creation_rate,
            "session_delivery_completion_rate": session_delivery_completion_rate,
        }
