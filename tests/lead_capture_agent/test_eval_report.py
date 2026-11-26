"""El informe de la evaluación, sobre resultados construidos a mano."""

import copy
import json
from pathlib import Path

import pytest

from backend.agents.lead_capture_agent.eval.report import summarize

EVAL = Path(__file__).resolve().parents[2] / "backend/agents/lead_capture_agent/eval"
S = json.loads((EVAL / "scripts.json").read_text(encoding="utf-8"))


def _turns(steps, email=None):
    return [
        {
            "turn": i,
            "visible": "Sure, how can I help you?",
            "raw": "",
            "marker_in_raw": False,
            "step_after": s,
            "email_after": email,
        }
        for i, s in enumerate(steps, start=1)
    ]


def _results():
    conversations = [
        {
            "id": f"{p['id']}-r{run}",
            "profile": p["id"],
            "run": run,
            "greeting": "Hi! How can I help you today?",
            "turns": _turns(["start"] * 4),
        }
        for run in range(1, 6)
        for p in S
    ]
    faithfulness = [
        {
            "id": f"F{q}-r{run}",
            "question": "q",
            "visible": "I don't have that information.",
            "raw": "",
            "flags": [],
        }
        for run in range(1, 6)
        for q in range(1, 6)
    ]
    return {"meta": {}, "conversations": conversations, "faithfulness": faithfulness}


R = _results()


def _with(conv_id, steps, email):
    r = copy.deepcopy(R)
    conv = next(c for c in r["conversations"] if c["id"] == conv_id)
    conv["turns"] = _turns(steps, email)
    return r


def test_las_categorias_suman_30():
    s = summarize(R, S, {})
    assert s["conversations"] == 30
    assert sum(s["by_category"].values()) == 30
    assert s["false_negatives"] == 10  # nadie envía: P1 y P6 fallan las 10


def test_override_mueve_a_no_aplica():
    s = summarize(R, S, {"overrides": {"P1-r1": {"label": "not_applicable", "reason": "x"}}})
    assert s["by_category_reviewed"]["not_applicable"] == 1
    assert sum(s["by_category_reviewed"].values()) == 30


def test_sin_overrides_no_hay_cifras_revisadas():
    assert "by_category_reviewed" not in summarize(R, S, {})


def test_override_sin_motivo_falla():
    with pytest.raises(ValueError):
        summarize(R, S, {"overrides": {"P1-r1": {"label": "not_applicable"}}})


def test_override_de_id_inexistente_falla():
    with pytest.raises(ValueError):
        summarize(R, S, {"overrides": {"P9-r1": {"label": "not_applicable", "reason": "x"}}})


def test_envio_correcto_y_duplicado():
    r = _with("P6-r1", ["start", "start", "send", "send"], "tomas.ruiz@shopflow.example")
    s = summarize(r, S, {})
    assert s["correct_sends"] == 1
    assert s["duplicate_deliveries"] == 1
    assert s["by_profile"]["P6"]["correct"] == 1


def test_p5_citada_debe_ser_falso_positivo_de_p5():
    r = _with("P5-r2", ["start", "start", "start", "send"], None)
    assert summarize(r, S, {"p5_quoted": ["P5-r2"]})["p5_quoted_marker"] == 1
    with pytest.raises(ValueError):
        summarize(r, S, {"p5_quoted": ["P5-r1"]})


def test_fidelidad_sin_etiquetar():
    assert summarize(R, S, {})["faithfulness"]["unlabelled"] == 25


def test_fidelidad_etiqueta_invalida_falla():
    with pytest.raises(ValueError):
        summarize(R, S, {"faithfulness": {"F1-r1": "maybe"}})


def test_saludo_ingles_y_marca():
    s = summarize(R, S, {})
    assert s["greeting_english"] == 30
    assert s["marker_leaked"] == 0
