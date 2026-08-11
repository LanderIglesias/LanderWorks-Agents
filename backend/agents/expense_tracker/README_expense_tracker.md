# Expense Tracker

Seguimiento personal de gastos, instalable en iPhone como PWA desde Safari.
Agente 13 del portfolio, uso individual, no publicado en App Store.

## Por qué el alta manual no es un "nice to have"

El trigger de "Transacción" de Atajos, usado en la automatización de Wallet
(punto 1 más abajo), tiene bugs documentados y sin resolver por Apple
(**FB14035016**, **FB16379100**): la automatización puede hacer timeout y
fallar en silencio, sin notificar al usuario. Esto significa que, para
cualquier compra, la fuente "principal" de datos puede simplemente no
llegar. El botón de alta manual (flotante, siempre visible en la pantalla
principal de la PWA) no es una función secundaria — es la red de seguridad
del sistema completo. Si el diseño de este proyecto dependiera de que Wallet
funcione siempre, el sistema perdería gastos de forma silenciosa.

Como capa adicional de fiabilidad, cuando la tarjeta de Laboral Kutxa se usa
con Apple Pay, la misma compra real llega por DOS canales independientes —
Wallet y el email del banco. `engine.py` deduplica esos dos eventos en una
sola fila (ver la sección de deduplicación más abajo); si en algún momento
ambos fallan a la vez, solo el alta manual cubre el hueco.

## Modelo de datos

Ver `database.py`. Nota sobre dos decisiones que se apartan ligeramente de
la spec original del proyecto:

- **`amount` es nullable**, no `NOT NULL`. Si el regex de `parsers.py` no
  encuentra ni siquiera el importe en un email, la fila se guarda igual con
  `needs_review=True` y `raw_text` intacto — nunca se descarta el dato. Un
  `NOT NULL` habría forzado a inventar un `0.0` que se confundiría con
  gastos reales de importe cero en los totales agregados.
- **`merged_source`** (nullable, mismo enum que `source`) marca cuándo un
  gasto fue confirmado por dos canales independientes — ver deduplicación.

## Deduplicación (engine.py)

Pagar con Apple Pay usando la tarjeta de Laboral Kutxa dispara DOS eventos
para la misma compra real: el trigger de Wallet y el email de aviso del
banco. `ingest_webhook()` en `engine.py` evita que eso cree dos filas:

1. Al llegar un gasto de `source=wallet` o `source=email_bank`,
   `find_duplicate_candidate()` busca una fila existente del canal
   contrario con el mismo importe exacto y `occurred_at` dentro de
   **±90 segundos** (no ±5 minutos: una ventana más ancha aumentaría el
   riesgo de fusionar dos compras reales distintas — p. ej. dos cafés
   seguidos del mismo importe — en una sola fila, perdiendo una sin dejar
   rastro. A diferencia de cualquier otro fallo del sistema, una fusión
   incorrecta no se marca `needs_review`: la segunda fila simplemente nunca
   se crea. Por eso la ventana es deliberadamente ajustada).
2. Si hay match, `merge_duplicate()` actualiza la fila existente en vez de
   insertar: se queda con el `merchant` más descriptivo de los dos, rellena
   `raw_text` si la fila venía de Wallet sin él, y anota `merged_source`.
3. Cada fusión (y cada desempate cuando hay más de un candidato en la
   ventana) queda registrada con `logger.info(...)` — IDs implicados,
   fuentes, importe, y el criterio de desempate usado si aplicable. Es la
   única forma de diagnosticar si el total no cuadra.

`email_paypal` y `manual` nunca pasan por deduplicación: no existe un
segundo canal que reporte la misma compra de PayPal.

## Automatizaciones de Atajos (iPhone)

Configúralas en la app **Atajos** de iOS, en la pestaña **Automatización**.
Las tres llaman a `POST https://<tu-dominio>/expense-tracker/webhook/expense`
con `Content-Type: application/json`.

> Desde que se añadió autenticación (ver sección "Seguridad" más abajo),
> las tres automatizaciones también deben añadir `Authorization: Bearer
> <EXPENSE_TRACKER_WEBHOOK_SECRET>` y `X-Timestamp` en las cabeceras — sin
> ellas el servidor responde 401.

### 1. Transacción de Wallet

1. Automatización → **+** → **Crear automatización personal**.
2. Elige el activador **Transacción** → selecciona la(s) tarjeta(s) que
   quieras trackear (p. ej. la tarjeta de Laboral Kutxa) → **Siguiente**.
3. Desactiva **"Preguntar antes de ejecutar"** (si no, no dispara en
   segundo plano).
4. Añade la acción **Obtener contenido de URL**:
   - **URL:** `https://<tu-dominio>/expense-tracker/webhook/expense`
   - **Método:** `POST`
   - **Cabeceras:**
     - `Content-Type: application/json`
     - `Authorization: Bearer <EXPENSE_TRACKER_WEBHOOK_SECRET>`
     - `X-Timestamp`: hora actual en formato **ISO 8601** — en Atajos,
       **Fecha actual** → **Formatear fecha** → elige **"ISO 8601"**
       directamente en el desplegable de formato, sin pasos intermedios.
       (El patrón de formato personalizado no genera unix time como cabría
       esperar — por eso el header usa ISO 8601 y no un entero unix.)
   - **Cuerpo de solicitud:** `JSON`, con estos campos (usa las variables
     mágicas del activador de Transacción):
     ```json
     {
       "source": "wallet",
       "merchant": "Comercio de la Transacción",
       "amount": "Importe de la Transacción",
       "occurred_at": "Fecha actual"
     }
     ```
     (En el editor de Atajos, sustituye cada valor de texto por la variable
     mágica correspondiente: "Comercio", "Importe" y "Fecha actual" del
     activador de Transacción — no escribas el texto literal.)

### 2. Email de Laboral Kutxa (`postamail@laboralkutxa.com`)

1. Automatización → **+** → **Crear automatización personal**.
2. Activador **Email** → **Remitente:** `postamail@laboralkutxa.com` →
   **Cualquier cuenta** (o la que uses para el banco) → **Siguiente**.
3. Desactiva **"Preguntar antes de ejecutar"**.
4. Añade **Obtener contenido de URL**:
   - **URL / Método / Cabeceras:** igual que arriba.
   - **Cuerpo de solicitud:** `JSON`:
     ```json
     {
       "source": "email_bank",
       "raw_text": "Contenido del correo del activador",
       "occurred_at": "Fecha actual"
     }
     ```
     (Usa la variable mágica "Contenido del correo" del activador de
     Email para `raw_text` — texto completo, sin recortar.)

### 3. Email de PayPal

Igual que el punto 2, cambiando:
- **Remitente:** el remitente de notificaciones de PayPal (revisa un email
  real de PayPal en tu cuenta para confirmar la dirección exacta).
- **Cuerpo de solicitud:**
  ```json
  {
    "source": "email_paypal",
    "raw_text": "Contenido del correo del activador",
    "occurred_at": "Fecha actual"
  }
  ```

## Parseo de emails (parsers.py) — la pieza más frágil

`parsers.py` tiene un regex por remitente. Ambos devuelven `None` (nunca
lanzan excepción) si el formato no coincide exactamente, para que
`engine.py` pueda guardar la fila con `needs_review=True` en vez de perder
el dato. Los patrones actuales están escritos sobre el formato típico
documentado de cada remitente — en cuanto tengas emails reales guardados,
ajústalos contra esos ejemplos exactos y añade el caso a
`tests/expense_tracker/test_parsers.py`.

- **`parse_bank_email`**: espera `"... en {COMERCIO} por importe de
  {IMPORTE} EUR"`. Dos regex independientes (importe y comercio); si
  cualquiera de los dos no matchea, devuelve `None` entero — un match
  parcial (solo importe sin comercio, o viceversa) no se considera
  suficiente porque una fila con `merchant=None` no es útil para
  categorizar ni para dedup.
- **`parse_paypal_email`**: cubre español (`"Has pagado X EUR a Y"`) e
  inglés (`"You paid €X to Y"`), porque PayPal manda el idioma según la
  configuración de la cuenta.
- **`_parse_spanish_decimal`** convierte `"1.234,56"` → `1234.56`;
  **`_parse_english_decimal`** convierte `"45.90"` → `45.90` directamente.

## Seguridad

Dos esquemas de autenticación distintos, para dos audiencias distintas
(ver `security.py`):

- **`POST /webhook/expense`** (llamado por las automatizaciones de Atajos,
  sin usuario presente — se disparan solas al pagar o al recibir un email):
  **Bearer token + timestamp**, no un login. La idea original era firmar
  cada petición con HMAC-SHA256 (como haría un webhook "de verdad"), pero
  Atajos —la app de automatizaciones de iOS que dispara estas llamadas— no
  tiene ninguna acción nativa para calcular un HMAC, solo hash plano
  (MD5/SHA1/SHA256/SHA512), que no es lo mismo: construir un HMAC real
  requeriría una extensión nativa en Swift, fuera de alcance de este
  proyecto. El esquema real, más simple pero suficiente dado que el secreto
  nunca se transmite en claro por otro canal, es:
  - `Authorization: Bearer <EXPENSE_TRACKER_WEBHOOK_SECRET>` — secreto
    estático, **distinto** de `EXPENSE_TRACKER_APP_TOKEN` (nunca se
    reutiliza el mismo secreto para el webhook y para la PWA).
  - `X-Timestamp`: fecha en formato ISO 8601 (ej. "2026-08-11T10:45:00Z"),
    generada por el propio Atajo en el momento de la llamada — no unix
    timestamp: Atajos no tiene forma sencilla de generar un entero unix
    directamente (el patrón de formato personalizado no lo soporta como
    cabría esperar), pero sí ofrece "ISO 8601" nativo en el desplegable de
    formato de fecha.

  El servidor rechaza la petición (401 genérico, sin detallar cuál de las
  dos comprobaciones falló) si el token no coincide (comparación con
  `hmac.compare_digest`, no `==`, para evitar timing attacks — eso no
  cambia aunque ya no haya HMAC de por medio) o si el timestamp se aleja
  más de 60s de la hora del servidor (previene repetición de una petición
  capturada: sin esto, un token filtrado permitiría reenviar la misma
  petición indefinidamente). Además, `/webhook/expense` está limitado a
  **20 peticiones/minuto por IP** (`slowapi`) muy por encima del uso real
  (unas pocas al día), como corte ante fuerza bruta contra el token.

  Al configurar la acción **Obtener contenido de URL** en Atajos, añade en
  **Cabeceras** `Authorization: Bearer <EXPENSE_TRACKER_WEBHOOK_SECRET>` y
  `X-Timestamp` con la hora actual en formato ISO 8601 (**Fecha actual** →
  **Formatear fecha** → elige "ISO 8601" directamente en el desplegable,
  sin pasos intermedios).

- **`GET /expenses`, `GET /expenses/{id}`, `GET /expenses/review`,
  `PATCH /expenses/{id}`, `POST /expenses`** (usados solo por ti, desde el
  navegador en la PWA): token estático simple en cabecera
  `Authorization: Bearer <EXPENSE_TRACKER_APP_TOKEN>`, comparado con
  `hmac.compare_digest`. Deliberadamente más simple que la firma del
  webhook — aquí sí hay un humano (tú) tecleando en el momento, así que no
  hace falta protegerse contra ataques de repetición automatizados. La PWA
  pide la clave una sola vez (pantalla "Introduce tu clave de acceso") y la
  guarda en `localStorage`; si el servidor responde 401 (p. ej. porque
  rotaste el token), la PWA borra el valor guardado y vuelve a pedirla.

### Rotación de secretos

Rota `EXPENSE_TRACKER_WEBHOOK_SECRET` y `EXPENSE_TRACKER_APP_TOKEN` cada
**trimestre**, o de inmediato si sospechas que alguno se filtró. Es un paso
manual, no automatizado:

1. Genera un valor nuevo:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Actualiza el `.env` del servidor (EC2) con el nuevo valor.
3. Reinicia el servicio (`docker compose restart` o el proceso de
   `uvicorn`, según cómo lo tengas desplegado) para que recoja el cambio.
4. Actualiza el valor en las **3 automatizaciones de Atajos** (cabecera
   `Authorization: Bearer ...`) si rotaste `EXPENSE_TRACKER_WEBHOOK_SECRET`.
5. Si rotaste `EXPENSE_TRACKER_APP_TOKEN`: la próxima vez que abras la PWA
   verás la pantalla de clave de nuevo automáticamente (el 401 limpia el
   valor viejo de `localStorage`) — solo tienes que volver a teclear el
   nuevo token.

## Ejecutar en local

```bash
docker-compose up db_expense_tracker --build
uvicorn backend.main:app --reload --port 8000
# PWA: http://localhost:8000/expense-tracker/
# Docs: http://localhost:8000/docs
```

Para instalar en iPhone: abre la URL pública en Safari → compartir →
**"Añadir a pantalla de inicio"**.

## Tests

```bash
pytest tests/expense_tracker -v
```
