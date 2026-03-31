# Scaffold Web Agent

A multi-tenant SaaS platform for deploying AI-powered lead capture agents on any website. Each client (tenant) gets their own embeddable chat widget, powered by Claude, trained on their own business knowledge.

Built as a portfolio project to demonstrate real-world AI engineering skills: multi-tenant architecture, LLM integration, production deployment, and automated lead delivery.

**Live demo:** [dental-agent-bn18.onrender.com/scaffold-agent/demo?token=tok_synapse_demo_001](https://dental-agent-bn18.onrender.com/scaffold-agent/demo?token=tok_synapse_demo_001)

---

## What it does

- Embeddable chat widget installable on any website with a single `<script>` tag
- Each tenant has their own knowledge base — the agent answers questions about their specific business
- Captures leads naturally: collects visitor email and need through conversation
- Delivers leads by email to the tenant's inbox when the visitor confirms
- Admin panel to manage tenants, inspect sessions, analytics, leads, and events

---

## Architecture

```
Browser widget (JS)
      │
      ▼
FastAPI backend
      │
      ├── /scaffold-agent/chat          ← widget sends messages here
      ├── /scaffold-agent/admin/page    ← admin panel UI
      ├── /scaffold-agent/admin/*       ← admin API (token protected)
      └── /scaffold-agent/widget.js     ← embeddable widget script
            │
            ├── LLM Engine (Claude Haiku)   ← tenants with knowledge_text
            └── Rules Engine                ← tenants without knowledge_text
```

**Multi-tenant routing:** each request is authenticated by `widget_token`. The backend resolves the tenant, loads their `knowledge_text`, and routes to the correct engine.

**Conversation persistence:** full message history is stored per session in SQLite, so the LLM has context across messages.

**Lead pipeline:** when the LLM collects an email and the visitor confirms, the agent saves the lead to the database and sends it by email to the tenant's inbox.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| AI | Anthropic Claude Haiku (claude-haiku-4-5) |
| Database | SQLite (via custom store with auto-migrations) |
| Email | Resend |
| Frontend | Vanilla JS widget, embedded HTML admin panel |
| Deploy | Render (auto-deploy from GitHub) |
| Testing | pytest, with mocked Anthropic API |
| Linting | Ruff + pre-commit hooks |

---

## Project structure

```
backend/
├── main.py                          # FastAPI app entrypoint
├── apps/
│   └── scaffold_web_agent/
│       ├── api.py                   # All routes
│       ├── llm_engine.py            # Claude-powered conversation engine
│       ├── engine.py                # Rule-based engine (fallback)
│       ├── chat_service.py          # Routes to LLM or rules engine
│       ├── domain.py                # SessionState, Step, CaseData models
│       ├── sqlite_store.py          # SQLite persistence + auto-migrations
│       ├── tenant_service.py        # Tenant CRUD
│       ├── session_service.py       # Session management
│       ├── lead_service.py          # Lead storage
│       ├── analytics_service.py     # Session analytics
│       ├── event_service.py         # Event logging
│       ├── delivery_service.py      # Lead email delivery
│       ├── admin_template.py        # Admin panel HTML/JS
│       ├── widget_template.py       # Embeddable chat widget JS
│       └── demo_template.py         # Demo page
├── data/
│   └── synapse_labs_knowledge.md    # Example knowledge base
scripts/
└── create_scaffold_tenant.py        # CLI to create/update tenants
tests/
└── test_llm_engine.py               # LLM engine, routing, serialization tests
```

---

## Running locally

**1. Clone and install dependencies**

```bash
git clone https://github.com/SpicySabeso/LanderWorks-Agents
cd dental-agent
pip install -r requirements.txt
```

**2. Set up environment variables**

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
ADMIN_TOKEN=your-secret-admin-token
```

**3. Start the server**

```bash
uvicorn backend.main:app --reload --port 8000
```

**4. Create a tenant**

```bash
python scripts/create_scaffold_tenant.py \
  http://localhost:8000 \
  your-admin-token \
  demo \
  youremail@example.com \
  "http://localhost:8000" \
  --knowledge backend/data/synapse_labs_knowledge.md
```

**5. Open the demo**

```
http://localhost:8000/scaffold-agent/demo?token=<widget_token_from_step_4>
```

---

## Admin panel

Access at `/scaffold-agent/admin/page`. Enter the base URL and admin token to manage tenants.

Each tenant card exposes:
- **Analytics** — session counts, lead conversion rate
- **Sessions** — full session history with state JSON
- **Leads** — captured leads with email, topic, and conversation summary
- **Events** — detailed event log per session
- **Knowledge** — the business knowledge text powering the agent
- **Rotate token** — generate a new widget token (invalidates the old one)
- **Revoke token** — disable the widget immediately

---

## Installing the widget on any website

After creating a tenant, add one line to any HTML page:

```html
<script src="https://dental-agent-bn18.onrender.com/scaffold-agent/widget.js?token=YOUR_WIDGET_TOKEN"></script>
```

---

## Running tests

```bash
pytest tests/ -v
```

Tests cover: LLM engine responses, lead marker detection, email extraction, chat service routing (LLM vs rules), SQLite serialization, and backward compatibility with old sessions.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude Haiku |
| `ADMIN_TOKEN` | Yes | Secret token to access the admin API |
| `SCAFFOLD_INBOX_EMAIL` | No | Default inbox (overridden per tenant) |