from __future__ import annotations

import json
import secrets
import sys
import urllib.request


def main():
    if len(sys.argv) < 6:
        print(
            "Usage: python scripts/create_scaffold_tenant.py <BASE_URL> <ADMIN_TOKEN> <TENANT_ID> <INBOX_EMAIL> <ALLOWED_ORIGINS_CSV> [SUBJECT_PREFIX]"
        )
        print(
            'Example: python scripts/create_scaffold_tenant.py https://xxx.onrender.com supertoken scaffold_china sales@acme.com "https://client.com,https://www.client.com" "[Scaffold China]"'
        )
        raise SystemExit(2)

    base_url = sys.argv[1].rstrip("/")
    admin_token = sys.argv[2]
    tenant_id = sys.argv[3]
    inbox_email = sys.argv[4]
    allowed_origins_csv = sys.argv[5]
    subject_prefix = sys.argv[6] if len(sys.argv) >= 7 else "[Scaffold Web Agent]"

    allowed_origins = [x.strip() for x in allowed_origins_csv.split(",") if x.strip()]
    if not allowed_origins:
        print("Error: ALLOWED_ORIGINS_CSV is empty")
        raise SystemExit(2)

    widget_token = "tok_" + secrets.token_urlsafe(24)

    payload = {
        "tenant_id": tenant_id,
        "widget_token": widget_token,
        "inbox_email": inbox_email,
        "subject_prefix": subject_prefix,
        "allowed_origins": allowed_origins,
    }

    url = f"{base_url}/scaffold-agent/admin/tenants/upsert"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Admin-Token": admin_token,
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        _ = resp.read()

    print("\nOK. Tenant created/updated:\n")
    print("tenant_id:", tenant_id)
    print("widget_token:", widget_token)
    print("inbox_email:", inbox_email)
    print("allowed_origins:", ", ".join(allowed_origins))
    print("\nInstall snippet:\n")
    print(f'<script src="{base_url}/scaffold-agent/widget.js?token={widget_token}"></script>\n')


if __name__ == "__main__":
    main()
