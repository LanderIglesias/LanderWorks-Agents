"""Demo page del BI Agent — con gráficas inline."""

from __future__ import annotations


def demo_html() -> str:
    return r"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>BI Agent — Multi-Agent Analytics</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }

      :root {
        --bg: #0b0d12;
        --surface: #131722;
        --surface-hover: #1a1f2e;
        --border: #242938;
        --border-strong: #2f3548;
        --text: #e4e6eb;
        --text-dim: #8b93a7;
        --text-muted: #5b6378;
        --accent: #3b82f6;
        --success: #10b981;
        --success-dim: #064e3b;
        --warn: #f59e0b;
        --warn-dim: #451a03;
        --error: #ef4444;
        --error-dim: #7f1d1d;
      }

      html, body {
        background: var(--bg); color: var(--text);
        font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        font-size: 14px; height: 100vh; overflow: hidden;
      }

      .app { display: grid; grid-template-rows: auto 1fr; height: 100vh; }

      /* ── Header ── */
      .header {
        background: var(--surface); border-bottom: 1px solid var(--border);
        padding: 14px 24px; display: flex; align-items: center; gap: 32px;
      }
      .brand { display: flex; align-items: center; gap: 10px; }
      .brand-logo {
        width: 28px; height: 28px;
        background: linear-gradient(135deg, var(--accent) 0%, #6366f1 100%);
        border-radius: 7px; display: flex; align-items: center; justify-content: center;
        font-weight: 700; color: white; font-size: 14px;
      }
      .brand-name { font-weight: 600; font-size: 15px; }
      .brand-tag { font-size: 10px; color: var(--text-dim); margin-top: 1px; letter-spacing: 0.04em; text-transform: uppercase; }

      .stats { display: flex; gap: 28px; margin-left: auto; }
      .stat { display: flex; flex-direction: column; gap: 2px; }
      .stat-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; }
      .stat-value { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
      .stat-value.dim { color: var(--text-dim); font-weight: 400; }

      .actions { display: flex; gap: 10px; }
      .btn-secondary {
        padding: 7px 14px; background: transparent; color: var(--text-dim);
        border: 1px solid var(--border); border-radius: 6px; font-size: 12px;
        cursor: pointer; transition: all .15s;
      }
      .btn-secondary:hover:not(:disabled) { border-color: var(--border-strong); color: var(--text); }
      .btn-secondary:disabled { opacity: .4; cursor: not-allowed; }
      .btn-primary {
        padding: 7px 14px; background: var(--accent); color: white; border: 0;
        border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; transition: background .15s;
      }
      .btn-primary:hover:not(:disabled) { background: #2563eb; }
      .btn-primary:disabled { opacity: .4; cursor: not-allowed; }
      .btn-warn {
        padding: 7px 14px;
        background: linear-gradient(135deg, #f59e0b 0%, #ef4444 100%);
        color: white; border: 0; border-radius: 6px; font-size: 12px; font-weight: 500;
        cursor: pointer; display: inline-flex; align-items: center; gap: 6px; transition: opacity .15s;
      }
      .btn-warn:hover:not(:disabled) { opacity: .9; }
      .btn-warn:disabled { opacity: .4; cursor: not-allowed; }

      /* ── Layout ── */
      .body { display: grid; grid-template-columns: 1fr 340px; overflow: hidden; }
      .main { display: flex; flex-direction: column; border-right: 1px solid var(--border); overflow: hidden; }

      .empty-state {
        flex: 1; display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 20px;
        padding: 40px; text-align: center;
      }
      .empty-title { font-size: 18px; font-weight: 600; }
      .empty-sub { color: var(--text-dim); font-size: 13px; max-width: 480px; line-height: 1.6; }

      .load-options { display: flex; gap: 12px; margin-top: 20px; }
      .load-card {
        padding: 18px 22px; background: var(--surface); border: 1px solid var(--border);
        border-radius: 10px; min-width: 180px; cursor: pointer; transition: all .15s; text-align: left;
      }
      .load-card:hover { border-color: var(--accent); background: var(--surface-hover); }
      .load-card-title { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
      .load-card-sub { font-size: 11px; color: var(--text-dim); line-height: 1.5; }
      .load-card input { display: none; }

      /* ── Chat ── */
      .chat-area {
        flex: 1; overflow-y: auto; padding: 24px 32px;
        display: flex; flex-direction: column; gap: 20px;
      }
      .msg-user {
        align-self: flex-end; max-width: 70%; background: var(--accent); color: white;
        padding: 10px 16px; border-radius: 14px 14px 4px 14px; font-size: 14px; line-height: 1.5;
      }
      .msg-bot { align-self: flex-start; max-width: 92%; display: flex; flex-direction: column; gap: 10px; }
      .msg-bubble {
        background: var(--surface); border: 1px solid var(--border);
        padding: 14px 18px; border-radius: 14px 14px 14px 4px; line-height: 1.65; font-size: 14px;
      }

      /* ── Chart ── */
      .chart-container {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 12px; overflow: hidden; padding: 4px;
      }
      .chart-container img {
        width: 100%; display: block; border-radius: 8px;
      }

      /* ── Markdown ── */
      .markdown h1, .markdown h2, .markdown h3 { font-size: 14px; font-weight: 600; margin: 12px 0 6px; }
      .markdown h1:first-child, .markdown h2:first-child, .markdown h3:first-child { margin-top: 0; }
      .markdown p { margin-bottom: 8px; }
      .markdown p:last-child { margin-bottom: 0; }
      .markdown ul, .markdown ol { padding-left: 20px; margin-bottom: 8px; }
      .markdown li { margin-bottom: 4px; }
      .markdown strong { font-weight: 600; color: #fff; }
      .markdown code { background: var(--border); color: #93c5fd; padding: 1px 6px; border-radius: 4px; font-size: 12px; font-family: 'SF Mono', Consolas, monospace; }
      .markdown table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 12px; background: var(--bg); border-radius: 6px; overflow: hidden; }
      .markdown th { background: var(--border); color: var(--text); padding: 8px 12px; text-align: left; font-weight: 600; border-bottom: 1px solid var(--border-strong); }
      .markdown td { padding: 7px 12px; border-bottom: 1px solid var(--border); }
      .markdown tr:last-child td { border-bottom: 0; }

      /* ── Result table ── */
      .result-table-wrap { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; overflow: auto; max-height: 320px; }
      .result-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
      .result-table th { background: var(--border); color: var(--text); padding: 8px 14px; text-align: left; font-weight: 600; position: sticky; top: 0; border-bottom: 1px solid var(--border-strong); }
      .result-table td { padding: 7px 14px; border-bottom: 1px solid var(--border); color: var(--text-dim); }
      .result-table tr:hover td { background: var(--surface); color: var(--text); }
      .truncated-note { padding: 8px 14px; font-size: 11px; color: var(--text-muted); background: var(--surface); border-top: 1px solid var(--border); }

      /* ── Code block ── */
      .code-toggle { font-size: 11px; color: var(--text-dim); cursor: pointer; user-select: none; display: flex; align-items: center; gap: 4px; padding: 4px 0; transition: color .15s; }
      .code-toggle:hover { color: var(--accent); }
      .code-toggle::before { content: '▸'; font-size: 9px; transition: transform .2s; }
      .code-toggle.open::before { transform: rotate(90deg); }
      .code-block { display: none; background: #05070c; border: 1px solid var(--border); border-radius: 8px; padding: 14px; font-family: 'SF Mono', Consolas, monospace; font-size: 12px; line-height: 1.6; color: #93c5fd; white-space: pre-wrap; overflow-x: auto; }
      .code-block.open { display: block; }

      .thinking { color: var(--text-muted); font-size: 13px; font-style: italic; display: flex; align-items: center; gap: 8px; }
      .thinking::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 1.4s infinite; }
      @keyframes pulse { 0%, 100% { opacity: .3; transform: scale(.8); } 50% { opacity: 1; transform: scale(1); } }

      .subtasks-summary { font-size: 11px; color: var(--text-muted); padding: 10px 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; margin-bottom: 16px; }
      .subtasks-summary strong { color: var(--text-dim); font-weight: 500; }

      /* ── Input bar ── */
      .input-bar { padding: 16px 24px; border-top: 1px solid var(--border); background: var(--surface); }
      .suggestions { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
      .suggestion { background: var(--bg); color: var(--text-dim); border: 1px solid var(--border); padding: 5px 11px; border-radius: 20px; font-size: 11px; cursor: pointer; transition: all .15s; }
      .suggestion:hover { border-color: var(--accent); color: var(--text); background: var(--surface-hover); }
      .input-row { display: flex; gap: 10px; }
      .chat-input { flex: 1; padding: 10px 14px; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 8px; font-size: 14px; outline: none; transition: border-color .15s; font-family: inherit; }
      .chat-input:focus { border-color: var(--accent); }
      .chat-input:disabled { opacity: .5; }
      .chat-input::placeholder { color: var(--text-muted); }

      /* ── Trace panel ── */
      .trace-panel { background: var(--surface); display: flex; flex-direction: column; overflow: hidden; }
      .trace-header { padding: 14px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
      .trace-title { font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-dim); }
      .trace-badge { font-size: 10px; color: var(--text-muted); background: var(--bg); padding: 3px 8px; border-radius: 10px; border: 1px solid var(--border); }
      .trace-body { flex: 1; overflow-y: auto; padding: 16px 20px; }
      .trace-empty { color: var(--text-muted); font-size: 12px; text-align: center; padding: 40px 20px; line-height: 1.6; }

      .trace-step { position: relative; padding: 10px 0 10px 24px; opacity: 0; transform: translateX(-6px); animation: stepIn .35s ease forwards; border-left: 2px solid var(--border); margin-left: 8px; padding-left: 20px; }
      .trace-step:not(:last-child) { padding-bottom: 14px; }
      @keyframes stepIn { to { opacity: 1; transform: translateX(0); } }
      .trace-step::before { content: ''; position: absolute; left: -6px; top: 13px; width: 10px; height: 10px; border-radius: 50%; background: var(--border); border: 2px solid var(--surface); box-sizing: content-box; }

      .trace-step.s-planner::before { background: #a78bfa; box-shadow: 0 0 10px rgba(167,139,250,.5); }
      .trace-step.s-pandas::before { background: #60a5fa; box-shadow: 0 0 10px rgba(96,165,250,.5); }
      .trace-step.s-sql::before { background: #f59e0b; box-shadow: 0 0 10px rgba(245,158,11,.5); }
      .trace-step.s-executor::before { background: #34d399; box-shadow: 0 0 10px rgba(52,211,153,.5); }
      .trace-step.s-anomaly::before { background: #f97316; box-shadow: 0 0 10px rgba(249,115,22,.5); }
      .trace-step.s-validator.ok::before { background: var(--success); box-shadow: 0 0 10px rgba(16,185,129,.5); }
      .trace-step.s-validator.retry::before { background: var(--warn); box-shadow: 0 0 10px rgba(245,158,11,.5); }
      .trace-step.s-validator.fail::before { background: var(--error); box-shadow: 0 0 10px rgba(239,68,68,.5); }
      .trace-step.s-synthesizer::before { background: #ec4899; box-shadow: 0 0 10px rgba(236,72,153,.5); }
      .trace-step.s-chart::before { background: #8b5cf6; box-shadow: 0 0 10px rgba(139,92,246,.5); }

      .trace-node { font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 2px; }
      .trace-detail { font-size: 11px; color: var(--text-dim); line-height: 1.5; }

      .status-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 500; margin-top: 3px; }
      .status-badge.ok { background: var(--success-dim); color: #6ee7b7; }
      .status-badge.retry { background: rgba(245,158,11,.15); color: var(--warn); }
      .status-badge.fail { background: var(--error-dim); color: #fca5a5; }

      .session-info { padding: 14px 20px; border-bottom: 1px solid var(--border); }
      .session-info-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); margin-bottom: 6px; }

      /* ── Anomaly modal ── */
      .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.7); z-index: 1000; display: none; align-items: center; justify-content: center; padding: 40px; }
      .modal-backdrop.open { display: flex; }
      .modal { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; max-width: 720px; width: 100%; max-height: 85vh; overflow: hidden; display: flex; flex-direction: column; }
      .modal-header { padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
      .modal-title-row { display: flex; align-items: center; gap: 10px; }
      .modal-icon { width: 30px; height: 30px; border-radius: 50%; background: linear-gradient(135deg, #f59e0b 0%, #ef4444 100%); display: flex; align-items: center; justify-content: center; font-size: 16px; color: white; }
      .modal-title { font-size: 16px; font-weight: 600; }
      .modal-close { background: transparent; border: 0; color: var(--text-dim); cursor: pointer; font-size: 20px; padding: 4px 8px; }
      .modal-close:hover { color: var(--text); }
      .modal-body { padding: 20px 24px; overflow-y: auto; flex: 1; }
      .modal-summary { font-size: 13px; color: var(--text-dim); padding: 12px 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 16px; }
      .anomaly-item { padding: 14px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 10px; border-left: 3px solid var(--border); }
      .anomaly-item.sev-high { border-left-color: var(--error); }
      .anomaly-item.sev-medium { border-left-color: var(--warn); }
      .anomaly-item.sev-low { border-left-color: var(--text-muted); }
      .anomaly-header { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
      .anomaly-title { font-size: 13px; font-weight: 600; color: var(--text); flex: 1; }
      .anomaly-severity { font-size: 10px; padding: 2px 8px; border-radius: 4px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
      .anomaly-severity.sev-high { background: var(--error-dim); color: #fca5a5; }
      .anomaly-severity.sev-medium { background: var(--warn-dim); color: #fcd34d; }
      .anomaly-severity.sev-low { background: var(--border); color: var(--text-dim); }
      .anomaly-message { font-size: 12px; color: var(--text-dim); line-height: 1.6; }
      .anomaly-metric { display: inline-block; font-size: 10px; color: var(--text-muted); margin-top: 6px; padding: 2px 6px; background: var(--border); border-radius: 4px; font-family: 'SF Mono', Consolas, monospace; }
      .modal-empty { text-align: center; padding: 30px; color: var(--text-dim); }

      ::-webkit-scrollbar { width: 8px; height: 8px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
    </style>
  </head>
  <body>
    <div class="app">
      <header class="header">
        <div class="brand">
          <div class="brand-logo">BI</div>
          <div>
            <div class="brand-name">BI Agent</div>
            <div class="brand-tag">Multi-Agent Analytics</div>
          </div>
        </div>

        <div class="stats">
          <div class="stat"><div class="stat-label">Source</div><div class="stat-value dim" id="statSource">—</div></div>
          <div class="stat"><div class="stat-label">Rows</div><div class="stat-value dim" id="statRows">—</div></div>
          <div class="stat"><div class="stat-label">Columns</div><div class="stat-value dim" id="statCols">—</div></div>
          <div class="stat"><div class="stat-label">Questions</div><div class="stat-value dim" id="statQuestions">0</div></div>
        </div>

        <div class="actions">
          <button class="btn-warn" id="btnScanAnomalies" onclick="scanAnomalies()" disabled>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="12" height="12">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            Scan anomalies
          </button>
          <button class="btn-secondary" id="btnReset" onclick="resetSession()" disabled>Reset</button>
        </div>
      </header>

      <div class="body">
        <div class="main">
          <div class="chat-area" id="chatArea">
            <div class="empty-state" id="emptyState">
              <div>
                <div class="empty-title">Start analyzing your data</div>
                <div class="empty-sub">Upload a CSV or load the sample SaaS dataset. The multi-agent system will plan, execute and validate each query, then synthesize the answer with a chart.</div>
              </div>
              <div class="load-options">
                <label class="load-card">
                  <input type="file" accept=".csv" onchange="setFile(this.files[0])" />
                  <div class="load-card-title">Upload CSV</div>
                  <div class="load-card-sub">Your own dataset<br>Max 10 MB</div>
                </label>
                <div class="load-card" onclick="loadSample()">
                  <div class="load-card-title">Sample dataset</div>
                  <div class="load-card-sub">SaaS metrics<br>500 users · 6 months</div>
                </div>
              </div>
            </div>
          </div>

          <div class="input-bar" id="inputBar" style="display:none;">
            <div class="suggestions">
              <div class="suggestion" onclick="askSuggested(this.textContent)">Total MRR by plan</div>
              <div class="suggestion" onclick="askSuggested(this.textContent)">Churn rate by plan</div>
              <div class="suggestion" onclick="askSuggested(this.textContent)">Users signed up each month</div>
              <div class="suggestion" onclick="askSuggested(this.textContent)">Top 5 countries by user count</div>
              <div class="suggestion" onclick="askSuggested(this.textContent)">MRR growth between October and March</div>
            </div>
            <div class="input-row">
              <input type="text" class="chat-input" id="questionInput"
                placeholder="Ask anything about your data..."
                onkeydown="if(event.key==='Enter') sendQuestion()" />
              <button class="btn-primary" id="sendBtn" onclick="sendQuestion()">Ask</button>
            </div>
          </div>
        </div>

        <aside class="trace-panel">
          <div id="sessionInfo"></div>
          <div class="trace-header">
            <div class="trace-title">LangGraph Trace</div>
            <div class="trace-badge" id="traceBadge">Idle</div>
          </div>
          <div class="trace-body" id="traceBody">
            <div class="trace-empty">
              The execution graph will show here once you ask a question.<br><br>
              <strong>Planner</strong> → <strong>Specialist</strong> → <strong>Executor</strong> → <strong>Anomaly Detector</strong> → <strong>Validator</strong> → <strong>Synthesizer</strong> → <strong>Visualizer</strong>
            </div>
          </div>
        </aside>
      </div>
    </div>

    <!-- Anomaly modal -->
    <div class="modal-backdrop" id="anomalyModal" onclick="if(event.target===this) closeAnomalyModal()">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title-row">
            <div class="modal-icon">!</div>
            <div class="modal-title">Anomaly scan</div>
          </div>
          <button class="modal-close" onclick="closeAnomalyModal()">×</button>
        </div>
        <div class="modal-body" id="modalBody">
          <div class="thinking">Scanning dataset...</div>
        </div>
      </div>
    </div>

    <script>
      let sessionId = null;
      let questionCount = 0;

      marked.setOptions({ breaks: true, gfm: true });

      function setFile(file) { if (file) uploadFile(file); }

      async function uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        try {
          const res = await fetch('/bi-agent/upload', { method: 'POST', body: formData });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Upload failed');
          onDataLoaded(data);
        } catch (err) { alert('Error: ' + err.message); }
      }

      async function loadSample() {
        try {
          const res = await fetch('/bi-agent/sample');
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Failed to load sample');
          onDataLoaded(data);
        } catch (err) { alert('Error: ' + err.message); }
      }

      function onDataLoaded(data) {
        sessionId = data.session_id;
        questionCount = 0;

        document.getElementById('statSource').textContent = data.filename;
        document.getElementById('statSource').classList.remove('dim');
        document.getElementById('statRows').textContent = data.rows.toLocaleString();
        document.getElementById('statRows').classList.remove('dim');
        document.getElementById('statCols').textContent = data.columns.length;
        document.getElementById('statCols').classList.remove('dim');
        document.getElementById('statQuestions').textContent = '0';
        document.getElementById('btnReset').disabled = false;
        document.getElementById('btnScanAnomalies').disabled = false;

        const cols = data.columns.map(c =>
          '<span style="color:var(--text-dim);font-size:11px;display:inline-block;background:var(--bg);padding:2px 7px;margin:2px 3px 2px 0;border-radius:4px;border:1px solid var(--border);">' + c + '</span>'
        ).join('');
        document.getElementById('sessionInfo').innerHTML =
          '<div class="session-info"><div class="session-info-label">Columns</div><div style="margin-top:4px;">' + cols + '</div></div>';

        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('inputBar').style.display = 'block';
        document.getElementById('chatArea').innerHTML = '';
        addBotMessage('Dataset loaded. Ask a question — the agent will generate an answer and a chart when applicable.', null, null, null, null);
      }

      async function sendQuestion() {
        const input = document.getElementById('questionInput');
        const question = input.value.trim();
        if (!question || !sessionId) return;

        input.value = '';
        input.disabled = true;
        document.getElementById('sendBtn').disabled = true;

        addUserMessage(question);
        const thinkingId = addThinking();

        document.getElementById('traceBody').innerHTML = '';
        document.getElementById('traceBadge').textContent = 'Running';
        document.getElementById('traceBadge').style.color = 'var(--accent)';

        try {
          const res = await fetch('/bi-agent/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, question })
          });
          const data = await res.json();

          removeThinking(thinkingId);
          if (!res.ok) throw new Error(data.detail || 'Error');

          // Trace (incluyendo nodo visualizer si hay chart)
          const traceWithChart = data.trace ? [...data.trace] : [];
          if (data.chart) traceWithChart.push('visualizer: chart generated');

          animateTrace(traceWithChart, data.subtasks || []);

          setTimeout(() => {
            addBotMessage(data.answer, data.code, data.result, data.subtasks, data.chart);
            questionCount++;
            document.getElementById('statQuestions').textContent = questionCount;
          }, Math.min(traceWithChart.length * 200, 1800));

        } catch (err) {
          removeThinking(thinkingId);
          addBotMessage('Error: ' + err.message, null, null, null, null);
          document.getElementById('traceBadge').textContent = 'Error';
          document.getElementById('traceBadge').style.color = 'var(--error)';
        } finally {
          input.disabled = false;
          document.getElementById('sendBtn').disabled = false;
          input.focus();
        }
      }

      function askSuggested(q) {
        document.getElementById('questionInput').value = q;
        sendQuestion();
      }

      function addUserMessage(text) {
        const chat = document.getElementById('chatArea');
        const div = document.createElement('div');
        div.className = 'msg-user';
        div.textContent = text;
        chat.appendChild(div);
        chat.scrollTop = chat.scrollHeight;
      }

      function addBotMessage(text, code, result, subtasks, chart) {
        const chat = document.getElementById('chatArea');
        const codeId = 'code-' + Date.now() + Math.random();
        const rendered = marked.parse(text || '');
        const answerHasTable = /<table/i.test(rendered);

        let subtasksBlock = '';
        if (subtasks && subtasks.length > 1) {
          const tasksText = subtasks.map((st, i) =>
            (i + 1) + '. ' + esc(st.description) + ' <span style="color:var(--text-muted);">[' + st.specialist + ']</span>'
          ).join('<br>');
          subtasksBlock = '<div class="subtasks-summary"><strong>Plan (' + subtasks.length + ' subtasks):</strong><br>' + tasksText + '</div>';
        }

        // Gráfica — se muestra si viene y antes de la tabla de datos raw
        let chartBlock = '';
        if (chart) {
          chartBlock = '<div class="chart-container"><img src="data:image/png;base64,' + chart + '" alt="Chart" /></div>';
        }

        // Solo mostramos tabla raw si no hay gráfica Y no hay tabla en el markdown
        let tableBlock = '';
        if (!chart && !answerHasTable && result && typeof result === 'object') {
          if (result.type === 'dataframe') tableBlock = renderDataframe(result);
          else if (result.type === 'series') tableBlock = renderSeries(result);
        }

        let codeBlock = '';
        if (code) {
          codeBlock =
            '<div class="code-toggle" onclick="toggleCode(\'' + codeId + '\', this)"><span>Show generated code</span></div>' +
            '<div class="code-block" id="' + codeId + '">' + esc(code) + '</div>';
        }

        const div = document.createElement('div');
        div.className = 'msg-bot';
        div.innerHTML =
          subtasksBlock +
          '<div class="msg-bubble markdown">' + rendered + '</div>' +
          chartBlock +
          tableBlock +
          codeBlock;
        chat.appendChild(div);
        chat.scrollTop = chat.scrollHeight;
      }

      function renderDataframe(df) {
        if (!df.rows || !df.rows.length) return '<div class="truncated-note">No rows returned.</div>';
        const cols = df.columns;
        let html = '<div class="result-table-wrap"><table class="result-table"><thead><tr>';
        cols.forEach(c => html += '<th>' + esc(c) + '</th>');
        html += '</tr></thead><tbody>';
        df.rows.forEach(row => {
          html += '<tr>';
          cols.forEach(c => {
            const v = row[c];
            html += '<td>' + esc(v == null ? '' : formatValue(v)) + '</td>';
          });
          html += '</tr>';
        });
        html += '</tbody></table>';
        if (df.truncated) html += '<div class="truncated-note">Showing first 200 of ' + df.total_rows.toLocaleString() + ' rows</div>';
        html += '</div>';
        return html;
      }

      function renderSeries(s) {
        if (!s.data || !Object.keys(s.data).length) return '';
        let html = '<div class="result-table-wrap"><table class="result-table"><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>';
        Object.entries(s.data).forEach(([k, v]) => {
          html += '<tr><td>' + esc(k) + '</td><td>' + esc(formatValue(v)) + '</td></tr>';
        });
        html += '</tbody></table></div>';
        return html;
      }

      function formatValue(v) {
        if (typeof v === 'number') {
          if (Number.isInteger(v)) return v.toLocaleString();
          return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
        }
        return String(v);
      }

      function toggleCode(id, toggle) {
        const el = document.getElementById(id);
        el.classList.toggle('open');
        toggle.classList.toggle('open');
        toggle.querySelector('span').textContent =
          el.classList.contains('open') ? 'Hide generated code' : 'Show generated code';
      }

      function addThinking() {
        const id = 'thinking-' + Date.now();
        const chat = document.getElementById('chatArea');
        const div = document.createElement('div');
        div.id = id; div.className = 'msg-bot';
        div.innerHTML = '<div class="msg-bubble"><div class="thinking">Planning query...</div></div>';
        chat.appendChild(div);
        chat.scrollTop = chat.scrollHeight;
        return id;
      }

      function removeThinking(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
      }

      function animateTrace(trace, subtasks) {
        const body = document.getElementById('traceBody');
        body.innerHTML = '';

        if (!trace.length) {
          document.getElementById('traceBadge').textContent = 'Done';
          document.getElementById('traceBadge').style.color = 'var(--success)';
          return;
        }

        let i = 0;
        const interval = setInterval(() => {
          if (i >= trace.length) {
            clearInterval(interval);
            const badge = document.getElementById('traceBadge');
            const anyFail = trace.some(t => t.includes('FAIL'));
            badge.textContent = anyFail ? 'Completed with errors' : 'Completed';
            badge.style.color = anyFail ? 'var(--warn)' : 'var(--success)';
            return;
          }
          body.appendChild(buildTraceStep(trace[i], i));
          body.scrollTop = body.scrollHeight;
          i++;
        }, 200);
      }

      function buildTraceStep(step, idx) {
        const div = document.createElement('div');
        div.className = 'trace-step';

        let nodeName = '', detail = '', statusBadge = '';

        if (step.startsWith('planner')) {
          div.classList.add('s-planner'); nodeName = 'Planner';
          const m = step.match(/\((\d+) subtask/);
          detail = m ? 'Generated ' + m[1] + ' subtask' + (m[1] === '1' ? '' : 's') : step;
        } else if (step.startsWith('pandas_specialist')) {
          div.classList.add('s-pandas'); nodeName = 'Pandas Specialist';
          const m = step.match(/task (\d+), retry=(\d+)/);
          if (m) detail = 'Task ' + m[1] + (m[2] !== '0' ? ' — retry #' + m[2] : '') + ' — generating code';
          else detail = step;
        } else if (step.startsWith('sql_specialist')) {
          div.classList.add('s-sql'); nodeName = 'SQL Specialist';
          const m = step.match(/task (\d+), retry=(\d+)/);
          if (m) detail = 'Task ' + m[1] + (m[2] !== '0' ? ' — retry #' + m[2] : '') + ' — generating query';
          else detail = step;
        } else if (step.startsWith('executor')) {
          div.classList.add('s-executor'); nodeName = 'Executor';
          if (step.includes('ok')) detail = 'Code executed successfully';
          else if (step.includes('error')) detail = 'Execution failed';
          else detail = 'Running code';
        } else if (step.startsWith('anomaly_detector')) {
          div.classList.add('s-anomaly'); nodeName = 'Anomaly Detector';
          if (step.includes('no anomalies')) detail = 'No anomalies detected';
          else if (step.includes('detected')) { const m = step.match(/(\d+) detected/); detail = m ? m[1] + ' anomalies flagged' : 'Anomalies flagged'; }
          else if (step.includes('minor')) detail = 'Minor deviations only';
          else detail = 'Scanning for outliers';
        } else if (step.startsWith('validator')) {
          div.classList.add('s-validator'); nodeName = 'Validator';
          if (step.includes('PASS')) { div.classList.add('ok'); detail = 'Result validated'; statusBadge = '<span class="status-badge ok">PASS</span>'; }
          else if (step.includes('retry')) { div.classList.add('retry'); const m = step.match(/retry (\d+)\/(\d+)/); detail = m ? 'Retrying attempt ' + m[1] + ' of ' + m[2] : 'Retrying'; statusBadge = '<span class="status-badge retry">RETRY</span>'; }
          else if (step.includes('FAIL')) { div.classList.add('fail'); detail = 'Validation failed after retries'; statusBadge = '<span class="status-badge fail">FAIL</span>'; }
        } else if (step.startsWith('synthesizer')) {
          div.classList.add('s-synthesizer'); nodeName = 'Synthesizer'; detail = 'Generating final answer';
        } else if (step.startsWith('visualizer')) {
          div.classList.add('s-chart'); nodeName = 'Visualizer'; detail = 'Chart generated';
        } else {
          nodeName = step; detail = '';
        }

        div.innerHTML =
          '<div class="trace-node">' + esc(nodeName) + '</div>' +
          '<div class="trace-detail">' + esc(detail) + ' ' + statusBadge + '</div>';
        return div;
      }

      // ── Anomaly scan ──
      async function scanAnomalies() {
        if (!sessionId) return;
        const modal = document.getElementById('anomalyModal');
        const body = document.getElementById('modalBody');
        modal.classList.add('open');
        body.innerHTML = '<div class="thinking">Scanning dataset for anomalies...</div>';
        try {
          const res = await fetch('/bi-agent/scan-anomalies', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId })
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Scan failed');
          renderAnomalies(data);
        } catch (err) {
          body.innerHTML = '<div class="modal-empty">Error: ' + esc(err.message) + '</div>';
        }
      }

      function renderAnomalies(data) {
        const body = document.getElementById('modalBody');
        if (!data.anomalies || data.anomalies.length === 0) {
          body.innerHTML = '<div class="modal-empty"><div style="font-size:24px;margin-bottom:10px;opacity:.6">✓</div>' + esc(data.summary || 'No anomalies found') + '</div>';
          return;
        }
        let html = '<div class="modal-summary">' + esc(data.summary) + '</div>';
        data.anomalies.forEach(a => {
          const sev = (a.severity || 'medium').toLowerCase();
          html += '<div class="anomaly-item sev-' + sev + '">' +
            '<div class="anomaly-header"><div class="anomaly-title">' + esc(a.title || 'Anomaly') + '</div>' +
            '<div class="anomaly-severity sev-' + sev + '">' + esc(sev.toUpperCase()) + '</div></div>' +
            '<div class="anomaly-message">' + esc(a.message || '') + '</div>' +
            (a.metric ? '<div class="anomaly-metric">' + esc(a.metric) + '</div>' : '') +
            '</div>';
        });
        body.innerHTML = html;
      }

      function closeAnomalyModal() {
        document.getElementById('anomalyModal').classList.remove('open');
      }

      async function resetSession() {
        if (!sessionId) return;
        try { await fetch('/bi-agent/session/' + sessionId, { method: 'DELETE' }); } catch (e) {}
        location.reload();
      }

      function esc(text) {
        return String(text == null ? '' : text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      }
    </script>
  </body>
</html>"""
