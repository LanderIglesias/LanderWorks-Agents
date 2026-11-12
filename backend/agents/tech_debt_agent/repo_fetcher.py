"""repo_fetcher.py — metadatos de GitHub y clonado acotado del repositorio a analizar."""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from .tools import (
    Cancelled,
    ToolTimeout,
    ToolUnavailable,
    run_tool,
)

logger = logging.getLogger(__name__)

MAX_REPO_KB = 200_000
MAX_CLONE_BYTES = 400 * 1024**2
CLONE_TIMEOUT_S = 120
MAX_FILE_BYTES = 300_000
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
EXCLUDED_DIRS = {
    ".git",
    "venv",
    ".venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".next",
    "migrations",
    "vendor",
    "__pycache__",
    "site-packages",
    "coverage",
}
_WATCH_SECONDS = 1.0
_HTTP_TIMEOUT_S = 10
_GITHUB_HOSTS = {"github.com", "www.github.com"}
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_NOT_FOUND = "El repositorio no existe o es privado"


class FetchError(Exception):
    """Su mensaje es seguro para mostrarlo al cliente."""


@dataclass
class RepoMeta:
    owner: str
    repo: str
    size_kb: int
    default_branch: str
    head_sha: str


def normalize_github_url(url: str) -> tuple[str, str]:
    invalid = FetchError("URL de GitHub no válida")
    try:
        parts = urlsplit(url.strip())
        host, port = parts.hostname, parts.port
    except ValueError:
        raise invalid from None
    if (
        parts.scheme not in {"http", "https"}
        or host not in _GITHUB_HOSTS
        or port is not None
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
    ):
        raise invalid
    segments = parts.path.strip("/").split("/")
    if len(segments) != 2:
        raise invalid
    owner, repo = segments
    repo = repo.removesuffix(".git")
    if not (_SEGMENT_RE.fullmatch(owner) and _SEGMENT_RE.fullmatch(repo)) or repo in {".", ".."}:
        raise invalid
    if owner in {".", ".."}:
        raise invalid
    return owner, repo


def _github_get(client: httpx.Client, path: str, headers: dict) -> httpx.Response:
    try:
        resp = client.get(f"https://api.github.com{path}", headers=headers, timeout=_HTTP_TIMEOUT_S)
    except httpx.HTTPError as e:
        logger.warning("GitHub API no disponible: %s", type(e).__name__)
        raise FetchError("No se pudo contactar con GitHub, inténtalo más tarde") from None
    if resp.status_code == 404:
        raise FetchError(_NOT_FOUND)
    if resp.status_code in (403, 429):
        raise FetchError("GitHub ha limitado las peticiones, inténtalo más tarde")
    if resp.status_code != 200:
        logger.warning("GitHub API devolvió %s en %s", resp.status_code, path)
        raise FetchError("GitHub devolvió un error inesperado")
    return resp


def get_repo_meta(owner: str, repo: str, client: httpx.Client | None = None) -> RepoMeta:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    own_client = client is None
    client = client or httpx.Client()
    try:
        data = _github_get(client, f"/repos/{owner}/{repo}", headers).json()
        if not isinstance(data, dict):
            raise TypeError
        if data.get("private"):
            raise FetchError(_NOT_FOUND)
        size_kb = int(data.get("size", 0))
        if size_kb > MAX_REPO_KB:
            raise FetchError("El repositorio es demasiado grande para analizarlo")
        branch = data["default_branch"]
        if not isinstance(branch, str) or not branch:
            raise TypeError
        path = f"/repos/{owner}/{repo}/commits/{quote(branch, safe='')}"
        commit = _github_get(client, path, headers).json()
        if not isinstance(commit, dict):
            raise TypeError
        sha = commit["sha"]
        if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
            raise TypeError
        return RepoMeta(owner, repo, size_kb, branch, sha)
    except (KeyError, TypeError, ValueError):
        raise FetchError("GitHub devolvió una respuesta inesperada") from None
    finally:
        if own_client:
            client.close()


def _rmtree(path: Path) -> None:
    def force(func, p, _exc):
        os.chmod(p, 0o700)
        func(p)

    if path.exists():
        shutil.rmtree(path, onerror=force)


def _dir_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def clone_repo(
    meta: RepoMeta,
    dest: Path,
    cancel: threading.Event,
    _url_override: str | None = None,
) -> None:
    url = _url_override or f"https://github.com/{meta.owner}/{meta.repo}.git"
    if cancel.is_set():
        raise Cancelled("clone")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError("dest debe no existir o estar vacío")
    dest.parent.mkdir(parents=True, exist_ok=True)
    internal = threading.Event()
    stop = threading.Event()
    too_big = threading.Event()

    def watch() -> None:
        while not stop.wait(_WATCH_SECONDS):
            if cancel.is_set():
                internal.set()
                return
            if _dir_bytes(dest) > MAX_CLONE_BYTES:
                too_big.set()
                internal.set()
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    protocols = ["-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]
    if _url_override:
        protocols += ["-c", "protocol.file.allow=always"]
    args = [
        "git",
        "-c",
        "core.symlinks=false",
        *protocols,
        "clone",
        "--no-tags",
        "--single-branch",  # solo el historial de la rama por defecto; el resto queda fuera de alcance
        "--",
        url,
        str(dest),
    ]
    env = {"GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    try:
        run_tool(args, dest.parent, CLONE_TIMEOUT_S, internal, env=env)
        if _dir_bytes(dest) > MAX_CLONE_BYTES:
            raise FetchError("El repositorio es demasiado grande para analizarlo")
    except FetchError:
        _rmtree(dest)
        raise
    except Cancelled:
        _rmtree(dest)
        if too_big.is_set():
            raise FetchError("El repositorio es demasiado grande para analizarlo") from None
        raise
    except ToolTimeout:
        _rmtree(dest)
        raise FetchError("La descarga del repositorio tardó demasiado") from None
    except (ToolUnavailable, RuntimeError) as e:
        logger.warning("Clonado fallido: %s", type(e).__name__)
        _rmtree(dest)
        raise FetchError("No se pudo clonar el repositorio") from None
    except BaseException:
        _rmtree(dest)
        raise
    finally:
        stop.set()
        watcher.join(timeout=_WATCH_SECONDS + 1)


def _is_text_source(path: Path) -> bool:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            return False
        with path.open("rb") as f:
            return b"\x00" not in f.read(8192)
    except OSError:
        return False


def list_source_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames if d not in EXCLUDED_DIRS and not (Path(dirpath) / d).is_symlink()
        ]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix not in SOURCE_SUFFIXES or name.endswith(".min.js"):
                continue
            if _is_text_source(path):
                found.append(path)
    return sorted(found)
