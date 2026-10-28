"""
Informe de la corrección a ciegas: reparte cada nota del corrector a todas sus apariciones
(con blind_key) y la compara con la nota de la regla automática.

Uso (desde la raíz del repo):
    python -m backend.agents.rag_pdf_agent.eval.grades_report backend/agents/rag_pdf_agent/eval/results/results_<stamp>.json --exclude 29
    ... --diff "qwen3:14b (local)" "claude-haiku-4.5 (API)"

Lee junto al results_<stamp>.json: blind_<stamp>.json, blind_key_<stamp>.json y grades_<stamp>.json.
Los recuentos son por aparición (pregunta x pasada), no por pregunta: las pasadas de una misma
pregunta no son independientes.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

RANK = {"incorrecta": 0, "parcial": 1, "correcta": 2}


def join(
    records: list[dict],
    items: list[dict],
    key: dict[str, list[dict]],
    grades: list[dict],
    exclude: set[int] = frozenset(),
) -> list[dict]:
    """Una fila por aparición, con la nota del corrector (grade) y la de la regla (auto)."""
    question = {b["blind_id"]: b["question_id"] for b in items}
    graded = {g["blind_id"]: g for g in grades}
    assert graded.keys() == question.keys() == key.keys(), "notas, blind y clave no cuadran"
    auto = {(r["config"], r["repeat"], r["id"]): r["auto_grade"] for r in records}

    rows = []
    for blind_id, occurrences in key.items():
        qid = question[blind_id]
        if qid in exclude:
            continue
        for o in occurrences:
            rows.append(
                {**o, "qid": qid, **graded[blind_id], "auto": auto[(o["config"], o["repeat"], qid)]}
            )
    # Cada aparición recibe su nota exactamente una vez.
    expected = {k for k in auto if k[2] not in exclude}
    assert sorted((r["config"], r["repeat"], r["qid"]) for r in rows) == sorted(expected)
    return rows


def summary(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Por configuración: n, notas, extra_claims, rounding_only y el detector de sesgo
    (cuántas veces el corrector pone más o menos nota que la regla automática)."""
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        s = out.setdefault(
            r["config"],
            dict.fromkeys(["n", *RANK, "extra_claims", "rounding_only", "higher", "lower"], 0),
        )
        s["n"] += 1
        s[r["grade"]] += 1
        s["extra_claims"] += r["extra_claims"]
        s["rounding_only"] += r["rounding_only"]
        s["higher"] += RANK[r["grade"]] > RANK[r["auto"]]
        s["lower"] += RANK[r["grade"]] < RANK[r["auto"]]
    return out


def mode(grades: list[str]) -> str:
    """Nota mayoritaria de las pasadas; "mixed" si hay empate (p. ej. c, p, i)."""
    top = Counter(grades).most_common(2)
    if not top:
        return "-"
    return "mixed" if len(top) == 2 and top[0][1] == top[1][1] else top[0][0]


def question_diff(rows: list[dict], a: str, b: str) -> list[tuple[int, list[str], list[str]]]:
    """Preguntas en las que la nota mayoritaria difiere o, con el mismo número de pasadas,
    difieren las notas pasada a pasada (así una configuración de 1 pasada se puede comparar
    con una de 3 sin que todas las preguntas salgan distintas)."""
    by_q: dict[int, dict[str, list[str]]] = {}
    for r in sorted(rows, key=lambda r: r["repeat"]):
        by_q.setdefault(r["qid"], {}).setdefault(r["config"], []).append(r["grade"])
    out = []
    for q, g in sorted(by_q.items()):
        ga, gb = g.get(a, []), g.get(b, [])
        if mode(ga) != mode(gb) or (len(ga) == len(gb) and sorted(ga) != sorted(gb)):
            out.append((q, ga, gb))
    return out


def main(results_path: Path, exclude: set[int], diff: list[str] | None) -> None:
    stamp = results_path.stem.removeprefix("results_")

    def load(name: str):
        return json.loads(results_path.with_name(name).read_text(encoding="utf-8"))

    rows = join(
        load(results_path.name)["records"],
        load(f"blind_{stamp}.json")["items"],
        load(f"blind_key_{stamp}.json"),
        load(f"grades_{stamp}.json"),
        exclude,
    )
    if exclude:
        print(f"Excluidas: {', '.join(f'Q{q}' for q in sorted(exclude))}\n")

    header = [
        "Configuration",
        "n",
        "Correct",
        "Partial",
        "Incorrect",
        "Extra",
        "Rounding",
        "Higher",
        "Lower",
    ]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for config, s in summary(rows).items():
        cells = [config, s["n"], s["correcta"], s["parcial"], s["incorrecta"]]
        cells += [s["extra_claims"], s["rounding_only"], s["higher"], s["lower"]]
        print("| " + " | ".join(map(str, cells)) + " |")
    print("\nHigher/Lower: apariciones en las que el corrector pone más/menos nota que la regla.")

    if diff:
        a, b = diff
        configs = {r["config"] for r in rows}
        for c in (a, b):
            if c not in configs:
                raise SystemExit(f"Configuración desconocida: {c!r}. Hay: {sorted(configs)}")
        print(f"\n| Question | {a} | {b} |\n|---|---|---|")
        for q, ga, gb in question_diff(rows, a, b):
            same = " (misma moda)" if mode(ga) == mode(gb) else ""
            print(f"| Q{q}{same} | {' '.join(g[0] for g in ga)} | {' '.join(g[0] for g in gb)} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("results", type=Path, help="results_<stamp>.json de run_eval")
    parser.add_argument(
        "--exclude", type=int, nargs="*", default=[], help="ids de pregunta a excluir"
    )
    parser.add_argument(
        "--diff", nargs=2, metavar="CONFIG", help="lista las preguntas donde difieren"
    )
    args = parser.parse_args()
    main(args.results, set(args.exclude), args.diff)
