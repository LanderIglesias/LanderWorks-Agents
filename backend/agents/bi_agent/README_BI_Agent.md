# BI Agent — Multi-Agent Analytics

Natural language analytics for any CSV dataset. Ask questions in plain English, get answers with automatic charts and proactive anomaly detection — powered by a 7-node LangGraph multi-agent pipeline with SQL and Pandas specialists, a quality gate with automatic retry, and statistical anomaly detection interpreted by Claude.

**Live demo:** [coming soon]  
**Portfolio:** [notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d](https://www.notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d)

---

## The problem

Business teams spend hours answering data questions that should take seconds. Pulling a report from a CSV, writing a SQL query, building a chart — each step requires a different tool and a different skill. Most "AI analytics" tools are just a ChatGPT wrapper: they generate SQL that hallucinates column names, return results without validating them, and have no way to recover when something goes wrong.

This agent is different: it plans, executes, validates, auto-corrects, and generates visualizations before answering.

---

## Solution

A 7-node LangGraph pipeline where each node has a single responsibility:

- A **Planner** that reads the question and decomposes it into subtasks, assigning each to the right specialist
- A **SQL Specialist** and a **Pandas Specialist** that generate code tailored to the task
- An **Executor** that runs the code in a sandboxed environment
- An **Anomaly Detector** that scans each result for statistical outliers before returning it
- A **Validator** that checks result validity and sends failed results back to the specialist with specific feedback (up to 2 retries per subtask)
- A **Synthesizer** that combines all subtask results into a single natural language answer
- A **Visualizer** that generates a Matplotlib chart automatically when the result supports it

On top of the Q&A pipeline, a separate `/scan-anomalies` endpoint runs a proactive statistical scan over the entire dataset — no question needed.

---

## Architecture

```
User question
      │
      ▼
  ┌─────────┐
  │ Planner │  decomposes question into subtasks, assigns specialist per task
  └────┬────┘
       │
  ┌────▼────────────┐
  │ specialist_router│  conditional edge: pandas or sql?
  └────┬─────────┬──┘
       │         │
  ┌────▼──┐ ┌───▼────┐
  │Pandas │ │  SQL   │  generates Pandas code or SQLite query
  │Spec.  │ │ Spec.  │
  └────┬──┘ └───┬────┘
       │         │
       └────┬────┘
            │
       ┌────▼────┐
       │Executor │  runs code in restricted namespace (Pandas) or SQLite
       └────┬────┘
            │
       ┌────▼────────────┐
       │Anomaly Detector │  z-score, disparity, concentration scan
       └────┬────────────┘
            │
       ┌────▼─────┐
       │Validator │  pass → next subtask / retry → back to specialist / fail → synthesizer
       └────┬─────┘
            │
     ┌──────▼──────┐
     │ Synthesizer │  combines all subtask results into final answer
     └──────┬──────┘
            │
     ┌──────▼──────┐
     │ Visualizer  │  generates bar or line chart if result supports it
     └─────────────┘
```

The validator retry loop is the key architectural decision. When generated code returns an empty result or fails, the validator sends the error back to the specialist as feedback, which regenerates a corrected version — up to 2 times per subtask. This makes the system self-correcting without human intervention.

---

## Key features

**Natural language to analysis**  
Ask any question in plain English. The Planner decides if it needs one subtask or several, and which specialist handles each one.

**SQL + Pandas routing**  
SQL for aggregations (GROUP BY, COUNT, JOIN). Pandas for transformations SQL handles poorly (pivots, correlations, window calculations). The Planner chooses automatically based on the question.

**Quality gate with retry**  
The Validator checks every result before it reaches the user. Empty results or execution errors trigger a retry with specific feedback — the specialist knows what went wrong and regenerates.

**Anomaly detection**  
Two modes: in-flight (each subtask result is scanned as part of the pipeline) and proactive (full dataset scan via the "Scan anomalies" button). Statistical detection is deterministic and fast; Claude interprets the findings in business language.

**Automatic chart generation**  
Bar charts for categorical comparisons, line charts for time series. The Visualizer detects the result type and chooses automatically. If chart generation fails, the answer is returned without it — no crashes.

**Real-time LangGraph trace**  
Every node lights up in the sidebar as it executes. Retry loops are visible in orange (RETRY badge). The user sees exactly what the system is doing.

---

## Anomaly detection

The `/scan-anomalies` endpoint runs five statistical tests over the entire dataset:

| Detection type | Method | Example |
|---|---|---|
| Outliers | Z-score (\|z\| > 2) | A daily MRR spike 3 standard deviations above average |
| Segment anomalies | Ratio vs mean of other segments | Free plan churn 2.3x higher than pro plan |
| Concentration | Single segment > 35% of total | USA represents 40% of all users |
| Disparity | Top segment > 1.8x bottom segment | Enterprise MRR 7x higher than pro |
| Churn disparity | SaaS-specific: churn rate ratio between segments | Free 53% vs enterprise 20% |

Statistical detection is fast and deterministic. Claude then interprets each anomaly in business language, adds a hypothesis for why it might be happening, and assigns a severity level (high / medium / low).

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph |
| LLM | Anthropic Claude Haiku |
| Data analysis | Pandas, NumPy |
| SQL engine | SQLite (auto-converted from CSV on first query) |
| Charts | Matplotlib — dark theme, type selected automatically |
| Backend | FastAPI, Python 3.12 |
| Data validation | Pydantic |
| Code execution | Python `exec()` with restricted namespace |
| Deployment | Render |
| CI/CD | GitHub Actions |
| Code quality | ruff, Black, pytest, gitleaks (pre-commit) |

---

## Key technical decisions

**Why LangGraph instead of a linear pipeline?**  
A linear pipeline can't handle retry loops. When the Validator decides a result needs to be regenerated, it needs to route back to the specialist — that's a cycle, which LangGraph handles natively as a conditional edge. With a plain LangChain chain you'd have to build retry logic manually and it would be tightly coupled to each specialist.

**Why `exec()` with a restricted namespace instead of subprocess?**  
Subprocess isolation is more secure but adds complexity: serialization, process management, OS-level timeouts. For this use case — the user writes questions in natural language, Claude generates the code — the threat model is contained. The restricted namespace blocks all imports, file access, and dangerous builtins (`open`, `eval`, `import`) while keeping the implementation debuggable. For a public production deployment, subprocess or containerized execution would be the right upgrade.

**Why SQLite in addition to Pandas?**  
SQL is more readable and often faster for aggregations (GROUP BY, COUNT, JOIN) on tabular data. Pandas is better for transformations that SQL handles poorly: pivots, correlations, time-series resampling, complex column calculations. Having both means the Planner can assign the right tool per subtask instead of forcing everything through one paradigm.

**Why separate statistical detection from Claude interpretation?**  
Statistical detection (z-score, ratios) is deterministic, fast, and costs nothing. Claude interpretation is non-deterministic, slower, and costs tokens. Separating them means: the detector always runs the same logic regardless of cost, and Claude is only invoked when anomalies are found and need business-language explanation. This also makes the anomaly threshold easy to tune without changing any prompts.

**Why convert CSV to SQLite on first query instead of at upload time?**  
Lazy conversion means if the user only asks Pandas questions, the SQLite file is never created. The conversion only happens when a SQL subtask is actually needed, and the result is cached for the session. This avoids unnecessary disk writes on Render's ephemeral storage.

---

## Limitations

- **`exec()` is not full sandboxing.** A determined attacker with knowledge of Python internals could escape the restricted namespace. For public deployments, replace with subprocess isolation or containerized execution.
- **Render uses ephemeral storage.** SQLite files and session data are lost on redeploy. Sessions are also in-memory only — restarting the server clears all active sessions.
- **No conversation memory between sessions.** Each new session starts fresh. There is no persistent history of previous questions or results.
- **Time-series datasets require careful prompting.** Datasets with one row per entity per day (like the sample SaaS dataset) can confuse naive LLM-generated queries that count rows instead of unique entities. The specialists are instructed to use `nunique()` and `COUNT(DISTINCT ...)`, but edge cases may still occur.
- **Chart generation is best-effort.** If the result structure doesn't match any known pattern (Series, DataFrame with date column, DataFrame with category + numeric), no chart is generated. The answer is always returned regardless.
- **Not suitable for very large datasets.** The entire CSV is loaded into memory at session start. For files above ~100MB, memory pressure on a free Render instance may cause timeouts.

---

## Supported data formats

The agent works best with:
- **Tabular CSVs** with clear column names and consistent data types
- **SaaS metrics** (users, plans, MRR, churn, signups) — the sample dataset is designed for this
- **E-commerce data** (orders, products, customers, revenue) — columns map naturally to SQL aggregations
- **Time series data** — any CSV with a date column and one or more numeric metrics

Column naming matters. Columns with `_id` suffix are treated as entity identifiers (not aggregated). Columns with `date` or `time` in the name are parsed as timestamps automatically.

---

## Sample dataset

The included `generate_sample_data.py` generates a realistic SaaS metrics dataset:

- **500 users** across 6 months (Oct 2025 — Mar 2026)
- **55,000+ rows** — one snapshot per user per day
- **Plans:** free (60%), pro (30%), enterprise (10%)
- **Churn rates:** ~20%/month free, ~8% pro, ~3% enterprise
- **Countries:** USA, Spain, UK, Germany, France, Brazil, Japan, Mexico
- **MRR:** $0 free, $29/month pro, $299/month enterprise

This dataset is designed to produce interesting anomalies (USA dominates user share, free plan has 2.3x the churn of pro, enterprise drives 78% of MRR) so demos are always meaningful.

---

## Running locally

```bash
# Clone the repo
git clone https://github.com/SpicySabeso/ai-portfolio
cd ai-portfolio

# Install dependencies
pip install -r requirements.txt

# Add your API key
echo "ANTHROPIC_API_KEY=your_key_here" > .env

# Generate the sample dataset
python backend/agents/bi_agent/generate_sample_data.py

# Start the server
uvicorn backend.main:app --reload

# Open the demo
open http://localhost:8000/bi-agent/demo
```

---

## API

```
GET  /bi-agent/demo
     Returns the demo UI

GET  /bi-agent/sample
     Loads the sample SaaS dataset into a new session
     Response: { session_id, rows, columns, schema, filename }

POST /bi-agent/upload
     Body: multipart/form-data — file (CSV, max 10MB)
     Response: { session_id, rows, columns, schema, filename }

POST /bi-agent/ask
     Body: { session_id: str, question: str }
     Response: {
       success: bool,
       answer: str,            — natural language answer
       code: str | null,       — last generated code (Pandas or SQL)
       result: dict | null,    — serialized result (dataframe or series)
       chart: str | null,      — base64 PNG
       trace: list[str],       — LangGraph node execution log
       subtasks: list[dict],   — planner subtask breakdown
       anomalies: list[dict],  — in-flight anomalies detected
       error: str | null
     }

POST /bi-agent/scan-anomalies
     Body: { session_id: str }
     Response: {
       success: bool,
       anomalies: list[dict],  — interpreted anomaly alerts
       raw_count: int,         — anomalies found before LLM interpretation
       summary: str            — 1-2 sentence summary of scan results
     }

GET  /bi-agent/session/{session_id}
     Returns session schema, source info, and row count

DELETE /bi-agent/session/{session_id}
     Deletes session and frees memory
```

---

## Project structure

```
backend/agents/bi_agent/
├── api.py                    # FastAPI endpoints and Pydantic schemas
├── engine.py                 # Graph orchestrator — invokes LangGraph, calls visualizer
├── graph.py                  # LangGraph graph definition (nodes + edges)
├── state.py                  # Shared AgentState TypedDict
├── data_loader.py            # CSV/SQLite loader with in-memory session cache
├── code_executor.py          # Sandboxed Python exec() with NaN/Inf sanitization
├── sqlite_store.py           # DataFrame → SQLite conversion (lazy, cached per session)
├── anomaly_detector.py       # Statistical anomaly detection (5 detection types)
├── visualizer.py             # Matplotlib chart generation — dark theme, auto type selection
├── demo_template.py          # Demo UI — dark dashboard with LangGraph trace panel
├── generate_sample_data.py   # SaaS dataset generator (500 users, 6 months)
├── nodes/
│   ├── planner.py            # Decomposes question into subtasks, assigns specialists
│   ├── router.py             # specialist_router and post_validation_router functions
│   ├── pandas_specialist.py  # Generates Pandas code via Claude with time-series context
│   ├── sql_specialist.py     # Generates SQLite queries via Claude with time-series context
│   ├── executor.py           # Runs Pandas or SQL, sanitizes NaN/Inf before returning
│   ├── anomaly_node.py       # In-flight anomaly detection node (runs after executor)
│   ├── validator.py          # Quality gate — pass / retry / fail logic, no LLM calls
│   └── synthesizer.py        # Combines subtask results into final answer via Claude
└── data/
    └── saas_metrics.csv      # Generated sample dataset (gitignored, generate locally)
```