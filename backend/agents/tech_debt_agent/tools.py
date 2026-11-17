import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_SECONDS = 0.25
MAX_OUTPUT_BYTES = 50 * 1024 * 1024


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


# Los escáneres procesan código no confiable: solo heredan lo imprescindible, nunca las API keys.
_ENV_ALLOWLIST = {
    "PATH", "PATHEXT", "HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR",
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
    "LANG", "LC_ALL", "LC_CTYPE", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
}  # fmt: skip


def _base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.upper() in _ENV_ALLOWLIST}


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
    if cancel.is_set():
        raise Cancelled(args[0])

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
            env={**_base_env(), **(env or {})},
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
        finally:
            if os.name == "posix":
                _kill(proc)

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
        data = out.read(MAX_OUTPUT_BYTES + 1)
        if len(data) > MAX_OUTPUT_BYTES:
            raise RuntimeError(f"salida de {args[0]} demasiado grande")
        return data.decode("utf-8", "replace")


def find_executable(name: str) -> str | None:
    # run_tool exige un ejecutable resoluble; los paquetes pip (ruff, lizard) viven junto al
    # intérprete (Scripts/ o bin/) y ese directorio puede no estar en PATH.
    found = shutil.which(name)
    if found:
        return found
    for candidate in (name, f"{name}.exe"):
        path = Path(sys.executable).parent / candidate
        if path.is_file():
            return str(path)
    return None


def chunk_args(items: list[str], budget: int = 20000) -> list[list[str]]:
    # Windows limita la línea de comandos a ~32k caracteres.
    chunks: list[list[str]] = []
    size = 0
    for item in items:
        if not chunks or size + len(item) + 1 > budget:
            chunks.append([])
            size = 0
        chunks[-1].append(item)
        size += len(item) + 1
    return chunks
