"""Tests de la skill senior-cleanup: línea base y verificación por lote. Solo stdlib; Python 3.10+.

Subcomandos (imprimen JSON en stdout; salida 2 con PlanError):
  baseline [--cmd "..."]   ejecuta los tests del plan (o --cmd) y guarda baseline.json.
  verify                   repite la ejecución y compara con la base; sale con 1 si no está OK.
  accept TEST_ID           añade un test a los fallos conocidos (mantenerlo en rojo).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan  # noqa: E402
from plan import PlanError, git, state_dir  # noqa: E402

_TAIL_LINES = 40


def _timeout() -> int:
    return int(os.environ.get("SENIOR_CLEANUP_TEST_TIMEOUT", 900))


def _is_pytest(cmd: list[str]) -> bool:
    return "pytest" in cmd


def _failed_ids(junit: Path) -> list[str] | None:
    """Ids classname::name de los testcase con failure o error; None si el XML no se puede leer."""
    try:
        tree = ET.parse(junit)
    except (OSError, ET.ParseError):
        return None
    return sorted(
        f"{tc.get('classname')}::{tc.get('name')}"
        for tc in tree.iter("testcase")
        if tc.find("failure") is not None or tc.find("error") is not None
    )


def run_command(cmd: list[str], root: Path, junit: Path | None, timeout: int) -> dict:
    argv = list(cmd)
    env = dict(os.environ)
    pytest_run = _is_pytest(cmd) and junit is not None
    if pytest_run:
        argv += [f"--junitxml={junit}", "-p", "no:cacheprovider"]
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # sin __pycache__ en el repo del usuario
        junit.unlink(missing_ok=True)
    argv[0] = shutil.which(argv[0]) or argv[0]  # en Windows, npm es npm.cmd
    timed_out = False
    # Salida a un archivo y no a una tubería: si un proceso nieto (node bajo npm.cmd) sobrevive
    # al kill del timeout, una tubería abierta dejaría run() esperando para siempre.
    # ponytail: los nietos huérfanos siguen vivos; matar el árbol entero pide Job Objects / killpg.
    with tempfile.TemporaryFile() as log:
        try:
            res = subprocess.run(
                argv, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout
            )
            exit_code = res.returncode
        except subprocess.TimeoutExpired:
            timed_out, exit_code = True, None
        except FileNotFoundError:
            exit_code = 127
            log.write(f"No se encuentra el ejecutable {cmd[0]!r}.".encode())
        log.seek(0)
        output = log.read().decode("utf-8", errors="replace")
    if timed_out:
        output += f"\n[timeout tras {timeout} s]"

    failed: list[str] = []
    collect_error = False
    if pytest_run and not timed_out:
        ids = _failed_ids(junit)
        # 0 = verde y 1 = hay fallos; 1 sin ids fallidos, 5 (cero tests) o 2-4 = la ejecución no vale.
        collect_error = ids is None or exit_code not in (0, 1) or (exit_code == 1 and not ids)
        failed = ids or []
    return {
        "cmd": cmd,
        "exit": exit_code,
        "timed_out": timed_out,
        "failed": failed,
        "collect_error": collect_error,
        "tail": "\n".join(output.splitlines()[-_TAIL_LINES:]),
    }


def _run_all(root: Path, commands: list[list[str]]) -> list[dict]:
    state = state_dir(root)
    return [
        run_command(c, root, state / f"junit-{i}.xml", _timeout()) for i, c in enumerate(commands)
    ]


def _root(cwd: Path) -> Path:
    return Path(git(cwd, "rev-parse", "--show-toplevel"))


def baseline(cwd: Path, cmd: str | None = None) -> dict:
    root = _root(cwd)
    state = state_dir(root)
    if cmd:
        # ponytail: shlex en modo POSIX; en Windows una ruta con barras invertidas fuera de
        # comillas pierde las barras. Si hace falta, se citaría la ruta o se usaría posix=False.
        commands = [shlex.split(cmd)]
    else:
        plan_data = plan._load_json(state / "plan.json")
        if plan_data is None:
            raise PlanError("no_plan", "No hay plan. Ejecuta antes plan.py plan.")
        commands = plan_data.get("test_commands") or []
    if not commands:
        raise PlanError("no_tests", "No se detectó cómo ejecutar los tests. Pásalo con --cmd.")
    results = _run_all(root, commands)
    data = {
        "commands": commands,
        "results": results,
        "known_failures": sorted({t for r in results for t in r["failed"]}),
        "opaque_red": any(r["exit"] != 0 for r in results if not _is_pytest(r["cmd"])),
    }
    state.mkdir(exist_ok=True)  # con --cmd puede no haber plan todavía
    plan._write_json(state / "baseline.json", data)
    return data


def _load_baseline(root: Path) -> dict:
    base = plan._load_json(state_dir(root) / "baseline.json")
    if base is None:
        raise PlanError("no_baseline", "No hay línea base. Ejecuta antes run_tests.py baseline.")
    return base


def verify(cwd: Path) -> dict:
    root = _root(cwd)
    base = _load_baseline(root)
    results = _run_all(root, base["commands"])
    known = set(base["known_failures"])
    failed = {t for r in results for t in r["failed"]}
    new_failures = sorted(failed - known)
    broken = any(r["collect_error"] or r["timed_out"] for r in results)
    opaque_fail = not base["opaque_red"] and any(
        r["exit"] != 0 for r in results if not _is_pytest(r["cmd"])
    )
    return {
        "ok": not (new_failures or broken or opaque_fail),
        "new_failures": new_failures,
        "fixed": sorted(known - failed),
        "results": results,
    }


def accept(cwd: Path, test_id: str) -> dict:
    root = _root(cwd)
    base = _load_baseline(root)
    base["known_failures"] = sorted(set(base["known_failures"]) | {test_id})
    plan._write_json(state_dir(root) / "baseline.json", base)
    return base


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # en Windows la tubería usa cp1252
    parser = argparse.ArgumentParser(prog="run_tests.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_base = sub.add_parser("baseline", help="ejecuta los tests y guarda la línea base")
    p_base.add_argument("--cmd", help='comando de tests manual, p. ej. "python -m pytest tests"')
    sub.add_parser("verify", help="repite los tests y compara con la base")
    p_accept = sub.add_parser("accept", help="acepta un test en rojo como fallo conocido")
    p_accept.add_argument("test_id")
    args = parser.parse_args(argv)
    cwd = Path.cwd()
    try:
        if args.command == "baseline":
            out = baseline(cwd, args.cmd)
        elif args.command == "verify":
            out = verify(cwd)
        else:
            out = accept(cwd, args.test_id)
    except PlanError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0 if args.command != "verify" or out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
