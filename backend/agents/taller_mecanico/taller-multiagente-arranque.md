# Sistema Multiagente para Taller Mecánico — Documento de Arranque

## 1. Objetivo

Demostrar un patrón real de orquestación multiagente (router + especialistas + evaluador con bucle de aprobación/rechazo + log de decisiones auditable) aplicado a la gestión de un taller mecánico, construible en solitario con software 100% local o autoalojado.

## 2. Agentes reales (4)

Solo son "agente" los componentes que razonan con un LLM y toman una decisión no determinista.

| Agente | Entrada | Razonamiento | Salida |
|---|---|---|---|
| **Router/Recepción** | Mensaje del cliente en lenguaje natural | Clasifica intención (cita, presupuesto, urgencia, consulta técnica, queja) y decide a qué agente derivar, o si resuelve con una herramienta simple | Acción + justificación |
| **Diagnóstico** | Síntomas, historial del vehículo, códigos OBD si los hay | Propone causas probables ordenadas por probabilidad, sugiere qué revisar primero, explica el porqué | Informe estructurado (causas, confianza, siguiente paso) |
| **Presupuestador** | Diagnóstico aprobado, piezas necesarias, mano de obra, historial del cliente | Calcula coste, decide margen y alternativas (pieza original vs. compatible), valora descuento por fidelidad/urgencia. Un único agente con prompt de razonamiento rico — no simula dos partes negociando | Presupuesto con justificación y advertencias |
| **Evaluador** | Salida de cualquiera de los tres agentes anteriores | Revisa coherencia, rango esperado, contradicciones con el historial, nivel de confianza | Veredicto: aprobar / rechazar y devolver al origen con feedback / escalar a revisión humana |

## 3. Herramientas deterministas (no son agentes)

CRUD y cálculos sin razonamiento de IA, invocados por los agentes cuando lo necesitan:

- Agenda/reservas
- Inventario
- Facturación
- CRM (historial de cliente y vehículo)
- Recordatorios
- Plantillas PDF
- Base de conocimiento técnica (búsqueda vectorial simple sobre manuales/notas)

## 4. Bucle de evaluación

1. Un agente (Diagnóstico o Presupuestador) produce una salida.
2. El Evaluador la recibe junto con el contexto relevante (historial, inventario, rangos históricos de precio).
3. El Evaluador decide una de tres cosas:
   - **Aprobar** (con o sin advertencia) — el flujo continúa.
   - **Rechazar y devolver al agente de origen con feedback específico** — el agente reintenta con esa corrección.
   - **Escalar a intervención humana** — el flujo se detiene, queda marcado para revisión manual, no se envía nada al cliente.
4. Cada una de estas tres rutas queda registrada en el decision log, incluida la razón del veredicto.

## 5. Decision log — tabla central

```sql
CREATE TABLE decision_log (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    input_text TEXT NOT NULL,
    agent TEXT NOT NULL,              -- router | diagnostico | presupuestador | evaluador
    reasoning TEXT NOT NULL,          -- explicación del propio agente, no un resumen nuestro
    output TEXT NOT NULL,             -- salida estructurada (JSON) del agente
    reviewed_by TEXT,                 -- 'evaluador' o NULL si no aplica revisión
    verdict TEXT,                     -- aprobado | rechazado | escalado_humano | NULL
    verdict_reason TEXT,              -- por qué, solo si reviewed_by no es NULL
    parent_decision_id INTEGER REFERENCES decision_log(id)  -- para encadenar reintentos tras un rechazo
);
```

## 6. Stack propuesto

- **Backend**: Python + FastAPI (mismo patrón que ya usas en el resto del monorepo)
- **Base de datos**: SQLite (archivo local, sin servidor — coherente con "montable desde casa sin infraestructura externa")
- **LLM**: Claude Haiku vía API — consistencia con el resto del portfolio y mejor calidad de razonamiento que una alternativa local. Ollama queda anotado como posible optimización futura (offline, sin coste por token), no como base.
- **Interfaz**: web local simple (HTML + FastAPI), accesible desde el móvil en la misma red

## 7. Orden de construcción (hitos pequeños)

1. Esquema de base de datos completo (clientes, vehículos, citas, piezas, presupuestos, `decision_log`) — sin ningún agente todavía.
2. Herramientas deterministas (CRUD de agenda, inventario, CRM) probadas de forma aislada, con sus propios tests.
3. Agente Router, aislado — clasifica intención sobre mensajes de prueba, escribe en `decision_log`, sin conectar aún a los demás agentes.
4. Agente Diagnóstico, aislado — mismo criterio: probado solo, escribiendo en el log.
5. Agente Evaluador — probado primero contra salidas *fijas* de Diagnóstico (no en vivo), para validar el bucle de aprobar/rechazar/escalar sin depender de que Diagnóstico ya funcione perfecto.
6. Conectar Router → Diagnóstico → Evaluador en flujo real, con el ejemplo de la sección 8 como test de aceptación.
7. Agente Presupuestador + su propio paso por el Evaluador.
8. Flujo completo de extremo a extremo con el ejemplo de la sección 8.

No construir los 4 agentes en paralelo — cada uno se valida solo antes de conectarlo al siguiente, para poder aislar fallos.

## 8. Ejemplo de interacción completa (test de aceptación)

**Entrada del cliente:** *"Mi coche hace un ruido raro al frenar por las mañanas"*

1. **Router** clasifica: consulta técnica → deriva a Diagnóstico. *(log: agent=router, verdict=N/A)*
2. **Diagnóstico** propone: "pastillas desgastadas o discos con óxido superficial; revisar primero pastillas" con confianza media. *(log: agent=diagnostico)*
3. **Evaluador** revisa:
   - ¿Síntoma frecuente para ese modelo según historial? Sí.
   - ¿Piezas en inventario? Consulta la herramienta de inventario.
   - ¿Confianza suficiente? Media → falta inspección visual.
   - **Veredicto: aprobar con advertencia** — "Se recomienda inspección visual antes de presupuestar". *(log: reviewed_by=evaluador, verdict=aprobado)*
4. Cliente acepta cita → Router usa la herramienta de agenda para reservar hueco.
5. **Presupuestador** recibe diagnóstico aprobado + piezas necesarias, genera presupuesto (mano de obra + piezas + margen). *(log: agent=presupuestador)*
6. **Evaluador** revisa el presupuesto:
   - ¿Precio dentro del rango histórico para ese trabajo? Sí.
   - ¿Margen correcto? Sí.
   - ¿Cliente con deuda pendiente? No.
   - **Veredicto: aprobar**. *(log: reviewed_by=evaluador, verdict=aprobado)*
7. Presupuesto en PDF enviado al cliente. Todo el flujo queda trazado en `decision_log`.

**Caso de rechazo, para probar la otra rama del bucle:** si Diagnóstico sugiriera cambiar discos de freno en un coche con 10.000 km, el Evaluador debe detectar la incoherencia con el kilometraje del historial y **escalar a intervención humana** en vez de aprobar — este caso debe tener su propio test explícito antes de dar el bucle de evaluación por validado.
