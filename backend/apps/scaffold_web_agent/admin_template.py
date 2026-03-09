from __future__ import annotations


def admin_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Scaffold Admin</title>
    <style>
      body {
        margin: 0;
        padding: 24px;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        background: #f6f7f9;
        color: #111;
      }
      .wrap {
        max-width: 1100px;
        margin: 0 auto;
      }
      .card {
        background: white;
        border-radius: 14px;
        box-shadow: 0 8px 30px rgba(0,0,0,.08);
        padding: 18px;
        margin-bottom: 18px;
      }
      h1, h2 {
        margin-top: 0;
      }
      input, button, select {
        padding: 10px 12px;
        border: 1px solid #ddd;
        border-radius: 10px;
        font-size: 14px;
      }
      button {
        cursor: pointer;
        background: #111;
        color: white;
        border: 0;
      }
      .row {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-bottom: 14px;
      }
      pre {
        background: #f0f2f5;
        padding: 14px;
        border-radius: 10px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .muted {
        color: #666;
        font-size: 13px;
      }
      .leads {
        display: grid;
        gap: 12px;
      }
      .lead-card {
        background: #f8f9fb;
        border: 1px solid #e4e7eb;
        border-radius: 12px;
        padding: 14px;
      }
      .lead-head {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }
      .lead-title {
        font-weight: 700;
      }
      .lead-meta {
        font-size: 13px;
        color: #666;
      }
      .lead-line {
        font-size: 14px;
        margin: 4px 0;
      }
      .lead-summary {
        margin-top: 10px;
        padding: 10px;
        background: #eef2f6;
        border-radius: 10px;
        white-space: pre-wrap;
        font-size: 13px;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h1>Scaffold Admin</h1>
        <div class="row">
          <input id="baseUrl" style="width:320px" placeholder="Base URL" />
          <input id="adminToken" style="width:320px" placeholder="Admin token" />
          <button id="loadTenants">Load tenants</button>
        </div>
        <div class="muted">Use this page to inspect tenants, analytics, and recent sessions.</div>
      </div>

      <div class="card">
        <h2>Tenants</h2>
        <pre id="tenantsOut">(not loaded)</pre>
      </div>

      <div class="card">
        <h2>Tenant details</h2>
        <div class="row">
          <input id="tenantId" style="width:260px" placeholder="tenant_id" />
          <button id="loadAnalytics">Load analytics</button>
          <button id="loadSessions">Load sessions</button>
        </div>
        <h3>Analytics</h3>
        <pre id="analyticsOut">(not loaded)</pre>
        <h3>Sessions</h3>
        <pre id="sessionsOut" style="display:none">(not loaded)</pre>
        <div id="leadsOut" class="leads"></div>
      </div>
    </div>

    <script>
      const baseUrlEl = document.getElementById("baseUrl");
      const adminTokenEl = document.getElementById("adminToken");
      const tenantIdEl = document.getElementById("tenantId");
      const tenantsOut = document.getElementById("tenantsOut");
      const analyticsOut = document.getElementById("analyticsOut");
      const sessionsOut = document.getElementById("sessionsOut");
      const leadsOut = document.getElementById("leadsOut");

      baseUrlEl.value = window.location.origin;

      async function apiGet(path) {
        const base = baseUrlEl.value.replace(/\\/+$/, "");
        const token = adminTokenEl.value.trim();
        const res = await fetch(base + path, {
          headers: { "X-Admin-Token": token }
        });
        const text = await res.text();
        if (!res.ok) {
          throw new Error(text || ("HTTP " + res.status));
        }
        try {
          return JSON.parse(text);
        } catch {
          return text;
        }
      }
    function fmtTs(ts) {
        if (!ts) return "-";
        try {
          return new Date(ts * 1000).toLocaleString();
        } catch {
          return String(ts);
        }
      }

      function renderLeads(data) {
        leadsOut.innerHTML = "";

        const sessions = (data && data.sessions) || [];
        if (!sessions.length) {
          leadsOut.innerHTML = "<div class='muted'>No sessions found.</div>";
          return;
        }

        for (const s of sessions) {
          let parsed = {};
          try {
            parsed = JSON.parse(s.state_json || "{}");
          } catch {
            parsed = {};
          }

          const step = parsed.step || "-";
          const payload = parsed.data || {};
          const email = payload.email || "-";
          const topic = payload.topic || "-";
          const summary = payload.summary || "-";

          const card = document.createElement("div");
          card.className = "lead-card";

          card.innerHTML = `
            <div class="lead-head">
              <div class="lead-title">Session ${s.session_id}</div>
              <div class="lead-meta">${fmtTs(s.updated_at)}</div>
            </div>
            <div class="lead-line"><strong>Step:</strong> ${step}</div>
            <div class="lead-line"><strong>Email:</strong> ${email}</div>
            <div class="lead-line"><strong>Topic:</strong> ${topic}</div>
            <div class="lead-summary">${summary}</div>
          `;

          leadsOut.appendChild(card);
        }
      }
      document.getElementById("loadTenants").addEventListener("click", async () => {
        try {
          const data = await apiGet("/scaffold-agent/admin/tenants");
          tenantsOut.textContent = JSON.stringify(data, null, 2);
        } catch (e) {
          tenantsOut.textContent = String(e);
        }
      });

      document.getElementById("loadAnalytics").addEventListener("click", async () => {
        try {
          const tenantId = tenantIdEl.value.trim();
          const data = await apiGet("/scaffold-agent/admin/analytics/" + encodeURIComponent(tenantId));
          analyticsOut.textContent = JSON.stringify(data, null, 2);
        } catch (e) {
          analyticsOut.textContent = String(e);
        }
      });

      document.getElementById("loadSessions").addEventListener("click", async () => {
        try {
          const tenantId = tenantIdEl.value.trim();
          const data = await apiGet("/scaffold-agent/admin/sessions/" + encodeURIComponent(tenantId));
          sessionsOut.textContent = JSON.stringify(data, null, 2);
          renderLeads(data);
        } catch (e) {
          sessionsOut.textContent = String(e);
          leadsOut.innerHTML = "";
        }
      });
    </script>
  </body>
</html>
"""
