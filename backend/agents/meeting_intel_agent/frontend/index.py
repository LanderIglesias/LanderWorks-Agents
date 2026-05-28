"""UI del Meeting Intelligence Agent — Glassmorphism light theme."""

from __future__ import annotations


def demo_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Meeting Intelligence</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg1: #EEF2FF;
      --bg2: #E0E7FF;
      --glass: rgba(255,255,255,0.65);
      --glass2: rgba(255,255,255,0.45);
      --glass3: rgba(255,255,255,0.25);
      --blur: blur(20px);
      --border: rgba(255,255,255,0.8);
      --border2: rgba(139,92,246,0.15);
      --shadow: 0 8px 32px rgba(99,102,241,0.1);
      --shadow2: 0 4px 16px rgba(99,102,241,0.08);
      --text: #1E1B4B;
      --text2: #4338CA;
      --text3: #818CF8;
      --text4: #6B7280;
      --violet: #7C3AED;
      --violet2: #6D28D9;
      --lavender: #8B5CF6;
      --indigo: #4F46E5;
      --emerald: #059669;
      --rose: #DC2626;
      --amber: #D97706;
      --sans: 'Inter', sans-serif;
    }

    html { scroll-behavior: smooth; }

    body {
      min-height: 100vh;
      font-family: var(--sans);
      font-size: 14px;
      line-height: 1.6;
      color: var(--text);
      background:
        radial-gradient(ellipse 80% 80% at 20% 20%, rgba(167,139,250,0.25) 0%, transparent 60%),
        radial-gradient(ellipse 60% 60% at 80% 80%, rgba(99,102,241,0.2) 0%, transparent 60%),
        radial-gradient(ellipse 100% 100% at 50% 50%, #EEF2FF 0%, #E0E7FF 100%);
      background-attachment: fixed;
    }

    /* ── NAV ── */
    nav {
      position: sticky; top: 0; z-index: 100;
      height: 64px;
      background: rgba(255,255,255,0.7);
      backdrop-filter: var(--blur);
      -webkit-backdrop-filter: var(--blur);
      border-bottom: 1px solid var(--border);
      display: flex; align-items: center;
      padding: 0 40px; gap: 16px;
      box-shadow: 0 1px 0 rgba(139,92,246,0.08);
    }

    .nav-logo {
      width: 38px; height: 38px; border-radius: 12px;
      background: linear-gradient(135deg, #7C3AED, #4F46E5);
      display: flex; align-items: center; justify-content: center;
      font-size: 20px; box-shadow: 0 4px 12px rgba(124,58,237,0.35);
      flex-shrink: 0;
    }

    .nav-name { font-size: 16px; font-weight: 700; color: var(--text); }
    .nav-dot { width: 4px; height: 4px; border-radius: 50%; background: var(--text3); }
    .nav-sub { font-size: 12px; color: var(--text3); font-weight: 500; }
    .nav-right { margin-left: auto; display: flex; gap: 8px; }

    .chip {
      font-size: 11px; font-weight: 600;
      padding: 4px 12px; border-radius: 20px;
      background: rgba(124,58,237,0.08);
      color: var(--lavender);
      border: 1px solid rgba(124,58,237,0.15);
      letter-spacing: 0.02em;
    }
    .chip.dark { background: linear-gradient(135deg, #7C3AED, #4F46E5); color: white; border: none; box-shadow: 0 2px 8px rgba(124,58,237,0.3); }

    /* ── LAYOUT ── */
    .wrap { max-width: 1120px; margin: 0 auto; padding: 40px; }
    .grid { display: grid; grid-template-columns: 360px 1fr; gap: 24px; align-items: start; }

    /* ── GLASS CARD ── */
    .glass {
      background: var(--glass);
      backdrop-filter: var(--blur);
      -webkit-backdrop-filter: var(--blur);
      border: 1px solid var(--border);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }
    .glass-sm {
      background: var(--glass2);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: var(--shadow2);
    }

    /* ── FORM ── */
    .form-card { padding: 28px; }
    .form-title { font-size: 18px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
    .form-sub { font-size: 13px; color: var(--text4); margin-bottom: 24px; }

    /* Upload */
    .upload-zone {
      border: 2px dashed rgba(124,58,237,0.25);
      border-radius: 18px;
      padding: 28px 20px;
      text-align: center;
      cursor: pointer;
      position: relative;
      transition: all 0.25s;
      background: rgba(124,58,237,0.04);
      margin-bottom: 20px;
    }
    .upload-zone:hover {
      border-color: var(--lavender);
      background: rgba(124,58,237,0.08);
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(124,58,237,0.12);
    }
    .upload-zone input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
    .upload-ring {
      width: 64px; height: 64px; border-radius: 50%; margin: 0 auto 14px;
      background: linear-gradient(135deg, rgba(124,58,237,0.15), rgba(79,70,229,0.1));
      border: 1.5px solid rgba(124,58,237,0.2);
      display: flex; align-items: center; justify-content: center;
      font-size: 28px;
      box-shadow: 0 0 0 8px rgba(124,58,237,0.06);
    }
    .upload-zone h3 { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
    .upload-zone p { font-size: 12px; color: var(--text4); }
    .upload-zone p strong { color: var(--lavender); font-weight: 600; }
    .upload-zone.has-file { border-color: var(--emerald); background: rgba(5,150,105,0.05); }
    .upload-zone.has-file .upload-ring { background: rgba(5,150,105,0.12); border-color: rgba(5,150,105,0.25); box-shadow: 0 0 0 8px rgba(5,150,105,0.05); }

    /* Divider */
    .divider { display: flex; align-items: center; gap: 12px; margin: 18px 0; }
    .div-line { flex: 1; height: 1px; background: rgba(139,92,246,0.15); }
    .div-text { font-size: 11px; font-weight: 600; color: var(--text3); letter-spacing: 0.08em; }

    /* Inputs */
    .field { margin-bottom: 16px; }
    .field label { font-size: 12px; font-weight: 600; color: var(--text2); display: block; margin-bottom: 6px; letter-spacing: 0.02em; }
    .inp {
      width: 100%; padding: 11px 14px; border-radius: 12px;
      border: 1.5px solid rgba(139,92,246,0.2);
      background: rgba(255,255,255,0.7);
      color: var(--text); font-family: var(--sans); font-size: 13px;
      outline: none; transition: all 0.2s;
    }
    .inp:focus { border-color: var(--lavender); box-shadow: 0 0 0 4px rgba(124,58,237,0.1); background: white; }
    .inp::placeholder { color: #A5B4FC; }
    .inp-row { display: flex; gap: 8px; }
    select.inp { cursor: pointer; max-width: 100px; }
    textarea.inp { min-height: 80px; resize: vertical; font-size: 12px; }

    /* Button */
    .btn-primary {
      width: 100%; padding: 14px;
      background: linear-gradient(135deg, #7C3AED, #4F46E5);
      color: white; border: none; border-radius: 14px;
      font-family: var(--sans); font-size: 14px; font-weight: 600;
      cursor: pointer; transition: all 0.25s;
      box-shadow: 0 6px 24px rgba(124,58,237,0.35);
      letter-spacing: 0.01em; margin-top: 4px;
    }
    .btn-primary:hover:not(:disabled) {
      transform: translateY(-2px);
      box-shadow: 0 10px 32px rgba(124,58,237,0.45);
    }
    .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }

    /* ── CONTENT ── */
    .content-col { display: flex; flex-direction: column; gap: 20px; }

    /* Empty state */
    .empty {
      padding: 80px 40px; text-align: center;
    }
    .empty-blob {
      width: 100px; height: 100px; border-radius: 50%; margin: 0 auto 24px;
      background: linear-gradient(135deg, rgba(124,58,237,0.15), rgba(79,70,229,0.1));
      display: flex; align-items: center; justify-content: center; font-size: 44px;
    }
    .empty h2 { font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
    .empty p { font-size: 14px; color: var(--text4); max-width: 280px; margin: 0 auto; line-height: 1.6; }

    /* Progress */
    .prog-card { padding: 24px; display: none; }
    .prog-card.visible { display: block; }
    .prog-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .prog-title { font-size: 14px; font-weight: 600; color: var(--text); }
    .prog-pct { font-size: 13px; font-weight: 700; color: var(--lavender); }
    .ptrack { height: 8px; border-radius: 8px; background: rgba(139,92,246,0.12); overflow: hidden; margin-bottom: 20px; }
    .pfill {
      height: 100%; width: 0%; border-radius: 8px;
      background: linear-gradient(90deg, #7C3AED, #818CF8);
      transition: width 0.4s ease;
      box-shadow: 0 0 12px rgba(124,58,237,0.4);
    }
    .steps { display: flex; flex-direction: column; gap: 6px; max-height: 200px; overflow-y: auto; }
    .step {
      display: flex; align-items: center; gap: 12px; padding: 9px 14px;
      border-radius: 10px; background: rgba(255,255,255,0.5);
      border: 1px solid rgba(255,255,255,0.8);
    }
    .sdot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: #DDD6FE; }
    .step.done .sdot { background: var(--emerald); box-shadow: 0 0 6px rgba(5,150,105,0.4); }
    .step.active .sdot { background: var(--lavender); animation: pulse 1s infinite; }
    .step.error .sdot { background: var(--rose); }
    .smsg { font-size: 12px; color: var(--text4); font-weight: 500; }
    @keyframes pulse { 0%,100%{transform:scale(1);opacity:1} 50%{transform:scale(1.5);opacity:0.6} }

    /* Stats */
    .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
    .stat {
      padding: 18px; border-radius: 18px; text-align: center;
      background: rgba(255,255,255,0.6);
      backdrop-filter: blur(10px);
      border: 1px solid var(--border);
      box-shadow: var(--shadow2);
    }
    .stat-e { font-size: 24px; margin-bottom: 8px; }
    .stat-n { font-size: 30px; font-weight: 800; color: var(--text); line-height: 1; margin-bottom: 4px; }
    .stat-l { font-size: 11px; font-weight: 600; color: var(--text3); letter-spacing: 0.04em; }

    /* Ask */
    .ask-card { padding: 20px; }
    .ask-label { font-size: 12px; font-weight: 600; color: var(--text2); margin-bottom: 12px; letter-spacing: 0.02em; }
    .ask-row { display: flex; gap: 8px; }
    .ask-btn {
      padding: 11px 18px; border-radius: 12px;
      background: linear-gradient(135deg, rgba(124,58,237,0.12), rgba(79,70,229,0.08));
      border: 1.5px solid rgba(124,58,237,0.2);
      color: var(--lavender); font-family: var(--sans);
      font-size: 13px; font-weight: 600; cursor: pointer;
      white-space: nowrap; transition: all 0.2s;
    }
    .ask-btn:hover { background: rgba(124,58,237,0.18); transform: translateY(-1px); }
    .ask-ans {
      margin-top: 14px; padding: 14px 16px; border-radius: 12px;
      background: rgba(124,58,237,0.06); border: 1px solid rgba(124,58,237,0.15);
      border-left: 3px solid var(--lavender);
      font-size: 13px; color: var(--text); line-height: 1.75;
      display: none;
    }
    .ask-ans.visible { display: block; }

    /* Tabs */
    .tabs { display: flex; gap: 4px; background: rgba(139,92,246,0.08); padding: 4px; border-radius: 14px; }
    .tab-btn {
      flex: 1; text-align: center; padding: 9px;
      font-size: 13px; font-weight: 600; color: var(--text3);
      cursor: pointer; border-radius: 11px; transition: all 0.2s;
    }
    .tab-btn.active {
      background: white; color: var(--text);
      box-shadow: 0 2px 10px rgba(99,102,241,0.15);
    }
    .tab-panel { display: none; padding-top: 16px; }
    .tab-panel.active { display: block; }

    /* Sections */
    .sect {
      background: rgba(255,255,255,0.6); backdrop-filter: blur(8px);
      border: 1px solid var(--border); border-radius: 18px;
      overflow: hidden; margin-bottom: 12px;
      box-shadow: 0 2px 12px rgba(99,102,241,0.06);
    }
    .sect-hd {
      padding: 16px 20px; display: flex; align-items: center;
      justify-content: space-between; cursor: pointer;
      transition: background 0.15s;
    }
    .sect-hd:hover { background: rgba(124,58,237,0.04); }
    .sect-left { display: flex; align-items: center; gap: 10px; }
    .sect-ico { font-size: 18px; }
    .sect-name { font-size: 14px; font-weight: 600; color: var(--text); }
    .sect-right { display: flex; align-items: center; gap: 8px; }
    .sect-badge {
      font-size: 11px; font-weight: 700;
      background: rgba(124,58,237,0.1); color: var(--lavender);
      padding: 3px 10px; border-radius: 20px;
    }
    .sect-chev { color: var(--text3); font-size: 11px; transition: transform 0.2s; }
    .sect-hd.open .sect-chev { transform: rotate(180deg); }
    .sect-body { display: none; padding: 0 20px 16px; }
    .sect-body.open { display: block; }
    .summary-p { font-size: 14px; color: var(--text4); line-height: 1.8; }

    /* Items */
    .item {
      background: white; border-radius: 12px; padding: 14px 16px;
      margin-bottom: 8px; border: 1px solid rgba(139,92,246,0.1);
      box-shadow: 0 2px 8px rgba(99,102,241,0.05);
      border-left: 4px solid rgba(139,92,246,0.2);
    }
    .item:last-child { margin-bottom: 0; }
    .item.hi { border-left-color: var(--rose); }
    .item.me { border-left-color: var(--amber); }
    .item.lo { border-left-color: var(--emerald); }
    .item-main { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
    .item-sub { font-size: 11px; color: var(--text4); }

    /* Markdown */
    .md-wrap { background: rgba(255,255,255,0.7); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: 20px; padding: 28px; line-height: 1.8; box-shadow: var(--shadow); }
    .dl-btn {
      display: inline-flex; align-items: center; gap: 6px; margin-bottom: 16px;
      padding: 8px 16px; border-radius: 10px;
      background: rgba(124,58,237,0.08); border: 1.5px solid rgba(124,58,237,0.2);
      color: var(--lavender); font-size: 12px; font-weight: 600;
      cursor: pointer; text-decoration: none; transition: all 0.2s;
    }
    .dl-btn:hover { background: rgba(124,58,237,0.15); }
    .md-wrap h1 { font-size: 20px; font-weight: 700; color: var(--text); margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(139,92,246,0.15); }
    .md-wrap h2 { font-size: 15px; font-weight: 700; color: var(--text); margin: 24px 0 10px; }
    .md-wrap h3 { font-size: 13px; font-weight: 600; color: var(--lavender); margin: 16px 0 8px; }
    .md-wrap p { color: var(--text4); margin-bottom: 10px; }
    .md-wrap ul, .md-wrap ol { padding-left: 20px; margin-bottom: 10px; }
    .md-wrap li { color: var(--text4); margin-bottom: 4px; }
    .md-wrap code { background: rgba(124,58,237,0.08); color: var(--lavender); padding: 2px 7px; border-radius: 6px; font-size: 12px; }
    .md-wrap table { width: 100%; border-collapse: collapse; margin-bottom: 16px; border-radius: 10px; overflow: hidden; }
    .md-wrap th { text-align: left; padding: 8px 12px; font-size: 11px; color: var(--text3); background: rgba(139,92,246,0.06); }
    .md-wrap td { padding: 8px 12px; font-size: 13px; color: var(--text4); border-bottom: 1px solid rgba(139,92,246,0.08); }
    .md-wrap hr { border: none; border-top: 1px solid rgba(139,92,246,0.12); margin: 20px 0; }
    .md-wrap strong { color: var(--text); }
    .md-wrap blockquote { border-left: 3px solid var(--lavender); padding-left: 14px; color: var(--text3); }

    /* Error */
    .err { display: none; padding: 14px 16px; border-radius: 12px; background: rgba(220,38,38,0.06); border: 1px solid rgba(220,38,38,0.2); color: #B91C1C; font-size: 13px; margin-bottom: 16px; }
    .err.visible { display: block; }

    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-thumb { background: rgba(124,58,237,0.2); border-radius: 4px; }
  </style>
</head>
<body>

<nav>
  <div class="nav-logo">🎙️</div>
  <span class="nav-name">Meeting Intelligence</span>
  <div class="nav-dot"></div>
  <span class="nav-sub">Whisper · Claude · LangGraph · pgvector</span>
  <div class="nav-right">
    <span class="chip">faster-whisper</span>
    <span class="chip">PostgreSQL</span>
    <span class="chip dark">Claude</span>
  </div>
</nav>

<div class="wrap">
  <div class="grid">

    <!-- FORM -->
    <div class="glass form-card">
      <div class="form-title">Analyze a Meeting</div>
      <div class="form-sub">Upload a recording or paste a transcript to extract structured insights.</div>

      <div class="upload-zone" id="uploadZone">
        <input type="file" id="audioFile" accept=".mp3,.wav,.m4a,.ogg,.flac,.webm" onchange="handleFile(this)"/>
        <div class="upload-ring">🎙️</div>
        <h3>Drop your recording here</h3>
        <p>or <strong>click to browse</strong> · MP3, WAV, M4A</p>
      </div>

      <div class="divider">
        <div class="div-line"></div>
        <span class="div-text">OR PASTE TRANSCRIPT</span>
        <div class="div-line"></div>
      </div>

      <div class="field">
        <textarea class="inp" id="rawText" placeholder="Paste meeting transcript here..."></textarea>
      </div>

      <div class="field">
        <label>Meeting Title & Language</label>
        <div class="inp-row">
          <input type="text" class="inp" id="meetingTitle" placeholder="Q2 Planning, Sprint Review..."/>
          <select class="inp" id="language">
            <option value="auto">Auto</option>
            <option value="es">ES</option>
            <option value="en">EN</option>
          </select>
        </div>
      </div>

      <button class="btn-primary" id="analyzeBtn" onclick="startAnalysis()">
        Analyze Meeting →
      </button>
    </div>

    <!-- CONTENT -->
    <div class="content-col">

      <!-- Empty -->
      <div class="glass empty" id="emptyState">
        <div class="empty-blob">📋</div>
        <h2>Ready to analyze</h2>
        <p>Upload a recording or paste a transcript to extract decisions, action items, and key insights.</p>
      </div>

      <!-- Error -->
      <div class="err" id="errBox"></div>

      <!-- Progress -->
      <div class="glass prog-card" id="progressCard">
        <div class="prog-top">
          <span class="prog-title">Analyzing meeting...</span>
          <span class="prog-pct" id="progPct">0%</span>
        </div>
        <div class="ptrack"><div class="pfill" id="pfill"></div></div>
        <div class="steps" id="stepsLog"></div>
      </div>

      <!-- Report -->
      <div id="reportWrap" style="display:none">

        <!-- Stats -->
        <div class="stats" id="statsRow"></div>

        <!-- Ask -->
        <div class="glass-sm ask-card" style="margin-top:20px">
          <div class="ask-label">💬 Ask about this meeting</div>
          <div class="ask-row">
            <input type="text" class="inp" id="askInput" placeholder="Who is responsible for the dashboard?" onkeydown="if(event.key==='Enter') askQ()"/>
            <button class="ask-btn" onclick="askQ()">Ask →</button>
          </div>
          <div class="ask-ans" id="askAns"></div>
        </div>

        <!-- Tabs -->
        <div style="margin-top:20px">
          <div class="tabs">
            <div class="tab-btn active" onclick="switchTab('structured')">Structured</div>
            <div class="tab-btn" onclick="switchTab('report')">Full Report</div>
          </div>
          <div class="tab-panel active" id="panel-structured">
            <div id="structuredContent"></div>
          </div>
          <div class="tab-panel" id="panel-report">
            <a class="dl-btn" id="dlBtn" href="#" download>↓ Download Report (.md)</a>
            <div class="md-wrap" id="mdWrap"></div>
          </div>
        </div>

      </div>
    </div>
  </div>
</div>

<script>
  marked.setOptions({ breaks: true, gfm: true });
  let currentMeetingId = null;

  function handleFile(input) {
    const z = document.getElementById('uploadZone');
    if (input.files[0]) {
      z.classList.add('has-file');
      z.querySelector('h3').textContent = '✓ ' + input.files[0].name;
      z.querySelector('p').textContent = 'Ready to analyze';
      document.getElementById('rawText').value = '';
    }
  }

  function switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach((t,i) => t.classList.toggle('active', ['structured','report'][i] === name));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('panel-' + name).classList.add('active');
  }

  function addStep(msg, status) {
    const log = document.getElementById('stepsLog');
    const prev = log.querySelector('.step.active');
    if (prev) prev.className = 'step done';
    const el = document.createElement('div');
    el.className = 'step ' + status;
    el.innerHTML = `<div class="sdot"></div><span class="smsg">${esc(msg)}</span>`;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  function setProgress(pct) {
    document.getElementById('pfill').style.width = pct + '%';
    document.getElementById('progPct').textContent = pct + '%';
  }

  async function startAnalysis() {
    const file = document.getElementById('audioFile').files[0];
    const rawText = document.getElementById('rawText').value.trim();
    const title = document.getElementById('meetingTitle').value.trim() || 'Untitled Meeting';
    const lang = document.getElementById('language').value;
    if (!file && !rawText) { showErr('Please upload an audio file or paste a transcript.'); return; }

    document.getElementById('errBox').classList.remove('visible');
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('reportWrap').style.display = 'none';
    document.getElementById('progressCard').classList.add('visible');
    document.getElementById('stepsLog').innerHTML = '';
    document.getElementById('analyzeBtn').disabled = true;
    setProgress(0);

    const fd = new FormData();
    if (file) fd.append('file', file);
    if (rawText) fd.append('raw_text', rawText);
    fd.append('meeting_title', title);
    fd.append('language', lang);

    try {
      const res = await fetch('/meeting-intel/analyze/stream', { method: 'POST', body: fd });
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n'); buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try { handleEvt(JSON.parse(line.slice(6))); } catch(e) {}
        }
      }
    } catch(e) { showErr('Connection error: ' + e.message); }
    finally { document.getElementById('analyzeBtn').disabled = false; }
  }

  function handleEvt(data) {
    if (data.error) { showErr(data.message); return; }
    setProgress(data.progress);
    if (data.step !== 'done') addStep(data.message, 'active');
    if (data.step === 'done' && data.report) {
      const last = document.querySelector('.step.active');
      if (last) last.className = 'step done';
      addStep('Analysis complete!', 'done');
      setTimeout(() => renderReport(data.report), 600);
    }
  }

  function renderReport(report) {
    document.getElementById('progressCard').classList.remove('visible');
    document.getElementById('reportWrap').style.display = 'block';
    currentMeetingId = report.meeting_id;

    const s = report.stats || {};
    document.getElementById('statsRow').innerHTML = [
      stat('✅', s.total_decisions||0, 'Decisions'),
      stat('📌', s.total_action_items||0, 'Action Items'),
      stat('❓', s.total_open_questions||0, 'Open Questions'),
      stat('🔄', s.total_pending_topics||0, 'Pending'),
    ].join('');

    const sc = document.getElementById('structuredContent');
    sc.innerHTML = '';
    if (report.executive_summary) sc.innerHTML += sect('📋', 'Executive Summary', null,
      `<p class="summary-p">${esc(report.executive_summary)}</p>`);
    if (report.decisions?.length) sc.innerHTML += sect('✅', 'Decisions', report.decisions.length,
      report.decisions.map(d => `<div class="item"><div class="item-main">${esc(d.text)}</div><div class="item-sub">${esc(d.context)}</div></div>`).join(''));
    if (report.action_items?.length) sc.innerHTML += sect('📌', 'Action Items', report.action_items.length,
      report.action_items.map(a => {
        const p = (a.priority||'medium').toLowerCase();
        return `<div class="item ${p==='high'?'hi':p==='low'?'lo':'me'}">
          <div class="item-main">${esc(a.task)}</div>
          <div class="item-sub">Owner: ${esc(a.owner)} · Deadline: ${esc(a.deadline)} · ${esc(a.priority)}</div>
        </div>`;
      }).join(''));
    if (report.open_questions?.length) sc.innerHTML += sect('❓', 'Open Questions', report.open_questions.length,
      report.open_questions.map(q => `<div class="item"><div class="item-main">${esc(q.question)}</div><div class="item-sub">${esc(q.context)}</div></div>`).join(''));
    if (report.pending_topics?.length) sc.innerHTML += sect('🔄', 'Pending Topics', report.pending_topics.length,
      report.pending_topics.map(p => `<div class="item"><div class="item-main">${esc(p.topic)}</div><div class="item-sub">${esc(p.reason)}</div></div>`).join(''));

    if (report.report_markdown) {
      document.getElementById('mdWrap').innerHTML = marked.parse(report.report_markdown);
      const blob = new Blob([report.report_markdown], { type: 'text/markdown' });
      const btn = document.getElementById('dlBtn');
      btn.href = URL.createObjectURL(blob);
      btn.download = (report.title||'meeting') + '-report.md';
    }
  }

  function stat(emoji, num, label) {
    return `<div class="stat"><div class="stat-e">${emoji}</div><div class="stat-n">${num}</div><div class="stat-l">${label}</div></div>`;
  }

  function sect(icon, name, count, content) {
    const badge = count !== null ? `<span class="sect-badge">${count}</span>` : '';
    return `<div class="sect">
      <div class="sect-hd open" onclick="toggleSect(this)">
        <div class="sect-left"><span class="sect-ico">${icon}</span><span class="sect-name">${name}</span></div>
        <div class="sect-right">${badge}<span class="sect-chev">▼</span></div>
      </div>
      <div class="sect-body open">${content}</div>
    </div>`;
  }

  function toggleSect(hd) {
    hd.classList.toggle('open');
    hd.nextElementSibling.classList.toggle('open');
  }

  async function askQ() {
    if (!currentMeetingId) return;
    const q = document.getElementById('askInput').value.trim();
    if (!q) return;
    const el = document.getElementById('askAns');
    el.classList.add('visible'); el.textContent = 'Searching...';
    try {
      const r = await fetch('/meeting-intel/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meeting_id: currentMeetingId, question: q })
      });
      const data = await r.json();
      el.textContent = data.answer;
    } catch(e) { el.textContent = 'Error: ' + e.message; }
  }

  function showErr(msg) {
    const b = document.getElementById('errBox');
    b.textContent = '✗ ' + msg; b.classList.add('visible');
    document.getElementById('progressCard').classList.remove('visible');
  }

  function esc(t) { return String(t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
</script>
</body>
</html>"""
