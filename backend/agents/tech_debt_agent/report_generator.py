"""report_generator.py — informe final (score, familias, top y markdown) del Technical Debt Analyzer."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from .findings import Family, FamilyResult, Finding
from .scoring import (
    FAMILY_NAMES,
    family_score,
    global_score,
    grade,
    security_gate_triggered,
    top_findings,
)

_MD_SPECIAL = re.compile(r"([\\[\]()`*_#|~!])")


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _esc(text: object, limit: int = 500) -> str:
    """Neutraliza texto no confiable: sin enlaces, imágenes, HTML ni saltos de línea."""
    s = _truncate(" ".join(str(text if text is not None else "").split()), limit)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("://", ":/​/").replace("www.", "www​.")
    return _MD_SPECIAL.sub(lambda m: "\\" + m.group(1), s)


def _location(f: Finding) -> str:
    if f.file == ".":
        return "`proyecto`"
    where = _truncate(" ".join(f.file.replace("`", "").split()), 300)
    if f.line_start is not None:
        where += f":{f.line_start}"
    return f"`{where}`"


def _finding_md(f: Finding, with_family: bool) -> str:
    prefix = f"[{FAMILY_NAMES[f.family]}] " if with_family else ""
    return (
        f"- **{f.severity.upper()}** {prefix}{_location(f)} — {_esc(f.title)}\n"
        f"  - Por qué: {_esc(f.why)}\n"
        f"  - Cómo arreglarlo: {_esc(f.fix)}"
    )


def _normalize_results(results: list[FamilyResult]) -> list[FamilyResult]:
    by_family = {r.family: r for r in results}
    return [
        by_family.get(fam) or FamilyResult(fam, "not_analyzed", "sin resultados") for fam in Family
    ]


def _report_markdown(
    repo_label: str,
    score: int,
    gate: bool,
    results: list[FamilyResult],
    top: list[Finding],
    summary: str | None,
    kloc: float,
    files_analyzed: int,
) -> str:
    lines = [
        f"# Informe de deuda técnica: {_esc(repo_label)}",
        "",
        f"**Score: {score}/100 ({grade(score)})**",
        "",
        f"_{files_analyzed} archivos analizados, {max(kloc, 0):.1f} KLOC._",
        "",
    ]
    if gate:
        lines += [
            "> **Puerta de seguridad aplicada:** hay hallazgos críticos en secretos, "
            "vulnerabilidades o dependencias, así que el score queda limitado a 40.",
            "",
        ]
    skipped = [r for r in results if r.status == "not_analyzed"]
    if skipped:
        lines.append("> **Familias no analizadas** (no cuentan en el score):")
        lines += [f"> - {FAMILY_NAMES[r.family]}: {_esc(r.reason)}" for r in skipped]
        lines.append("")
    if summary:
        lines += ["## Resumen ejecutivo", "", "**Resumen:** " + _esc(summary, 2000), ""]
    lines += ["## Qué tocar primero", ""]
    lines += [_finding_md(f, True) for f in top] if top else ["Sin hallazgos."]
    lines.append("")
    for r in results:
        title = f"## {int(r.family)}. {FAMILY_NAMES[r.family]}"
        s = family_score(r, kloc)
        if s is not None:
            title += f" — {s}/100 ({grade(s)})"
        lines += [title, ""]
        if r.status == "not_analyzed":
            lines += [f"No analizada: {_esc(r.reason)}", ""]
            continue
        if r.reason:
            lines += [f"_Nota: {_esc(r.reason)}_", ""]
        lines += [_finding_md(f, False) for f in r.findings] or ["Sin hallazgos."]
        lines.append("")
    return "\n".join(lines)


def build_report(
    owner: str,
    repo: str,
    head_sha: str,
    results: list[FamilyResult],
    kloc: float,
    executive_summary: str | None,
    files_analyzed: int,
) -> dict:
    """generated_at: ISO-8601 UTC con sufijo 'Z'."""
    full = _normalize_results(results)
    score = global_score(full, kloc)
    gate = security_gate_triggered(full)
    top = top_findings(full)
    families = []
    for r in full:
        s = family_score(r, kloc)
        families.append(
            {
                "id": int(r.family),
                "name": FAMILY_NAMES[r.family],
                "status": r.status,
                "reason": r.reason,
                "score": s,
                "grade": grade(s) if s is not None else None,
                "findings": [f.to_dict() for f in r.findings],
            }
        )
    return {
        "repo": f"{owner}/{repo}",
        "head_sha": head_sha,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "score": score,
        "grade": grade(score),
        "security_gate_applied": gate,
        "families": families,
        "top": [f.to_dict() for f in top],
        "not_analyzed": [
            {"id": f["id"], "name": f["name"], "reason": f["reason"]}
            for f in families
            if f["status"] == "not_analyzed"
        ],
        "executive_summary": executive_summary,
        "markdown": _report_markdown(
            f"{owner}/{repo}", score, gate, full, top, executive_summary, kloc, files_analyzed
        ),
    }
