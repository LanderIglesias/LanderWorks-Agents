import pytest

from backend.agents.tech_debt_agent.findings import (
    Family,
    FamilyResult,
    Finding,
    Severity,
    is_valid_ref,
    parse_line_ref,
)


@pytest.mark.parametrize(
    "ref,expected",
    [
        (12, (12, 12)),
        ("12", (12, 12)),
        ("10-15", (10, 15)),
        ("L10-L15", (10, 15)),
        ("líneas 10-15", (10, 15)),
        ("lines 10–15", (10, 15)),
        ("app.py:7", (7, 7)),
        ("app.py:10-15", (10, 15)),
        ("15-10", None),
        ("0", None),
        ("abc", None),
        ("9" * 5000, None),
        ("1-" + "9" * 5000, None),
    ],
)
def test_parse_line_ref(ref, expected):
    assert parse_line_ref(ref) == expected


def test_is_valid_ref(tmp_path):
    (tmp_path / "a.py").write_text("x\n" * 20)
    ok = {"a.py"}
    assert is_valid_ref(tmp_path, "a.py", 10, 15, ok)
    assert not is_valid_ref(tmp_path, "a.py", 18, 25, ok)
    assert not is_valid_ref(tmp_path, "b.py", 1, 1, ok)
    assert not is_valid_ref(tmp_path, "../../etc/passwd", 1, 1, ok | {"../../etc/passwd"})


def test_finding_to_dict():
    f = Finding(Family.SECRETS, Severity.HIGH, "a.py", 1, 2, "t", "w", "f", "gitleaks")
    d = f.to_dict()
    assert d["family"] == 1 and d["severity"] == "high" and d["file"] == "a.py"
    assert FamilyResult(Family.CVE, "ok", None, [f]).findings == [f]
