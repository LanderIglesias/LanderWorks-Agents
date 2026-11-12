import subprocess

from tests.tech_debt_agent.conftest import PLANTED

TOKENS = {
    ("app/main.py", 9): 'allow_origins=["*"]',
    ("app/main.py", 14): "print(",
    ("app/main.py", 17): "SELECT",
    ("app/main.py", 19): "except Exception",
    ("app/utils.py", 8): "eval(",
    ("app/utils.py", 13): "yaml.load",
    ("app/utils.py", 18): "shell=True",
    ("app/utils.py", 24): "except:",
    ("app/god_module.py", 4): "def process_batch_a",
    ("app/god_module.py", 30): "def classify",
    ("app/god_module.py", 58): "def process_batch_b",
    ("web/src/App.tsx", 15): "catch {}",
    ("web/src/App.tsx", 18): "console.log",
    ("web/src/App.tsx", 20): "dangerouslySetInnerHTML",
    ("tests/test_ghost.py", 6): "def test_no_asserts",
    ("tests/test_ghost.py", 10): "def test_trivial_assert",
    ("tests/test_ghost.py", 14): "def test_only_mock_called",
    ("web/src/App.test.tsx", 4): "it(",
    ("requirements.txt", 1): "pyyaml==5.3.1",
    ("requirements.txt", 2): "jinja2==2.10",
    ("requirements.txt", 3): "requests==2.19.0",
    ("web/package-lock.json", 14): "node_modules/lodash",
    ("app/config.py", 2): "STRIPE_KEY",
}


def test_planted_lines_match_generated_repo(vibe_repo):
    for family, entries in PLANTED.items():
        for rel, line in entries:
            if rel == "app/config.py":
                continue
            lines = (vibe_repo / rel).read_text(encoding="utf-8").splitlines()
            assert 1 <= line <= len(lines), (family, rel, line)
            token = TOKENS.get((rel, line))
            if token:
                assert token in lines[line - 1], (rel, line, lines[line - 1])


def test_secret_only_in_history(vibe_repo):
    assert not (vibe_repo / "app" / "config.py").exists()
    log = subprocess.run(
        ["git", "log", "-p", "--all"], cwd=vibe_repo, capture_output=True, text=True, check=True
    ).stdout
    assert "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc" in log


def test_god_module_is_long(vibe_repo):
    assert len((vibe_repo / "app/god_module.py").read_text().splitlines()) > 400


def test_every_token_is_planted():
    planted = {(rel, line) for entries in PLANTED.values() for rel, line in entries}
    assert set(TOKENS) <= planted
