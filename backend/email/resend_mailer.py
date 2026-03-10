from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class ResendMailer:
    api_key: str
    from_email: str
    base_url: str = "https://api.resend.com/emails"

    def send(
        self,
        to_email: str | Iterable[str],
        subject: str,
        text: str | None = None,
        html: str | None = None,
        reply_to: str | None = None,
    ) -> None:
        if not self.api_key:
            raise RuntimeError("RESEND_API_KEY is missing")
        if not self.from_email:
            raise RuntimeError("RESEND_FROM is missing")
        if not text and not html:
            raise ValueError("Either text or html must be provided")

        to_list = [to_email] if isinstance(to_email, str) else list(to_email)

        payload = {
            "from": self.from_email,
            "to": to_list,
            "subject": subject,
        }
        if html:
            payload["html"] = html
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to

        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "landerworks-scaffold-agent/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                # Resend returns JSON. We don't need it right now.
                _ = resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Resend HTTPError {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Resend URLError: {e}") from e


def load_resend_mailer() -> ResendMailer:
    return ResendMailer(
        api_key=os.getenv("RESEND_API_KEY", "").strip(),
        from_email=os.getenv("RESEND_FROM", "").strip(),
    )
