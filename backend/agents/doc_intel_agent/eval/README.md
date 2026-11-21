# Evaluación del Document Intelligence Agent

Mide el agente tal como está desplegado (OpenAI `text-embedding-3-small`, pgvector, Claude Haiku 4.5, `top_k` 5 en preguntas y 3 por documento en comparaciones) sobre tres contratos SaaS reales. Por cada respuesta mide dos cosas: **si es correcta** y **si cita el documento y la página correctos**. Además separa la recuperación del etiquetado de páginas: si algún chunk recuperado contenía la evidencia, sea cual sea la página que lleva.

Diseño completo: `docs/superpowers/specs/2026-11-20-doc-intel-case-study-design.md` (repo del portfolio).

## Documentos (congelados)

En `data/`, con sha256 comprobado antes de cada ejecución. No se regeneran ni se vuelven a descargar: las páginas de referencia dependen del archivo exacto.

| Clave | Archivo | Documento | Versión | Páginas | sha256 |
|---|---|---|---|---|---|
| HS | `hubspot_tos.pdf` | HubSpot Customer Terms of Service | modificado 2026-04-14 | 47 | `c7e7145f…5599508d71` |
| SF | `salesforce_msa.pdf` | Salesforce Main Services Agreement | 2026-10-15 | 17 | `ad7d78a2…fa9f403abe5381` |
| FW | `freshworks_tos.pdf` | Freshworks Terms of Service | en vigor desde 2026-04-01 | 28 | `841dae24…bad8bb0e30e842748` |

HubSpot y Salesforce son los PDF oficiales. Freshworks no publica PDF: `freshworks.com/terms` se imprimió a PDF A4 con Chromium (puppeteer) el 2026-11-20, quitando los elementos fijos, la cabecera, la navegación, el pie y el aviso de cookies. Los hashes completos están en `questions.json`.

## Preguntas

24 en `questions.json`: 10 de extracción (`ask`), 8 de comparación (`compare`, un elemento por contrato) y 6 trampas (`ask`; lo correcto es decir que no está). En total 40 elementos por pasada y 120 en tres pasadas. Cada elemento se divide en hechos con sus páginas y una cita literal corta (`evidence`) del texto de pypdf de esa página; `test_eval_questions.py` comprueba que cada cita está en su página.

## Cómo se ejecuta

Base de datos propia y local (nunca la de producción del `.env`; `run_eval.py` se niega si el host no es `localhost`/`127.0.0.1`, si la URL lleva parámetros `?...` o si el nombre de la base no contiene `eval`, porque vacía la tabla antes de indexar):

```
docker run -d --name doc-intel-eval-db -e POSTGRES_USER=eval -e POSTGRES_PASSWORD=eval -e POSTGRES_DB=doc_intel_eval -p 5436:5432 pgvector/pgvector:pg16
```

(Puerto 5436 porque 5432-5435 los usan otros contenedores en esta máquina.)

```
set EVAL_DATABASE_URL=postgresql://eval:eval@localhost:5436/doc_intel_eval
python -m backend.agents.doc_intel_agent.eval.run_eval              # 3 pasadas, 24 preguntas
python -m backend.agents.doc_intel_agent.eval.run_eval --repeats 1 --only E1,C1,T1
python -m backend.agents.doc_intel_agent.eval.report backend/agents/doc_intel_agent/eval/results/results_<fecha>.json
```

`run_eval` vacía la tabla, indexa los tres PDF con `process_pdf` + `save_chunks` (sin subir nada a R2) y responde con `answer_question` / `compare_documents`. Guarda `results/results_<fecha>.json`; si se corta a medias (por ejemplo, un error de la API) guarda lo hecho como `results/results_partial_<fecha>.json`, con `meta.complete: false`. `report` imprime el resumen y escribe `results/review_<fecha>.csv` para la revisión manual; si existe `results/grades_<fecha>.json` (`[{id, run, doc, grade}]`), esas notas sustituyen a la corrección automática.

## Métricas

- **Nota**: correcta / parcial / incorrecta. Primera pasada automática por términos clave (`grading.auto_grade`); la nota final es la revisión manual. Las trampas solo son correctas si dicen que no está y no dan ninguna cifra prohibida (`forbidden`, por ejemplo el 99.95 % de HubSpot en una pregunta sobre Salesforce).
- **Cita**: `exact` si cada hecho tiene citada una de sus páginas en el documento correcto; `adjacent` si solo acierta a ±1 página; `wrong` en otro caso; `n/a` si el elemento no tiene páginas (trampas).
- **Reparto de fallos de cita** (elementos con página cuya cita no es `exact`): no recuperado (ningún chunk contenía la evidencia) · recuperado pero mal etiquetado (ningún chunk con la evidencia lleva una de sus páginas: el problema conocido de abajo) · recuperado con la etiqueta correcta y aun así citado mal.
- **Inestables**: pares (pregunta, documento) cuya nota o estado de cita cambia entre pasadas.

## Problema conocido (medido, no corregido)

`document_processor.split_into_chunks` hace ventanas de ~500 palabras (50 de solape) que cruzan páginas y etiqueta cada chunk con la página **donde empieza**. Un dato al principio de la página 13 dentro de un chunk que empezó en la 12 se cita como página 12. La evaluación lo hace visible con el estado `adjacent` en lugar de perdonarlo.

## Regla de congelación

El test de cordura debe pasar antes de la primera ejecución completa; después `questions.json` queda congelado. Se permite un piloto de 2-3 preguntas para probar la tubería, que se descarta. Tras la ejecución completa, una respuesta esperada solo puede cambiar si es errónea frente al texto del PDF, nunca por lo que haya respondido el agente; cada cambio se apunta abajo con su motivo y la ejecución se vuelve a corregir, no a ejecutar.

## Cambios al set

- 2026-11-20 (antes de congelar): T2 tiene `forbidden: ["99.95"]` en vez de `["99.9"]`, porque la propia pregunta dice "99.9%" y una negativa correcta que la repita no debe contar como incorrecta. Ninguna página de la spec tuvo que corregirse (E9 verificada: SF página 3).
