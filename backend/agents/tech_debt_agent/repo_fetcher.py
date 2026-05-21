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
