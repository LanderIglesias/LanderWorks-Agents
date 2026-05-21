"""Demo UI del Technical Debt Analyzer — dark industrial theme."""

from __future__ import annotations


def demo_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Technical Debt Analyzer</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0A0B0E; --bg2: #0F1015; --bg3: #141519; --panel: #1A1B21;
      --border: rgba(255,255,255,0.07); --border2: rgba(255,255,255,0.12);
      --text: #E8E9EF; --text2: #8B8D9A; --text3: #4A4C5A;
      --accent: #00FF88; --accent2: #00CC6A;
      --red: #FF4444; --orange: #FF8844; --yellow: #FFD700; --blue: #4488FF;
      --mono: 'JetBrains Mono', monospace; --sans: 'Syne', sans-serif;
    }
    html, body { min-height: 100vh; background: var(--bg); color: var(--text); font-family: var(--mono); font-size: 13px; line-height: 1.6; }
    body::before { content: ''; position: fixed; inset: 0; background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px); pointer-events: none; z-index: 999; }

    .header { border-bottom: 1px solid var(--border); padding: 20px 40px; display: flex; align-items: center; gap: 20px; background: var(--bg2); }
    .logo { width: 36px; height: 36px; border: 1.5px solid var(--accent); display: flex; align-items: center; justify-content: center; font-family: var(--sans); font-weight: 800; font-size: 16px; color: var(--accent); flex-shrink: 0; }
    .header-brand { display: flex; flex-direction: column; gap: 2px; }
    .header-title { font-family: var(--sans); font-weight: 800; font-size: 18px; color: var(--text); letter-spacing: -0.02em; }
    .header-sub { font-size: 11px; color: var(--text3); letter-spacing: 0.08em; }
    .header-pills { display: flex; gap: 8px; margin-left: auto; }
    .hpill { font-size: 10px; padding: 3px 8px; border: 1px solid var(--border2); color: var(--text2); letter-spacing: 0.05em; }
    .hpill.green { border-color: var(--accent); color: var(--accent); }

    .main { max-width: 1100px; margin: 0 auto; padding: 40px; }

    .input-section { background: var(--panel); border: 1px solid var(--border); padding: 28px; margin-bottom: 32px; }
    .input-label { font-size: 11px; color: var(--text3); letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 12px; display: block; }
    .input-row { display: flex; gap: 12px; }
    .repo-input { flex: 1; background: var(--bg); border: 1px solid var(--border2); color: var(--text); font-family: var(--mono); font-size: 13px; padding: 12px 16px; outline: none; transition: border-color 0.2s; }
    .repo-input:focus { border-color: var(--accent); }
    .repo-input::placeholder { color: var(--text3); }
    .analyze-btn { padding: 12px 24px; background: var(--accent); color: var(--bg); border: none; font-family: var(--mono); font-size: 12px; font-weight: 700; letter-spacing: 0.05em; cursor: pointer; transition: background 0.2s; white-space: nowrap; }
    .analyze-btn:hover:not(:disabled) { background: var(--accent2); }
    .analyze-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    .progress-section { background: var(--panel); border: 1px solid var(--border); padding: 24px; margin-bottom: 32px; display: none; }
    .progress-section.visible { display: block; }
    .progress-header { display: flex; justify-content: space-between; margin-bottom: 16px; }
    .progress-label { font-size: 11px; color: var(--text2); letter-spacing: 0.08em; }
    .progress-pct { font-size: 11px; color: var(--accent); font-weight: 700; }
    .progress-bar-track { height: 2px; background: var(--border); margin-bottom: 20px; }
    .progress-bar-fill { height: 100%; background: var(--accent); transition: width 0.4s ease; width: 0%; box-shadow: 0 0 8px var(--accent); }
    .steps-log { display: flex; flex-direction: column; gap: 6px; max-height: 200px; overflow-y: auto; }
    .step-item { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--text2); padding: 4px 0; border-bottom: 1px solid var(--border); }
    .step-item:last-child { border-bottom: none; }
    .step-dot { width: 6px; height: 6px; flex-shrink: 0; background: var(--text3); }
    .step-item.done .step-dot { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
    .step-item.active .step-dot { background: var(--yellow); animation: blink 0.8s infinite; }
    .step-item.error .step-dot { background: var(--red); }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }

    .report-section { display: none; }
    .report-section.visible { display: block; }

    .score-header { display: grid; grid-template-columns: auto 1fr; gap: 32px; background: var(--panel); border: 1px solid var(--border); padding: 32px; margin-bottom: 24px; align-items: center; }
    .score-ring-wrapper { position: relative; width: 120px; height: 120px; }
    .score-ring { width: 120px; height: 120px; transform: rotate(-90deg); }
    .score-ring-bg { fill: none; stroke: var(--border2); stroke-width: 6; }
    .score-ring-fill { fill: none; stroke-width: 6; stroke-linecap: square; stroke-dasharray: 314; stroke-dashoffset: 314; transition: stroke-dashoffset 1.2s ease, stroke 0.5s ease; }
    .score-number { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; font-family: var(--sans); font-weight: 800; font-size: 28px; color: var(--text); line-height: 1; }
    .score-number span { font-size: 11px; color: var(--text3); font-family: var(--mono); font-weight: 400; margin-top: 3px; }
    .score-repo { font-family: var(--sans); font-weight: 800; font-size: 22px; color: var(--text); margin-bottom: 8px; letter-spacing: -0.02em; }
    .score-label { font-size: 13px; margin-bottom: 16px; }
    .score-meta { display: flex; gap: 16px; flex-wrap: wrap; }
    .meta-item { font-size: 11px; color: var(--text2); }
    .meta-item strong { color: var(--text); }

    .summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
    .summary-card { background: var(--panel); border: 1px solid var(--border); padding: 16px; }
    .summary-card-label { font-size: 10px; color: var(--text3); letter-spacing: 0.1em; margin-bottom: 6px; }
    .summary-card-value { font-family: var(--sans); font-size: 22px; font-weight: 700; }
    .summary-card-value.green { color: var(--accent); }
    .summary-card-value.red { color: var(--red); }
    .summary-card-value.orange { color: var(--orange); }
    .summary-card-value.yellow { color: var(--yellow); }

    .tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 24px; }
    .tab { padding: 10px 20px; font-size: 11px; letter-spacing: 0.06em; color: var(--text3); cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s; }
    .tab:hover { color: var(--text2); }
    .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    .issues-table { width: 100%; border-collapse: collapse; }
    .issues-table th { text-align: left; padding: 8px 12px; font-size: 10px; color: var(--text3); letter-spacing: 0.1em; border-bottom: 1px solid var(--border); }
    .issues-table td { padding: 8px 12px; font-size: 12px; color: var(--text2); border-bottom: 1px solid var(--border); vertical-align: top; }
    .issues-table tr:hover td { background: var(--bg3); }
    .severity-badge { font-size: 9px; font-weight: 700; padding: 2px 6px; letter-spacing: 0.08em; display: inline-block; }
    .severity-badge.critical { background: var(--red); color: #000; }
    .severity-badge.high { background: var(--orange); color: #000; }
    .severity-badge.medium { background: var(--yellow); color: #000; }
    .severity-badge.low { background: var(--text3); color: var(--text); }

    .markdown-report { background: var(--panel); border: 1px solid var(--border); padding: 28px; line-height: 1.8; }
    .markdown-report h1 { font-family: var(--sans); font-size: 20px; font-weight: 800; color: var(--text); margin: 0 0 16px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
    .markdown-report h2 { font-family: var(--sans); font-size: 15px; font-weight: 700; color: var(--text); margin: 24px 0 10px; }
    .markdown-report h3 { font-size: 13px; font-weight: 700; color: var(--accent); margin: 16px 0 8px; }
    .markdown-report p { color: var(--text2); margin-bottom: 10px; }
    .markdown-report ul, .markdown-report ol { padding-left: 20px; margin-bottom: 10px; }
    .markdown-report li { color: var(--text2); margin-bottom: 4px; }
    .markdown-report code { background: var(--bg); color: var(--accent); padding: 1px 6px; font-family: var(--mono); font-size: 12px; }
    .markdown-report table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
    .markdown-report th { text-align: left; padding: 6px 10px; font-size: 10px; letter-spacing: 0.08em; color: var(--text3); border-bottom: 1px solid var(--border); }
    .markdown-report td { padding: 6px 10px; font-size: 12px; color: var(--text2); border-bottom: 1px solid var(--border); }
    .markdown-report blockquote { border-left: 2px solid var(--accent); padding-left: 12px; color: var(--text3); }
    .markdown-report hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
    .markdown-report strong { color: var(--text); }

    .download-btn { display: inline-block; margin-bottom: 16px; padding: 8px 16px; background: transparent; border: 1px solid var(--accent); color: var(--accent); font-family: var(--mono); font-size: 11px; cursor: pointer; text-decoration: none; transition: all 0.2s; }
    .download-btn:hover { background: var(--accent); color: var(--bg); }

    .error-box { background: rgba(255,68,68,0.08); border: 1px solid var(--red); padding: 16px 20px; color: var(--red); font-size: 12px; margin-bottom: 24px; display: none; }
    .error-box.visible { display: block; }

    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border2); }
  </style>
</head>
<body>
<header class="header">
  <div class="logo">TD</div>
  <div class="header-brand">
    <div class="header-title">Technical Debt Analyzer</div>
    <div class="header-sub">AST · radon · Claude · LangGraph</div>
  </div>
  <div class="header-pills">
    <span class="hpill">Python</span>
    <span class="hpill">LangGraph</span>
    <span class="hpill green">Claude</span>
  </div>
</header>

<div class="main">
  <div class="input-section">
    <label class="input-label">GitHub Repository URL</label>
    <div class="input-row">
      <input type="text" class="repo-input" id="repoInput"
        placeholder="https://github.com/owner/repository"
        onkeydown="if(event.key==='Enter') startAnalysis()"/>
      <button class="analyze-btn" id="analyzeBtn" onclick="startAnalysis()">ANALYZE →</button>
    </div>
  </div>

  <div class="error-box" id="errorBox"></div>

  <div class="progress-section" id="progressSection">
    <div class="progress-header">
      <span class="progress-label">ANALYSIS PROGRESS</span>
      <span class="progress-pct" id="progressPct">0%</span>
    </div>
    <div class="progress-bar-track">
      <div class="progress-bar-fill" id="progressFill"></div>
    </div>
    <div class="steps-log" id="stepsLog"></div>
  </div>

  <div class="report-section" id="reportSection">
    <div class="score-header">
      <div class="score-ring-wrapper">
        <svg class="score-ring" viewBox="0 0 120 120">
          <circle class="score-ring-bg" cx="60" cy="60" r="50"/>
          <circle class="score-ring-fill" id="scoreRingFill" cx="60" cy="60" r="50"/>
        </svg>
        <div class="score-number">
          <span id="scoreNumber">0</span>
          <span>/100</span>
        </div>
      </div>
      <div>
        <div class="score-repo" id="scoreRepo">—</div>
        <div class="score-label" id="scoreLabel">—</div>
        <div class="score-meta" id="scoreMeta"></div>
      </div>
    </div>

    <div class="summary-grid" id="summaryGrid"></div>

    <div class="tabs">
      <div class="tab active" onclick="switchTab('issues')">ISSUES</div>
      <div class="tab" onclick="switchTab('report')">FULL REPORT</div>
    </div>

    <div class="tab-panel active" id="panel-issues">
      <table class="issues-table">
        <thead><tr><th>SEVERITY</th><th>TYPE</th><th>FILE</th><th>MESSAGE</th></tr></thead>
        <tbody id="issuesBody"></tbody>
      </table>
    </div>

    <div class="tab-panel" id="panel-report">
      <a class="download-btn" id="downloadBtn" href="#" download>↓ DOWNLOAD REPORT (.md)</a>
      <div class="markdown-report" id="markdownReport"></div>
    </div>
  </div>
</div>

<script>
  marked.setOptions({ breaks: true, gfm: true });

  function switchTab(name) {
    document.querySelectorAll('.tab').forEach((t,i) => {
      t.classList.toggle('active', ['issues','report'][i] === name);
    });
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('panel-' + name).classList.add('active');
  }

  function addStep(message, status) {
    const log = document.getElementById('stepsLog');
    const prev = log.querySelector('.step-item.active');
    if (prev) prev.className = 'step-item done';
    const item = document.createElement('div');
    item.className = 'step-item ' + status;
    item.innerHTML = `<div class="step-dot"></div><span>${esc(message)}</span>`;
    log.appendChild(item);
    log.scrollTop = log.scrollHeight;
  }

  function setProgress(pct) {
    document.getElementById('progressFill').style.width = pct + '%';
    document.getElementById('progressPct').textContent = pct + '%';
  }

  async function startAnalysis() {
    const url = document.getElementById('repoInput').value.trim();
    if (!url) return;
    document.getElementById('errorBox').classList.remove('visible');
    document.getElementById('reportSection').classList.remove('visible');
    document.getElementById('progressSection').classList.add('visible');
    document.getElementById('stepsLog').innerHTML = '';
    document.getElementById('analyzeBtn').disabled = true;
    setProgress(0);

    try {
      const response = await fetch('/tech-debt/analyze/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ github_url: url })
      });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try { handleEvent(JSON.parse(line.slice(6))); } catch(e) {}
        }
      }
    } catch(e) {
      showError('Connection error: ' + e.message);
    } finally {
      document.getElementById('analyzeBtn').disabled = false;
    }
  }

  function handleEvent(data) {
    if (data.error) { showError(data.message); return; }
    setProgress(data.progress);
    if (data.step !== 'done') addStep(data.message, 'active');
    if (data.step === 'done' && data.report) {
      const last = document.querySelector('.step-item.active');
      if (last) last.className = 'step-item done';
      addStep('Analysis complete!', 'done');
      renderReport(data.report);
    }
  }

  function renderReport(report) {
    document.getElementById('progressSection').classList.remove('visible');
    document.getElementById('reportSection').classList.add('visible');
    const summary = report.summary || {};
    const score = report.health_score;

    const fill = document.getElementById('scoreRingFill');
    fill.style.strokeDashoffset = 314 - (score / 100 * 314);
    fill.style.stroke = score >= 80 ? '#00FF88' : score >= 60 ? '#FFD700' : score >= 40 ? '#FF8844' : '#FF4444';
    animateNumber('scoreNumber', 0, score, 1200);

    document.getElementById('scoreRepo').textContent = summary.repo_name || '—';
    document.getElementById('scoreLabel').textContent = report.score_label || '—';
    document.getElementById('scoreMeta').innerHTML = [
      `<span class="meta-item">Files: <strong>${summary.files_analyzed||0}</strong></span>`,
      `<span class="meta-item">Issues: <strong>${summary.total_issues||0}</strong></span>`,
      `<span class="meta-item">Tests: <strong>${summary.has_tests ? 'Yes ('+summary.test_ratio+'%)' : 'No'}</strong></span>`,
      `<span class="meta-item">CI/CD: <strong>${summary.has_ci_cd ? 'Yes' : 'No'}</strong></span>`,
    ].join('');

    const risk = summary.risk_level || 'unknown';
    const riskColor = risk === 'low' ? 'green' : risk === 'medium' ? 'yellow' : 'red';
    document.getElementById('summaryGrid').innerHTML = [
      card('HEALTH SCORE', score+'/100', score>=60?'green':score>=40?'yellow':'red'),
      card('RISK LEVEL', risk.toUpperCase(), riskColor),
      card('OUTDATED DEPS', summary.outdated_deps||0, (summary.outdated_deps||0)>5?'orange':'green'),
      card('TEST COVERAGE', (summary.test_ratio||0)+'%', (summary.test_ratio||0)>=60?'green':(summary.test_ratio||0)>=30?'yellow':'red'),
    ].join('');

    document.getElementById('issuesBody').innerHTML =
      '<tr><td colspan="4" style="color:var(--text3);text-align:center;padding:20px;">See Full Report tab for detailed issues breakdown</td></tr>';

    document.getElementById('markdownReport').innerHTML = marked.parse(report.markdown || '');
    const blob = new Blob([report.markdown||''], { type: 'text/markdown' });
    const dlBtn = document.getElementById('downloadBtn');
    dlBtn.href = URL.createObjectURL(blob);
    dlBtn.download = (summary.repo_name||'report') + '-tech-debt.md';
  }

  function card(label, value, colorClass) {
    return `<div class="summary-card"><div class="summary-card-label">${label}</div><div class="summary-card-value ${colorClass}">${value}</div></div>`;
  }

  function animateNumber(id, from, to, duration) {
    const el = document.getElementById(id);
    const start = performance.now();
    function step(now) {
      const t = Math.min((now - start) / duration, 1);
      el.textContent = Math.round(from + (to - from) * t);
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function showError(msg) {
    const box = document.getElementById('errorBox');
    box.textContent = '✗ ' + msg;
    box.classList.add('visible');
    document.getElementById('progressSection').classList.remove('visible');
  }

  function esc(t) { return String(t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
</script>
</body>
</html>"""
