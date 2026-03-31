# reorganize.ps1
# Reorganiza el repo en una estructura de portfolio multi-agente.
# Ejecutar desde la RAIZ del proyecto (donde esta backend/ y tests/)
#
# Uso: .\scripts\reorganize.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "`n=== Reorganizando repositorio ===" -ForegroundColor Cyan

# ── 1. Crear nueva estructura de directorios ──────────────────────────────────

$dirs = @(
    "backend\agents",
    "backend\agents\dental_agent",
    "backend\agents\dental_agent\data",
    "backend\agents\scaffold_web_agent",
    "backend\agents\scaffold_web_agent\data",
    "tests\dental_agent",
    "tests\scaffold_web_agent"
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
        Write-Host "  Creado: $dir" -ForegroundColor Green
    }
}

# ── 2. Mover archivos del dental agent a backend/agents/dental_agent/ ─────────

$dentalFiles = @(
    "agent.py",
    "config.py",
    "metrics.py",
    "notify.py",
    "orchestrator.py",
    "rag.py",
    "schemas.py",
    "store.py",
    "tools.py",
    "twilio_client.py",
    "twilio_worker.py",
    "validators.py",
    "generate_dental_faq_md.py"
)

foreach ($file in $dentalFiles) {
    $src = "backend\$file"
    $dst = "backend\agents\dental_agent\$file"
    if (Test-Path $src) {
        Move-Item -Path $src -Destination $dst
        Write-Host "  Movido: $src -> $dst" -ForegroundColor Yellow
    }
}

# Mover datos del dental agent
$dataFiles = @("clinic_config.yaml", "dental_faq.md", "RUNBOOK.md")
foreach ($file in $dataFiles) {
    $src = "backend\data\$file"
    $dst = "backend\agents\dental_agent\data\$file"
    if (Test-Path $src) {
        Move-Item -Path $src -Destination $dst
        Write-Host "  Movido: $src -> $dst" -ForegroundColor Yellow
    }
}

# ── 3. Mover scaffold_web_agent a backend/agents/ ────────────────────────────

if (Test-Path "backend\apps\scaffold_web_agent") {
    # Mover todos los archivos .py del scaffold
    Get-ChildItem "backend\apps\scaffold_web_agent\*.py" | ForEach-Object {
        $dst = "backend\agents\scaffold_web_agent\$($_.Name)"
        Move-Item -Path $_.FullName -Destination $dst
        Write-Host "  Movido: $($_.FullName) -> $dst" -ForegroundColor Yellow
    }
    Write-Host "  Scaffold web agent movido" -ForegroundColor Green
}

# Mover synapse_labs_knowledge.md si existe en backend/data/
if (Test-Path "backend\data\synapse_labs_knowledge.md") {
    Move-Item "backend\data\synapse_labs_knowledge.md" "backend\agents\scaffold_web_agent\data\synapse_labs_knowledge.md"
    Write-Host "  Movido: synapse_labs_knowledge.md" -ForegroundColor Yellow
}

# ── 4. Crear __init__.py necesarios ──────────────────────────────────────────

$initFiles = @(
    "backend\agents\__init__.py",
    "backend\agents\dental_agent\__init__.py",
    "backend\agents\scaffold_web_agent\__init__.py",
    "tests\dental_agent\__init__.py",
    "tests\scaffold_web_agent\__init__.py"
)

foreach ($f in $initFiles) {
    if (-not (Test-Path $f)) {
        New-Item -ItemType File -Path $f | Out-Null
        Write-Host "  Creado: $f" -ForegroundColor Green
    }
}

# ── 5. Mover tests a subdirectorios ──────────────────────────────────────────

# Tests del dental agent
$dentalTests = @(
    "test_agent.py",
    "test_booking_name_surname.py",
    "test_conversations.py",
    "test_faq_prices.py",
    "test_greetings.py",
    "test_handoff_short_treatment.py",
    "test_handoff_triggers_email.py",
    "test_notify_email.py",
    "test_question_like_never_fallback.py",
    "test_smalltalk_greetings.py",
    "test_tools_placeholders.py",
    "test_twilio_webhook.py",
    "test_twilio_webhook_dedupe.py",
    "test_twilio_worker.py"
)

foreach ($file in $dentalTests) {
    $src = "tests\$file"
    $dst = "tests\dental_agent\$file"
    if (Test-Path $src) {
        Move-Item -Path $src -Destination $dst
        Write-Host "  Movido: $src -> $dst" -ForegroundColor Yellow
    }
}

# Tests del scaffold agent
Get-ChildItem "tests\test_scaffold_*.py" | ForEach-Object {
    $dst = "tests\scaffold_web_agent\$($_.Name)"
    Move-Item -Path $_.FullName -Destination $dst
    Write-Host "  Movido: $($_.FullName) -> $dst" -ForegroundColor Yellow
}

# test_echo_runtime y test_llm_engine van con scaffold
foreach ($file in @("test_echo_runtime.py", "test_llm_engine.py")) {
    $src = "tests\$file"
    $dst = "tests\scaffold_web_agent\$file"
    if (Test-Path $src) {
        Move-Item -Path $src -Destination $dst
        Write-Host "  Movido: $src -> $dst" -ForegroundColor Yellow
    }
}

# ── 6. Actualizar imports en main.py ─────────────────────────────────────────

Write-Host "`n  Actualizando imports en backend\main.py..." -ForegroundColor Cyan

$mainPath = "backend\main.py"
$mainContent = Get-Content $mainPath -Raw

$mainContent = $mainContent -replace `
    'from backend\.apps\.scaffold_web_agent\.tenant_cors import', `
    'from backend.agents.scaffold_web_agent.tenant_cors import'

$mainContent = $mainContent -replace `
    'from \.apps\.scaffold_web_agent\.api import', `
    'from .agents.scaffold_web_agent.api import'

$mainContent = $mainContent -replace `
    'from \.agent import', `
    'from .agents.dental_agent.agent import'

$mainContent = $mainContent -replace `
    'from \.config import settings', `
    'from .agents.dental_agent.config import settings'

$mainContent = $mainContent -replace `
    'from \.metrics import', `
    'from .agents.dental_agent.metrics import'

$mainContent = $mainContent -replace `
    'from \.notify import', `
    'from .agents.dental_agent.notify import'

$mainContent = $mainContent -replace `
    'from \.rag import', `
    'from .agents.dental_agent.rag import'

$mainContent = $mainContent -replace `
    'from \.schemas import', `
    'from .agents.dental_agent.schemas import'

$mainContent = $mainContent -replace `
    'from \.store import', `
    'from .agents.dental_agent.store import'

$mainContent = $mainContent -replace `
    'from \.tools import', `
    'from .agents.dental_agent.tools import'

$mainContent = $mainContent -replace `
    'from \.twilio_worker import', `
    'from .agents.dental_agent.twilio_worker import'

Set-Content $mainPath $mainContent -NoNewline
Write-Host "  main.py actualizado" -ForegroundColor Green

# ── 7. Actualizar ruta en rag.py ─────────────────────────────────────────────

Write-Host "  Actualizando ruta en backend\agents\dental_agent\rag.py..." -ForegroundColor Cyan

$ragPath = "backend\agents\dental_agent\rag.py"
if (Test-Path $ragPath) {
    $ragContent = Get-Content $ragPath -Raw
    # parent.parent apuntaba a backend/ — ahora el archivo esta en dental_agent/
    # parent = dental_agent/, parent.parent = agents/, parent.parent.parent = backend/
    $ragContent = $ragContent -replace `
        'Path\(__file__\)\.resolve\(\)\.parent\.parent / "chroma"', `
        'Path(__file__).resolve().parent / "data" / "chroma"'
    # La ruta del dental_faq.md si existe en rag.py
    $ragContent = $ragContent -replace `
        'Path\(__file__\)\.resolve\(\)\.parent / "data"', `
        'Path(__file__).resolve().parent / "data"'
    Set-Content $ragPath $ragContent -NoNewline
    Write-Host "  rag.py actualizado" -ForegroundColor Green
}

# ── 8. Actualizar imports en conftest.py ─────────────────────────────────────

Write-Host "  Actualizando imports en tests\conftest.py..." -ForegroundColor Cyan

$confPath = "tests\conftest.py"
$confContent = Get-Content $confPath -Raw

$confContent = $confContent -replace `
    'from backend\.config import settings', `
    'from backend.agents.dental_agent.config import settings'

$confContent = $confContent -replace `
    'import backend\.store as store', `
    'import backend.agents.dental_agent.store as store'

Set-Content $confPath $confContent -NoNewline
Write-Host "  conftest.py actualizado" -ForegroundColor Green

# ── 9. Actualizar imports en tests del dental agent ──────────────────────────

Write-Host "  Actualizando imports en tests del dental agent..." -ForegroundColor Cyan

Get-ChildItem "tests\dental_agent\*.py" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw

    $content = $content -replace 'from backend\.agent import', 'from backend.agents.dental_agent.agent import'
    $content = $content -replace 'from backend\.store import', 'from backend.agents.dental_agent.store import'
    $content = $content -replace 'from backend\.notify import', 'from backend.agents.dental_agent.notify import'
    $content = $content -replace 'import backend\.notify as notify', 'import backend.agents.dental_agent.notify as notify'
    $content = $content -replace 'from backend import tools', 'from backend.agents.dental_agent import tools'
    $content = $content -replace 'from backend\.tools import', 'from backend.agents.dental_agent.tools import'
    $content = $content -replace 'from backend\.twilio_worker import', 'from backend.agents.dental_agent.twilio_worker import'

    Set-Content $_.FullName $content -NoNewline
    Write-Host "  Actualizado: $($_.Name)" -ForegroundColor Yellow
}

# ── 10. Actualizar imports en tests del scaffold agent ───────────────────────

Write-Host "  Actualizando imports en tests del scaffold agent..." -ForegroundColor Cyan

Get-ChildItem "tests\scaffold_web_agent\*.py" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    $content = $content -replace 'from backend\.apps\.scaffold_web_agent\.', 'from backend.agents.scaffold_web_agent.'
    $content = $content -replace 'import backend\.apps\.scaffold_web_agent\.', 'import backend.agents.scaffold_web_agent.'
    Set-Content $_.FullName $content -NoNewline
    Write-Host "  Actualizado: $($_.Name)" -ForegroundColor Yellow
}

# ── 11. Actualizar pyproject.toml ────────────────────────────────────────────

Write-Host "  Actualizando pyproject.toml..." -ForegroundColor Cyan

$pyprojectPath = "pyproject.toml"
$pyprojectContent = Get-Content $pyprojectPath -Raw
$pyprojectContent = $pyprojectContent -replace '"backend/data"', '"backend/agents/dental_agent/data", "backend/agents/scaffold_web_agent/data"'
$pyprojectContent = $pyprojectContent -replace '"backend/data/leads\.db"', '"backend/agents/dental_agent/data/leads.db"'
Set-Content $pyprojectPath $pyprojectContent -NoNewline
Write-Host "  pyproject.toml actualizado" -ForegroundColor Green

# ── 12. Limpiar carpetas vacías ───────────────────────────────────────────────

Write-Host "`n  Limpiando carpetas vacías..." -ForegroundColor Cyan

@("backend\apps\scaffold_web_agent", "backend\apps", "backend\data") | ForEach-Object {
    if (Test-Path $_) {
        $items = Get-ChildItem $_ -Recurse
        if ($items.Count -eq 0) {
            Remove-Item $_ -Recurse
            Write-Host "  Eliminada carpeta vacía: $_" -ForegroundColor DarkGray
        }
        else {
            Write-Host "  Carpeta no vacía, revisar manualmente: $_" -ForegroundColor Red
        }
    }
}

# ── Resumen ───────────────────────────────────────────────────────────────────

Write-Host "`n=== Reorganizacion completada ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Proximos pasos:" -ForegroundColor White
Write-Host "  1. Ejecuta los tests: pytest tests/ -v" -ForegroundColor White
Write-Host "  2. Si todo pasa, haz commit: git add . && git commit -m 'refactor: reorganize into multi-agent portfolio structure'" -ForegroundColor White
Write-Host "  3. Renombra el repo en GitHub: Settings -> Repository name -> 'ai-portfolio'" -ForegroundColor White
Write-Host ""