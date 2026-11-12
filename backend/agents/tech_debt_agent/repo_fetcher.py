"""
repo_fetcher.py — Nodo 1 del Technical Debt Analyzer

Responsabilidad: recibir una URL de GitHub, clonar el repositorio
en una carpeta temporal y devolver la información básica del repo
junto con la lista de archivos Python para analizar.

Usa:
- gitpython  → clonar el repo sin usar el terminal
- tempfile   → carpeta temporal que se borra sola
- pathlib    → navegar la estructura de carpetas de forma limpia
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import git


def fetch_repo(github_url: str) -> dict:
    """
    Clona un repositorio de GitHub en una carpeta temporal
    y devuelve la información básica del repo.

    Args:
        github_url: URL del repositorio. Ejemplos:
            "https://github.com/usuario/repo"
            "https://github.com/usuario/repo.git"

    Returns:
        {
            "repo_name": str,           # nombre del repositorio
            "repo_path": str,           # ruta temporal donde está clonado
            "python_files": list[str],  # rutas de todos los .py encontrados
            "total_files": int,         # total de archivos en el repo
            "python_file_count": int,   # cuántos son .py
            "languages": list[str],     # extensiones de archivos encontradas
        }

    Raises:
        ValueError: si la URL no es válida o el repo no existe
        RuntimeError: si falla la clonación
    """

    # Limpiamos la URL por si tiene .git al final
    url = github_url.strip().rstrip("/")
    if not url.startswith("https://github.com/"):
        raise ValueError(f"URL no válida. Debe empezar por https://github.com/: {url}")

    # Extraemos el nombre del repo de la URL
    # Ejemplo: "https://github.com/usuario/mi-repo" → "mi-repo"
    repo_name = url.split("/")[-1].replace(".git", "")

    # Creamos una carpeta temporal
    # mkdtemp() crea una carpeta con nombre aleatorio en /tmp (Linux) o AppData (Windows)
    # Devuelve la ruta como string
    temp_dir = tempfile.mkdtemp(prefix="tech_debt_")

    try:
        print(f"[RepoFetcher] Clonando {url} en {temp_dir}...")

        # Clonamos el repo en la carpeta temporal
        # depth=1 significa que solo descargamos el último commit (más rápido)
        # No necesitamos el historial completo para analizar el código actual
        git.Repo.clone_from(url, temp_dir, depth=1)

        print("[RepoFetcher] Clonación completada.")

        # Convertimos la ruta a Path para navegar la estructura de carpetas
        repo_path = Path(temp_dir)

        # Recopilamos TODOS los archivos del repo
        # rglob("*") busca recursivamente en todas las subcarpetas
        # .file() filtra solo archivos (no carpetas)
        all_files = [f for f in repo_path.rglob("*") if f.is_file()]

        # Filtramos solo los archivos Python
        # Excluimos carpetas de entorno virtual y cachés de Python
        python_files = [
            str(f)
            for f in all_files
            if f.suffix == ".py"
            and ".venv" not in f.parts
            and "__pycache__" not in f.parts
            and ".git" not in f.parts
        ]

        # Detectamos los lenguajes presentes en el repo
        # Recogemos todas las extensiones únicas de archivos
        extensions = list(
            set(
                f.suffix
                for f in all_files
                if f.suffix and ".git" not in f.parts  # excluimos archivos sin extensión
            )
        )

        return {
            "repo_name": repo_name,
            "repo_path": temp_dir,
            "python_files": python_files,
            "total_files": len(all_files),
            "python_file_count": len(python_files),
            "languages": sorted(extensions),
        }

    except git.exc.GitCommandError as e:
        # Si falla la clonación, borramos la carpeta temporal antes de lanzar el error
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"Error al clonar el repositorio: {e}") from e
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"Error inesperado: {e}") from e


def cleanup_repo(repo_path: str) -> None:
    """
    Borra la carpeta temporal del repo clonado.
    Se llama al final del análisis completo.

    Args:
        repo_path: ruta devuelta por fetch_repo()
    """
    shutil.rmtree(repo_path, ignore_errors=True)
    print(f"[RepoFetcher] Carpeta temporal borrada: {repo_path}")


# --- v2: fetcher endurecido -------------------------------------------------

import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from urllib.parse import quote, urlsplit  # noqa: E402

import httpx  # noqa: E402

from backend.agents.tech_debt_agent.tools import (  # noqa: E402
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
