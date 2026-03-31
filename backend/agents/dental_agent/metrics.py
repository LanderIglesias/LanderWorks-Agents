from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

COUNTS: Counter = Counter()
LOGS: list[dict[str, Any]] = []


def log_event(kind: str, text: str = "", sender: str = "", meta: dict[str, Any] | None = None):
    COUNTS[kind] += 1
    item = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "sender": sender,
        "text": text[:500] if text else "",
    }
    if meta:
        item["meta"] = meta
    LOGS.append(item)


def snapshot() -> dict:
    # métricas "vendibles"
    total_closed = (
        COUNTS["outcome:auto_completed"]
        + COUNTS["outcome:needs_human"]
        + COUNTS["outcome:timeout"]
        + COUNTS["outcome:abandoned"]
    )
    auto = COUNTS["outcome:auto_completed"]
    needs_human = COUNTS["outcome:needs_human"]
    auto_rate = (auto / total_closed) if total_closed else 0.0

    return {
        "counts": dict(COUNTS),
        "kpis": {
            "closed_conversations": total_closed,
            "auto_completed": auto,
            "needs_human": needs_human,
            "auto_resolution_rate": round(auto_rate, 3),
        },
        "logs": LOGS[-50:],
    }
