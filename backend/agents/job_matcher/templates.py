def job_matcher_html() -> str:
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Matcher — AI Portfolio</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #F5F4FF;
  color: #1a1a1a;
  min-height: 100vh;
}

header {
  background: #534AB7;
  padding: 1.25rem 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left { display: flex; align-items: center; gap: 12px; }

.header-logo {
  width: 42px; height: 42px; border-radius: 10px;
  background: rgba(255,255,255,0.15);
  display: flex; align-items: center; justify-content: center;
  font-size: 22px;
}

header h1 { font-size: 17px; font-weight: 600; color: white; margin-bottom: 2px; }
header p { font-size: 12px; color: #CECBF6; }

.header-badge {
  background: rgba(255,255,255,0.12);
  border: 0.5px solid rgba(255,255,255,0.2);
  border-radius: 20px;
  padding: 5px 14px;
  font-size: 11px;
  color: #EEEDFE;
  letter-spacing: 0.03em;
}

main { max-width: 1100px; margin: 0 auto; padding: 2rem; }

.form-card {
  background: white;
  border-radius: 14px;
  border: 0.5px solid #CECBF6;
  padding: 1.75rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 2px 12px rgba(83,74,183,0.06);
}

.form-section-title {
  font-size: 12px; font-weight: 600; color: #534AB7;
  text-transform: uppercase; letter-spacing: 0.07em;
  margin-bottom: 1.25rem;
  padding-bottom: 10px;
  border-bottom: 2px solid #EEEDFE;
}

.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
@media (max-width: 680px) { .form-grid { grid-template-columns: 1fr; } }

.field label {
  display: block; font-size: 11px; font-weight: 600;
  color: #7F77DD; text-transform: uppercase;
  letter-spacing: 0.06em; margin-bottom: 6px;
}

.file-dropzone {
  width: 100%; height: 90px;
  border: 2px dashed #CECBF6; border-radius: 10px;
  background: #FAFAFE; cursor: pointer;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 6px;
  transition: border-color 0.2s, background 0.2s;
  position: relative;
}

.file-dropzone:hover { border-color: #7F77DD; background: #EEEDFE; }
.file-dropzone input[type="file"] {
  position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
}

.file-icon { font-size: 24px; color: #CECBF6; }
.file-label { font-size: 12px; color: #888; }
.file-selected { font-size: 12px; color: #534AB7; font-weight: 600; }

input[type="url"], textarea {
  width: 100%;
  border: 1.5px solid #CECBF6;
  border-radius: 8px;
  padding: 9px 12px;
  font-size: 13px;
  font-family: inherit;
  background: #FAFAFE;
  color: #1a1a1a;
  transition: border-color 0.2s, background 0.2s;
  outline: none;
}

input[type="url"]:focus, textarea:focus {
  border-color: #534AB7;
  background: white;
}

textarea { resize: vertical; min-height: 130px; }

.or-divider {
  display: flex; align-items: center; gap: 8px;
  font-size: 11px; color: #B4B2A9; margin: 8px 0;
}
.or-divider::before, .or-divider::after {
  content: ''; flex: 1; height: 1px; background: #EEEDFE;
}

.btn-analyze {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  width: 100%; margin-top: 1.25rem; padding: 13px;
  background: #534AB7; color: white;
  border: none; border-radius: 10px;
  font-size: 14px; font-weight: 600;
  cursor: pointer; transition: background 0.2s, transform 0.1s;
}

.btn-analyze:hover { background: #3C3489; }
.btn-analyze:active { transform: scale(0.99); }
.btn-analyze:disabled { background: #B4B2A9; cursor: not-allowed; transform: none; }

.error-msg {
  background: #FCEBEB; border: 1px solid #F09595;
  border-radius: 10px; padding: 12px 16px;
  color: #A32D2D; font-size: 13px;
  margin-bottom: 1.5rem; display: none;
}

.loading {
  display: none; text-align: center;
  padding: 3rem 2rem;
}

.spinner {
  width: 44px; height: 44px;
  border: 3px solid #EEEDFE;
  border-top-color: #534AB7;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin { to { transform: rotate(360deg); } }

.loading-text { font-size: 14px; color: #534AB7; font-weight: 500; margin-bottom: 12px; }
.loading-sub { font-size: 12px; color: #888; }

.progress-track {
  height: 4px; background: #EEEDFE; border-radius: 2px;
  margin-top: 12px; overflow: hidden;
}

.progress-fill {
  height: 100%; border-radius: 2px;
  background: #534AB7;
  transition: width 0.6s ease;
}

#result { display: none; }

.score-card {
  background: white; border-radius: 14px;
  border: 0.5px solid #CECBF6;
  padding: 1.5rem;
  box-shadow: 0 2px 12px rgba(83,74,183,0.06);
  margin-bottom: 1.25rem;
  display: flex; align-items: center; gap: 1.5rem;
}

.score-ring {
  width: 90px; height: 90px; border-radius: 50%;
  border: 5px solid #534AB7;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  flex-shrink: 0;
  background: #EEEDFE;
}

.score-ring.excelente { border-color: #1D9E75; background: #E1F5EE; }
.score-ring.bueno { border-color: #534AB7; background: #EEEDFE; }
.score-ring.medio { border-color: #BA7517; background: #FAEEDA; }
.score-ring.bajo { border-color: #A32D2D; background: #FCEBEB; }

.score-num { font-size: 28px; font-weight: 700; line-height: 1; }
.score-ring.excelente .score-num { color: #0F6E56; }
.score-ring.bueno .score-num { color: #534AB7; }
.score-ring.medio .score-num { color: #854F0B; }
.score-ring.bajo .score-num { color: #791F1F; }
.score-denom { font-size: 11px; color: #888; margin-top: 2px; }

.nivel-pill {
  display: inline-block; padding: 4px 12px;
  border-radius: 20px; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em;
  margin-bottom: 6px;
}

.pill-excelente { background: #E1F5EE; color: #0F6E56; }
.pill-bueno { background: #EEEDFE; color: #534AB7; }
.pill-medio { background: #FAEEDA; color: #854F0B; }
.pill-bajo { background: #FCEBEB; color: #791F1F; }

.score-title { font-size: 16px; font-weight: 600; color: #1a1a1a; margin-bottom: 4px; }
.score-desc { font-size: 12px; color: #888; }

.two-col {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1.25rem; margin-bottom: 1.25rem;
}
@media (max-width: 680px) { .two-col { grid-template-columns: 1fr; } }

.info-card {
  background: white; border-radius: 14px;
  border: 0.5px solid #CECBF6; padding: 1.25rem;
  box-shadow: 0 2px 12px rgba(83,74,183,0.06);
}

.card-title {
  font-size: 11px; font-weight: 600; color: #534AB7;
  text-transform: uppercase; letter-spacing: 0.07em;
  margin-bottom: 10px; padding-bottom: 8px;
  border-bottom: 2px solid #EEEDFE;
}

.stat-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 7px 0; border-bottom: 0.5px solid #F5F4FF;
  font-size: 12.5px;
}
.stat-row:last-child { border-bottom: none; }
.stat-label { color: #666; }
.stat-val { font-weight: 600; }
.stat-ok { color: #1D9E75; }
.stat-warn { color: #BA7517; }
.stat-bad { color: #A32D2D; }
.stat-neutral { color: #534AB7; }

.tech-section-label {
  font-size: 11px; color: #888; margin-bottom: 6px; margin-top: 10px;
}
.tech-section-label:first-child { margin-top: 0; }

.tech-list { display: flex; flex-wrap: wrap; gap: 5px; }

.tech-tag {
  padding: 3px 9px; border-radius: 10px;
  font-size: 11px; font-weight: 500;
}
.tag-match { background: #E1F5EE; color: #0F6E56; }
.tag-gap { background: #FCEBEB; color: #A32D2D; }
.tag-none { font-size: 11px; color: #aaa; }

.report-card {
  background: white; border-radius: 14px;
  border: 0.5px solid #CECBF6; padding: 1.5rem;
  box-shadow: 0 2px 12px rgba(83,74,183,0.06);
  margin-bottom: 1.25rem;
}

.report-body {
  font-size: 13.5px; line-height: 1.75; color: #333;
}

.report-body h2 {
  font-size: 14px; font-weight: 600; color: #534AB7;
  margin: 1.2rem 0 0.5rem;
}
.report-body h3 {
  font-size: 13px; font-weight: 600; color: #3C3489;
  margin: 1rem 0 0.4rem;
}
.report-body p { margin-bottom: 0.5rem; }
.report-body ul { padding-left: 1.4rem; margin-bottom: 0.5rem; }
.report-body li { margin-bottom: 3px; }
.report-body strong { color: #1a1a1a; font-weight: 600; }

.report-body table {
  width: 100%; border-collapse: collapse;
  margin: 0.8rem 0; font-size: 12.5px;
}
.report-body th {
  background: #EEEDFE; color: #534AB7;
  padding: 7px 10px; text-align: left; font-weight: 600;
}
.report-body td {
  padding: 7px 10px; border-bottom: 1px solid #F5F4FF;
}

.footer-note {
  text-align: center; font-size: 11px; color: #B4B2A9;
  margin-top: 0.5rem; padding-bottom: 1rem;
}
</style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="header-logo">⚡</div>
    <div>
      <h1>Job Matcher Agent</h1>
      <p>Analiza tu encaje con una oferta usando ML + IA</p>
    </div>
  </div>
  <span class="header-badge">GradientBoosting + Claude Haiku</span>
</header>

<main>

  <div class="form-card">
    <div class="form-section-title">Analizar encaje</div>
    <div class="form-grid">

      <div class="field">
        <label>CV (PDF o DOCX)</label>
        <div class="file-dropzone" id="dropzone" onclick="document.getElementById('cv-file').click()">
            <input type="file" id="cv-file" accept=".pdf,.docx" style="display:none" onchange="onFileChange(this)">
            <div class="file-icon">↑</div>
            <div class="file-label" id="file-label">Arrastra o haz clic para subir tu CV</div>
        </div>
      </div>

      <div>
        <div class="field">
          <label>URL de la oferta</label>
          <input type="url" id="oferta-url" placeholder="https://www.infojobs.net/oferta/...">
          <div style="font-size:11px;color:#aaa;margin-top:4px;">Infojobs, Indeed, web de empresa (no LinkedIn)</div>
        </div>
        <div class="or-divider">o pega el texto directamente</div>
        <div class="field">
          <label>Texto de la oferta</label>
          <textarea id="oferta-texto" placeholder="Pega aquí el texto completo de la oferta..."></textarea>
        </div>
      </div>

    </div>

    <button class="btn-analyze" id="btn-analyze" onclick="analizar()">
      <span>⚡</span> Analizar encaje
    </button>
  </div>

  <div class="error-msg" id="error-msg"></div>

  <div class="loading" id="loading">
    <div class="spinner"></div>
    <div class="loading-text" id="loading-text">Extrayendo texto del CV...</div>
    <div class="loading-sub" id="loading-sub">Esto puede tardar 15-20 segundos</div>
    <div class="progress-track">
      <div class="progress-fill" id="progress-fill" style="width:5%"></div>
    </div>
  </div>

  <div id="result">

    <div class="score-card">
      <div class="score-ring" id="score-ring">
        <span class="score-num" id="score-num">0</span>
        <span class="score-denom">/ 100</span>
      </div>
      <div>
        <span class="nivel-pill" id="nivel-pill">–</span>
        <div class="score-title" id="score-title">–</div>
        <div class="score-desc" id="score-desc">–</div>
      </div>
    </div>

    <div class="two-col">

      <div class="info-card">
        <div class="card-title">Perfil detectado</div>
        <div id="cv-stats"></div>
      </div>

      <div class="info-card">
        <div class="card-title">Tecnologías</div>
        <div class="tech-section-label">Match con la oferta</div>
        <div class="tech-list" id="techs-match"></div>
        <div class="tech-section-label">Gaps detectados</div>
        <div class="tech-list" id="techs-gap"></div>
      </div>

    </div>

    <div class="report-card">
      <div class="card-title">Informe detallado</div>
      <div class="report-body" id="report-body"></div>
    </div>

    <div class="footer-note">
      Score calculado por GradientBoostingRegressor (MAE ±<span id="mae-val">–</span> puntos sobre 100).
      Informe generado por Claude Haiku.
    </div>

  </div>

</main>

<script>
function onFileChange(input) {
  const label = document.getElementById('file-label');
  if (input.files[0]) {
    label.textContent = input.files[0].name;
    label.style.color = '#534AB7';
    label.style.fontWeight = '600';
  }
}

function md2html(text) {
  if (!text) return '';
  const lines = text.split('\\n');
  let html = '';
  for (let line of lines) {
    line = line.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
    if (line.startsWith('### ')) {
      html += '<h3>' + line.slice(4) + '</h3>';
    } else if (line.startsWith('## ')) {
      html += '<h2>' + line.slice(3) + '</h2>';
    } else if (line.startsWith('- ')) {
      html += '<li>' + line.slice(2) + '</li>';
    } else if (line.startsWith('|')) {
      const cells = line.split('|').filter(c => c.trim() && !c.trim().match(/^[-:]+$/));
      if (cells.length) html += '<tr>' + cells.map(c => '<td>' + c.trim() + '</td>').join('') + '</tr>';
    } else if (line.trim()) {
      html += '<p>' + line + '</p>';
    }
  }
  return html;
}

let loadingInterval;

function startLoading() {
  const steps = [
    ['Extrayendo texto del CV...', 15],
    ['Analizando perfil del candidato con Claude...', 40],
    ['Analizando requisitos de la oferta...', 65],
    ['Calculando score con el modelo ML...', 82],
    ['Generando informe de encaje...', 93],
  ];
  let i = 0;
  document.getElementById('loading').style.display = 'block';
  document.getElementById('result').style.display = 'none';
  document.getElementById('error-msg').style.display = 'none';
  document.getElementById('progress-fill').style.width = '5%';

  loadingInterval = setInterval(() => {
    if (i < steps.length) {
      document.getElementById('loading-text').textContent = steps[i][0];
      document.getElementById('progress-fill').style.width = steps[i][1] + '%';
      i++;
    }
  }, 2200);
}

function stopLoading() {
  clearInterval(loadingInterval);
  document.getElementById('loading').style.display = 'none';
  document.getElementById('progress-fill').style.width = '100%';
}

function showError(msg) {
  stopLoading();
  const el = document.getElementById('error-msg');
  el.textContent = msg;
  el.style.display = 'block';
}

function cls(nivel) {
  return { excelente: 'excelente', bueno: 'bueno', medio: 'medio', bajo: 'bajo' }[nivel] || 'medio';
}

function titleFromNivel(nivel) {
  return {
    excelente: 'Encaje excelente — aplica hoy',
    bueno: 'Buen encaje — vale la pena aplicar',
    medio: 'Encaje medio — hay gaps importantes',
    bajo: 'Encaje bajo — gaps críticos'
  }[nivel] || '';
}

function renderResult(data) {
  const c = cls(data.nivel_encaje);

  document.getElementById('score-num').textContent = Math.round(data.score);
  document.getElementById('score-ring').className = 'score-ring ' + c;

  const pill = document.getElementById('nivel-pill');
  pill.textContent = data.nivel_encaje.toUpperCase();
  pill.className = 'nivel-pill pill-' + c;

  document.getElementById('score-title').textContent = titleFromNivel(data.nivel_encaje);

  const cv = data.info_cv;
  const oferta = data.info_oferta;
  document.getElementById('score-desc').textContent =
    `${cv.nivel} · ${cv.anos_experiencia} año(s) · ${cv.n_proyectos_produccion} proyectos en producción vs oferta ${oferta.nivel_pedido} en ${oferta.sector}`;

  const f = data.features;
  const stats = [
    ['Nivel detectado', cv.nivel, cv.nivel === 'senior' ? 'ok' : cv.nivel === 'mid' ? 'neutral' : 'warn'],
    ['Años de experiencia', cv.anos_experiencia, cv.anos_experiencia >= 2 ? 'ok' : 'warn'],
    ['Proyectos en producción', cv.n_proyectos_produccion, cv.n_proyectos_produccion >= 3 ? 'ok' : 'warn'],
    ['Experiencia LLMs', cv.tiene_llm_experience ? 'Sí' : 'No', cv.tiene_llm_experience ? 'ok' : 'bad'],
    ['Cloud', cv.tiene_cloud ? 'Sí' : 'No', cv.tiene_cloud ? 'ok' : 'warn'],
    ['Docker', cv.tiene_docker ? 'Sí' : 'No', cv.tiene_docker ? 'ok' : 'warn'],
    ['SQL', cv.tiene_sql ? 'Sí' : 'No', cv.tiene_sql ? 'ok' : 'warn'],
    ['Inglés', cv.ingles_nivel, ['avanzado','nativo'].includes(cv.ingles_nivel) ? 'ok' : 'warn'],
    ['Cobertura técnica', Math.round(f.cobertura_tech * 100) + '%',
      f.cobertura_tech >= 0.6 ? 'ok' : f.cobertura_tech >= 0.4 ? 'warn' : 'bad'],
  ];

  document.getElementById('cv-stats').innerHTML = stats.map(([label, val, s]) =>
    `<div class="stat-row">
      <span class="stat-label">${label}</span>
      <span class="stat-val stat-${s}">${val}</span>
    </div>`).join('');

  const techs = data.info_oferta.tecnologias_requeridas || [];
  const matches = (data.features.techs_match_detalle || []);
  const gaps = techs.filter(t => !matches.includes(t));

  document.getElementById('techs-match').innerHTML = matches.length
    ? matches.map(t => `<span class="tech-tag tag-match">${t}</span>`).join('')
    : '<span class="tag-none">Ninguno detectado</span>';

  document.getElementById('techs-gap').innerHTML = gaps.length
    ? gaps.map(t => `<span class="tech-tag tag-gap">${t}</span>`).join('')
    : '<span class="tag-none" style="color:#1D9E75">Sin gaps técnicos</span>';

  document.getElementById('report-body').innerHTML = md2html(data.informe);
  document.getElementById('mae-val').textContent = data.modelo_mae;

  document.getElementById('result').style.display = 'block';
  document.getElementById('result').scrollIntoView({ behavior: 'smooth' });
}

async function analizar() {
  const cvFile = document.getElementById('cv-file').files[0];
  const url = document.getElementById('oferta-url').value.trim();
  const texto = document.getElementById('oferta-texto').value.trim();

  if (!cvFile) { showError('Sube tu CV en formato PDF o DOCX'); return; }
  if (!url && !texto) { showError('Proporciona una URL o el texto de la oferta'); return; }

  document.getElementById('btn-analyze').disabled = true;
  document.getElementById('error-msg').style.display = 'none';
  startLoading();

  const form = new FormData();
  form.append('cv', cvFile);
  form.append('oferta_url', url);
  form.append('oferta_texto', texto);

  try {
    const res = await fetch('/job-matcher/analyze', { method: 'POST', body: form });
    stopLoading();

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Error en el servidor');
    }

    renderResult(await res.json());

  } catch (e) {
    showError(e.message);
  } finally {
    document.getElementById('btn-analyze').disabled = false;
  }
}
</script>
</body>
</html>"""
