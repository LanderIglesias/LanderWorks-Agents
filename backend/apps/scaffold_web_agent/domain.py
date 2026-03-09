from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Category(str, Enum):
    PRODUCT_INFO = "product_info"
    PRICING_QUOTE = "pricing_quote"
    SHIPPING_LOGISTICS = "shipping_logistics"
    DOCUMENTS_COMPLIANCE = "documents_compliance"
    AFTER_SALES_ISSUE = "after_sales_issue"
    OTHER = "other"


class Urgency(str, Enum):
    URGENT = "urgent"  # today
    NORMAL = "normal"  # this week
    LOW = "low"  # no rush


class Status(str, Enum):
    COLLECTING = "collecting"
    READY_TO_SEND = "ready_to_send"
    SENT = "sent"
    NEEDS_HUMAN = "needs_human"


class Step(str, Enum):
    START = "start"
    COLLECT_CONTACT = "collect_contact"
    COLLECT_CASE = "collect_case"
    CONFIRM = "confirm"
    SEND = "send"
    DONE = "done"
    HANDOFF = "handoff"


@dataclass
class CaseData:
    contact_name: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None

    category: Category | None = None
    urgency: Urgency | None = None
    topic: str | None = None
    details: str | None = None
    attachments: list[str] = field(default_factory=list)

    summary: str | None = None
    status: Status = Status.COLLECTING


@dataclass
class SessionState:
    step: Step = Step.START
    data: CaseData = field(default_factory=CaseData)
