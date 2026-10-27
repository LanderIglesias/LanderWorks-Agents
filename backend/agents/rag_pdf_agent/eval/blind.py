"""
Corrección a ciegas: prepara las respuestas de un results_*.json para que un LLM las corrija
sin saber qué configuración las escribió ni qué nota les puso la regla automática.

Uso (desde la raíz del repo):
    python -m backend.agents.rag_pdf_agent.eval.blind backend/agents/rag_pdf_agent/eval/results/results_<stamp>.json

Escribe junto al JSON de entrada:
    blind_<stamp>.json      lo que ve el corrector: la rúbrica y, por respuesta distinta, pregunta,
                            tipo, respuesta de referencia y respuesta (barajadas con semilla fija)
    blind_key_<stamp>.json  blind_id -> todas las (configuración, pasada) que dieron esa respuesta
El corrector escribe grades_<stamp>.json: [{blind_id, grade, extra_claims, rounding_only, reason}].
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SEED = 0

RUBRIC = """Corrige cada respuesta comparándola SOLO con "expected" (la respuesta de referencia).
No tienes el documento: no juzgues si un dato que no está en "expected" es cierto o falso.

grade:
- "correcta": contiene los datos clave de "expected" y no contradice ninguno.
- "parcial": contiene una parte de los datos clave y no contradice ninguno.
- "incorrecta": da un dato que contradice "expected", o le falta lo esencial, o dice que no
  encontró la información cuando "expected" sí la da.
Las cifras valen con cualquier formato (237.294,59 = 237,294.59); redondearlas es "parcial".

Tipos con regla propia:
- "no_en_documento": "correcta" si afirma que el documento no tiene esa información; "parcial" si
  lo insinúa sin afirmarlo; "incorrecta" si responde con un dato.
- "premisa_falsa": "correcta" si rechaza la premisa de forma explícita, como hace "expected"
  (si "expected" dice que el documento no lo menciona, decir que no está cuenta como rechazo);
  "parcial" si responde a la pregunta de fondo sin corregir la premisa; "incorrecta" si acepta la
  premisa (da una cifra, un motivo o un premio que la pregunta da por supuesto).

extra_claims: true si la respuesta incluye afirmaciones de contenido que no están en "expected"
(reformular, sinónimos o unidades no cuentan). No cambia la nota.

rounding_only: true si lo único que separa la respuesta de "expected" es el redondeo o el
formato de alguna cifra. No cambia la nota.

reason: una frase que explique la nota.

Devuelve una lista JSON:
[{"blind_id": ..., "grade": ..., "extra_claims": ..., "rounding_only": ..., "reason": ...}],
un elemento por respuesta."""


def blind_export(records: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    """Una entrada por (pregunta, respuesta) distinta: con temperatura 0 muchas pasadas repiten
    la misma respuesta y basta corregirla una vez; la clave reparte la nota a todas sus apariciones.
    """
    groups: dict[tuple, list[dict]] = {}
    for r in records:
        groups.setdefault((r["id"], r["answer"]), []).append(r)
    unique = list(groups.values())
    random.Random(SEED).shuffle(unique)

    items, key = [], {}
    for i, group in enumerate(unique, 1):
        r = group[0]
        blind_id = f"b{i:03d}"
        items.append(
            {
                "blind_id": blind_id,
                "question_id": r["id"],
                "type": r["type"],
                "question": r["question"],
                "expected": r["expected"],
                "answer": r["answer"],
            }
        )
        key[blind_id] = [{"config": g["config"], "repeat": g["repeat"]} for g in group]
    return items, key


def main(results_path: Path) -> None:
    records = json.loads(results_path.read_text(encoding="utf-8"))["records"]
    items, key = blind_export(records)
    stamp = results_path.stem.removeprefix("results_")
    for name, data in [
        (f"blind_{stamp}.json", {"rubric": RUBRIC, "items": items}),
        (f"blind_key_{stamp}.json", key),
    ]:
        path = results_path.with_name(name)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)
    print(f"{len(items)} respuestas distintas de {len(records)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("results", type=Path, help="results_<stamp>.json de run_eval")
    main(parser.parse_args().results)
