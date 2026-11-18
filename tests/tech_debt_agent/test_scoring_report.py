import re

from backend.agents.tech_debt_agent.findings import (
    Family,
    FamilyResult,
    Finding,
    Severity,
)
from backend.agents.tech_debt_agent.report_generator import _esc, build_report
from backend.agents.tech_debt_agent.scoring import (
    family_score,
    global_score,
    grade,
    top_findings,
)


def f(fam, sev=Severity.MEDIUM, file="app/main.py", line=12, title="t"):
    return Finding(Family(fam), sev, file, line, line, title, "why", "fix", "test")


def ok(fam, *findings, reason=None):
    return FamilyResult(Family(fam), "ok", reason, list(findings))


def na(fam, reason="fallo"):
    return FamilyResult(Family(fam), "not_analyzed", reason, [])


def clean():
    return [ok(i) for i in range(1, 9)]


def build(results, kloc=1.0, summary=None):
    return build_report("o", "r", "abc123", results, kloc, summary, 10)


def test_clean_repo_is_100_A():
    r = build(clean())
    assert r["score"] == 100 and r["grade"] == "A"
    assert r["security_gate_applied"] is False
    assert [x["id"] for x in r["families"]] == list(range(1, 9))
    assert r["generated_at"].endswith("Z")


def test_secret_critical_applies_gate():
    res = clean()
    res[0] = ok(1, f(1, Severity.CRITICAL))
    r = build(res)
    assert r["score"] <= 40 and r["security_gate_applied"] is True
    assert "puerta" in r["markdown"].lower()


def test_critical_family6_no_gate():
    res = clean()
    res[5] = ok(6, f(6, Severity.CRITICAL))
    assert build(res)["security_gate_applied"] is False


def test_kloc_normalization():
    r = ok(6, *[f(6) for _ in range(10)])
    assert family_score(r, 1.0) == 40
    assert family_score(r, 5.0) == 88
    assert family_score(r, 0) == family_score(r, 1) == family_score(r, 0.2)


def test_unnormalized_families():
    r = ok(1, f(1, Severity.HIGH))
    assert family_score(r, 100) == 50
    assert family_score(ok(5, f(5, Severity.HIGH)), 1) == 85


def test_family_score_none_and_floor():
    assert family_score(na(2), 1) is None
    assert family_score(ok(1, *[f(1, Severity.CRITICAL)] * 3), 1) == 0


def test_grade_boundaries():
    assert [grade(s) for s in (100, 90, 89, 75, 74, 60, 59, 40, 39, 0)] == list("AABBCCDDFF")


def test_not_analyzed_excluded_and_reported():
    res = clean()
    res[7] = na(8, "no disponible")
    r = build(res)
    assert r["score"] == 100
    assert r["not_analyzed"] == [{"id": 8, "name": "Huella de IA", "reason": "no disponible"}]
    assert "Huella de IA" in r["markdown"] and "no disponible" in r["markdown"]


def test_all_not_analyzed_is_zero():
    r = build([na(i) for i in range(1, 9)])
    assert r["score"] == 0 and r["grade"] == "F"
    assert global_score([], 1) == 0


def test_missing_families_become_not_analyzed():
    r = build([ok(1)])
    assert len(r["families"]) == 8
    assert {x["reason"] for x in r["not_analyzed"]} == {"sin resultados"}
    assert len(r["not_analyzed"]) == 7


def test_top_orders_security_first_and_limits():
    res = [ok(6, f(6, Severity.HIGH)), ok(1, f(1, Severity.HIGH))]
    assert [x.family for x in top_findings(res)] == [1, 6]
    many = [ok(6, *[f(6, line=i) for i in range(1, 30)])]
    assert len(top_findings(many)) == 10
    mixed = [ok(6, f(6, Severity.LOW), f(6, Severity.CRITICAL))]
    assert top_findings(mixed)[0].severity == Severity.CRITICAL


def test_markdown_has_file_line_and_notes():
    res = clean()
    res[0] = ok(1, f(1, Severity.HIGH))
    res[2] = ok(3, reason="sin manifiestos de dependencias")
    res[3] = ok(4, f(4, file=".", line=None))
    md = build(res, summary="Resumen")["markdown"]
    assert "`app/main.py:12`" in md
    assert "sin manifiestos de dependencias" in md
    assert "None" not in md
    assert "proyecto" in md
    assert md.index("Resumen") < md.index("Qué tocar primero")


def test_malicious_text_is_neutralized():
    evil = "[click](javascript:alert(1)) <img src=x onerror=alert(1)>\n# head"
    res = clean()
    res[1] = ok(2, f(2, title=evil, file="a`b.py"))
    md = build(res, summary=evil)["markdown"]
    assert "](" not in md
    assert "<img" not in md
    assert not re.search(r"^# head", md, re.M)
    assert "`ab.py:12`" in md


def test_esc_exact_output():
    assert _esc("a_b") == r"a\_b"
    assert _esc("f(x) *y*") == r"f\(x\) \*y\*"
    assert _esc("plain text, 1.5") == "plain text, 1.5"


def test_esc_breaks_autolinks():
    out = _esc("see https://evil.com and www.evil.com")
    assert "://" not in out and "www." not in out


def test_summary_line_start_injection():
    for summary in ("- item", "---", "# h", "1. x"):
        md = build(clean(), summary=summary)["markdown"]
        line = next(x for x in md.splitlines() if "Resumen:" in x)
        assert line.startswith("**Resumen:** ")


def test_length_caps():
    assert len(_esc("x" * 5000)) == 500 and _esc("x" * 5000).endswith("…")
    res = clean()
    res[1] = ok(2, f(2, file="p" * 1000, title="t" * 1000))
    md = build(res, summary="s" * 5000)["markdown"]
    assert "p" * 301 not in md and "t" * 501 not in md and "s" * 2001 not in md


def test_informe_lleva_schema_version():
    assert build_report("o", "r", "a" * 40, [], 1.0, None, 0)["schema_version"] == 1
