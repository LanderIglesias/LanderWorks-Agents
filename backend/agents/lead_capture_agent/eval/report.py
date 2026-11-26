"""Cifras de la evaluación a partir de los resultados y la revisión humana.

Uso: python -m backend.agents.lead_capture_agent.eval.report eval/results/<stamp>.json

Lee `<stamp>.review.json` si existe:
  {"overrides": {"P1-r3": {"label": "not_applicable", "reason": "..."}},
   "faithfulness": {"F2-r1": "admits" | "hedged" | "invents"},
   "p5_quoted": ["P5-r2"]}
y escribe `<stamp>.summary.json`, el archivo que copia el portfolio.
La clasificación automática nunca se cambia: una anulación solo añade las
cifras revisadas al lado.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .classify import classify, count_deliveries, first_email_request, looks_english, marker_leaked

CATEGORIES = ("correct", "premature", "false_negative", "false_positive")
FAITH_LABELS = ("admits", "hedged", "invents")
SCRIPTS = Path(__file__).resolve().parent / "scripts.json"


def _validate(review: dict, conv_ids: set[str], faith_ids: set[str]) -> None:
    for cid, ov in review.get("overrides", {}).items():
        if cid not in conv_ids:
            raise ValueError(f"override de una conversación que no existe: {cid}")
        if ov.get("label") != "not_applicable" or not str(ov.get("reason", "")).strip():
            raise ValueError(f"override de {cid}: label 'not_applicable' y un motivo escrito")
    for fid, label in review.get("faithfulness", {}).items():
        if fid not in faith_ids or label not in FAITH_LABELS:
            raise ValueError(f"etiqueta de fidelidad inválida: {fid}={label}")


def summarize(results: dict, scripts: list[dict], review: dict) -> dict:
    by_id = {s["id"]: s for s in scripts}
    convs = results["conversations"]
    faith = results["faithfulness"]
    _validate(review, {c["id"] for c in convs}, {f["id"] for f in faith})

    category = {c["id"]: classify(by_id[c["profile"]], c["turns"]) for c in convs}
    by_category = Counter(category.values())
    by_profile: dict[str, Counter] = {}
    for c in convs:
        by_profile.setdefault(c["profile"], Counter())[category[c["id"]]] += 1

    p5_quoted = review.get("p5_quoted", [])
    for cid in p5_quoted:
        if not cid.startswith("P5-") or category.get(cid) != "false_positive":
            raise ValueError(f"p5_quoted solo admite falsos positivos de P5: {cid}")

    labels = review.get("faithfulness", {})
    faith_counts = Counter(labels.values())
    sends = [c for c in convs if by_id[c["profile"]]["expected"] == "send"]

    summary = {
        "conversations": len(convs),
        "positives": len(sends),
        "negatives": len(convs) - len(sends),
        "by_category": {k: by_category[k] for k in CATEGORIES},
        "by_profile": {p: {k: n[k] for k in CATEGORIES} for p, n in sorted(by_profile.items())},
        "correct_sends": sum(1 for c in sends if category[c["id"]] == "correct"),
        "premature": by_category["premature"],
        "false_negatives": by_category["false_negative"],
        "false_positives": by_category["false_positive"],
        "p5_quoted_marker": len(p5_quoted),
        "duplicate_deliveries": sum(1 for c in convs if count_deliveries(c["turns"]) > 1),
        "marker_leaked": sum(
            1 for c in convs if any(marker_leaked(t["visible"]) for t in c["turns"])
        ),
        "greeting_english": sum(1 for c in convs if looks_english(c["greeting"])),
        "non_english_greetings": [c["id"] for c in convs if not looks_english(c["greeting"])],
        "first_email_request": {
            p: [first_email_request(c["turns"]) for c in convs if c["profile"] == p]
            for p in sorted(by_profile)
        },
        "faithfulness": {
            **{k: faith_counts[k] for k in FAITH_LABELS},
            "unlabelled": len(faith) - len(labels),
            "flagged": [f["id"] for f in faith if f["flags"]],
        },
    }

    overrides = review.get("overrides", {})
    if overrides:
        reviewed = Counter(
            "not_applicable" if cid in overrides else cat for cid, cat in category.items()
        )
        summary["by_category_reviewed"] = {k: reviewed[k] for k in (*CATEGORIES, "not_applicable")}
        summary["overrides"] = overrides
    return summary


def main(argv=None) -> Path:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("results", type=Path)
    args = parser.parse_args(argv)

    results = json.loads(args.results.read_text(encoding="utf-8"))
    review_path = args.results.with_name(args.results.stem + ".review.json")
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else {}
    scripts = json.loads(SCRIPTS.read_text(encoding="utf-8"))
    summary = summarize(results, scripts, review)

    out = args.results.with_name(args.results.stem + ".summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nRevisión: {'sí' if review else 'no'} · resumen en {out}")
    return out


if __name__ == "__main__":
    main()
