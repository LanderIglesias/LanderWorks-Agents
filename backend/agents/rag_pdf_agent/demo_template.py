"""Demo page v2 del RAG PDF Agent — con historial, fuentes expandibles y modo comparar."""

from __future__ import annotations


def demo_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PDF Chat Agent</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body {
        font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        background: #f6f7f9; color: #111; min-height: 100vh; padding: 24px;
      }
      .container { max-width: 900px; margin: 0 auto; }
      .card {
        background: white; border-radius: 16px;
        box-shadow: 0 4px 24px rgba(0,0,0,.07); padding: 24px; margin-bottom: 16px;
      }
      h1 { font-size: 22px; font-weight: 600; margin-bottom: 4px; }
      .subtitle { font-size: 14px; color: #666; margin-bottom: 20px; }
      .tabs { display: flex; gap: 8px; margin-bottom: 20px; }
      .tab {
        padding: 8px 16px; border-radius: 8px; font-size: 14px;
        cursor: pointer; border: 1px solid #ddd; background: white; color: #555; transition: all .15s;
      }
      .tab.active { background: #6366f1; color: white; border-color: #6366f1; }
      .upload-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .upload-zone {
        border: 2px dashed #ddd; border-radius: 12px; padding: 20px;
        text-align: center; cursor: pointer; transition: all .2s;
      }
      .upload-zone:hover, .upload-zone.drag { border-color: #6366f1; background: #f5f5ff; }
      .upload-zone input { display: none; }
      .upload-label { font-size: 13px; font-weight: 600; color: #555; margin-bottom: 4px; }
      .upload-text { font-size: 13px; color: #888; }
      .upload-sub { font-size: 11px; color: #bbb; margin-top: 4px; }
      .badge {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 5px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; margin-top: 8px;
      }
      .badge-processing { background: #fef3c7; color: #92400e; }
      .badge-ready { background: #d1fae5; color: #065f46; }
      .badge-error { background: #fee2e2; color: #991b1b; }
      .btn {
        padding: 10px 18px; background: #111; color: white;
        border: 0; border-radius: 10px; font-size: 14px; cursor: pointer; transition: opacity .15s;
      }
      .btn:disabled { opacity: .4; cursor: not-allowed; }
      .btn-primary { background: #6366f1; width: 100%; margin-top: 12px; padding: 12px; }
      .doc-info {
        background: #f5f5ff; border: 1px solid #e0e0ff; border-radius: 10px;
        padding: 10px 14px; font-size: 13px; color: #4338ca; margin-bottom: 12px; display: none;
      }
      .chat-area {
        height: 440px; overflow-y: auto; border: 1px solid #eee;
        border-radius: 12px; padding: 16px; margin-bottom: 12px;
        display: flex; flex-direction: column; gap: 14px;
      }
      .msg-user { align-self: flex-end; max-width: 80%; }
      .msg-bot { align-self: flex-start; width: 100%; }
      .msg-bubble { padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.55; }
      .msg-user .msg-bubble { background: #6366f1; color: white; border-radius: 12px 12px 2px 12px; }
      .msg-bot .msg-bubble { background: #f4f4f5; color: #111; border-radius: 12px 12px 12px 2px; }
      /* Markdown */
      .markdown h1, .markdown h2 { font-size: 15px; font-weight: 600; margin: 12px 0 6px; }
      .markdown h3 { font-size: 14px; font-weight: 600; margin: 10px 0 4px; }
      .markdown p { margin-bottom: 8px; }
      .markdown ul, .markdown ol { padding-left: 18px; margin-bottom: 8px; }
      .markdown li { margin-bottom: 3px; }
      .markdown strong { font-weight: 600; }
      .markdown table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }
      .markdown th { background: #e8e8ff; color: #3730a3; padding: 8px 12px; text-align: left; border: 1px solid #ddd; font-weight: 600; }
      .markdown td { padding: 7px 12px; border: 1px solid #ddd; vertical-align: top; }
      .markdown tr:nth-child(even) td { background: #fafafa; }
      .markdown code { background: #e8e8ff; color: #3730a3; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
      /* Fuentes */
      .sources-toggle { font-size: 11px; color: #6366f1; cursor: pointer; margin-top: 5px; padding-left: 4px; user-select: none; }
      .sources-toggle:hover { text-decoration: underline; }
      .sources-list { display: none; margin-top: 6px; }
      .sources-list.open { display: block; }
      .source-item { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; font-size: 12px; }
      .source-page { font-weight: 600; color: #6366f1; margin-bottom: 3px; }
      .source-text { color: #555; line-height: 1.4; }
      .sources-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
      .source-doc-label { font-size: 11px; font-weight: 600; margin-bottom: 4px; color: #555; }
      .input-row { display: flex; gap: 8px; }
      .chat-input {
        flex: 1; padding: 10px 14px; border: 1px solid #ddd;
        border-radius: 10px; font-size: 14px; outline: none; transition: border-color .2s;
      }
      .chat-input:focus { border-color: #6366f1; }
      .chat-input:disabled { background: #f9f9f9; }
      .empty-state { text-align: center; color: #ccc; font-size: 13px; margin: auto; }
      .thinking { color: #999; font-style: italic; font-size: 13px; }
      .hidden { display: none !important; }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="card">
        <h1>PDF Chat Agent</h1>
        <p class="subtitle">Sube uno o dos PDFs y hazles preguntas. El agente responde basándose en el contenido.</p>
        <div class="tabs">
          <button class="tab active" onclick="switchMode('single')">Un documento</button>
          <button class="tab" onclick="switchMode('compare')">Comparar dos documentos</button>
        </div>
        <div id="modeSingle">
          <div class="upload-zone" id="dropZoneA" onclick="document.getElementById('fileA').click()">
            <input type="file" id="fileA" accept=".pdf" onchange="setFile('A', this.files[0])" />
            <div class="upload-text">Arrastra un PDF aquí o haz click</div>
            <div class="upload-sub">Máximo 20 MB</div>
          </div>
          <div id="statusA"></div>
          <button class="btn btn-primary" id="uploadBtnA" disabled onclick="uploadPdf('A')">Procesar PDF</button>
        </div>
        <div id="modeCompare" class="hidden">
          <div class="upload-grid">
            <div>
              <div class="upload-label">Documento A</div>
              <div class="upload-zone" onclick="document.getElementById('fileA2').click()">
                <input type="file" id="fileA2" accept=".pdf" onchange="setFile('A2', this.files[0])" />
                <div class="upload-text">Seleccionar PDF</div>
              </div>
              <div id="statusA2"></div>
              <button class="btn btn-primary" id="uploadBtnA2" disabled onclick="uploadPdf('A2')">Procesar</button>
            </div>
            <div>
              <div class="upload-label">Documento B</div>
              <div class="upload-zone" onclick="document.getElementById('fileB').click()">
                <input type="file" id="fileB" accept=".pdf" onchange="setFile('B', this.files[0])" />
                <div class="upload-text">Seleccionar PDF</div>
              </div>
              <div id="statusB"></div>
              <button class="btn btn-primary" id="uploadBtnB" disabled onclick="uploadPdf('B')">Procesar</button>
            </div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="doc-info" id="docInfo"></div>
        <div class="chat-area" id="chatArea">
          <div class="empty-state">Sube un PDF para empezar</div>
        </div>
        <div class="input-row">
          <input type="text" class="chat-input" id="questionInput"
            placeholder="Haz una pregunta sobre el documento..."
            disabled onkeydown="if(event.key==='Enter') sendQuestion()" />
          <button class="btn" id="sendBtn" disabled onclick="sendQuestion()">Enviar</button>
        </div>
      </div>
    </div>

    <script>
      let mode = 'single';
      let sessions = { A: null, A2: null, B: null };
      let selectedFiles = { A: null, A2: null, B: null };
      let chatHistory = [];

      marked.setOptions({ breaks: true, gfm: true });

      function switchMode(newMode) {
        mode = newMode;
        document.querySelectorAll('.tab').forEach((t, i) => {
          t.classList.toggle('active', (i === 0 && newMode === 'single') || (i === 1 && newMode === 'compare'));
        });
        document.getElementById('modeSingle').classList.toggle('hidden', newMode !== 'single');
        document.getElementById('modeCompare').classList.toggle('hidden', newMode !== 'compare');
        resetChat();
      }

      function resetChat() {
        chatHistory = [];
        document.getElementById('chatArea').innerHTML = '<div class="empty-state">Sube un PDF para empezar</div>';
        document.getElementById('questionInput').disabled = true;
        document.getElementById('sendBtn').disabled = true;
        document.getElementById('docInfo').style.display = 'none';
      }

      function setFile(key, file) {
        if (!file) return;
        selectedFiles[key] = file;
        document.getElementById('uploadBtn' + key).disabled = false;
        document.getElementById('status' + key).innerHTML =
          `<span class="badge badge-ready">📎 ${file.name} (${(file.size/1024/1024).toFixed(1)} MB)</span>`;
      }

      async function uploadPdf(key) {
        const file = selectedFiles[key];
        if (!file) return;
        document.getElementById('uploadBtn' + key).disabled = true;
        document.getElementById('status' + key).innerHTML = '<span class="badge badge-processing">⏳ Procesando...</span>';
        const formData = new FormData();
        formData.append('file', file);
        try {
          const res = await fetch('/rag-agent/upload', { method: 'POST', body: formData });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Error');
          sessions[key] = data.session_id;
          document.getElementById('status' + key).innerHTML =
            `<span class="badge badge-ready">✓ ${data.pages} págs, ${data.chunks} fragmentos</span>`;
          checkReadyToChat();
        } catch (err) {
          document.getElementById('status' + key).innerHTML = `<span class="badge badge-error">✗ ${err.message}</span>`;
          document.getElementById('uploadBtn' + key).disabled = false;
        }
      }

      function checkReadyToChat() {
        let ready = false, infoText = '';
        if (mode === 'single' && sessions.A) {
          ready = true; infoText = `Documento activo: ${selectedFiles.A.name}`;
        } else if (mode === 'compare' && sessions.A2 && sessions.B) {
          ready = true; infoText = `Comparando: ${selectedFiles.A2.name} vs ${selectedFiles.B.name}`;
        }
        if (ready) {
          chatHistory = [];
          document.getElementById('questionInput').disabled = false;
          document.getElementById('sendBtn').disabled = false;
          document.getElementById('chatArea').innerHTML = '';
          document.getElementById('docInfo').style.display = 'block';
          document.getElementById('docInfo').textContent = infoText;
          addBotMessage('¡Listo! Puedes hacerme preguntas sobre el documento.', [], null);
        }
      }

      async function sendQuestion() {
        const input = document.getElementById('questionInput');
        const question = input.value.trim();
        if (!question) return;
        input.value = '';
        input.disabled = true;
        document.getElementById('sendBtn').disabled = true;
        addUserMessage(question);
        const thinkingId = addThinking();
        try {
          let res, data;
          if (mode === 'single') {
            res = await fetch('/rag-agent/chat', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ session_id: sessions.A, question, chat_history: chatHistory })
            });
            data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error');
            removeThinking(thinkingId);
            addBotMessage(data.answer, data.sources, null);
          } else {
            res = await fetch('/rag-agent/compare', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ session_id_a: sessions.A2, session_id_b: sessions.B, question, chat_history: chatHistory })
            });
            data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error');
            removeThinking(thinkingId);
            addBotMessage(data.answer, data.sources_a, data.sources_b);
          }
          chatHistory.push({ role: 'user', content: question });
          chatHistory.push({ role: 'assistant', content: data.answer });
        } catch (err) {
          removeThinking(thinkingId);
          addBotMessage('Error: ' + err.message, [], null);
        } finally {
          input.disabled = false;
          document.getElementById('sendBtn').disabled = false;
          input.focus();
        }
      }

      function addUserMessage(text) {
        const chatArea = document.getElementById('chatArea');
        const div = document.createElement('div');
        div.className = 'msg-user';
        div.innerHTML = `<div class="msg-bubble">${esc(text)}</div>`;
        chatArea.appendChild(div);
        chatArea.scrollTop = chatArea.scrollHeight;
      }

      function addBotMessage(text, sourcesA, sourcesB) {
        const chatArea = document.getElementById('chatArea');
        const id = 'src-' + Date.now();
        const rawRenderedText = typeof marked !== 'undefined' ? marked.parse(text) : esc(text);
        const renderedText = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(rawRenderedText) : esc(text);
        let sourcesHtml = '';
        if (sourcesA && sourcesA.length) {
          if (sourcesB && sourcesB.length) {
            sourcesHtml = `
              <div class="sources-toggle" onclick="toggleSources('${id}')">Ver fuentes (A y B)</div>
              <div class="sources-list" id="${id}">
                <div class="sources-compare">
                  <div><div class="source-doc-label">Documento A</div>${sourcesA.map(s => sourceItem(s)).join('')}</div>
                  <div><div class="source-doc-label">Documento B</div>${sourcesB.map(s => sourceItem(s)).join('')}</div>
                </div>
              </div>`;
          } else {
            sourcesHtml = `
              <div class="sources-toggle" onclick="toggleSources('${id}')">Ver fuentes (${sourcesA.length})</div>
              <div class="sources-list" id="${id}">${sourcesA.map(s => sourceItem(s)).join('')}</div>`;
          }
        }
        const div = document.createElement('div');
        div.className = 'msg-bot';
        div.innerHTML = `<div class="msg-bubble markdown">${renderedText}</div>${sourcesHtml}`;
        chatArea.appendChild(div);
        chatArea.scrollTop = chatArea.scrollHeight;
      }

      function sourceItem(s) {
        return `<div class="source-item"><div class="source-page">Página ${s.page}</div><div class="source-text">${esc(s.content)}</div></div>`;
      }

      function toggleSources(id) {
        const el = document.getElementById(id);
        el.classList.toggle('open');
        const toggle = el.previousElementSibling;
        const isOpen = el.classList.contains('open');
        toggle.textContent = isOpen ? 'Ocultar fuentes'
          : (el.querySelector('.sources-compare') ? 'Ver fuentes (A y B)' : `Ver fuentes (${el.querySelectorAll('.source-item').length})`);
      }

      function addThinking() {
        const id = 'thinking-' + Date.now();
        const chatArea = document.getElementById('chatArea');
        const div = document.createElement('div');
        div.id = id; div.className = 'msg-bot';
        div.innerHTML = '<div class="msg-bubble thinking">Buscando en el documento...</div>';
        chatArea.appendChild(div);
        chatArea.scrollTop = chatArea.scrollHeight;
        return id;
      }

      function removeThinking(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
      }

      function esc(text) {
        return String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      }
    </script>
  </body>
</html>"""
