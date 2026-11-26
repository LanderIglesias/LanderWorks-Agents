"""Evaluación de Lead Capture: visitantes con guion fijo contra el motor real.

Uso (desde la raíz de AI-Portfolio, con ANTHROPIC_API_KEY):
  python -m backend.agents.lead_capture_agent.eval.run_eval --pilot     # P1 una vez, se descarta
  python -m backend.agents.lead_capture_agent.eval.run_eval --runs 5    # 30 conversaciones + 25 respuestas

Llama a las funciones reales del motor, sin HTTP: el saludo con
`handle_user_message_llm(..., lang="en")` y cada turno con
`stream_user_message_llm` (la ruta del widget). Un cliente grabador
envuelve al de Anthropic para guardar la respuesta original, con la marca
<<<SEND_LEAD>>>, que el motor borra antes de que salga nada. El estado
entre turnos se arrastra como lo deja el endpoint en streaming (el paso
se queda en "send" tras una entrega). Sin Langfuse, Resend ni SQLite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import anthropic as _anthropic
from dotenv import load_dotenv

from .. import langfuse_utils, llm_engine
from ..domain import SessionState
from ..llm_engine import _LEAD_MARKER, handle_user_message_llm, stream_user_message_llm
from .classify import faithfulness_flags

MODEL = "claude-haiku-4-5-20251001"
EVAL_DIR = Path(__file__).resolve().parent
KNOWLEDGE = EVAL_DIR.parent / "data" / "synapse_labs_knowledge.md"
SCRIPTS = EVAL_DIR / "scripts.json"
FAITHFULNESS = EVAL_DIR / "faithfulness.json"
ENV_FILE = EVAL_DIR.parents[3] / ".env"  # raíz de AI-Portfolio


class _RecordingStream:
    def __init__(self, inner, recorder: Recorder):
        self._inner = inner
        self._recorder = recorder
        self._chunks: list[str] = []

    def __enter__(self):
        self._stream = self._inner.__enter__()
        return self

    @property
    def text_stream(self):
        for chunk in self._stream.text_stream:
            self._chunks.append(chunk)
            yield chunk

    def __exit__(self, *exc):
        final = getattr(self._stream, "get_final_message", None)
        usage = final().usage if final and exc[0] is None else None
        self._recorder.record("stream", "".join(self._chunks), usage)
        return self._inner.__exit__(*exc)


class _RecordingMessages:
    def __init__(self, inner, recorder: Recorder):
        self._inner = inner
        self._recorder = recorder

    def create(self, **kwargs):
        response = self._inner.create(**kwargs)
        self._recorder.record("create", response.content[0].text, response.usage)
        return response

    def stream(self, **kwargs):
        return _RecordingStream(self._inner.stream(**kwargs), self._recorder)


class Recorder:
    """Guarda el texto original y el uso de tokens de cada llamada."""

    def __init__(self):
        self.calls: list[dict] = []

    def record(self, kind: str, raw: str, usage) -> None:
        self.calls.append(
            {
                "kind": kind,
                "raw": raw,
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            }
        )

    def install(self, client_factory=None) -> None:
        """Sustituye el `anthropic` que ve el motor (solo en llm_engine) por
        uno cuyo cliente graba cada llamada."""
        factory = client_factory or _anthropic.Anthropic

        def make_client():
            real = factory()
            return SimpleNamespace(messages=_RecordingMessages(real.messages, self))

        llm_engine.anthropic = SimpleNamespace(Anthropic=make_client)


def disable_langfuse() -> None:
    """La evaluación no debe mandar trazas al proyecto real de Langfuse."""
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    langfuse_utils._client_singleton = None


def _visible(sse_events: list[str]) -> str:
    """Texto que vería el visitante: los `chunk` de los eventos SSE."""
    parts = []
    for event in sse_events:
        for line in event.splitlines():
            if line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
                parts.append(data.get("chunk", ""))
    return "".join(parts)


def run_conversation(script: dict, knowledge: str, recorder: Recorder) -> dict:
    state, greeting = handle_user_message_llm(SessionState(), "__greeting__", knowledge, lang="en")
    turns = []
    for i, text in enumerate(script["turns"], start=1):
        box = {}
        events = list(
            stream_user_message_llm(
                state, text, knowledge, on_complete=lambda s, _r, box=box: box.update(state=s)
            )
        )
        state = box["state"]
        raw = recorder.calls[-1]["raw"]
        turns.append(
            {
                "turn": i,
                "visitor": text,
                "visible": _visible(events),
                "raw": raw,
                "marker_in_raw": _LEAD_MARKER in raw,
                "step_after": state.step.value,
                "email_after": state.data.email,
            }
        )
    return {"greeting": greeting, "turns": turns}


def run_faithfulness(question: dict, knowledge: str, recorder: Recorder) -> dict:
    events = list(stream_user_message_llm(SessionState(), question["question"], knowledge))
    visible = _visible(events)
    return {
        "visible": visible,
        "raw": recorder.calls[-1]["raw"],
        "flags": faithfulness_flags(visible, knowledge),
    }


def results_name(stamp: str, pilot: bool) -> str:
    return f"pilot-{stamp}.json" if pilot else f"{stamp}.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=EVAL_DIR, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None, results_dir=None, client_factory=None, stamp=None) -> Path:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--pilot", action="store_true", help="P1 una vez; el resultado se descarta")
    args = parser.parse_args(argv)

    results_dir = Path(results_dir or EVAL_DIR / "results")
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now().strftime("%Y-%m-%d-%H%M")
    path = results_dir / results_name(stamp, args.pilot)
    if path.exists():
        raise SystemExit(f"{path} ya existe; no se sobrescribe.")

    # Primero el .env (la clave de Anthropic vive ahí) y después apagar
    # Langfuse, porque el .env también trae sus claves.
    load_dotenv(ENV_FILE)
    disable_langfuse()
    recorder = Recorder()
    recorder.install(client_factory)

    knowledge = KNOWLEDGE.read_text(encoding="utf-8")
    scripts = json.loads(SCRIPTS.read_text(encoding="utf-8"))
    questions = json.loads(FAITHFULNESS.read_text(encoding="utf-8"))
    runs = args.runs
    if args.pilot:
        scripts, questions, runs = scripts[:1], [], 1

    data = {
        "meta": {
            "date": datetime.now().isoformat(timespec="seconds"),
            "model": MODEL,
            "anthropic_version": _anthropic.__version__,
            "temperature": "api default (1.0)",
            "lang": "en",
            "git_commit": _git_commit(),
            "knowledge_sha256": _sha256(KNOWLEDGE),
            "scripts_sha256": _sha256(SCRIPTS),
            "faithfulness_sha256": _sha256(FAITHFULNESS),
            "runs": runs,
            "pilot": args.pilot,
        },
        "conversations": [],
        "faithfulness": [],
    }
    try:
        for run in range(1, runs + 1):
            for script in scripts:
                conv = run_conversation(script, knowledge, recorder)
                data["conversations"].append(
                    {"id": f"{script['id']}-r{run}", "profile": script["id"], "run": run, **conv}
                )
            for q in questions:
                answer = run_faithfulness(q, knowledge, recorder)
                data["faithfulness"].append(
                    {"id": f"{q['id']}-r{run}", "question": q["question"], **answer}
                )
    except BaseException:
        _write(results_dir / f"{path.name}.partial.json", data)
        raise

    data["meta"]["calls"] = len(recorder.calls)
    data["meta"]["input_tokens"] = sum(c["input_tokens"] for c in recorder.calls)
    data["meta"]["output_tokens"] = sum(c["output_tokens"] for c in recorder.calls)
    _write(path, data)
    print(
        f"{path}: {len(data['conversations'])} conversaciones, "
        f"{len(data['faithfulness'])} respuestas, {data['meta']['calls']} llamadas"
    )
    return path


if __name__ == "__main__":
    main()
