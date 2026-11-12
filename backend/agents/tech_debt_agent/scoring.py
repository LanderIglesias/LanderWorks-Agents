from .findings import Family, FamilyResult, Finding, Severity

SEVERITY_WEIGHT = {
    Severity.CRITICAL: 10,
    Severity.HIGH: 5,
    Severity.MEDIUM: 2,
    Severity.LOW: 0.5,
}
SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}
FAMILY_NAMES = {
    Family.SECRETS: "Secretos",
    Family.SAST: "Vulnerabilidades en código",
    Family.CVE: "Dependencias con CVEs",
    Family.ERRORS: "Manejo de errores",
    Family.MONOLITH: "Monolitos y duplicación",
    Family.DEBUG: "Basura de depuración",
    Family.GHOST_TESTS: "Tests fantasma",
    Family.AI_TELLS: "Huella de IA",
}
UNNORMALIZED = {Family.SECRETS, Family.CVE, Family.GHOST_TESTS}
SECURITY_FAMILIES = {Family.SECRETS, Family.SAST, Family.CVE}
GATE_CAP = 40


def family_score(result: FamilyResult, kloc: float) -> int | None:
    if result.status != "ok":
        return None
    total = sum(SEVERITY_WEIGHT[f.severity] for f in result.findings)
    if result.family in UNNORMALIZED:
        return max(0, round(100 - 10 * total))
    # round() redondea a par en los .5 (half-to-even)
    return max(0, round(100 - 3 * total / max(kloc, 1)))


def grade(score: int) -> str:
    for threshold, letter in ((90, "A"), (75, "B"), (60, "C"), (40, "D")):
        if score >= threshold:
            return letter
    return "F"


def security_gate_triggered(results: list[FamilyResult]) -> bool:
    return any(
        f.severity == Severity.CRITICAL and f.family in SECURITY_FAMILIES
        for r in results
        if r.status == "ok"
        for f in r.findings
    )


def global_score(results: list[FamilyResult], kloc: float) -> int:
    weighted = total_weight = 0
    for r in results:
        s = family_score(r, kloc)
        if s is None:
            continue
        w = 2 if r.family <= Family.ERRORS else 1
        weighted += s * w
        total_weight += w
    if not total_weight:
        return 0
    score = round(weighted / total_weight)
    return min(score, GATE_CAP) if security_gate_triggered(results) else score


def top_findings(results: list[FamilyResult], n: int = 10) -> list[Finding]:
    found = [f for r in results if r.status == "ok" for f in r.findings]
    found.sort(
        key=lambda f: (
            SEVERITY_ORDER[f.severity],
            int(f.family),
            f.file,
            f.line_start or 0,
        )
    )
    return found[:n]
