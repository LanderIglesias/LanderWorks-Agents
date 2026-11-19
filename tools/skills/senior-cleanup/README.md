# senior-cleanup

Skill local de Claude Code que lee el `report.json` del
[Technical Debt Analyzer](../../../backend/agents/tech_debt_agent/README_tech_debt_agent.md)
y arregla sus hallazgos por lotes en una rama nueva. Antes de commitear cada lote lo
verifica con los tests del propio repo. Lo mecánico lo arregla sola; lo delicado te lo
enseña con su diff y espera tu "sí".

## Requisitos

- Python 3.10 o superior. Los scripts solo usan la biblioteca estándar.
- git.
- Claude Code.

## De dónde sale `report.json`

Analiza el repo en la demo (`/tech-debt/demo`) y pulsa **↓ DOWNLOAD REPORT (.json)**.
El informe tiene que ser del mismo commit que tienes en local: la skill compara el
`head_sha` del informe con tu `HEAD` y se detiene si no coinciden.

## Instalación

Copia la carpeta:

```bash
cp -r tools/skills/senior-cleanup ~/.claude/skills/
```

O enlázala, para que los cambios del repo se vean sin volver a copiar.

Windows (PowerShell; requiere modo desarrollador o una consola de administrador):

```powershell
New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\senior-cleanup" -Target "$PWD\tools\skills\senior-cleanup"
```

Unix:

```bash
ln -s "$PWD/tools/skills/senior-cleanup" ~/.claude/skills/senior-cleanup
```

## Uso

En una sesión de Claude Code abierta en el repo que quieres limpiar, con el árbol limpio:

```
/senior-cleanup ruta/al/report.json
```

La skill:

1. comprueba el informe, el commit y el árbol;
2. te enseña el plan de lotes;
3. crea la rama `senior-cleanup/<sha7>`;
4. guarda la línea base de los tests;
5. aplica los lotes uno a uno, con un commit por lote que no rompe tests.

Si la sesión se corta, al volver a invocarla te ofrece retomar donde lo dejó.

El estado se guarda en `.git/senior-cleanup/`, nunca en el árbol de trabajo.

## Límites

- No hace push ni abre PRs. Revisas la rama y la fusionas tú.
- No reescribe el historial. Para los secretos que siguen en el historial te da las
  instrucciones de `git filter-repo` y te avisa de que rotes la clave, pero no ejecuta nada.
- No vuelve a escanear. Trabaja con lo que dice el informe; si el código cambió, hay
  que analizarlo de nuevo en la demo.
- Solo verifica con tests que existan. Sin comando de tests, todos los lotes piden
  confirmación.
- Comando de tests manual en Windows: si la ruta lleva barras invertidas, ponla entre
  comillas.

## Scripts

| Script | Subcomandos |
|---|---|
| `scripts/plan.py` | `check REPORT`, `plan REPORT`, `mark ID STATUS [--note TEXT]`, `revert` |
| `scripts/run_tests.py` | `baseline [--cmd "..."]`, `verify`, `accept TEST_ID` |

Todos imprimen JSON. Con un error de validación salen con código 2. `verify` sale con 1
si el lote rompe algo.

Tests: `pytest tests/senior_cleanup -q`.
