from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

YAML_PATH = Path("backend/data/clinic_config.yaml")
OUT_MD_PATH = Path("backend/data/dental_faq.md")


def _fmt_list(items: list[str]) -> str:
    return ", ".join([str(x).strip() for x in (items or []) if str(x).strip()])


def generate_md(cfg: dict) -> str:
    address = (cfg.get("address") or "").strip()
    phone = (cfg.get("phone") or "").strip()
    email = (cfg.get("email") or "").strip()
    map_url = (cfg.get("map_url") or "").strip()

    hours = cfg.get("hours") or {}
    mon_fri = (hours.get("mon_fri") or "").strip()
    sat = (hours.get("sat") or "").strip()
    sun = (hours.get("sun") or "").strip()

    holidays = cfg.get("holidays") or []
    holidays_txt = ", ".join([str(d) for d in holidays]) if holidays else ""

    insurances = cfg.get("insurances") or []
    payments = cfg.get("payments") or []
    financing = (cfg.get("financing") or "").strip()

    policies = cfg.get("policies") or {}
    pol_cancel = (policies.get("cancellation") or "").strip()
    pol_priv = (policies.get("privacy") or "").strip()
    pol_ster = (policies.get("sterilization") or "").strip()

    services = cfg.get("services") or {}
    treatments = services.get("treatments") or []
    pediatric = bool(services.get("pediatric"))
    sedation = (services.get("sedation") or "").strip()
    languages = services.get("languages") or []
    accessibility = (services.get("accessibility") or "").strip()

    prices = cfg.get("prices") or {}

    # Render
    lines: list[str] = []
    lines.append(
        f"<!-- AUTO-GENERATED FROM {YAML_PATH.as_posix()} | {datetime.utcnow().isoformat(timespec='seconds')}Z -->"
    )
    lines.append("")
    lines.append("# Horarios")
    if mon_fri or sat or sun:
        parts = []
        if mon_fri:
            parts.append(f"L–V: {mon_fri}")
        if sat:
            parts.append(f"Sábado: {sat}")
        if sun:
            parts.append(f"Domingo: {sun}")
        lines.append(". ".join(parts) + ".")
    else:
        lines.append("Horario no configurado.")
    if holidays_txt:
        lines.append(f"Festivos: cerrado. (Listado: {holidays_txt})")
    else:
        lines.append("Festivos: cerrado.")
        special_hours = cfg.get("special_hours") or []
        if special_hours:
            for sh in special_hours:
                dates = sh.get("dates") or []
                note = (sh.get("note") or "").strip()
                if dates and note:
                    lines.append(f"Horario especial: {', '.join(dates)} — {note}.")
    lines.append("")

    lines.append("")
    lines.append("# Urgencias")

    pol = ((cfg.get("policies") or {}).get("emergency") or "").strip()
    if pol:
        lines.append(pol)

    symptoms = cfg.get("emergency_symptoms") or []
    if symptoms:
        lines.append("Síntomas de urgencia: " + ", ".join(symptoms) + ".")
    lines.append("")

    lines.append("# Tratamientos")
    if treatments:
        for t in treatments:
            if isinstance(t, str):
                tt = t.strip()
                if tt:
                    lines.append(f"- {tt}")
            elif isinstance(t, dict):
                n = (t.get("name") or "").strip()
                d = (t.get("details") or "").strip()
                if n and d:
                    lines.append(f"- **{n}**: {d}.")
                elif n:
                    lines.append(f"- **{n}**.")
    else:
        lines.append("- Tratamientos no configurados.")
    extras: list[str] = []
    if pediatric:
        extras.append("Atención pediátrica")
    if sedation:
        extras.append(sedation)
    if languages:
        extras.append("Idiomas: " + _fmt_list(languages))
    if accessibility:
        extras.append("Accesibilidad: " + accessibility)
    if extras:
        lines.append("")
        lines.append("## Servicios adicionales")
        for e in extras:
            lines.append(f"- {e}")
    lines.append("")

    diag = cfg.get("diagnosis") or {}
    fv = (diag.get("first_visit") or "").strip()
    im = diag.get("imaging") or []
    lines.append("# Diagnóstico y revisiones")
    if fv:
        lines.append(f"- {fv}.")
    if im:
        lines.append("- " + " y ".join([str(x).strip() for x in im if str(x).strip()]) + ".")
    if not fv and not im:
        lines.append("Consultar con recepción.")
    lines.append("")

    lines.append("# Precios orientativos (desde)")
    prices = cfg.get("prices") or {}

    PRICE_LABELS = {
        "limpieza": "Limpieza",
        "blanqueamiento": "Blanqueamiento",
        "empaste": "Empaste",
        "endodoncia": "Endodoncia",
        "extraccion_simple": "Extracción simple",
        "implante_unitario": "Implante unitario (sin prótesis)",
        "ortodoncia_invisible": "Ortodoncia invisible (Invisalign)",
    }

    # Mantén un orden estable (si existe)
    price_order = [
        "limpieza",
        "blanqueamiento",
        "empaste",
        "endodoncia",
        "extraccion_simple",
        "implante_unitario",
        "ortodoncia_invisible",
    ]

    if prices:
        # 1) imprime en orden preferido
        for key in price_order:
            if key in prices and prices.get(key):
                label = PRICE_LABELS.get(key, key.replace("_", " ").capitalize())
                val = str(prices[key]).strip()
                lines.append(f"- {label}: **{val}**")

        # 2) imprime cualquier otra key no contemplada
        for key, val in prices.items():
            if key in price_order:
                continue
            if not val:
                continue
            label = PRICE_LABELS.get(key, key.replace("_", " ").capitalize())
            lines.append(f"- {label}: **{str(val).strip()}**")
    else:
        lines.append("Consultar con recepción.")

    lines.append("# Seguros concertados")
    if insurances:
        lines.append(_fmt_list(insurances) + ". Consultar otras pólizas.")
    else:
        lines.append("Consultar con recepción.")
    lines.append("")

    lines.append("# Formas de pago")
    if payments:
        lines.append(_fmt_list(payments) + ".")
    else:
        lines.append("Consultar con recepción.")
    lines.append("")

    lines.append("# Financiación")
    lines.append(financing or "Disponemos de opciones de financiación (sujeto a aprobación).")
    lines.append("")

    lines.append("# Políticas")
    pol_lines = []
    if pol_cancel:
        pol_lines.append(f"- **Cancelación**: {pol_cancel}")
    if pol_priv:
        pol_lines.append(f"- **Privacidad (RGPD)**: {pol_priv}")
    if pol_ster:
        pol_lines.append(f"- **Esterilización**: {pol_ster}")
    if pol_lines:
        lines.extend(pol_lines)
    else:
        lines.append("- Políticas no configuradas.")
    lines.append("")

    pk = cfg.get("parking") or {}
    street = (pk.get("street") or "").strip()
    pub = (pk.get("public") or "").strip()
    lines.append("# Aparcamiento")
    if street or pub:
        if street:
            lines.append(street + ".")
        if pub:
            lines.append(pub + ".")
    else:
        lines.append("Consultar con recepción.")
    lines.append("")

    lines.append("# Dirección y Contacto")
    if address:
        lines.append(address)
    if map_url:
        lines.append(f"Mapa: {map_url}")
    if phone:
        lines.append(f"Teléfono/WhatsApp: {phone}")
    if email:
        lines.append(f"Email: {email}")
    if not any([address, map_url, phone, email]):
        lines.append("Contacto no configurado.")
    lines.append("")

    lines.append("<!-- END AUTO-GENERATED -->")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not YAML_PATH.exists():
        raise SystemExit(f"No existe {YAML_PATH.as_posix()}")

    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8")) or {}
    md = generate_md(cfg)

    OUT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD_PATH.write_text(md, encoding="utf-8")
    print(f"[OK] Escrito {OUT_MD_PATH.as_posix()}")

    # Reindex opcional (si existe el módulo)
    try:
        from backend.rag import ingest_markdown  # type: ignore

        n = ingest_markdown(str(OUT_MD_PATH))
        print(f"[OK] Reindex Chroma: {n} chunks")
    except Exception as e:
        print(f"[WARN] No se reindexó Chroma automáticamente: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
