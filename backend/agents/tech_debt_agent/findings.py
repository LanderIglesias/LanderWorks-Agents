import re
from dataclasses import asdict, dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Literal


class Family(IntEnum):
    SECRETS = 1
    SAST = 2
    CVE = 3
    ERRORS = 4
    MONOLITH = 5
    DEBUG = 6
    GHOST_TESTS = 7
    AI_TELLS = 8


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class Finding:
    family: Family
    severity: Severity
    file: str
    line_start: int | None
    line_end: int | None
    title: str
    why: str
    fix: str
    source: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["family"] = int(self.family)
        d["severity"] = str(self.severity)
        return d


@dataclass
class FamilyResult:
    family: Family
    status: Literal["ok", "not_analyzed"]
    reason: str | None = None
    findings: list[Finding] = field(default_factory=list)


_PAIR = re.compile(r"(\d+)(?:\s*-\s*L?(\d+))?")


def parse_line_ref(ref: str | int) -> tuple[int, int] | None:
    matches = _PAIR.findall(str(ref).replace("–", "-"))
    if not matches:
        return None
    first, second = matches[-1]
    # int() falla con >4300 cifras; ningún archivo tiene tantas líneas
    if len(first) > 9 or len(second) > 9:
        return None
    start = int(first)
    end = int(second) if second else start
    if start < 1 or end < start:
        return None
    return start, end


def is_valid_ref(
    repo_root: Path, file: str, line_start: int, line_end: int, allowed_files: set[str]
) -> bool:
    if file not in allowed_files:
        return False
    root = repo_root.resolve()
    path = (root / file).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return False
    if line_start < 1 or line_end < line_start:
        return False
    with path.open("rb") as fh:
        total = sum(1 for _ in fh)
    return line_end <= total
