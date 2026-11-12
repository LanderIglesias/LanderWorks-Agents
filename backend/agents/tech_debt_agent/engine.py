import logging
import operator
import tempfile
import threading
import time
from collections.abc import Callable
from itertools import chain
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from .findings import Family, FamilyResult, Finding
from .llm_reviewer import review
from .repo_fetcher import MAX_FILE_BYTES, RepoMeta, _rmtree, clone_repo, list_source_files
from .report_generator import build_report
from .scanners.complexity import scan_complexity
from .scanners.deps import scan_deps
from .scanners.ghost_tests import scan_ghost_tests
from .scanners.python_lint import scan_python_lint
from .scanners.sast import scan_sast
from .scanners.secrets import scan_secrets
from .scoring import SEVERITY_ORDER
from .tools import Cancelled

logger = logging.getLogger(__name__)

ProgressEvent = dict

SCANNERS: dict[str, tuple[Callable, tuple[Family, ...]]] = {
    "secrets": (scan_secrets, (Family.SECRETS,)),
    "deps": (scan_deps, (Family.CVE,)),
    "sast": (scan_sast, (Family.SAST, Family.ERRORS, Family.DEBUG, Family.AI_TELLS)),
    "python_lint": (scan_python_lint, (Family.SAST, Family.ERRORS, Family.DEBUG)),
    "complexity": (scan_complexity, (Family.MONOLITH,)),
    "ghost_tests": (scan_ghost_tests, (Family.GHOST_TESTS,)),
}

SCANNER_LABELS = {
    "secrets": "secretos",
    "deps": "dependencias",
    "sast": "vulnerabilidades",
    "python_lint": "manejo de errores y depuración",
    "complexity": "complejidad",
    "ghost_tests": "tests fantasma",
}
SCAN_START, SCAN_END = 10, 70


class State(TypedDict, total=False):
    meta: RepoMeta
    root: str
    files: list[Path]
    kloc: float
    results: Annotated[list[FamilyResult], operator.add]
    merged: list[FamilyResult]
    llm_results: list[FamilyResult]
    summary: str | None
    cost: float
    final_report: dict


class _Progress:
    """Emisión serializada y monótona: los escáneres terminan en hilos distintos."""

    def __init__(self, emit: Callable[[ProgressEvent], None]):
        self._emit = emit
        self._lock = threading.Lock()
        self._last = 0
        self._scanners_done = 0

    def step(self, step: str, message: str, progress: int) -> None:
        with self._lock:
            self._send(step, message, progress)

    def scanner_done(self, step: str, message: str) -> None:
        with self._lock:
            self._scanners_done += 1
            span = SCAN_END - SCAN_START
            self._send(step, message, SCAN_START + span * self._scanners_done // len(SCANNERS))

    def _send(self, step: str, message: str, progress: int) -> None:
        self._last = max(self._last, progress)
        try:
            self._emit({"step": step, "message": message, "progress": self._last})
        except Exception as exc:  # noqa: BLE001 - un consumidor roto no debe abortar el análisis
            logger.warning("emit fallido: %s", type(exc).__name__)


def _dedupe(findings) -> list[Finding]:
    best: dict[tuple, Finding] = {}
    for f in findings:
        key = (f.family, f.file, f.line_start)
        if key not in best or SEVERITY_ORDER[f.severity] < SEVERITY_ORDER[best[key].severity]:
            best[key] = f
    return sorted(
        best.values(), key=lambda f: (SEVERITY_ORDER[f.severity], f.file, f.line_start or 0)
    )


def merge_results(results: list[FamilyResult]) -> list[FamilyResult]:
    """La familia 8 sale siempre not_analyzed: su estado lo decide solo el revisor LLM."""
    groups: dict[Family, list[FamilyResult]] = {}
    for r in results:
        groups.setdefault(r.family, []).append(r)
    merged = []
    for family, group in groups.items():
        ok = [r for r in group if r.status == "ok"]
        failed = [r.reason for r in group if r.status != "ok" and r.reason]
        if family == Family.AI_TELLS:
            findings = _dedupe(chain.from_iterable(r.findings for r in ok))
            merged.append(FamilyResult(family, "not_analyzed", "pendiente de revisión", findings))
            continue
        if not ok:
            reason = "; ".join(dict.fromkeys(failed)) or "sin resultados"
            merged.append(FamilyResult(family, "not_analyzed", reason))
            continue
        findings = _dedupe(chain.from_iterable(r.findings for r in ok))
        notes = [r.reason for r in ok if r.reason] + [f"fuente no disponible: {x}" for x in failed]
        merged.append(FamilyResult(family, "ok", "; ".join(dict.fromkeys(notes)) or None, findings))
    return merged


def attach_design(
    results: list[FamilyResult], llm_results: list[FamilyResult]
) -> list[FamilyResult]:
    """Hallazgos de diseño del LLM en la familia 5; el estado lo sigue fijando el escáner."""
    extra = [f for r in llm_results if r.family == Family.MONOLITH for f in r.findings]
    if not extra:
        return results
    out = []
    for r in results:
        if r.family != Family.MONOLITH:
            out.append(r)
            continue
        reason = r.reason
        if r.status != "ok":
            note = f"{len(extra)} hallazgos de la revisión con IA"
            reason = f"{reason}; {note}" if reason else note
        out.append(FamilyResult(r.family, r.status, reason, _dedupe(r.findings + extra)))
    return out


def combine_ai_tells(static: FamilyResult | None, llm: FamilyResult | None) -> FamilyResult:
    """Estado del LLM; hallazgos de reglas automáticas + LLM. Semgrep solo nunca da un ok."""
    found = (static.findings if static else []) + (llm.findings if llm else [])
    findings = _dedupe(found)
    if llm is None:
        return FamilyResult(Family.AI_TELLS, "not_analyzed", "no disponible", findings)
    reason = llm.reason
    if llm.status != "ok" and static and static.findings:
        note = f"{len(static.findings)} hallazgos de reglas automáticas"
        reason = f"{reason}; {note}" if reason else note
    return FamilyResult(Family.AI_TELLS, llm.status, reason, findings)


def _count_kloc(files: list[Path], cancel: threading.Event) -> float:
    lines = 0
    for path in files:
        if cancel.is_set():
            raise Cancelled()
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            with path.open("rb") as fh:
                while chunk := fh.read(1 << 20):
                    lines += chunk.count(b"\n")
        except OSError:
            continue
    return lines / 1000


def _ctx(config) -> tuple[threading.Event, _Progress]:
    conf = config["configurable"]
    if conf["cancel"].is_set():
        raise Cancelled()
    return conf["cancel"], conf["progress"]


def _node_clone(state: State, config) -> dict:
    cancel, progress = _ctx(config)
    progress.step("clone", "Clonando el repositorio", 2)
    root = Path(config["configurable"]["workdir"]) / "repo"
    clone_repo(state["meta"], root, cancel)
    files = list_source_files(root)
    progress.step("clone", "Repositorio clonado", SCAN_START)
    return {"root": str(root), "files": files, "kloc": _count_kloc(files, cancel)}


def _make_scanner_node(name: str):
    def node(state: State, config) -> dict:
        cancel, progress = _ctx(config)
        label = SCANNER_LABELS[name]
        progress.step(name, f"Analizando {label}", SCAN_START)
        fn, families = SCANNERS[name]
        files = state["files"]
        if not files:
            results = [FamilyResult(f, "not_analyzed", "sin código fuente") for f in families]
        else:
            try:
                results = fn(Path(state["root"]), files, cancel)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - solo el tipo: el mensaje puede traer rutas
                logger.warning("escáner %s fallido: %s", name, type(exc).__name__)
                results = [
                    FamilyResult(f, "not_analyzed", "error interno del analizador")
                    for f in families
                ]
        progress.scanner_done(name, f"Análisis de {label} terminado")
        return {"results": results}

    return node


def _node_dedupe(state: State, config) -> dict:
    _, progress = _ctx(config)
    progress.step("dedupe", "Unificando hallazgos", 72)
    merged = merge_results(state["results"])
    progress.step("dedupe", "Hallazgos unificados", 75)
    return {"merged": merged}


def _node_llm(state: State, config) -> dict:
    cancel, progress = _ctx(config)
    progress.step("llm_review", "Revisión con IA", 76)
    unavailable = {
        "llm_results": [FamilyResult(Family.AI_TELLS, "not_analyzed", "no disponible")],
        "summary": None,
        "cost": 0.0,
    }
    if not state["files"]:
        out = unavailable
    else:
        prior = [f for r in state["merged"] for f in r.findings]
        try:
            res = review(
                Path(state["root"]),
                state["files"],
                prior,
                cancel,
                config["configurable"].get("llm_client"),
            )
            out = {
                "llm_results": res.family_results,
                "summary": res.executive_summary,
                "cost": res.cost_usd,
            }
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - solo el tipo
            logger.warning("revisor LLM fallido: %s", type(exc).__name__)
            out = unavailable
    progress.step("llm_review", "Revisión con IA terminada", 92)
    return out


def _node_report(state: State, config) -> dict:
    _, progress = _ctx(config)
    progress.step("report", "Generando el informe", 94)
    meta = state["meta"]
    static = next((r for r in state["merged"] if r.family == Family.AI_TELLS), None)
    llm = next((r for r in state["llm_results"] if r.family == Family.AI_TELLS), None)
    rest = [r for r in state["merged"] if r.family != Family.AI_TELLS]
    report = build_report(
        meta.owner,
        meta.repo,
        meta.head_sha,
        attach_design(rest, state["llm_results"]) + [combine_ai_tells(static, llm)],
        state["kloc"],
        state.get("summary"),
        len(state["files"]),
    )
    progress.step("report", "Informe listo", 100)
    return {"final_report": report}


def _build_graph():
    graph = StateGraph(State)
    graph.add_node("clone", _node_clone)
    for name in SCANNERS:
        graph.add_node(name, _make_scanner_node(name))
        graph.add_edge("clone", name)
    graph.add_node("dedupe", _node_dedupe)
    graph.add_node("llm_review", _node_llm)
    graph.add_node("report", _node_report)
    graph.add_edge(START, "clone")
    graph.add_edge(list(SCANNERS), "dedupe")
    graph.add_edge("dedupe", "llm_review")
    graph.add_edge("llm_review", "report")
    graph.add_edge("report", END)
    return graph.compile()


_GRAPH = _build_graph()


def _cleanup(path: Path) -> None:
    # En Windows un proceso hijo recién cancelado puede seguir sujetando el directorio.
    for attempt in range(10):
        try:
            _rmtree(path)
            return
        except OSError:
            if attempt == 9:
                logger.warning("no se pudo borrar el directorio temporal")
                return
            time.sleep(0.3)


def run_analysis(
    meta: RepoMeta,
    cancel: threading.Event,
    emit: Callable[[ProgressEvent], None],
    llm_client=None,
) -> tuple[dict, float]:
    # El borrado es seguro porque el ejecutor de LangGraph espera a los nodos hermanos antes de
    # propagar la excepción (verificado con 0.2.28 fijado, en Docker); _cleanup cubre el resto.
    workdir = tempfile.mkdtemp(prefix="tech_debt_")
    try:
        configurable = {
            "cancel": cancel,
            "progress": _Progress(emit),
            "llm_client": llm_client,
            "workdir": workdir,
        }
        final = _GRAPH.invoke({"meta": meta, "results": []}, {"configurable": configurable})
        return final["final_report"], final.get("cost", 0.0)
    finally:
        _cleanup(Path(workdir))
