# AI Lead Capture SaaS Platform

Multi-tenant SaaS platform that deploys AI-powered lead capture agents on any website with a single `<script>` tag. Features streaming responses (SSE), LLM observability via Langfuse, and is deployed on both AWS EC2 and Azure App Service.

**Portfolio:** [notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d](https://www.notion.so/Lander-Iglesias-ed9bca668ca08368ab0c81aed0869e1d)  
**Live demo (Azure):** [lander-lead-capture.azurewebsites.net](https://lander-lead-capture.azurewebsites.net)

---

## The problem

Businesses need to capture leads from website visitors 24/7 — but generic chatbots feel robotic, and custom solutions are expensive to build and maintain per client. There's no easy way to deploy a knowledge-trained AI agent on a client's website without code changes, and no visibility into what the agent is doing in production.

---

## Solution

A multi-tenant platform where each client (tenant) gets their own AI agent configured with their business knowledge. The agent is deployed on any website with a single `<script>` tag — no backend changes required. Responses stream progressively like ChatGPT. Every conversation is traced in Langfuse for full LLM observability.

---

## Architecture

```
Client website (any domain)
       │
       ▼
  <script> widget tag
       │
       ▼
  FastAPI backend
       │
  ┌────┴────────────────────┐
  │                         │
  ▼                         ▼
Token validation      Tenant lookup (SQLite)
  │                         │
  └────────┬────────────────┘
           │
    knowledge_text injected
    as Claude system prompt
           │
           ▼
      Claude Haiku
  (tenant-specific agent)
           │
    ┌──────┴───────────────────┐
    │              │           │
    ▼              ▼           ▼
Lead captured  SSE stream  Langfuse trace
(email saved)  (chunks →   (tokens, latency,
    │           widget)     metadata logged)
    ▼
Email delivered
via Resend
```

---

## Key features

**Streaming responses (SSE)**
Words appear progressively as Claude generates them — same UX as ChatGPT. Implemented via `StreamingResponse` with `media_type="text/event-stream"` and `X-Accel-Buffering: no` to disable proxy buffering. The lead marker `<<<SEND_LEAD>>>` is detected in the accumulated buffer without ever being shown to the user.

**Multi-tenant isolation**
Each client has their own token, knowledge base, allowed origins, and conversation sessions. One platform, unlimited clients. Tenants are managed via an admin panel — no code changes needed to onboard a new client.

**Single script deployment**
```html
<script src="https://your-domain.com/scaffold-agent/widget.js?token=tok_client_123"></script>
```
Zero backend changes on the client's side.

**Per-tenant Claude agents**
Each tenant's `knowledge_text` is injected as Claude's system prompt. The agent answers as a specialist for that specific business without knowing anything about other tenants.

**LLM Observability with Langfuse**
Every conversation is traced:
- Token usage per message and per session
- Latency tracking per LLM call
- Input/output logged for quality monitoring
- Conversation metadata (tenant, session, lead status)

**Corrección aplicada tras un bug real** (ver "Errors resolved" abajo):
la ruta de streaming usaba `langfuse.trace(name=...).generation(...)`,
un método que **no existe** en la versión fijada en `requirements.txt`
(`langfuse==4.5.1`) — confirmado instanciando el cliente real:
`Langfuse().trace(...)` lanza `AttributeError`. Estaba envuelto en
`except Exception: pass`, así que fallaba en silencio en cada respuesta
en streaming, sin dejar rastro y sin que ningún test lo detectara (la
ruta sin streaming, con `create_event`, sí funcionaba y no se vio
afectada). La API correcta para `langfuse==4.5.x` es la de
spans/observaciones (`start_as_current_observation`/
`update_current_generation`/`create_event`) — ver
`langfuse_utils.py`, que centraliza los tres puntos de contacto con
Langfuse de este agente y replica el mismo patrón ya verificado en
`backend/agents/taller_mecanico/langfuse_utils.py`.

**Automatic lead capture**
The agent identifies when a visitor provides their email through natural conversation. The lead is confirmed, saved to SQLite, and delivered to the client via email (Resend).

**Deployed on two clouds**
- **AWS EC2** — t3.micro, eu-west-1, IAM user, CLI configuration
- **Azure App Service** — B1, West Europe, ACR, PaaS managed deployment

---

## Tech stack

| Layer | Technology |
|---|---|
| LLM | Anthropic Claude Haiku |
| LLM Observability | Langfuse |
| Streaming | Server-Sent Events (SSE) |
| Backend | FastAPI, Python 3.12 |
| Database | SQLite |
| Email delivery | Resend |
| Cloud (AWS) | EC2, IAM |
| Cloud (Azure) | App Service, Container Registry (ACR) |
| Containerization | Docker |
| CI/CD | GitHub Actions |
| Code quality | ruff, Black, pytest, gitleaks |

---

## Key technical decisions

**Why SSE instead of WebSockets?**
SSE is unidirectional (server → client) which is exactly what streaming LLM responses need. WebSockets are bidirectional and add unnecessary complexity. SSE works over standard HTTP, is easier to proxy, and FastAPI's `StreamingResponse` supports it natively.

**Why Langfuse for observability?**
Langfuse is the standard LLMOps tool for tracing LLM applications. Token-level visibility without changing the agent's logic. The correct API for the pinned SDK version (`langfuse==4.5.1`) is the spans/observations API (`start_as_current_observation`/`update_current_generation`/`create_event`) — **not** `langfuse.trace().generation()`, which doesn't exist in that version. See "Errors resolved" below for the real bug this caused and how it was found and fixed.

**Why inject knowledge as system prompt instead of RAG?**
For short business knowledge (services, pricing, FAQs), a system prompt is simpler, faster, and cheaper than a full RAG pipeline. For typical SMB clients, this is the right trade-off.

**AWS vs Azure — key differences learned**
- AWS uses static access keys; Azure uses OAuth interactive login (`az login`)
- Azure Resource Groups have no direct AWS equivalent — they're logical containers for all resources
- Azure App Service requires `WEBSITES_PORT=8000` explicitly — without it, Azure tries port 80 and the container fails
- Azure ACR ≈ AWS ECR for private Docker registries

---

## Auditoría de PII: transcripción completa a Langfuse

Cuando se corrigió el bug de `langfuse.trace().generation()` (ver
"Errors resolved"), la ruta de streaming empezó a mandar la
transcripción completa de la conversación (`messages_for_api`) a
Langfuse en cada turno. La ruta sin streaming seguía mandando solo
`{"user_text": user_text}` — mucho menos detalle. Antes de unificar
ambas rutas al mismo nivel (transcripción completa en las dos), se hizo
la misma auditoría de PII que ya se aplicó en `taller_mecanico` como
requisito no negociable, porque la transcripción de un visitante puede
contener nombre, email, teléfono o detalles sensibles de su consulta —
cualquier cosa que escriba buscando ser contactado.

**Dónde vive ya esa misma transcripción, fuera de este cambio** (el
mismo tipo de comprobación que en `taller_mecanico`: "¿ya está en el
mismo perímetro de confianza, o esto es exposición nueva?"):

1. `scaffold_leads.summary` (SQLite local, **sin cifrar** — a diferencia
   de `clientes` en `taller_mecanico`, que sí usa Fernet) — vía
   `_build_lead_summary()`, contiene la transcripción completa, pero
   **solo cuando el lead se confirma** (`SEND_LEAD`).
2. `delivery_service.py` → `mailer.send(tenant.inbox_email, subject,
   summary)` — esa misma transcripción completa **ya se manda hoy, en
   producción, sin ninguna redacción, a la bandeja de entrada de un
   tercero** (el negocio-cliente del tenant, vía Resend) — un salto de
   perímetro de confianza mayor que Langfuse, porque sale a una empresa
   distinta, no solo a la propia herramienta de analítica del operador.

**La asimetría real que NO comparten**: Langfuse recibe la transcripción
en **cada turno**, incluso si el visitante nunca confirma un lead.
SQLite/el email al tenant solo la capturan **una vez confirmado**. Al
unificar las dos rutas, Langfuse pasa a ver conversaciones completas que
ni siquiera llegan a convertirse en un lead — estrictamente más
superficie que la que hoy tienen SQLite o el email al tenant.

**Las tres opciones planteadas, y la decisión tomada:**

1. ~~Mandar la transcripción tal cual, sin redacción~~ — descartada.
2. **Redactar el email antes de mandar la transcripción — decisión
   tomada.** Reutiliza `_EMAIL_RE`, el regex que el propio motor ya usa
   para capturar el email del visitante — no es un mecanismo nuevo.
3. ~~Aceptable tal cual porque Langfuse ya es el mismo perímetro de
   confianza~~ — el argumento es parcialmente cierto (ver los dos puntos
   de arriba) pero no completo, precisamente por la asimetría de
   frecuencia (cada turno vs. solo al confirmar) — no bastaba por sí
   solo para renunciar a la redacción del campo más identificable y más
   fácil de detectar de forma fiable.

**Por qué NO se cubre teléfono ni nombre en texto libre**: no existe hoy
ningún regex de teléfono en el motor (los formatos internacionales son
poco fiables de cubrir con un único patrón), y el nombre no tiene ningún
patrón reconocible en absoluto. Intentar cubrirlos daría una falsa
sensación de protección completa sin ofrecerla de verdad — mismo
principio que llevó a NO intentar redactar teléfono en `taller_mecanico`.
**Riesgo residual aceptado explícitamente**: un visitante que escriba su
nombre o teléfono en texto libre, sin acompañarlo de un email
reconocible, verá ese dato llegar a Langfuse sin redactar.

**Implementación**: `_redactar_email()` (en `llm_engine.py`) se aplica a
`input` (la transcripción) **y a `output`** (la respuesta del LLM) antes
de mandar cualquiera de los dos a Langfuse, en ambas rutas. El campo
`output` no era obvio al principio: se descubrió al verificar contra el
**servidor real** de Langfuse (no un test mockeado) que Claude a veces
repite el email del visitante en su propia respuesta para confirmarlo
("He anotado tu email: real-test@empresa.com") — redactar solo la
transcripción de entrada dejaba el email intacto en la respuesta que
también se manda a Langfuse. Ningún test mockeado lo había detectado
porque ninguna respuesta de prueba anterior incluía un email — exactamente
el tipo de hallazgo que solo aparece verificando contra el SDK/servidor
real, no contra mocks. Test de regresión:
`test_llm_engine.py::TestObservabilidadLangfuseUnificada::test_email_repetido_por_el_llm_en_su_propia_respuesta_tambien_se_redacta`
(y su equivalente en streaming).

---

## Limitations

- **Render/SQLite ephemeral storage.** SQLite data is lost on redeploy. Re-create tenants via the admin panel.
- **No conversation memory across sessions.** Each new page load starts fresh.
- **Langfuse latency.** Adds ~50ms per trace. Acceptable for conversational agents.
- **Historical test pollution (found, not fully undoable).** Before this fix, `llm_engine.py` constructed a real `Langfuse()` client eagerly at import time (`langfuse = Langfuse()`), with no test-time gate. Any test calling `handle_user_message_llm()` (most of `test_llm_engine.py` did, mocking only `anthropic.Anthropic`) sent a real `create_event` to the live Langfuse project on every test run. This means some fraction of the historical `lead-capture-chat`/`lead-capture-greeting` traces in the Langfuse dashboard are test noise, not real visitor conversations — there's no reliable way to tell them apart after the fact from the trace name alone. Fixed going forward: `tests/lead_capture_agent/conftest.py` now has an autouse `langfuse_desactivado` fixture (same pattern as `taller_mecanico`'s) that disables Langfuse for the whole test suite by default.

---

## Deployment

### Azure App Service

```bash
# Login
az login

# Create resource group
az group create --name lander-portfolio-rg --location westeurope

# Create App Service plan (B1 = 1 core, 1.75GB RAM)
az appservice plan create --name lander-plan --resource-group lander-portfolio-rg --sku B1 --is-linux

# Create Container Registry
az acr create --name landerregistry --resource-group lander-portfolio-rg --sku Basic --admin-enabled true

# Build and push image
docker build -t landerregistry.azurecr.io/lead-capture:latest .
docker push landerregistry.azurecr.io/lead-capture:latest

# Create web app
az webapp create --name lander-lead-capture --resource-group lander-portfolio-rg \
  --plan lander-plan --deployment-container-image-name landerregistry.azurecr.io/lead-capture:latest

# Set environment variables (WEBSITES_PORT is critical)
az webapp config appsettings set --name lander-lead-capture \
  --resource-group lander-portfolio-rg \
  --settings WEBSITES_PORT=8000 ANTHROPIC_API_KEY=... RESEND_API_KEY=...
```

### Running locally

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.main:app --reload --port 8000
```

---

## Errors resolved

| Error | Cause | Fix |
|---|---|---|
| `ContainerTimeout` on Azure | Doc Intel Agent tried to connect to PostgreSQL at startup — blocked container init | `try/except` around `init_doc_intel_db()` in `main.py` |
| `ModuleNotFoundError: langfuse` | Works locally (installed in venv) but not in Docker (only requirements.txt is installed) | Add `langfuse` to `requirements.txt` |
| Container fails to start on Azure | Azure tries port 80 by default | Set `WEBSITES_PORT=8000` in App Settings |
| `TypeError: 'bool' object is not iterable` | Bug in SSE lead marker filter | Fixed generator logic in `stream_user_message_llm` |
| Streaming responses never appeared in Langfuse | `stream_user_message_llm` used `langfuse.trace(name=...).generation(...)` — that method doesn't exist in `langfuse==4.5.1` (`AttributeError`, confirmed against the real SDK), silently swallowed by `except Exception: pass`. Zero test coverage on this function meant it went undetected. | Rewrote to use the spans API (`langfuse_utils.py`, new module: `start_as_current_observation`/`update_current_generation`), with failures now logged via `logger.exception(...)` instead of silently discarded. Added the first tests ever written for `stream_user_message_llm`, including Langfuse resilience tests. Verified against the real SDK (real trace created and inspected via `client.api.trace.get(...)`/`get_trace_url()`), not just mocks. |

---

## Environment variables

| Variable | Required for |
|---|---|
| `ANTHROPIC_API_KEY` | Claude Haiku calls |
| `RESEND_API_KEY` | Email delivery |
| `ADMIN_TOKEN` | Admin panel access |
| `LANGFUSE_PUBLIC_KEY` | Langfuse tracing |
| `LANGFUSE_SECRET_KEY` | Langfuse tracing |
| `LANGFUSE_HOST` | Langfuse endpoint (default: cloud.langfuse.com) |
| `WEBSITES_PORT` | Azure App Service only — must be 8000 |

---

## Project structure

```
backend/agents/lead_capture_agent/
├── api.py              # FastAPI endpoints — /chat and /chat/stream (SSE)
├── llm_engine.py       # Claude integration + Langfuse + SSE streaming
├── tenant_store.py     # SQLite tenant management
├── session_state.py    # In-memory conversation history
├── lead_store.py       # Lead capture and storage
├── email_service.py    # Resend email delivery
├── admin_panel.py      # Admin UI and API
├── tenant_cors.py      # Per-tenant CORS middleware
└── widget_template.py  # Embeddable widget with ReadableStream SSE consumer
```