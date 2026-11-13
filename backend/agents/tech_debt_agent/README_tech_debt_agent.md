# Technical Debt Analyzer

Static analyzer for public GitHub repositories (Python and JS/TS). It runs mature
scanners in parallel, has Claude read the highest-risk files for design and
"AI-written code" smells, and returns a 0-100 score with findings grouped in eight
families. Every finding cites `file:line`.

The report itself is written in Spanish.

**Portfolio:** [notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d](https://www.notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d)

---

## What it detects

| # | Family | How |
|---|---|---|
| 1 | Secrets, including git history | gitleaks |
| 2 | Code vulnerabilities (SAST): SQL built from strings, `eval`/`exec`, `shell=True`, insecure deserialization, CORS `*` | semgrep with vendored rules, ruff `S` rules |
| 3 | Dependencies with known CVEs | osv-scanner |
| 4 | Error handling: swallowed errors and errors exposed to the client | semgrep rules, ruff `BLE` |
| 5 | Monoliths and duplication | lizard (complexity, duplicated blocks), plus Claude for design issues such as files mixing routes, business logic and data access |
| 6 | Debug leftovers: stray `print` / `console.log`, commented-out code | semgrep rules, ruff `T20` |
| 7 | Ghost tests: no tests, tests without assertions, `assert True`, tests that only check mocks | own static analysis (`ast` for Python, bounded block parsing for JS/TS) |
| 8 | AI-written code tells: narrating comments, generic names, giant try/except, reimplemented stdlib, tutorial boilerplate | Claude |

Nothing from the analyzed repository is executed: no tests, no dependency install.

---

## Pipeline

```
           clone (shallow, size-capped, temp dir)
                         |
   +--------+--------+---+----+-------------+------------+
   |        |        |        |             |            |
secrets   deps     sast   python_lint   complexity   ghost_tests     (in parallel)
gitleaks  osv     semgrep    ruff         lizard      ast / regex
   |        |        |        |             |            |
   +--------+--------+---+----+-------------+------------+
                         |
                      dedupe            same family + file + line counts once,
                         |              keeping the highest severity
                    llm_review          Claude reads the riskiest files (families 8 and 5)
                         |
                       report           per-family score, security gate, markdown
```

LangGraph orchestrates the graph. Cancellation (client disconnect on the SSE
endpoint) propagates to every running scanner, and the temp clone is always removed.

---

## Scoring

- Each finding weighs by severity: critical 10, high 5, medium 2, low 0.5.
- Families 1, 3 and 7 score `100 - 10 * weight`. The rest are normalized per KLOC
  (`100 - 3 * weight / KLOC`), so a medium-sized repo does not score 0 by default.
- The global score is the weighted average of the families that were analyzed. A
  family that could not be analyzed (tool missing, no lockfile, LLM error) is listed
  as such and does not count.
- **Security gate:** any critical finding in secrets, SAST or CVEs caps the global
  score at 40.
- Grades: A >= 90, B >= 75, C >= 60, D >= 40, F below.

---

## Hardening

The endpoint is public and processes untrusted repositories.

- URL validation: exact `github.com` host and an `owner/repo` path with an allowlisted
  character set. Public repositories only.
- Repository size checked through the GitHub API before cloning (200 MB), shallow
  clone with a timeout, and a 400 MB cap on the clone directory while it is written.
- Files over 300 KB, symlinks and vendored directories are skipped.
- Every external tool runs with a timeout, a bounded output size and cancellation.
- Config files from the analyzed repo (`.gitleaks.toml`, `.gitleaksignore`,
  `osv-scanner.toml`, inline `gitleaks:allow`) cannot silence findings.
- Repository content sent to Claude is wrapped as data, the prompt treats it as
  untrusted, and every cited line is checked against the real file; findings citing
  non-existent lines are dropped. Model text is escaped when rendering the report.
- The container runs as an unprivileged user.

---

## Cost limits

| Limit | Value |
|---|---|
| Analyses per day | 20 (global) |
| Monthly budget | 20 EUR |
| Rate limit per IP | 5/minute, 30/day |
| Concurrent analyses | 2 |
| Result cache | 24 h, keyed by repo and HEAD commit |

Before each analysis the maximum possible LLM cost is reserved; the reservation is
settled with the real cost afterwards. Counters live in SQLite (WAL mode) so they
survive restarts. A cache hit costs nothing and does not use quota.

Measured on three real repositories (2026-11-13): **0.10 to 0.12 USD per analysis**,
26 to 110 seconds.

---

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Claude review. Without it, family 8 is reported as not analyzed. |
| `GITHUB_TOKEN` | no | Raises the GitHub API rate limit for repository metadata. |
| `TECH_DEBT_DB_PATH` | no | SQLite file for quota, budget and cache. Defaults to `backend/data/`. Point it at a mounted volume in production. |
| `TECH_DEBT_EUR_PER_USD` | no | Exchange rate for the monthly budget. Default `0.92`. |

The scanners are pinned in the `Dockerfile` (gitleaks 8.18.4, osv-scanner 2.7.1,
semgrep 1.163.0 in an isolated venv) with SHA-256 verified downloads. The versions
must match the constants in `scanners/`.

### Docker image size

Measured with `docker image ls` against the image without the scanners:

| | Before | After | Increase |
|---|---|---|---|
| On disk | 2.66 GB | 3.27 GB | +610 MB |
| Compressed | 589 MB | 716 MB | +127 MB |

semgrep accounts for 436 MB on disk, gitleaks and osv-scanner for 65 MB. semgrep is
kept because it is the only SAST coverage for JS/TS.

---

## API

```
POST /tech-debt/analyze
     Body: {"github_url": "https://github.com/owner/repo"}
     200:  report + {"cached": bool}
     400:  invalid URL, private or missing repository, repository too large
     429:  daily quota, monthly budget or rate limit reached
     503:  too many analyses in progress

POST /tech-debt/analyze/stream
     Same body. Server-Sent Events: {step, message, progress}
     Final event: {"step": "done", "report": {...}, "cached": bool}
              or  {"step": "error", "status": int, "message": str}
     Closing the connection cancels the analysis.

GET  /tech-debt/demo
     Demo page with live progress and markdown download.
```

The report contains `repo`, `head_sha`, `generated_at`, `score`, `grade`,
`security_gate_applied`, `families`, `top` (the 10 findings to fix first),
`not_analyzed` and `markdown`.

---

## Limitations

- Python and JS/TS only. Other languages are counted but not analyzed.
- Tests are never run, so coverage is not measured; family 7 is static.
- CVEs need pinned versions: a repo with only `pyproject.toml` or `package.json` and
  no lockfile or `requirements*.txt` gets family 3 as not analyzed.
- SAST rules match patterns, with no data-flow analysis. SQL built from strings is
  reported as high; it is critical (and triggers the security gate) only when a
  function parameter is interpolated directly. A value that reaches the query through
  an intermediate variable is therefore high, not critical.
- Claude reviews a selection of files within a fixed byte budget, not the whole repo,
  and returns at most 20 findings.
- Public repositories only.

Out of scope for this phase: fixing code or opening PRs, private repositories, a
visual redesign of the demo.

---

## Running locally

The binary scanners are easiest to get through Docker:

```bash
docker build -t ai-portfolio .
docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY ai-portfolio
# http://localhost:8000/tech-debt/demo
```

Without Docker, `pip install -r requirements.txt` plus gitleaks, osv-scanner and
semgrep on the `PATH`. Missing scanners are reported as "not analyzed".

Tests: `pytest tests/tech_debt_agent`. Tests that need a binary are skipped when it
is not installed; CI installs all three.

---

## Project structure

```
backend/agents/tech_debt_agent/
├── api.py               # endpoints, limits, cache, cancellable SSE
├── cost_guard.py        # SQLite: daily quota, monthly budget, result cache
├── engine.py            # LangGraph graph
├── repo_fetcher.py      # URL validation, size checks, clone, file listing
├── tools.py             # subprocess runner with timeout and cancellation
├── findings.py          # finding model and line-reference validation
├── llm_reviewer.py      # Claude review via tool use
├── scoring.py           # family scores, security gate, global score
├── report_generator.py  # report dict and markdown
├── demo_template.py     # demo page
├── scanners/            # secrets, deps, sast, python_lint, complexity, ghost_tests
├── rules/               # vendored semgrep rules
└── rule_tests/          # semgrep rule test cases
```
