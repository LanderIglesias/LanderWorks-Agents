# Tech Debt Agent v2 — Fase 1: auditor "senior review"

Fecha: 2026-11-12 · Código actual: `backend/agents/tech_debt_agent/`

## Intención

El agente se pasa sobre un repo terminado con vibe coding, antes de enseñarlo (portfolio, cliente, producción), y señala con precisión lo que delata que lo hizo un junior o una IA sin supervisión, con la seguridad primero. Debe servir para proyectos de empresa y en producción, no solo de demo.

El agente actual solo produce un score genérico (longitud de funciones, versiones de PyPI), analiza solo Python, Claude nunca ve código, no detecta nada de seguridad y premia los tests por existir. Además el propio endpoint es inseguro.

Plan por fases:
- **Fase 1 (este documento):** auditor web que detecta y explica. No modifica código.
- **Fase 2 (después):** skill local de Claude Code que arregla por lotes y ejecuta los tests reales.
- **Fase 3 (después):** modo PR en la web.

## Qué detecta: 8 familias (decidido con el usuario)

Cada hallazgo lleva familia, severidad (critical/high/medium/low), `archivo:línea`, por qué importa y cómo arreglarlo.

1. **Secretos**: API keys (OpenAI, Supabase, Stripe, AWS…) en código, configs y frontend, **incluido el historial de git**.
2. **Vulnerabilidades en código (SAST)**: inyección SQL, `eval`/`exec`, CORS `*`, endpoints sin autenticación, deserialización insegura (`pickle`, `yaml.load`), `subprocess` con `shell=True`.
3. **Dependencias con CVEs**: solo vulnerabilidades conocidas. "Desactualizada" deja de ser un hallazgo por sí solo.
4. **Manejo de errores**, separado en dos hallazgos distintos:
   - *errores tragados*: `except: pass`, `except Exception as e: print(e)` sobre bloques grandes, `catch {}` vacío;
   - *errores expuestos*: stack trace o `str(e)` devueltos al cliente, `DEBUG=True` / modo debug en producción.
5. **Monolitos y duplicación**: archivos que mezclan rutas, lógica de negocio y acceso a datos; bloques copiados y pegados; complejidad alta.
6. **Basura de depuración**: `print` y `console.log` sueltos, código comentado.
7. **Tests fantasma** (detección **estática**, sin ejecutar nada): no hay tests; tests sin asserts; `assert True`; tests que solo comprueban mocks. Un test fantasma nunca suma puntos.
8. **Huella de IA**: comentarios que narran el qué en lugar del porqué; nombres genéricos (`data`, `res`, `temp`, `item`); try/except gigantes; reimplementar cosas de la stdlib (parsear URLs a mano…); boilerplate de tutorial (CORS `*`, `useEffect` innecesarios, estado duplicado); estilo mezclado (camelCase/snake_case, indentación); README con emojis y tono de folleto, docstrings más largas que la función.

Lenguajes: **Python y JS/TS** (decidido con el usuario). Lo demás se cuenta pero no se analiza.

## Cómo lo detecta

- **Familias 1-3, la mayor parte de la 4 y la 6: herramientas maduras y deterministas.** No se reimplementan a mano (ponytail). Candidatas (*mi elección; el builder puede cambiarla si mide algo mejor*):
  - gitleaks: secretos, con historial.
  - semgrep: SAST Python y JS/TS, más reglas propias para la 4 y la 6 y partes de la 8.
  - ruff: Python. Reglas S (bandit), BLE (except ciego), T20 (`print`) y estilo.
  - osv-scanner: CVEs en `requirements*.txt`, `pyproject.toml`, `uv.lock`, `poetry.lock`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`.
  - lizard: complejidad y duplicación en Python y JS/TS, sin necesidad de Node.
- **Familia 7: análisis AST propio** de los archivos de test (Python con `ast`; JS/TS con semgrep o regex acotado, a criterio del builder).
- **Familia 8 y la parte de diseño de la 5: Claude lee código real.** Es el cambio de fondo. No cabe el repo entero, así que se seleccionan los archivos de mayor riesgo (los más grandes y complejos, los que más hallazgos acumulan y los puntos de entrada como `main.py` o `App.tsx`) hasta un presupuesto fijo de tokens por análisis. Claude devuelve hallazgos estructurados con `archivo:línea`. Hay que validar que cada línea citada existe y descartar los que no.
- Claude también redacta el resumen ejecutivo y el "qué tocar primero", a partir de los hallazgos ya agregados.
- LLM: salida estructurada con tool use o structured outputs, no con `replace("```")`. Con modelo actual, timeout y reintentos acotados. **El builder debe consultar la skill `claude-api`** para el modelo, los parámetros y la API, y no fiarse de la memoria. Mi elección: modelo Sonnet actual para leer código, porque Haiku se queda corto en juicio de diseño.

## Informe

- Organizado por familia, con la seguridad (1-4) primero.
- Arriba: **"Qué tocar primero"**, los 10 hallazgos más importantes ordenados por riesgo, cada uno con `archivo:línea`.
- Nota por familia (A-F) y score global 0-100 **normalizado por tamaño** (hallazgos por KLOC), para que un repo mediano no saque 0 automáticamente.
- **Puerta de seguridad** (*mi elección*): un secreto expuesto o un CVE crítico limita el score global a como máximo 40, sea cual sea el resto.
- Se mantiene la descarga en markdown y el streaming SSE de progreso.
- La UI de demo (`demo_template.py`) se adapta a la nueva estructura. El rediseño visual no está en el alcance de la Fase 1.

## Endurecimiento del propio agente (obligatorio)

El endpoint es público y procesa repos ajenos: es una frontera de confianza.

- **Nunca ejecuta código del repo.** Ni tests ni instalación de dependencias. Solo herramientas de análisis estático.
- **Validación de URL** con `urllib.parse`: host `github.com` exacto y path `owner/repo` con caracteres permitidos. Solo repos públicos.
- **Límite de tamaño antes de clonar**, consultando el tamaño en la API de GitHub. Valor a decidir por el builder: el EC2 tiene **6,8 GB de disco**, compartido con otros servicios.
- **Timeout global** del análisis y timeout por herramienta (`subprocess` con `timeout`, sin `shell=True`).
- **Clonado:** el historial completo se necesita para gitleaks. El builder elige la estrategia que lo permita dentro del límite de tamaño. Sin submódulos ni LFS.
- **Archivos:** no se siguen symlinks; se ignoran los archivos de más de N KB y los binarios. Se excluyen `venv`, `.venv`, `node_modules`, `dist`, `build`, `.next`, `migrations`, `vendor` y archivos generados o minificados.
- **Rate limit** con slowapi, reutilizando el patrón de `backend/agents/expense_tracker/api.py`, y **límite de análisis concurrentes** (1-2), porque cada análisis usa CPU, disco y coste de Claude.
- **Sin bloquear el event loop**: `/analyze` no puede ser `async def` con trabajo bloqueante dentro.
- **Errores genéricos** al cliente; el detalle va al log del servidor. Nunca se devuelven rutas internas.
- **Prompt injection:** el contenido del repo se trata como datos. Hay que escapar o neutralizar los delimitadores (un nombre de archivo con `</untrusted_data>` no debe romperlos).
- **Limpieza garantizada** de la carpeta temporal en todos los caminos, también en timeout y cancelación del cliente SSE.

## Arquitectura

- **Un solo pipeline.** Hoy `engine.py` y `api.py` lo implementan dos veces. *Mi elección:* mantener LangGraph, porque es parte del valor de portfolio, pero darle sentido:
  - fan-out en paralelo de los escáneres;
  - el progreso SSE sale de `graph.stream`, de modo que ambos endpoints usan el mismo grafo.
- Los módulos caseros que sustituyen las herramientas se borran: el regex de `pyproject`, la consulta a PyPI y el `unused deps` con alias.
- Se quitan los comentarios de tutorial del propio agente. Debe pasar su propia auditoría.

## No-objetivos (Fase 1)

Arreglar código o abrir PRs (Fases 2-3); ejecutar tests o medir cobertura real (Fase 2, en local); repos privados; lenguajes distintos de Python y JS/TS; rediseño visual de la demo.

## Anti-objetivos (sería un fracaso aunque funcione)

- Un informe lleno de falsos positivos que el usuario tenga que filtrar a mano.
- Consejos genéricos sin `archivo:línea` ("escribe más tests").
- Que el agente sea un vector de ataque o de coste: ejecutar código ajeno, llenar el disco o permitir un abuso de la API de Claude.
- Que la imagen Docker crezca tanto que no quepa en el EC2.

## Restricciones

- Python 3.12 y FastAPI, en el monolito `backend/` actual, desplegado en Docker en un EC2 con 6,8 GB de disco. Antes de reconstruir en producción hay que ejecutar `docker system prune -f`.
- Las herramientas binarias (gitleaks, osv-scanner) se instalan en el `Dockerfile` con versión fija. Hay que medir y reportar el aumento de tamaño de la imagen; semgrep es el más pesado.
- Los tests del repo usan pytest. La CI ya existe; los tests que dependan de binarios externos deben saltarse si el binario no está.

## Criterio de éxito verificable

- Un **repo fixture "vibe-coded"** en `tests/tech_debt_agent/fixtures/` con al menos un caso plantado por familia. Las claves deben ser falsas, con un formato que gitleaks detecte. Hay que cubrir Python y TS, más un archivo limpio de control.
- Test de integración: cada caso plantado de las familias 1-7 aparece en el informe con su `archivo:línea`, y el archivo de control no genera hallazgos de esas familias.
- La familia 8 se verifica con la llamada a Claude mockeada (forma y validación de líneas) y con una ejecución manual real contra el fixture.
- Tests de coste:
  - la petición 21 del día devuelve 429;
  - con el gasto del mes en el límite devuelve 429 y no se llama a Claude;
  - un acierto de caché devuelve el informe sin clonar ni llamar a Claude, y no consume cupo;
  - los contadores sobreviven a reiniciar el proceso.
- Tests de endurecimiento: URL maliciosa rechazada, repo demasiado grande rechazado sin clonar, symlink no seguido, timeout que limpia la carpeta temporal y error al cliente sin rutas internas.
- Ejecución real contra 2-3 repos públicos del usuario: informe revisado a mano en busca de falsos positivos.
- README del agente actualizado para reflejar el nuevo funcionamiento.

## Control de coste de la demo pública (decidido con el usuario)

- **Tope global de 20 análisis al día**, para todas las IPs juntas. Se suma al rate limit por IP.
- **Tope de presupuesto mensual de 20 €.**
  - Al alcanzarlo, no se vuelve a llamar a Claude y la API responde **HTTP 429** con el mensaje "Demo temporalmente fuera de servicio por límite de presupuesto".
  - El gasto se calcula a partir del uso de tokens que devuelve cada respuesta de la API (entrada + salida) y una tabla de precios del modelo. El builder saca los precios de la skill `claude-api`, no de memoria.
  - Antes de cada análisis se comprueba que el presupuesto restante cubra el coste máximo posible de un análisis, calculado con el presupuesto de tokens. Así una última llamada no puede pasarse del límite.
- **Caché de 24 h:**
  - Clave: SHA-256 de la URL normalizada más el SHA del último commit. El SHA del commit se obtiene sin clonar (`git ls-remote` o la API de GitHub).
  - Si el mismo repo y commit se analizó en las últimas 24 h, se devuelve el informe guardado sin clonar ni llamar a Claude.

*Mis elecciones dentro de esto:*
- **Contadores en un SQLite persistente** (stdlib `sqlite3`) en un volumen Docker. Si fueran en memoria, se reiniciarían con cada despliegue y el tope no protegería nada. Ahí viven el contador diario, el gasto del mes y la caché.
- **Un acierto de caché no consume** el cupo diario ni el presupuesto.
- **El tope diario también devuelve 429**, con un mensaje propio ("límite diario de análisis alcanzado, vuelve mañana").
- **Moneda:** el gasto se acumula en USD, que es como se factura, y el límite de 20 € se convierte con una constante de tipo de cambio configurable. Si la conversión no es exacta, conviene quedarse por debajo.
- **Días y meses en UTC.**

## Decisiones tras la revisión del diseño (*mis elecciones*)

- **Puerta de seguridad ampliada:** cualquier hallazgo `critical` de las familias 1-3 (secreto, SAST crítico como `eval` sobre input o CVE crítico) limita el score global a como máximo 40.
- **Familias y score:**
  - Cada familia parte de A y baja según hallazgos ponderados por severidad y normalizados por KLOC.
  - El score global es la media ponderada de las familias. Peso doble para la seguridad (1-4) y peso simple para el resto (5-8).
  - El fixture solo afirma la presencia de hallazgos y que se active la puerta, nunca números exactos.
- **Escaneo incompleto:** si una herramienta falla, agota el tiempo o no tiene nada que analizar (por ejemplo, ruff en un repo solo JS), su familia aparece como **"no analizado"** con el motivo y queda fuera de la media. **Nunca una A silenciosa.** El informe lo indica arriba.
- **Sin API key o con el LLM caído:** se degrada a un informe de las familias 1-7, con la familia 8 marcada como "no disponible". No falla entero. La key sale de `ANTHROPIC_API_KEY`, como ahora, y el modelo de una constante del módulo.
- **Disco durante el clonado:** precheck por la API de GitHub y además un vigilante que mata el clonado y limpia si la carpeta supera el límite o se agota el tiempo.
- **Contrato de la API:** el único consumidor es la demo propia, así que la respuesta de `/analyze` y del SSE se puede rediseñar sin capa de compatibilidad.
- **Reglas semgrep:** vendorizadas en el repo con versión fija, sin descargar nada del registry en runtime.
- **Tamaño de imagen:** el builder mide cuánto añade cada herramienta. Si semgrep pasa de unos 400 MB, se cubre JS/TS con reglas mínimas y se documenta el hueco, en vez de inflar la imagen.

## Requisitos técnicos añadidos en la aprobación (usuario)

1. **SQLite sin `database is locked`:** modo WAL, `busy_timeout` y escrituras serializadas con un lock y ejecutadas fuera del event loop (threadpool). La reserva de cupo y presupuesto debe ser atómica (una transacción `BEGIN IMMEDIATE`) para que dos peticiones simultáneas no superen el tope.
2. **El validador de líneas acepta rangos:** `archivo:10`, `archivo:10-15` y `líneas 10-15`. Un rango es válido si está dentro del archivo y empieza en una línea que exista; los que no cumplan se descartan.
3. **Cancelación SSE:** si el cliente corta la conexión, el pipeline lo detecta (`request.is_disconnected()` o la cancelación del generador). Entonces mata los subprocesos de las herramientas en curso, sin dejar zombies, limpia la carpeta temporal y no sigue gastando en Claude. Hace falta un test que lo cubra.

## Queda a criterio del builder

Las versiones exactas de las herramientas, los umbrales numéricos (tamaño máximo de repo, KB por archivo, presupuesto de tokens, KLOC), las reglas semgrep concretas, la fórmula exacta del score dentro de lo descrito y la estructura interna de módulos.
