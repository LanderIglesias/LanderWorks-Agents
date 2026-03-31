from __future__ import annotations

import re
from dataclasses import replace

from .domain import Category, SessionState, Status, Step, Urgency

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _classify_category(text: str) -> Category:
    t = text.lower()
    if any(k in t for k in ["moq", "price", "quotation", "quote", "incoterm", "exw", "fob", "cif"]):
        return Category.PRICING_QUOTE
    if any(
        k in t for k in ["shipping", "lead time", "delivery", "port", "customs", "logistics", "eta"]
    ):
        return Category.SHIPPING_LOGISTICS
    if any(
        k in t
        for k in [
            "certificate",
            "ce",
            "en 12810",
            "en12810",
            "en 12811",
            "compliance",
            "documents",
            "invoice",
            "packing list",
        ]
    ):
        return Category.DOCUMENTS_COMPLIANCE
    if any(k in t for k in ["missing", "damaged", "broken", "complaint", "delay", "late"]):
        return Category.AFTER_SALES_ISSUE
    if any(
        k in t
        for k in [
            "model",
            "dimensions",
            "size",
            "spec",
            "compatible",
            "ringlock",
            "cuplock",
            "frame scaffold",
        ]
    ):
        return Category.PRODUCT_INFO
    return Category.OTHER


def _infer_urgency(text: str) -> Urgency:
    t = text.lower()
    if any(k in t for k in ["urgent", "asap", "today", "immediately"]):
        return Urgency.URGENT
    if any(k in t for k in ["this week", "soon", "next days"]):
        return Urgency.NORMAL
    return Urgency.NORMAL


def _is_yes(text: str) -> bool:
    t = text.strip().lower()
    return t in {"yes", "y", "yeah", "yep", "correct", "send", "ok", "okay", "please do"}


def _is_no(text: str) -> bool:
    t = text.strip().lower()
    return t in {"no", "n", "nope", "not yet", "wait"}


def _valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def _build_summary(state: SessionState) -> str:
    d = state.data
    lines = []
    lines.append("New B2B web inquiry")
    lines.append("")
    lines.append(f"Inquiry type: {d.category.value if d.category else 'unknown'}")
    lines.append(f"Urgency: {d.urgency.value if d.urgency else 'unknown'}")
    lines.append(f"Request summary: {d.topic or '—'}")
    lines.append("")
    lines.append("Contact")
    lines.append(f"- Name: {d.contact_name or '—'}")
    lines.append(f"- Company: {d.company or '—'}")
    lines.append(f"- Email: {d.email or '—'}")
    lines.append(f"- Phone: {d.phone or '—'}")
    lines.append(f"- Country: {d.country or '—'}")
    lines.append("")
    lines.append("Details")
    lines.append(d.details or "—")
    if d.attachments:
        lines.append("")
        lines.append("Attachments")
        for a in d.attachments:
            lines.append(f"- {a}")
    return "\n".join(lines)


def _ready_for_confirm(state: SessionState) -> bool:
    d = state.data
    return bool(d.category and d.topic and d.details and d.email and _valid_email(d.email))


def _details_prompt() -> str:
    return (
        "Great — to prepare an accurate quote, please add the key details in one message:\n"
        "- Scaffold type/model (e.g., ringlock/cuplock/frame)\n"
        "- Dimensions / quantities\n"
        "- Delivery country / city\n"
        "- Any deadlines\n"
        "You can also paste links to photos/documents."
    )


def handle_user_message(state: SessionState, user_text: str) -> tuple[SessionState, str]:
    """
    Pure function: takes current state + user message, returns (new_state, assistant_reply).
    No I/O here. Stable core.
    """
    text = (user_text or "").strip()

    # Hard handoff triggers (minimal)
    if any(k in text.lower() for k in ["legal action", "lawsuit", "fraud", "scam"]):
        new_state = replace(state, step=Step.HANDOFF)
        new_state.data.status = Status.NEEDS_HUMAN
        return (
            new_state,
            "I’m handing this to a human colleague. Please leave your email and we’ll get back to you.",
        )

    if state.step == Step.START:
        if text:
            state.data.category = _classify_category(text)
            state.data.urgency = _infer_urgency(text)
            state.data.topic = text[:80] if len(text) <= 80 else (text[:77] + "…")

            new_state = replace(state, step=Step.COLLECT_CONTACT)
            return new_state, (
                "Hi — I can help route your inquiry to our team.\n"
                "First, what’s your email so we can reply?"
            )

        return state, (
            "Hi 👋\n"
            "I can help with product inquiries, quotations, MOQ/Incoterms, shipping, documents, and issues.\n\n"
            "What do you need?"
        )

    if state.step == Step.COLLECT_CONTACT:
        # Try to extract email from message
        tokens = re.findall(r"[^ \n\r\t]+", text)
        email = None
        for tok in tokens:
            if "@" in tok and _valid_email(tok.strip(" ,;.")):
                email = tok.strip(" ,;.")
                break

        if email:
            state.data.email = email
            new_state = replace(state, step=Step.COLLECT_CASE)

            if state.data.topic:
                return new_state, _details_prompt()

            return new_state, (
                "Thanks. What do you need help with?\n"
                "Examples: product info, quotation (MOQ/Incoterms), shipping/lead time, compliance documents, or an after-sales issue."
            )

        return state, "Please share a valid email address (e.g., name@company.com)."

    if state.step == Step.COLLECT_CASE:
        if not state.data.category:
            state.data.category = _classify_category(text)
            state.data.urgency = _infer_urgency(text)

        if not state.data.topic:
            state.data.topic = text[:80] if len(text) <= 80 else (text[:77] + "…")
            return state, _details_prompt()

        if not state.data.details:
            state.data.details = text
            urls = re.findall(r"https?://\S+", text)
            state.data.attachments.extend([u.strip(" ,;.") for u in urls])

        if _ready_for_confirm(state):
            state.data.summary = _build_summary(state)
            state.data.status = Status.READY_TO_SEND
            new_state = replace(state, step=Step.CONFIRM)
            return new_state, (
                "Perfect. I’m going to send this summary to our team:\n\n"
                f"{state.data.summary}\n\n"
                "Reply YES to send, or NO to add more details."
            )

        if not state.data.email or not _valid_email(state.data.email):
            new_state = replace(state, step=Step.COLLECT_CONTACT)
            return new_state, "Before I send it, what’s the best email to reach you?"

        return state, "Please add a bit more detail so our team can reply accurately."

    if state.step == Step.CONFIRM:
        if _is_yes(text):
            new_state = replace(state, step=Step.SEND)
            return new_state, (
                "Thanks — your request has been sent to our team.\n\n"
                "We usually reply within 24 hours.\n\n"
                "If you need anything else, feel free to ask."
            )

        if _is_no(text):
            new_state = replace(state, step=Step.COLLECT_CASE)
            return new_state, "Sure. Please add the missing details in one message."

        return state, "Please reply YES to send, or NO to add more details."

    if state.step in {Step.SEND, Step.DONE}:
        return (
            state,
            "Your request is already being processed. If you have more info, paste it here.",
        )

    if state.step == Step.HANDOFF:
        return state, "A human will review this. Please leave any extra details and your email."

    return state, "I didn’t catch that — could you rephrase?"
