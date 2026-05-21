# Job Matcher Agent

Hybrid ML + LLM system that scores the fit between a CV and a job offer. Combines a GradientBoostingRegressor trained on Claude-labeled data with LLM-generated gap analysis and recommendations.

**Portfolio:** [notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d](https://www.notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d)

---

## The problem

Job seekers waste hours applying to roles they don't fit. Recruiters waste time screening mismatched candidates. There's no fast, objective way to score CV-job fit before applying — most people rely on gut feeling or keyword matching, which misses context entirely.

---

## Solution

A 3-phase pipeline that combines classical ML with LLMs:

1. **Claude labels training data** — 500 synthetic CV/job pairs scored 0-100 by Claude acting as an HR expert
2. **GradientBoosting learns the pattern** — model learns to imitate Claude's scoring criterion at millisecond speed
3. **The agent scores real CVs** — accepts PDF/DOCX/URL input, extracts structured features, returns ML score + LLM gap report

The key insight: use Claude to generate labeled data cheaply ($0.13 for 500 samples), train a fast ML model on that data, and use Claude again only for the qualitative report — not for every prediction.

---

## Architecture

```
User uploads CV (PDF/DOCX) + job offer (URL or text)
                    │
                    ▼
            extractor.py
    ┌───────────────┴──────────────┐
    │               │              │
  PyMuPDF      python-docx    httpx +
  (PDF)         (DOCX)       BeautifulSoup
                              (URL scraping)
                    │
                    ▼
         feature_extractor.py
         Claude extracts structured JSON:
         - experience_years, level, techs_match
         - diff_nivel, missing_techs, extra_techs
         - Synonym map: "LLM" → Claude API, OpenAI
                    │
            ┌───────┴───────┐
            │               │
            ▼               ▼
    GradientBoosting    llm_engine.py
    Regressor           Claude generates
    (milliseconds)      gap report + tips
            │               │
            └───────┬───────┘
                    ▼
            Score (0-100) + Report
            Circular ring UI
            Green pills (matches)
            Red pills (gaps)
```

---

## The 3 phases

### Phase 1 — generate_data.py
Generates 500 synthetic CV/job pairs with Python and scores each one with Claude (acting as an HR expert in AI Engineering). 

- **Cost:** ~$0.13 for 500 Claude calls
- **Output:** CSV with 14 features per pair + Claude score (0-100)
- **Features generated:** experience_years, level, techs_match_pct, missing_critical_techs, extra_techs, domain_match, language_match, diff_nivel, etc.

### Phase 2 — train_model.py
Trains a GradientBoostingRegressor to imitate Claude's scoring pattern.

| Metric | Value |
|---|---|
| MAE (cross-validation) | 8.04 points out of 100 |
| R² (test set) | 0.629 |
| Most important feature | diff_nivel (0.361) |
| Second most important | techs_match_pct (0.198) |

**Key finding:** the gap between candidate level and required level (`diff_nivel`) dominates the score. A junior applying to a senior role will score low regardless of tech stack match.

### Phase 3 — Full agent
Accepts a real CV (PDF or DOCX) and a job offer (URL or plain text). Returns:
- **ML score** — fast, deterministic, based on extracted features
- **LLM report** — Claude analyzes gaps and generates specific recommendations

---

## Key features

**Multi-format CV extraction**
- PDF via PyMuPDF (text extraction page by page)
- DOCX via python-docx
- Job offer URL via httpx + BeautifulSoup (scrapes and cleans HTML)

**Technology synonym map**
Normalizes different ways of saying the same thing before matching:
- "Vector databases" → ChromaDB, pgvector, vector search, Pinecone
- "LLM" → Claude API, OpenAI API, Anthropic, GPT
- "AI agents" → LangGraph, LangChain, CrewAI, AutoGen

Without this, "we use LLMs" and "Claude API experience required" would not match even though they mean the same thing.

**Hybrid scoring**
The ML model scores instantly (milliseconds). Claude is only called once for the qualitative report — not for every prediction. This keeps cost low and latency predictable.

**Score visualization**
Circular ring showing the score (0-100) with color gradient. Green pills for tech matches, red pills for gaps. Claude's report rendered in markdown below.

---

## Tech stack

| Layer | Technology |
|---|---|
| ML model | scikit-learn GradientBoostingRegressor |
| LLM | Anthropic Claude Haiku |
| PDF extraction | PyMuPDF |
| DOCX extraction | python-docx |
| URL scraping | httpx + BeautifulSoup |
| Backend | FastAPI, Python 3.12 |
| Training data | 500 synthetic pairs, Claude-labeled |

---

## Key technical decisions

**Why GradientBoosting instead of a simpler model?**
GradientBoosting handles non-linear relationships between features better than LinearRegression, and is more robust than RandomForest on small datasets. With 500 training samples and 14 features, GradientBoosting gave the best MAE/R² balance in cross-validation.

**Why use Claude to generate training data instead of human labels?**
Human labeling of 500 CV/job pairs would take days and cost hundreds of euros. Claude does it consistently in minutes for $0.13. The model learns Claude's scoring criterion — which is already a reasonable proxy for what an experienced HR professional would say.

**Why not use Claude for every prediction?**
Latency and cost. A Claude call takes 1-3 seconds and costs tokens. A trained GradientBoosting prediction takes <1ms and costs nothing after training. The ML model handles the scoring; Claude handles the qualitative report where its language generation is actually needed.

**Why pass `features` (full dict) and not `features_modelo` to the return?**
`features_modelo` only contains the numeric features used by the model. `techs_match_detalle` (the list of matched/missing technologies) exists in `features` but not in `features_modelo`. The frontend needs this for the green/red pills. Fix: always pass the full `features` dict to the return and to the LLM report; pass only `features_modelo` to the ML model.

---

## Limitations

- **500 training samples is small.** R²=0.629 means the model explains 63% of variance — decent for a first version, but a larger dataset would improve it significantly.
- **Claude labels introduce bias.** The model learns Claude's scoring criterion, which may differ from actual recruiter judgment. Validating against real hiring decisions would improve reliability.
- **URL scraping is fragile.** Job offer pages with JavaScript rendering (SPAs) return empty content to BeautifulSoup. A headless browser would be needed for those cases.
- **No model versioning.** The trained model is saved as a `.pkl` file. For production, MLflow or a similar tool would handle versioning and experiment tracking.

---

## Running locally

```bash
pip install -r requirements.txt

# Phase 1: generate training data
python backend/agents/job_matcher_agent/generate_data.py

# Phase 2: train the model
python backend/agents/job_matcher_agent/train_model.py

# Phase 3: run the agent
uvicorn backend.main:app --reload --port 8000
open http://localhost:8000/job-matcher/demo
```

---

## Project structure

```
backend/agents/job_matcher_agent/
├── api.py                  # FastAPI endpoints
├── extractor.py            # PDF/DOCX/URL content extraction
├── feature_extractor.py    # Claude extracts structured features + synonym map
├── llm_engine.py           # Claude gap report generation
├── templates.py            # Frontend — purple/violet UI, circular score ring
├── generate_data.py        # Phase 1: synthetic data generation + Claude labeling
├── train_model.py          # Phase 2: GradientBoosting training + evaluation
└── model/
    └── job_matcher.pkl     # Trained model (generated by train_model.py)
```
