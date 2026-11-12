import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_SECONDS = 0.25


class ToolUnavailable(Exception):
    pass


class ToolTimeout(Exception):
    pass


class Cancelled(Exception):
    pass


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            # ponytail: en Windows solo muere el proceso directo, no sus hijos; mejorar con taskkill /T si hace falta.
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    proc.wait()


def run_tool(
    args: list[str],
    cwd: Path,
    timeout: float,
    cancel: threading.Event,
    ok_codes: set[int] = frozenset({0}),
    env: dict[str, str] | None = None,
) -> str:
    if shutil.which(args[0]) is None:
        raise ToolUnavailable(args[0])

    popen_kwargs: dict = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    else:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            env={**os.environ, **env} if env else None,
            **popen_kwargs,
        )
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    proc.wait(timeout=_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if cancel.is_set():
                    _kill(proc)
                    raise Cancelled(args[0])
                if time.monotonic() >= deadline:
                    _kill(proc)
                    raise ToolTimeout(args[0])
        except BaseException:
            if proc.poll() is None:
                _kill(proc)
            raise

        if proc.returncode not in ok_codes:
            err.seek(0)
            logger.warning(
                "%s salió con %s: %s",
                args[0],
                proc.returncode,
                err.read(2000).decode("utf-8", "replace"),
            )
            raise RuntimeError(f"{args[0]} salió con código {proc.returncode}")
        out.seek(0)
        return out.read().decode("utf-8", "replace")
