"""Demo UI del Document Intelligence Agent — con chunks y compare mode."""

from __future__ import annotations


def demo_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Document Intelligence</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,300&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --cream: #F7F3EE; --cream-dark: #EDE7DD; --cream-mid: #F0EAE0;
      --sage: #C8D8C8; --sage-dark: #9BB89B;
      --blush: #E8C4C4; --blush-dark: #D4A0A0;
      --sky: #BDD4E4; --sky-dark: #90B8D0;
      --ink: #2C2824; --ink-mid: #5A5248; --ink-light: #8A8278; --ink-faint: #B8B0A8;
      --white: #FFFFFF; --border: rgba(44,40,36,0.10); --shadow: rgba(44,40,36,0.08);
    }
    html, body { height: 100vh; background: var(--cream); color: var(--ink); font-family: 'DM Sans', sans-serif; font-size: 14px; overflow: hidden; }
    .app { display: grid; grid-template-rows: auto 1fr; height: 100vh; }

    /* Header */
    .header { background: var(--white); border-bottom: 1px solid var(--border); padding: 0 28px; height: 60px; display: flex; align-items: center; gap: 16px; }
    .logo { width: 34px; height: 34px; background: linear-gradient(135deg, var(--sage), var(--sky)); border-radius: 10px; display: flex; align-items: center; justify-content: center; font-family: 'DM Serif Display', serif; font-size: 16px; color: var(--ink); flex-shrink: 0; }
    .header-brand { display: flex; flex-direction: column; gap: 1px; }
    .header-title { font-family: 'DM Serif Display', serif; font-size: 17px; color: var(--ink); line-height: 1; }
    .header-sub { font-size: 10px; color: var(--ink-faint); letter-spacing: 0.06em; text-transform: uppercase; }
    .header-pills { display: flex; gap: 6px; margin-left: 20px; }
    .pill { font-size: 10px; padding: 3px 9px; border-radius: 20px; border: 1px solid var(--border); color: var(--ink-mid); background: var(--cream); font-weight: 500; }
    .header-right { margin-left: auto; }
    .doc-count { font-size: 12px; color: var(--ink-light); background: var(--cream-dark); padding: 5px 12px; border-radius: 20px; }

    /* Body */
    .body { display: grid; grid-template-columns: 280px 1fr; overflow: hidden; }

    /* Sidebar */
    .sidebar { background: var(--white); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
    .sidebar-section { padding: 16px; border-bottom: 1px solid var(--border); }
    .sidebar-label { font-size: 10px; font-weight: 600; color: var(--ink-faint); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }
    .upload-zone { border: 2px dashed var(--sage-dark); border-radius: 12px; padding: 20px 16px; text-align: center; cursor: pointer; transition: all .2s; background: linear-gradient(135deg, rgba(200,216,200,.15), rgba(189,212,228,.15)); display: block; }
    .upload-zone:hover { border-color: var(--sky-dark); background: linear-gradient(135deg, rgba(200,216,200,.3), rgba(189,212,228,.3)); transform: translateY(-1px); box-shadow: 0 4px 12px var(--shadow); }
    .upload-zone input { display: none; }
    .upload-icon { font-size: 24px; margin-bottom: 8px; display: block; }
    .upload-text { font-size: 12px; font-weight: 500; color: var(--ink-mid); display: block; margin-bottom: 3px; }
    .upload-sub { font-size: 10px; color: var(--ink-faint); }
    .upload-status { font-size: 11px; color: var(--sage-dark); text-align: center; padding: 6px 0; display: none; font-weight: 500; }
    .scope-section { padding: 12px 16px; border-bottom: 1px solid var(--border); }
    .scope-select { width: 100%; padding: 7px 28px 7px 10px; background: var(--cream); border: 1px solid var(--border); border-radius: 8px; font-size: 12px; color: var(--ink); font-family: 'DM Sans', sans-serif; outline: none; cursor: pointer; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238A8278' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 10px center; }
    .doc-list { flex: 1; overflow-y: auto; padding: 10px; }
    .doc-empty { padding: 24px 12px; text-align: center; color: var(--ink-faint); font-size: 12px; line-height: 1.7; }
    .doc-card { padding: 10px 12px; border-radius: 10px; cursor: pointer; transition: all .15s; border: 1.5px solid transparent; margin-bottom: 5px; background: var(--cream); }
    .doc-card:hover { background: var(--cream-dark); border-color: var(--border); }
    .doc-card.active { background: linear-gradient(135deg, rgba(200,216,200,.4), rgba(189,212,228,.4)); border-color: var(--sage-dark); }
    .doc-card-name { font-size: 12px; font-weight: 500; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
    .doc-card-meta { display: flex; align-items: center; gap: 6px; font-size: 10px; color: var(--ink-faint); }
    .doc-card-chunks { background: var(--sage); color: var(--ink-mid); padding: 1px 6px; border-radius: 6px; font-size: 9px; font-weight: 600; }
    .doc-delete { margin-left: auto; font-size: 10px; color: var(--blush-dark); cursor: pointer; opacity: 0; transition: opacity .15s; font-weight: 500; }
    .doc-card:hover .doc-delete { opacity: 1; }

    /* Main */
    .main { display: flex; flex-direction: column; overflow: hidden; background: var(--cream); }
    .chat-area { flex: 1; overflow-y: auto; padding: 24px 36px; display: flex; flex-direction: column; gap: 18px; }
    .empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; padding: 40px; }
    .empty-decoration { width: 80px; height: 80px; background: linear-gradient(135deg, var(--sage), var(--sky)); border-radius: 24px; display: flex; align-items: center; justify-content: center; font-size: 36px; margin-bottom: 8px; box-shadow: 0 8px 24px rgba(155,184,155,.3); }
    .empty-title { font-family: 'DM Serif Display', serif; font-size: 22px; color: var(--ink); margin-bottom: 6px; }
    .empty-sub { font-size: 13px; color: var(--ink-light); max-width: 340px; line-height: 1.7; }

    /* Messages */
    .msg-user { align-self: flex-end; max-width: 68%; background: linear-gradient(135deg, var(--sage), var(--sky)); color: var(--ink); padding: 11px 16px; border-radius: 16px 16px 4px 16px; font-size: 14px; line-height: 1.5; box-shadow: 0 2px 8px var(--shadow); }
    .msg-bot { align-self: flex-start; max-width: 90%; display: flex; flex-direction: column; gap: 8px; }
    .msg-bubble { background: var(--white); border: 1px solid var(--border); padding: 14px 18px; border-radius: 4px 16px 16px 16px; line-height: 1.7; font-size: 14px; box-shadow: 0 2px 8px var(--shadow); }

    /* Source pills */
    .sources-row { display: flex; flex-wrap: wrap; gap: 5px; }
    .source-pill { font-size: 10px; background: linear-gradient(135deg, rgba(200,216,200,.5), rgba(189,212,228,.5)); color: var(--ink-mid); padding: 3px 9px; border-radius: 10px; border: 1px solid var(--sage); font-weight: 500; }

    /* Chunks expandible */
    .chunks-toggle { font-size: 11px; color: var(--ink-light); cursor: pointer; user-select: none; display: flex; align-items: center; gap: 5px; padding: 3px 0; transition: color .15s; }
    .chunks-toggle:hover { color: var(--sage-dark); }
    .chunks-toggle::before { content: '▸'; font-size: 9px; transition: transform .2s; }
    .chunks-toggle.open::before { transform: rotate(90deg); }
    .chunks-panel { display: none; flex-direction: column; gap: 8px; margin-top: 4px; }
    .chunks-panel.open { display: flex; }
    .chunk-item { background: var(--cream-mid); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; border-left: 3px solid var(--sage-dark); }
    .chunk-meta { font-size: 10px; color: var(--ink-light); margin-bottom: 5px; font-weight: 500; }
    .chunk-text { font-size: 12px; color: var(--ink-mid); line-height: 1.6; max-height: 120px; overflow-y: auto; }

    /* Compare mode — cards apiladas */
    .compare-header { font-family: 'DM Serif Display', serif; font-size: 16px; color: var(--ink); margin-bottom: 12px; }
    .compare-question { font-size: 12px; color: var(--ink-light); background: var(--cream-dark); padding: 8px 12px; border-radius: 8px; margin-bottom: 14px; font-style: italic; }
    .compare-cards { display: flex; flex-direction: column; gap: 12px; width: 100%; }
    .compare-card { background: var(--white); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px var(--shadow); }
    .compare-card-header { padding: 10px 16px; background: linear-gradient(135deg, rgba(200,216,200,.2), rgba(189,212,228,.2)); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }
    .compare-card-filename { font-size: 12px; font-weight: 600; color: var(--ink); flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .compare-card-pages { font-size: 10px; color: var(--ink-faint); }
    .compare-card-body { padding: 14px 16px; font-size: 13px; line-height: 1.7; color: var(--ink-mid); }
    .compare-card-sources { padding: 0 16px 10px; display: flex; flex-wrap: wrap; gap: 4px; }

    /* Markdown */
    .markdown p { margin-bottom: 8px; }
    .markdown p:last-child { margin-bottom: 0; }
    .markdown ul, .markdown ol { padding-left: 18px; margin-bottom: 8px; }
    .markdown li { margin-bottom: 4px; }
    .markdown strong { font-weight: 600; color: var(--ink); }
    .markdown code { background: var(--cream-dark); color: var(--ink-mid); padding: 1px 6px; border-radius: 4px; font-size: 12px; font-family: monospace; }
    .markdown h1, .markdown h2, .markdown h3 { font-family: 'DM Serif Display', serif; margin: 10px 0 5px; }

    /* Thinking */
    .thinking { color: var(--ink-faint); font-size: 13px; font-style: italic; display: flex; align-items: center; gap: 8px; }
    .thinking::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: var(--sage-dark); animation: pulse 1.4s infinite; flex-shrink: 0; }
    @keyframes pulse { 0%,100%{opacity:.3;transform:scale(.7)} 50%{opacity:1;transform:scale(1)} }

    /* Input bar */
    .input-bar { padding: 14px 28px 18px; background: var(--white); border-top: 1px solid var(--border); }
    .scope-indicator { font-size: 10px; color: var(--sage-dark); margin-bottom: 6px; font-weight: 500; min-height: 14px; }
    .input-row { display: flex; gap: 8px; align-items: center; }
    .chat-input { flex: 1; padding: 11px 16px; background: var(--cream); color: var(--ink); border: 1.5px solid var(--border); border-radius: 12px; font-size: 14px; font-family: 'DM Sans', sans-serif; outline: none; transition: border-color .2s, box-shadow .2s; }
    .chat-input:focus { border-color: var(--sage-dark); box-shadow: 0 0 0 3px rgba(155,184,155,.2); }
    .chat-input::placeholder { color: var(--ink-faint); }
    .send-btn { padding: 11px 18px; background: linear-gradient(135deg, var(--sage-dark), var(--sky-dark)); color: var(--white); border: none; border-radius: 12px; font-size: 13px; font-weight: 600; font-family: 'DM Sans', sans-serif; cursor: pointer; transition: all .2s; box-shadow: 0 2px 8px rgba(155,184,155,.4); white-space: nowrap; }
    .send-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(155,184,155,.5); }
    .send-btn:disabled { opacity: .5; cursor: not-allowed; transform: none; }
    .compare-btn { padding: 11px 14px; background: var(--cream-dark); color: var(--ink-mid); border: 1.5px solid var(--border); border-radius: 12px; font-size: 12px; font-weight: 500; font-family: 'DM Sans', sans-serif; cursor: pointer; transition: all .2s; white-space: nowrap; }
    .compare-btn:hover:not(:disabled) { border-color: var(--sage-dark); color: var(--ink); background: var(--sage); }
    .compare-btn:disabled { opacity: .4; cursor: not-allowed; }

    ::-webkit-scrollbar { width: 5px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: var(--cream-dark); border-radius: 3px; }
  </style>
</head>
<body>
<div class="app">
  <header class="header">
    <div class="logo">D</div>
    <div class="header-brand">
      <div class="header-title">Document Intelligence</div>
      <div class="header-sub">Powered by pgvector · Claude · R2</div>
    </div>
    <div class="header-pills">
      <span class="pill">PostgreSQL</span>
      <span class="pill">pgvector</span>
      <span class="pill">Cloudflare R2</span>
    </div>
    <div class="header-right">
      <div class="doc-count" id="docCount">0 documents</div>
    </div>
  </header>

  <div class="body">
    <aside class="sidebar">
      <div class="sidebar-section">
        <div class="sidebar-label">Upload</div>
        <label class="upload-zone">
          <input type="file" accept=".pdf" multiple onchange="uploadFiles(this.files)" />
          <span class="upload-icon">📂</span>
          <span class="upload-text">Drop PDFs or click to browse</span>
          <span class="upload-sub">Up to 20 MB per file</span>
        </label>
        <div class="upload-status" id="uploadStatus"></div>
      </div>
      <div class="scope-section">
        <div class="sidebar-label">Search scope</div>
        <select class="scope-select" id="filterSelect" onchange="onFilterChange()">
          <option value="">All documents</option>
        </select>
      </div>
      <div class="doc-list" id="docList">
        <div class="doc-empty">No documents indexed yet.<br>Upload a PDF to get started.</div>
      </div>
    </aside>

    <div class="main">
      <div class="chat-area" id="chatArea">
        <div class="empty-state" id="emptyState">
          <div class="empty-decoration">📄</div>
          <div class="empty-title">Ask anything about your documents</div>
          <div class="empty-sub">Upload PDFs on the left. Ask a question or use Compare to search across all documents at once.</div>
        </div>
      </div>
      <div class="input-bar">
        <div class="scope-indicator" id="scopeIndicator"></div>
        <div class="input-row">
          <input type="text" class="chat-input" id="questionInput"
            placeholder="Ask a question about your documents..."
            onkeydown="if(event.key==='Enter') sendQuestion()" />
          <button class="compare-btn" id="compareBtn" onclick="compareDocuments()" disabled>Compare all</button>
          <button class="send-btn" id="sendBtn" onclick="sendQuestion()">Ask →</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
  marked.setOptions({ breaks: true, gfm: true });
  let documents = [];
  let activeFilter = '';

  async function loadDocuments() {
    try {
      const res = await fetch('/doc-intel/documents');
      const data = await res.json();
      documents = data.documents || [];
      renderDocList();
      updateFilterSelect();
      const n = documents.length;
      document.getElementById('docCount').textContent = n + ' document' + (n !== 1 ? 's' : '');
      document.getElementById('compareBtn').disabled = n < 2;
    } catch(e) {}
  }

  function renderDocList() {
    const list = document.getElementById('docList');
    if (!documents.length) {
      list.innerHTML = '<div class="doc-empty">No documents indexed yet.<br>Upload a PDF to get started.</div>';
      return;
    }
    list.innerHTML = documents.map(doc => `
      <div class="doc-card ${activeFilter === doc.filename ? 'active' : ''}"
           onclick="setFilter('${esc(doc.filename)}')">
        <div class="doc-card-name" title="${esc(doc.filename)}">${esc(doc.filename)}</div>
        <div class="doc-card-meta">
          <span class="doc-card-chunks">${doc.chunk_count} chunks</span>
          <span>${doc.indexed_at ? doc.indexed_at.substring(0,10) : ''}</span>
          <span class="doc-delete" onclick="event.stopPropagation(); deleteDoc('${esc(doc.filename)}')">Remove</span>
        </div>
      </div>`).join('');
  }

  function updateFilterSelect() {
    const sel = document.getElementById('filterSelect');
    const cur = sel.value;
    sel.innerHTML = '<option value="">All documents</option>' +
      documents.map(d => `<option value="${esc(d.filename)}" ${cur===d.filename?'selected':''}>${esc(d.filename)}</option>`).join('');
  }

  function setFilter(filename) {
    activeFilter = (activeFilter === filename) ? '' : filename;
    document.getElementById('filterSelect').value = activeFilter;
    renderDocList();
    updateScopeIndicator();
  }

  function onFilterChange() {
    activeFilter = document.getElementById('filterSelect').value;
    renderDocList();
    updateScopeIndicator();
  }

  function updateScopeIndicator() {
    document.getElementById('scopeIndicator').textContent = activeFilter ? `Searching in: ${activeFilter}` : '';
  }

  async function uploadFiles(files) {
    if (!files.length) return;
    const status = document.getElementById('uploadStatus');
    status.style.display = 'block';
    for (const file of files) {
      status.textContent = `Uploading ${file.name}...`;
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch('/doc-intel/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed');
        status.textContent = `✓ ${file.name} — ${data.chunk_count} chunks indexed`;
        document.getElementById('emptyState').style.display = 'none';
      } catch(err) {
        status.textContent = `✗ ${file.name}: ${err.message}`;
      }
    }
    await loadDocuments();
    setTimeout(() => { status.style.display = 'none'; }, 3000);
  }

  async function deleteDoc(filename) {
    if (!confirm(`Remove "${filename}"?`)) return;
    await fetch(`/doc-intel/document/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (activeFilter === filename) { activeFilter = ''; updateScopeIndicator(); }
    await loadDocuments();
  }

  async function sendQuestion() {
    const input = document.getElementById('questionInput');
    const q = input.value.trim();
    if (!q) return;
    input.value = '';
    setLoading(true);
    document.getElementById('emptyState').style.display = 'none';
    addUserMsg(q);
    const tid = addThinking('Searching through your documents...');

    try {
      const res = await fetch('/doc-intel/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, filename: activeFilter || null, top_k: 5 })
      });
      const data = await res.json();
      removeThinking(tid);
      if (!res.ok) throw new Error(data.detail || 'Error');
      addBotMsg(data.answer, data.sources, data.chunks_text || []);
    } catch(err) {
      removeThinking(tid);
      addBotMsg('Error: ' + err.message, [], []);
    } finally {
      setLoading(false);
    }
  }

  async function compareDocuments() {
    const input = document.getElementById('questionInput');
    const q = input.value.trim();
    if (!q) {
      input.focus();
      input.placeholder = 'Enter a question first, then click Compare all';
      setTimeout(() => { input.placeholder = 'Ask a question about your documents...'; }, 2500);
      return;
    }
    input.value = '';
    setLoading(true);
    document.getElementById('emptyState').style.display = 'none';
    addUserMsg(q + ' ↔ comparing all documents');
    const tid = addThinking(`Comparing across ${documents.length} documents...`);

    try {
      const res = await fetch('/doc-intel/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, top_k: 3 })
      });
      const data = await res.json();
      removeThinking(tid);
      if (!res.ok) throw new Error(data.detail || 'Error');
      addCompareResult(q, data.results);
    } catch(err) {
      removeThinking(tid);
      addBotMsg('Error: ' + err.message, [], []);
    } finally {
      setLoading(false);
    }
  }

  function addUserMsg(text) {
    const chat = document.getElementById('chatArea');
    const d = document.createElement('div');
    d.className = 'msg-user'; d.textContent = text;
    chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
  }

  function addBotMsg(text, sources, chunksText) {
    const chat = document.getElementById('chatArea');
    const d = document.createElement('div');
    d.className = 'msg-bot';

    const cid = 'chunks-' + Date.now();

    // Source pills
    let srcHtml = '';
    if (sources && sources.length) {
      srcHtml = '<div class="sources-row">' +
        sources.map(s => `<span class="source-pill">📄 ${esc(s.filename)} · p.${s.page}</span>`).join('') +
        '</div>';
    }

    // Chunks toggle
    let chunksHtml = '';
    if (chunksText && chunksText.length) {
      const items = chunksText.map(c =>
        `<div class="chunk-item">
          <div class="chunk-meta">📄 ${esc(c.filename)} — Page ${c.page}</div>
          <div class="chunk-text">${esc(c.content)}</div>
        </div>`
      ).join('');
      chunksHtml = `
        <div class="chunks-toggle" onclick="toggleChunks('${cid}', this)">Show source chunks (${chunksText.length})</div>
        <div class="chunks-panel" id="${cid}">${items}</div>`;
    }

    d.innerHTML = `<div class="msg-bubble markdown">${marked.parse(text||'')}</div>${srcHtml}${chunksHtml}`;
    chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
  }

  function addCompareResult(question, results) {
  const chat = document.getElementById('chatArea');
  const d = document.createElement('div');
  d.className = 'msg-bot';
  d.style.width = '100%';

  const cards = results.map((r, i) => {
    const srcPills = r.sources && r.sources.length
      ? r.sources.map(s => `<span class="source-pill">p.${s.page}</span>`).join('')
      : '';

    const cid = 'compare-chunks-' + Date.now() + '-' + i;

    // Chunks toggle por card
    let chunksHtml = '';
    if (r.chunks_text && r.chunks_text.length) {
      const items = r.chunks_text.map(c =>
        `<div class="chunk-item">
          <div class="chunk-meta">📄 ${esc(c.filename)} — Page ${c.page}</div>
          <div class="chunk-text">${esc(c.content)}</div>
        </div>`
      ).join('');
      chunksHtml = `
        <div style="padding: 0 16px 10px;">
          <div class="chunks-toggle" onclick="toggleChunks('${cid}', this)">Show source chunks (${r.chunks_text.length})</div>
          <div class="chunks-panel" id="${cid}">${items}</div>
        </div>`;
    }

    return `
      <div class="compare-card">
        <div class="compare-card-header">
          <span style="font-size:14px;">📄</span>
          <span class="compare-card-filename" title="${esc(r.filename)}">${esc(r.filename)}</span>
          <span class="compare-card-pages">${r.chunks_used} chunks used</span>
        </div>
        <div class="compare-card-body markdown">${marked.parse(r.answer||'')}</div>
        ${srcPills ? `<div class="compare-card-sources">${srcPills}</div>` : ''}
        ${chunksHtml}
      </div>`;
  }).join('');

  d.innerHTML = `
    <div class="compare-header">Compare results</div>
    <div class="compare-question">"${esc(question)}"</div>
    <div class="compare-cards">${cards}</div>`;

  chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
  }

  function toggleChunks(id, toggle) {
    const panel = document.getElementById(id);
    panel.classList.toggle('open');
    toggle.classList.toggle('open');
    toggle.textContent = panel.classList.contains('open')
      ? toggle.textContent.replace('Show', 'Hide')
      : toggle.textContent.replace('Hide', 'Show');
  }

  function addThinking(msg) {
    const id = 'th-' + Date.now();
    const chat = document.getElementById('chatArea');
    const d = document.createElement('div');
    d.id = id; d.className = 'msg-bot';
    d.innerHTML = `<div class="msg-bubble"><div class="thinking">${esc(msg)}</div></div>`;
    chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
    return id;
  }

  function removeThinking(id) { const el = document.getElementById(id); if(el) el.remove(); }

  function setLoading(on) {
    document.getElementById('questionInput').disabled = on;
    document.getElementById('sendBtn').disabled = on;
    document.getElementById('compareBtn').disabled = on || documents.length < 2;
  }

  function esc(t) {
    return String(t??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  loadDocuments();
</script>
</body>
</html>"""
