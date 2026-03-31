🧠 DENTAL AGENT – COMANDOS ESENCIALES (VS Code / Windows)
1️⃣ Activar entorno virtual (venv)

👉 Siempre lo primero antes de ejecutar nada.

.\.venv\Scripts\Activate.ps1


Si no existe el venv (solo una vez):

python -m venv venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

2️⃣ Lanzar el backend / agente (FastAPI)

Desde la raíz del proyecto:

uvicorn backend.main:app --reload --port 8000


Resultado esperado:

API viva en http://localhost:8000

Logs en tiempo real en la terminal

3️⃣ Probar el agente en local (sin WhatsApp)

Si tienes endpoint tipo /chat:

curl -X POST http://localhost:8000/chat `
  -H "Content-Type: application/json" `
  -d '{"sender":"test-local","user":"Hola"}'


(O usa Postman / Thunder Client si prefieres GUI)

4️⃣ Exponer el backend con Cloudflare Tunnel (IMPRESCINDIBLE)

👉 Esto es lo que permite que Twilio llame a tu localhost.

Arrancar Cloudflare (cada vez que pruebas)
cloudflared tunnel --url http://localhost:8000


Salida clave (ejemplo):

https://seems-boxes-asn-servers.trycloudflare.com


⚠️ Ese dominio cambia cada vez.
Ese es el que tienes que copiar en Twilio.

5️⃣ URL correcta para Twilio WhatsApp Webhook

En Twilio → WhatsApp → Sandbox / Number → WHEN A MESSAGE COMES IN

https://TU-TUNEL.trycloudflare.com/whatsapp-twilio


Ejemplo real:

https://seems-boxes-asn-servers.trycloudflare.com/whatsapp-twilio


👉 Método: POST
👉 Guardar cambios

6️⃣ Ver base de datos (leads + handoffs)

Abrir SQLite:

sqlite3 .\backend\data\leads.db


Ver tablas:

.tables


Ver últimos handoffs:

SELECT * FROM handoffs ORDER BY id DESC LIMIT 10;


Salir:

.exit

7️⃣ Resetear estados / sesiones (si algo se queda pillado)

Si tienes función cleanup_sessions() se ejecuta sola, pero si no:

👉 Borra sesiones manualmente:

DELETE FROM sessions;


👉 O borra un sender concreto:

DELETE FROM sessions WHERE sender = 'test_final-1';

1️⃣ Preparación local (ANTES de tocar Render)
1.1 Entorno limpio
pytest
pre-commit run --all-files


✔️ Todos los tests deben pasar
✔️ Ningún hook debe fallar

Si aquí falla algo, NO continúes.

1.2 Commit final
git status
git add .
git commit -m "feat: production-ready"
git push


Este push es el que Render va a desplegar.

2️⃣ GitHub (una sola vez)

Requisitos:

Repositorio público o privado (Render soporta ambos)

Rama principal: main

Código subido y actualizado

Verificación rápida:

git branch
git log --oneline -5

3️⃣ Render – Web Service
3.1 Crear servicio

Tipo: Web Service

Source: GitHub

Repo: dental-agent

Branch: main

3.2 Runtime (CRÍTICO)

⚠️ NO usar Python 3.14

En Render → Settings → Runtime:

Python 3.12.x


Esto es obligatorio por chromadb + pydantic v1.

3.3 Start Command

En Render → Settings → Start Command:

uvicorn backend.main:app --host 0.0.0.0 --port 10000


✔️ backend.main:app
✔️ Puerto fijo (10000)

3.4 Variables de entorno (ENV)

Render → Environment → Add variables:

OPENAI_API_KEY=sk-xxxx
MODEL=gpt-4o-mini
DB_PATH=backend/data/leads.db

TWILIO_AUTH_TOKEN=xxxxxxxx


⚠️ Nunca subir estas claves a GitHub.

3.5 Deploy

Pulsa Deploy
Espera a que el estado sea:

✅ Live

Comprueba:

https://TU-SERVICIO.onrender.com/


Debe devolver ok.

4️⃣ Verificación API (sin Twilio)
4.1 Test /chat
curl -X POST https://TU-SERVICIO.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"user":"Quiero cita","sender":"demo"}'


Debe devolver JSON con reply.

5️⃣ Twilio – WhatsApp Sandbox
5.1 Sandbox activo

Twilio Console → Messaging → WhatsApp Sandbox

Copiar:

Sandbox number

Join code

5.2 Webhook correcto (ESTO ERA EL BUG)

En When a message comes in:

https://TU-SERVICIO.onrender.com/whatsapp-twilio


❌ /webhook/twilio → NO
✅ /whatsapp-twilio → SÍ

Método:

POST


Guardar cambios.

6️⃣ Verificación Twilio (manual)

Desde WhatsApp:

Quiero cita


Debe:

Responder el bot

Crear estado en SQLite

Entrar en booking flow

En Render logs debes ver:

POST /whatsapp-twilio 200

7️⃣ Tests automáticos de Twilio (local)
pytest tests/test_twilio_webhook.py


✔️ Status 200
✔️ application/xml
✔️ <Response><Message>