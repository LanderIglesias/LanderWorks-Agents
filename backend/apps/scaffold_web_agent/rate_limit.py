from __future__ import annotations

import time

from .sqlite_store import _connect

WINDOW_SECONDS = 300  # 5 minutes
MAX_REQUESTS = 20  # max messages per window


def ensure_rate_limit_table() -> None:
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS scaffold_rate_limits (
                tenant_id TEXT NOT NULL,
                ip TEXT NOT NULL,
                ts INTEGER NOT NULL
            )
            """
        )
        con.commit()


def is_rate_limited(tenant_id: str, ip: str) -> bool:
    ensure_rate_limit_table()
    now = int(time.time())
    cutoff = now - WINDOW_SECONDS

    with _connect() as con:
        # clean old rows first
        con.execute(
            "DELETE FROM scaffold_rate_limits WHERE ts < ?",
            (cutoff,),
        )

        count = con.execute(
            """
            SELECT COUNT(*)
            FROM scaffold_rate_limits
            WHERE tenant_id = ? AND ip = ? AND ts >= ?
            """,
            (tenant_id, ip, cutoff),
        ).fetchone()[0]

        if count >= MAX_REQUESTS:
            con.commit()
            return True

        con.execute(
            """
            INSERT INTO scaffold_rate_limits(tenant_id, ip, ts)
            VALUES (?, ?, ?)
            """,
            (tenant_id, ip, now),
        )
        con.commit()
        return False
