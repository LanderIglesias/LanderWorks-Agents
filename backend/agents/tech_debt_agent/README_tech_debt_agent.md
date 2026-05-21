# Technical Debt Analyzer

Production-grade repository health scanner that combines static code analysis with LLM interpretation. Give it a GitHub URL and it returns a 0-100 health score, prioritized issues, and a Claude-generated report with business impact and concrete recommendations — not just technical metrics.

**Portfolio:** [notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d](https://www.notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d)

---

## The problem

Every codebase accumulates technical debt. Developers know it exists but can't quantify it for non-technical stakeholders. Linters give you thousands of warnings with no prioritization. CTOs can't read code. There's no open-source tool that analyzes a Python repo, scores its health, and explains the business impact of each issue in plain language.

---

## Solution

A 6-node LangGraph pipeline that clones any GitHub repository, runs four independent analyzers in sequence, and feeds the structured results to Claude — which interprets them in business terms and generates a prioritized action plan.

**What makes it different from a linter:**
- Linters give you warnings. This gives you business impact.
- Linters treat all issues equally. This weights them by severity and category.
- Linters don't explain why something matters. Claude does.
- Linters don't estimate remediation effort. This does.

---

## Architecture

```
GitHub URL
     │
     ▼
┌─────────────┐
│ Repo Fetcher │  gitpython clones repo with depth=1
│  (Nodo 1)   │  into a temp folder (auto-deleted after)
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  Code Analyzer  │  AST: long functions, too many params,
│   (Nodo 2)      │  large classes, long files
│                 │  radon: cyclomatic complexity per function
│                 │  radon: maintainability index per file
└──────┬──────────┘
       │
       ▼
┌──────────────────────┐
│  Dependency Scanner  │  requirements.txt parsing
│     (Nodo 3)         │  PyPI API: detects outdated packages
│                      │  AST: detects unused dependencies
│                      │  Detects unpinned versions (no ==)
└──────┬───────────────┘
       │
       ▼
┌─────────────────┐
│  Test Analyzer  │  Counts test files vs source files
│   (Nodo 4)      │  Detects pytest config
│                 │  Detects CI/CD configuration
│                 │  Estimates untested public functions
└──────┬──────────┘
       │
       ▼
┌──────────────────┐
│ Health Score     │  Weighted formula:
│ (calculated      │  Code quality: 40pts
│  before Claude)  │  Tests: 30pts
│                  │  Dependencies: 20pts
└──────┬───────────┘  CI/CD: 10pts
       │
       ▼
┌──────────────────┐
│ LLM Interpreter  │  Claude receives structured summary
│   (Nodo 5)       │  (not raw code) and generates:
│                  │  - Executive summary for CTOs
│                  │  - Critical findings with business impact
│                  │  - Prioritized recommendations
│                  │  - Risk level + estimated remediation hours
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Report Generator │  Combines technical data + Claude output
│   (Nodo 6)       │  into structured report + markdown
│                  │  Health score label + summary cards
└──────────────────┘
```

---

## Key features

**AST-based code analysis**
Uses Python's built-in `ast` module to parse code into a syntax tree — not as text. This means no false positives from comments or strings that happen to look like code patterns.

**Cyclomatic complexity with radon**
Measures how many independent paths exist through each function. A function with complexity 26 needs 26 test cases to be fully covered — practically untestable. This is the most actionable metric for refactoring priorities.

**PyPI dependency checking**
Queries the PyPI public API for each pinned dependency and compares versions. Detects outdated packages, unpinned dependencies (no `==`), and dependencies declared in requirements.txt but never imported in the code.

**Weighted health score (0-100)**
Not a simple issue count — a weighted formula where a repo with no tests can never score above 70, regardless of code quality. A repo with critical syntax errors scores near 0. The weights reflect real engineering priorities.

**Claude as business interpreter**
Claude doesn't see the raw code — it receives a structured summary of findings and translates them into business language. "Function X has cyclomatic complexity 26" becomes "this module blocks all future feature development on the anomaly detection system because no engineer can safely modify it."

**Streaming progress (SSE)**
The analysis takes 30-90 seconds. Instead of a loading spinner, the UI shows real-time progress: cloning → analyzing → scanning dependencies → checking tests → Claude interpreting → generating report.

**Downloadable markdown report**
The full report is downloadable as a `.md` file for sharing with the team or attaching to engineering planning documents.

---

## Tech stack

| Layer | Technology |
|---|---|
| Pipeline orchestration | LangGraph (6-node stateful graph) |
| LLM | Anthropic Claude Haiku |
| Code parsing | Python `ast` (built-in) |
| Complexity analysis | radon |
| Repository cloning | gitpython |
| Dependency version checking | httpx + PyPI public API |
| Version comparison | packaging |
| Streaming | Server-Sent Events (SSE) |
| Backend | FastAPI, Python 3.12 |

---

## Key technical decisions

**Why AST instead of reading code as text?**
Text-based analysis with regex is fragile — "def " can appear in comments, strings, or docstrings. AST parses the actual structure of the code: every `FunctionDef`, `ClassDef`, `Import` is a node in the tree with exact line numbers and metadata. No false positives.

**Why `depth=1` when cloning?**
`git clone` downloads the full commit history by default. For a 2-year-old repo with thousands of commits, that's hundreds of MB. We only need the current state of the code — `depth=1` downloads only the latest commit, making the clone 10-100x faster.

**Why not give Claude the raw code?**
A medium-sized repo has 50,000+ lines of code. That's way beyond Claude's practical context window for analysis. More importantly, Claude doesn't need to read the code — it needs the structured findings. We run the analysis first, summarize the top issues, and give Claude exactly what it needs to interpret them in business terms.

**Why separate `calculate_health_score()` from `generate_report()`?**
The health score is calculated before calling Claude so Claude can use it in its interpretation ("a health score of 20/100 indicates..."). If it were calculated after, Claude wouldn't know the score while generating the executive summary.

**Why use a tempfile instead of a fixed directory?**
If we cloned repos to a fixed directory, analyzing 10 different repos would fill the disk with 10 copies of large codebases. `tempfile.mkdtemp()` creates a uniquely-named temp folder that's automatically cleaned up after analysis, regardless of success or failure (`finally` block).

**Why is the health score weighted instead of counting total issues?**
A repo with 50 style warnings is healthier than a repo with 5 critical issues. Simple issue counts are misleading. The weighted formula means: no tests → max 70/100, no CI/CD → max 90/100, critical syntax errors → near 0/100.

---

## Limitations

- **Python only.** The AST parser and radon only work with Python files. JavaScript, TypeScript, Go repos would need different parsers per language.
- **Estimated test coverage.** We detect which source files have a corresponding test file, not actual line coverage. Real coverage requires running the tests with `pytest --cov`.
- **PyPI API rate limits.** Checking 30+ dependencies against PyPI takes time and may hit rate limits on very large repos. We handle failures gracefully and skip packages that can't be checked.
- **Private repos require authentication.** The current implementation only supports public GitHub repos. Private repos would need a GitHub token passed as an environment variable.
- **Claude interprets findings, not code.** The LLM receives a structured summary, not the actual code. Its recommendations are general and based on the metrics — it can't suggest specific refactoring of individual functions.

---

## Running locally

```bash
git clone https://github.com/LanderIglesias/LanderWorks-Agents
cd LanderWorks-Agents
pip install -r requirements.txt
cp .env.example .env  # Add ANTHROPIC_API_KEY

uvicorn backend.main:app --reload --port 8000
open http://localhost:8000/tech-debt/demo
```

---

## API

```
POST /tech-debt/analyze
     Body: { github_url: str }
     Response: { health_score, score_label, markdown, summary }
     Note: synchronous, may take 30-90 seconds

POST /tech-debt/analyze/stream
     Body: { github_url: str }
     Response: SSE stream
     Events: { step, message, progress }
     Final event: { step: "done", report: { ... } }

GET  /tech-debt/demo
     Demo UI with real-time progress and downloadable report
```

---

## Project structure

```
backend/agents/tech_debt_agent/
├── api.py                  # FastAPI endpoints + SSE streaming
├── engine.py               # LangGraph orchestrator (6 nodes)
├── repo_fetcher.py         # Clone GitHub repo into temp folder
├── code_analyzer.py        # AST + radon: quality issues per file
├── dependency_scanner.py   # requirements.txt + PyPI version check
├── test_analyzer.py        # Test coverage + CI/CD detection
├── llm_interpreter.py      # Claude: findings → business impact
├── report_generator.py     # Health score formula + markdown report
└── demo_template.py        # Dark industrial UI with SSE progress
```