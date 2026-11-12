import os
import shutil
import subprocess
import threading

import httpx
import pytest

from backend.agents.tech_debt_agent import repo_fetcher as rf
from backend.agents.tech_debt_agent.tools import Cancelled


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/o/r",
        "https://github.com/o/r.git",
        "https://github.com/o/r/",
        "https://www.github.com/o/r",
        "http://github.com/o/r",
    ],
)
def test_normalize_accepts(url):
    assert rf.normalize_github_url(url) == ("o", "r")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com.evil.com/o/r",
        "https://evil.com/github.com/o/r",
        "https://github.com/o",
        "https://github.com/o/r/tree/main",
        "git@github.com:o/r",
        "https://github.com/o/r;rm",
        "file:///etc",
        "https://user:pw@github.com/o/r",
        "https://github.com/o/r?x=1",
        "https://github.com/o/r#frag",
    ],
)
def test_normalize_rejects(url):
    with pytest.raises(rf.FetchError):
        rf.normalize_github_url(url)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_meta_too_big():
    def h(req):
        return httpx.Response(200, json={"size": 300000, "default_branch": "dev", "private": False})

    with pytest.raises(rf.FetchError, match="demasiado grande"):
        rf.get_repo_meta("o", "r", _client(h))


def test_meta_ok_and_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    seen = []

    def h(req):
        seen.append(req.headers.get("authorization"))
        if req.url.path.endswith("/commits/dev"):
            return httpx.Response(200, json={"sha": "abc123"})
        return httpx.Response(200, json={"size": 10, "default_branch": "dev", "private": False})

    meta = rf.get_repo_meta("o", "r", _client(h))
    assert (meta.owner, meta.repo, meta.default_branch, meta.head_sha) == (
        "o",
        "r",
        "dev",
        "abc123",
    )
    assert meta.size_kb == 10
    assert seen == ["Bearer tok123", "Bearer tok123"]


def test_meta_no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    seen = []

    def h(req):
        seen.append(req.headers.get("authorization"))
        return httpx.Response(404)

    with pytest.raises(rf.FetchError):
        rf.get_repo_meta("o", "r", _client(h))
    assert seen == [None]


def test_meta_rate_limit():
    def h(req):
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0"})

    with pytest.raises(rf.FetchError) as e:
        rf.get_repo_meta("o", "r", _client(h))
    assert "GitHub" in str(e.value) and "Traceback" not in str(e.value)


def test_meta_404():
    with pytest.raises(rf.FetchError, match="no existe o es privado"):
        rf.get_repo_meta("o", "r", _client(lambda req: httpx.Response(404)))


def test_meta_private():
    def h(req):
        return httpx.Response(200, json={"size": 1, "default_branch": "main", "private": True})

    with pytest.raises(rf.FetchError, match="no existe o es privado"):
        rf.get_repo_meta("o", "r", _client(h))


def test_meta_network_error_is_safe():
    def h(req):
        raise httpx.ConnectError("boom /secret/path")

    with pytest.raises(rf.FetchError) as e:
        rf.get_repo_meta("o", "r", _client(h))
    assert "boom" not in str(e.value)


def _can_symlink(tmp_path):
    try:
        (tmp_path / "_probe").symlink_to(tmp_path)
        (tmp_path / "_probe").unlink()
        return True
    except (OSError, NotImplementedError):
        return False


def test_list_source_files(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "b.ts").write_text("let x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("1")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "y.py").write_text("1")
    (tmp_path / "bundle.min.js").write_text("1")
    (tmp_path / "big.py").write_text("x" * 400_000)
    (tmp_path / "nul.py").write_bytes(b"a\x00b")
    (tmp_path / "latin1.py").write_bytes("# caf\xe9\n".encode("latin1"))
    (tmp_path / "notes.txt").write_text("x")
    names = {p.relative_to(tmp_path).as_posix() for p in rf.list_source_files(tmp_path)}
    assert names == {"a.py", "src/b.ts", "latin1.py"}


def test_list_source_files_skips_symlinks(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("sin permisos de symlink")
    target = tmp_path / "outside.txt"
    target.write_text("x")
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.py").write_text("1")
    (root / "link.py").symlink_to(target)
    assert [p.name for p in rf.list_source_files(root)] == ["ok.py"]


def _make_repo(path):
    path.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    (path / "a.py").write_text("x = 1\n")
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=path, check=True, env=env)


@pytest.fixture
def meta():
    return rf.RepoMeta("o", "r", 1, "master", "x")


@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_clone_local(tmp_path, meta):
    src = tmp_path / "src"
    _make_repo(src)
    dest = tmp_path / "dest"
    rf.clone_repo(meta, dest, threading.Event(), _url_override=src.as_uri())
    assert (dest / "a.py").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_clone_cancelled(tmp_path, meta):
    src = tmp_path / "src"
    _make_repo(src)
    dest = tmp_path / "dest"
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        rf.clone_repo(meta, dest, cancel, _url_override=src.as_uri())
    assert not dest.exists() or not any(dest.iterdir())


@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_clone_too_big(tmp_path, meta, monkeypatch):
    src = tmp_path / "src"
    _make_repo(src)
    dest = tmp_path / "dest"
    monkeypatch.setattr(rf, "MAX_CLONE_BYTES", 0)
    monkeypatch.setattr(rf, "_WATCH_SECONDS", 0.01)
    real = rf.run_tool

    def slow(args, cwd, timeout, cancel, **kw):
        dest.mkdir(exist_ok=True)
        (dest / "junk").write_bytes(b"x" * 10)
        cancel.wait(5)
        return real(args, cwd, timeout, cancel, **kw)

    monkeypatch.setattr(rf, "run_tool", slow)
    with pytest.raises(rf.FetchError, match="demasiado grande"):
        rf.clone_repo(meta, dest, threading.Event(), _url_override=src.as_uri())
    assert not dest.exists()
