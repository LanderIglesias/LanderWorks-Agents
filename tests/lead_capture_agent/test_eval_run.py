"""El runner de la evaluación, con un cliente de Anthropic falso (sin red)."""

import json
from types import SimpleNamespace

import pytest

import backend.agents.lead_capture_agent.llm_engine as llm_engine
from backend.agents.lead_capture_agent import langfuse_utils
from backend.agents.lead_capture_agent.eval import run_eval
from backend.agents.lead_capture_agent.eval.run_eval import (
    Recorder,
    disable_langfuse,
    main,
    results_name,
    run_conversation,
)


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def text_stream(self):
        return iter(self._chunks)


class FakeAnthropic:
    """Respuestas por orden de llamada (el motor crea un cliente por
    llamada, así que el guion se comparte entre clientes). Una respuesta es
    una lista de trozos; una excepción se lanza en esa llamada."""

    def __init__(self, replies, default=("ok",)):
        self.replies = list(replies)
        self.default = list(default)
        self.create_calls = []
        self.n = 0

    def _next(self):
        self.n += 1
        reply = self.replies.pop(0) if self.replies else self.default
        if isinstance(reply, Exception):
            raise reply
        return reply

    def factory(self):
        fake = self

        class _Messages:
            def create(self, **kwargs):
                fake.create_calls.append(kwargs)
                text = "".join(fake._next())
                return SimpleNamespace(
                    content=[SimpleNamespace(text=text)],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=2),
                )

            def stream(self, **kwargs):
                return FakeStream(fake._next())

        return SimpleNamespace(messages=_Messages())


@pytest.fixture
def restore_engine(monkeypatch):
    monkeypatch.setattr(llm_engine, "anthropic", llm_engine.anthropic)


SCRIPT = {"id": "X", "turns": ["a", "b", "c", "d"]}


def test_la_marca_queda_en_raw_y_no_en_visible(restore_engine):
    fake = FakeAnthropic([["Hi there"], ["ok"], ["ok"], ["ok"], ["Done.", "<<<SEND_", "LEAD>>>"]])
    rec = Recorder()
    rec.install(fake.factory)
    last = run_conversation(SCRIPT, "kb", rec)["turns"][-1]
    assert last["marker_in_raw"]
    assert "<<<" not in last["visible"]
    assert last["visible"] == "Done."
    assert last["step_after"] == "send"


def test_el_estado_se_arrastra_como_en_el_endpoint(restore_engine):
    fake = FakeAnthropic([["Hi"], ["ok"], ["ok"], ["Sent! <<<SEND_LEAD>>>"], ["You're welcome"]])
    rec = Recorder()
    rec.install(fake.factory)
    turns = run_conversation(SCRIPT, "kb", rec)["turns"]
    assert [x["step_after"] for x in turns] == ["start", "start", "send", "send"]
    assert not turns[3]["marker_in_raw"]


def test_el_email_del_estado_se_registra(restore_engine):
    fake = FakeAnthropic([])
    rec = Recorder()
    rec.install(fake.factory)
    script = {"id": "X", "turns": ["hi", "mail me at a@b.example", "x", "y"]}
    turns = run_conversation(script, "kb", rec)["turns"]
    assert [x["email_after"] for x in turns] == [None, "a@b.example", "a@b.example", "a@b.example"]


def test_saludo_en_ingles_pedido(restore_engine):
    fake = FakeAnthropic([])
    rec = Recorder()
    rec.install(fake.factory)
    conv = run_conversation(SCRIPT, "kb", rec)
    assert "'en'" in fake.create_calls[0]["messages"][0]["content"]
    assert conv["greeting"] == "ok"


def test_langfuse_desactivado(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    disable_langfuse()
    assert not langfuse_utils._habilitado()


def test_ejecucion_completa_cuenta_30_y_25(tmp_path, restore_engine):
    fake = FakeAnthropic([])
    main(
        ["--runs", "5"], results_dir=tmp_path, client_factory=fake.factory, stamp="2026-01-01-0000"
    )
    data = json.loads((tmp_path / "2026-01-01-0000.json").read_text(encoding="utf-8"))
    assert len(data["conversations"]) == 30
    assert len(data["faithfulness"]) == 25
    assert data["conversations"][0]["id"] == "P1-r1"
    assert data["meta"]["model"] == "claude-haiku-4-5-20251001"
    assert data["meta"]["input_tokens"] > 0


def test_fallo_a_mitad_deja_parcial(tmp_path, restore_engine):
    # P1 = 1 saludo + 4 turnos = 5 llamadas; la 10.ª cae en P2.
    fake = FakeAnthropic([["ok"]] * 9 + [RuntimeError("API caída")])
    with pytest.raises(RuntimeError):
        main(
            ["--runs", "1"],
            results_dir=tmp_path,
            client_factory=fake.factory,
            stamp="2026-01-01-0000",
        )
    partial = json.loads(
        (tmp_path / "2026-01-01-0000.json.partial.json").read_text(encoding="utf-8")
    )
    assert [c["id"] for c in partial["conversations"]] == ["P1-r1"]
    assert not (tmp_path / "2026-01-01-0000.json").exists()


def test_no_sobrescribe(tmp_path, restore_engine):
    (tmp_path / results_name("2026-01-01-0000", pilot=False)).write_text("{}", encoding="utf-8")
    fake = FakeAnthropic([])
    with pytest.raises(SystemExit):
        main(
            ["--runs", "1"],
            results_dir=tmp_path,
            client_factory=fake.factory,
            stamp="2026-01-01-0000",
        )
    assert fake.n == 0


def test_piloto_solo_p1_una_vez(tmp_path, restore_engine):
    fake = FakeAnthropic([])
    main(["--pilot"], results_dir=tmp_path, client_factory=fake.factory, stamp="2026-01-01-0000")
    data = json.loads((tmp_path / "pilot-2026-01-01-0000.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in data["conversations"]] == ["P1-r1"]
    assert data["faithfulness"] == []


def test_nombres():
    assert results_name("2026-11-26-1200", pilot=False) == "2026-11-26-1200.json"
    assert results_name("2026-11-26-1200", pilot=True) == "pilot-2026-11-26-1200.json"
    assert run_eval.MODEL == "claude-haiku-4-5-20251001"


def test_carga_el_env_y_despues_apaga_langfuse(tmp_path, monkeypatch, restore_engine):
    env = tmp_path / ".env"
    env.write_text(
        "ANTHROPIC_API_KEY=clave-de-prueba\nLANGFUSE_PUBLIC_KEY=pk\nLANGFUSE_SECRET_KEY=sk\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_eval, "ENV_FILE", env)
    fake = FakeAnthropic([])
    main(["--pilot"], results_dir=tmp_path, client_factory=fake.factory, stamp="2026-01-01-0000")
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "clave-de-prueba"
    assert not langfuse_utils._habilitado()


def test_meta_registra_la_version_del_sdk(tmp_path, restore_engine):
    import anthropic

    fake = FakeAnthropic([])
    main(["--pilot"], results_dir=tmp_path, client_factory=fake.factory, stamp="2026-01-01-0000")
    data = json.loads((tmp_path / "pilot-2026-01-01-0000.json").read_text(encoding="utf-8"))
    assert data["meta"]["anthropic_version"] == anthropic.__version__
