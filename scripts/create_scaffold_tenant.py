"""
Crea o actualiza un tenant en el scaffold agent.

Uso básico:
  python scripts/create_scaffold_tenant.py \
    https://tu-app.onrender.com \
    TU_ADMIN_TOKEN \
    demo \
    tuemail@ejemplo.com \
    "https://tu-app.onrender.com"

Con knowledge desde fichero:
  python scripts/create_scaffold_tenant.py \
    https://tu-app.onrender.com \
    TU_ADMIN_TOKEN \
    demo \
    tuemail@ejemplo.com \
    "https://tu-app.onrender.com" \
    --knowledge backend/data/dental_faq.md

Con knowledge inline:
  python scripts/create_scaffold_tenant.py ... --knowledge-text "Somos una clínica dental..."
"""

from __future__ import annotations

import json
import secrets
import sys
import urllib.request
from pathlib import Path


def main() -> None:
    # ── Argumentos posicionales obligatorios ──────────────────────────────
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = sys.argv[1:]

    if len(positional) < 5:
        print(__doc__)
        print("Error: faltan argumentos obligatorios.")
        print(
            "Uso: python scripts/create_scaffold_tenant.py "
            "<BASE_URL> <ADMIN_TOKEN> <TENANT_ID> <INBOX_EMAIL> <ALLOWED_ORIGINS_CSV> "
            "[SUBJECT_PREFIX] [--agent-type TYPE] [--knowledge FICHERO] [--knowledge-text TEXTO] [--token TOKEN]"
        )
        raise SystemExit(2)

    base_url = positional[0].rstrip("/")
    admin_token = positional[1]
    tenant_id = positional[2]
    inbox_email = positional[3]
    allowed_csv = positional[4]
    subject_prefix = positional[5] if len(positional) >= 6 else "[Web Lead Agent]"

    allowed_origins = [x.strip() for x in allowed_csv.split(",") if x.strip()]
    if not allowed_origins:
        print("Error: ALLOWED_ORIGINS_CSV está vacío.")
        raise SystemExit(2)

    # ── Flags opcionales ──────────────────────────────────────────────────

    # --agent-type scaffold_web_agent | echo | ...
    agent_type = "scaffold_web_agent"
    if "--agent-type" in flags:
        idx = flags.index("--agent-type")
        agent_type = flags[idx + 1]

    # --knowledge <ruta a fichero .md o .txt>
    knowledge_text = ""
    if "--knowledge" in flags:
        idx = flags.index("--knowledge")
        path = Path(flags[idx + 1])
        if not path.exists():
            print(f"Error: no encuentro el fichero de knowledge: {path}")
            raise SystemExit(2)
        knowledge_text = path.read_text(encoding="utf-8").strip()
        print(f"[knowledge] Cargado desde {path} ({len(knowledge_text)} caracteres)")

    # --knowledge-text "texto directo"
    if "--knowledge-text" in flags:
        idx = flags.index("--knowledge-text")
        knowledge_text = flags[idx + 1].strip()
        print(f"[knowledge] Texto inline ({len(knowledge_text)} caracteres)")

    # --token tok_xxx  (para reusar un token existente en vez de generar uno nuevo)
    widget_token = "tok_" + secrets.token_urlsafe(24)
    if "--token" in flags:
        idx = flags.index("--token")
        widget_token = flags[idx + 1].strip()
        print(f"[token] Usando token existente: {widget_token}")

    # ── Payload ───────────────────────────────────────────────────────────
    payload = {
        "tenant_id": tenant_id,
        "widget_token": widget_token,
        "inbox_email": inbox_email,
        "subject_prefix": subject_prefix,
        "allowed_origins": allowed_origins,
        "agent_type": agent_type,
        "knowledge_text": knowledge_text,
    }

    url = f"{base_url}/scaffold-agent/admin/tenants/upsert"
    print(f"\nEnviando a {url} ...")

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Admin-Token": admin_token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode()
            print(f"Respuesta del servidor: {body}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"\nError HTTP {e.code}: {body}")
        raise SystemExit(1) from None

    # ── Resumen ───────────────────────────────────────────────────────────
    sep = "─" * 55
    print(f"\n{sep}")
    print("  TENANT CREADO / ACTUALIZADO")
    print(sep)
    print(f"  tenant_id      : {tenant_id}")
    print(f"  widget_token   : {widget_token}")
    print(f"  agent_type     : {agent_type}")
    print(f"  inbox_email    : {inbox_email}")
    print(f"  subject_prefix : {subject_prefix}")
    print(f"  allowed_origins: {', '.join(allowed_origins)}")
    if knowledge_text:
        preview = knowledge_text[:80].replace("\n", " ")
        print(f"  knowledge      : {preview}{'...' if len(knowledge_text) > 80 else ''}")
    print(sep)
    print("\n  Snippet de instalación del widget:\n")
    print(f'  <script src="{base_url}/scaffold-agent/widget.js?token={widget_token}"></script>')
    print(f"\n  Página demo:\n  {base_url}/scaffold-agent/demo?token={widget_token}")
    print(f"\n  Admin panel:\n  {base_url}/scaffold-agent/admin/page")
    print()


if __name__ == "__main__":
    main()
