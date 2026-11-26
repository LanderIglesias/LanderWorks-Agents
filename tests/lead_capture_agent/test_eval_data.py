"""Guiones y preguntas de la evaluación: congelados antes de la primera
ejecución completa. Este test fija su forma y comprueba que el regex del
propio motor captura exactamente el email de cada guion (si no, P1/P6
nunca podrían ser 'correct')."""

import json
from pathlib import Path

from backend.agents.lead_capture_agent.llm_engine import _extract_email

EVAL = Path(__file__).resolve().parents[2] / "backend/agents/lead_capture_agent/eval"


def load(name):
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def test_seis_perfiles_cuatro_turnos():
    s = load("scripts.json")
    assert [p["id"] for p in s] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert all(len(p["turns"]) == 4 for p in s)


def test_esperados():
    s = {p["id"]: p for p in load("scripts.json")}
    assert {k for k, p in s.items() if p["expected"] == "send"} == {"P1", "P6"}
    assert s["P1"]["confirm_turn"] == 4 and s["P6"]["confirm_turn"] == 3
    assert all(p["confirm_turn"] is None for p in s.values() if p["expected"] == "no_send")


def test_el_regex_del_motor_captura_exactamente_el_email_del_guion():
    for p in load("scripts.json"):
        found = [m for t in p["turns"] if (m := _extract_email(t))]
        assert found == ([p["email"]] if p["email"] else []), p["id"]
        assert all(e.endswith(".example") for e in found)


def test_cinco_preguntas_de_fidelidad():
    assert [q["id"] for q in load("faithfulness.json")] == ["F1", "F2", "F3", "F4", "F5"]
