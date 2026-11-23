"""
Corrección de la evaluación de Document Intelligence (solo stdlib, sin red).

- normalise: texto comparable (ligaduras, comillas tipográficas, tildes, espacios).
- cited_pages: páginas citadas en una respuesta, por documento.
- facts_hit_by_chunks: si algún chunk recuperado contiene la evidencia de cada hecho.
- citation_status: exact / adjacent (±1) / wrong / n/a.
- auto_grade: correcta / parcial / incorrecta (provisional; manda la revisión manual).
"""

from __future__ import annotations

import re
import unicodedata

PROVIDERS = {"hubspot": "HS", "salesforce": "SF", "sfdc": "SF", "freshworks": "FW"}

REFUSAL = re.compile(
    r"couldn't find|could not find|can't find|cannot find|no information"
    r"|not (?:explicitly )?(?:mentioned|specified|stated|included|provided)"
    r"|(?:does not|doesn't|do not|don't) (?:explicitly )?(?:specify|mention|state|include|contain)"
)

_NUM_LIST = r"\d+(?:\s*(?:-|–|to)\s*\d+)?(?:\s*(?:,|and|&)\s*\d+(?:\s*(?:-|–|to)\s*\d+)?)*"
PAGE_MENTION = re.compile(rf"\b(?:pages?|pp?\.)\s*:?\s*({_NUM_LIST})", re.IGNORECASE)
MAX_RANGE = 10  # ponytail: rangos más largos se ignoran (no son citas, son ruido)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for ch in "ʼ’‘":
        text = text.replace(ch, "'")
    text = text.replace("“", '"').replace("”", '"').lower()
    text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def _expand(numbers: str) -> set[int]:
    pages: set[int] = set()
    for part in re.split(r"\s*(?:,|and|&)\s*", numbers):
        bounds = [int(n) for n in re.findall(r"\d+", part)]
        if len(bounds) == 2 and 0 <= bounds[1] - bounds[0] <= MAX_RANGE:
            pages.update(range(bounds[0], bounds[1] + 1))
        elif bounds:
            pages.add(bounds[0])
    return pages


def cited_pages(
    answer: str, default_doc: str | None, file_to_key: dict[str, str]
) -> dict[str, set[int]]:
    """Páginas citadas por documento; cada mención va al documento nombrado antes más cercano."""
    names = {**PROVIDERS, **{f.lower(): k for f, k in file_to_key.items()}}
    doc_re = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)), re.I)
    docs_at = [(m.start(), names[m.group(0).lower()]) for m in doc_re.finditer(answer)]

    cited: dict[str, set[int]] = {}
    for m in PAGE_MENTION.finditer(answer):
        before = [key for pos, key in docs_at if pos < m.start()]
        key = before[-1] if before else (default_doc or "?")
        cited.setdefault(key, set()).update(_expand(m.group(1)))
    return cited


def facts_hit_by_chunks(item: dict, chunks: list[dict]) -> list[bool]:
    contents = [normalise(c["content"]) for c in chunks]
    return [any(normalise(f["evidence"]) in c for c in contents) for f in item["facts"]]


def citation_status(item: dict, cited: dict[str, set[int]]) -> str:
    facts = [f for f in item["facts"] if f["pages"]]
    if not facts:
        return "n/a"
    pages = cited.get(item["doc"], set())
    if all(pages & set(f["pages"]) for f in facts):
        return "exact"
    if all(any(abs(c - p) <= 1 for c in pages for p in f["pages"]) for f in facts):
        return "adjacent"
    return "wrong"


def auto_grade(item: dict, answer: str) -> str:
    text = normalise(answer)
    if any(normalise(term) in text for term in item.get("forbidden", [])):
        return "incorrecta"
    if item["expect_refusal"]:
        return "correcta" if REFUSAL.search(text) else "incorrecta"
    ok = [
        all(any(alt in text for alt in alternatives) for alternatives in fact["terms"])
        for fact in item["facts"]
    ]
    if all(ok):
        return "correcta"
    return "parcial" if any(ok) else "incorrecta"
