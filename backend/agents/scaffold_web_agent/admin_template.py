from __future__ import annotations


def admin_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Web Lead Agent Admin</title>
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
        transition: opacity .15s;
      }
      button:disabled {
        opacity: .45;
        cursor: not-allowed;
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
      .lead-email {
        font-weight: 600;
      }
      .lead-topic {
        font-size: 14px;
        color: #333;
      }
      .lead-created {
        font-size: 12px;
        color: #666;
      }
      .tenant-list {
        display: grid;
        gap: 12px;
      }
      .tenant-card {
        background: #f8f9fb;
        border: 1px solid #e4e7eb;
        border-radius: 12px;
        padding: 14px;
        transition: border-color .2s;
      }
      .tenant-card.active {
        border-color: #6366f1;
        box-shadow: 0 0 0 3px rgba(99,102,241,.15);
      }
      .tenant-head {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }
      .tenant-name {
        font-weight: 700;
      }
      .tenant-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 10px;
      }
      .tenant-actions button {
        background: #222;
        color: white;
        border: 0;
        border-radius: 8px;
        padding: 8px 10px;
        cursor: pointer;
        font-size: 13px;
      }
      .tenant-actions button[data-action="use"] {
        background: #6366f1;
      }
      .tenant-actions button[data-action="rotate"] {
        background: #d97706;
      }
      .tenant-actions button[data-action="revoke"] {
        background: #dc2626;
      }

      /* ── Detail panel (inline, below each tenant card) ── */
      .detail-panel {
        display: none;
        margin-top: 12px;
        border-top: 1px solid #e4e7eb;
        padding-top: 12px;
      }
      .detail-panel.open {
        display: block;
      }
      .detail-panel h4 {
        margin: 0 0 8px;
        font-size: 14px;
        color: #555;
        text-transform: uppercase;
        letter-spacing: .05em;
      }
      .detail-panel pre {
        margin: 0;
        font-size: 13px;
      }
      .detail-panel .leads {
        margin: 0;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h1>Web Lead Agent Admin</h1>
        <div class="row">
          <input id="baseUrl" style="width:320px" placeholder="Base URL" />
          <input id="adminToken" style="width:320px" placeholder="Admin token" />
          <button id="loadTenants">Load tenants</button>
        </div>
        <div class="muted">Use this page to inspect tenants, analytics, and recent sessions.</div>
      </div>

      <div class="card">
        <h2>Tenants</h2>
        <div id="tenantCards" class="tenant-list"></div>
      </div>
    </div>

    <script>
  document.addEventListener("DOMContentLoaded", function () {
    const baseUrlEl    = document.getElementById("baseUrl");
    const adminTokenEl = document.getElementById("adminToken");
    const tenantCards  = document.getElementById("tenantCards");
    const loadTenantsBtn = document.getElementById("loadTenants");

    baseUrlEl.value = window.location.origin;

    // ── helpers ──────────────────────────────────────────────────────────

    function fmtTs(ts) {
      if (!ts) return "-";
      try { return new Date(ts * 1000).toLocaleString(); }
      catch (e) { return String(ts); }
    }

    async function apiGet(path) {
      const base  = (baseUrlEl.value || "").replace(/\/+$/, "");
      const token = (adminTokenEl.value || "").trim();
      const res   = await fetch(base + path, {
        method: "GET",
        headers: { "X-Admin-Token": token },
      });
      const text = await res.text();
      if (!res.ok) throw new Error(text || ("HTTP " + res.status));
      try { return JSON.parse(text); } catch (e) { return text; }
    }

    async function apiPost(path) {
      const base  = (baseUrlEl.value || "").replace(/\/+$/, "");
      const token = (adminTokenEl.value || "").trim();
      const res   = await fetch(base + path, {
        method: "POST",
        headers: { "X-Admin-Token": token },
      });
      const text = await res.text();
      if (!res.ok) throw new Error(text || ("HTTP " + res.status));
      try { return JSON.parse(text); } catch (e) { return text; }
    }

    // Set a button to loading state; returns restore function
    function setLoading(btn) {
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = "…";
      return () => { btn.disabled = false; btn.textContent = orig; };
    }

    // ── detail panel helpers ──────────────────────────────────────────────

    function getPanel(card) {
      return card.querySelector(".detail-panel");
    }

    function showPanel(card, title, html) {
      const panel = getPanel(card);
      panel.querySelector("h4").textContent = title;
      panel.querySelector(".panel-body").innerHTML = html;
      panel.classList.add("open");
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function buildLeadsHtml(data) {
      const leads = (data && data.leads) || [];
      if (!leads.length) return "<div class='muted'>No leads found.</div>";
      return leads.map(lead => `
        <div class="lead-card">
          <div class="lead-head">
            <div class="lead-title">Lead #${lead.id}</div>
            <div class="lead-created">${fmtTs(lead.created_at)}</div>
          </div>
          <div class="lead-line lead-email"><strong>Email:</strong> ${lead.email || "-"}</div>
          <div class="lead-line lead-topic"><strong>Topic:</strong> ${lead.topic || "-"}</div>
          <div class="lead-summary">${lead.summary || "-"}</div>
        </div>
      `).join("");
    }

    // ── render tenants ────────────────────────────────────────────────────

    function renderTenants(data) {
      tenantCards.innerHTML = "";

      const tenants = (data && data.tenants) || [];
      if (!tenants.length) {
        tenantCards.innerHTML = "<div class='muted'>No tenants found.</div>";
        return;
      }

      for (const tenant of tenants) {
        const card = document.createElement("div");
        card.className = "tenant-card";
        card.dataset.tenantId = tenant.tenant_id;

        const allowed    = (tenant.allowed_origins || []).join(", ") || "-";
        const tokenState = tenant.token_active ? "active" : "revoked";

        card.innerHTML = `
          <div class="tenant-head">
            <div class="tenant-name">${tenant.tenant_id}</div>
            <div class="muted">token: ${tokenState}</div>
          </div>
          <div class="lead-line"><strong>Agent type:</strong> ${tenant.agent_type || "-"}</div>
          <div class="lead-line"><strong>Inbox:</strong> ${tenant.inbox_email || "-"}</div>
          <div class="lead-line"><strong>Subject prefix:</strong> ${tenant.subject_prefix || "-"}</div>
          <div class="lead-line"><strong>Allowed origins:</strong> ${allowed}</div>
          <div class="tenant-actions">
            <button data-action="analytics" data-tenant="${tenant.tenant_id}">Analytics</button>
            <button data-action="sessions"  data-tenant="${tenant.tenant_id}">Sessions</button>
            <button data-action="leads"     data-tenant="${tenant.tenant_id}">Leads</button>
            <button data-action="events"    data-tenant="${tenant.tenant_id}">Events</button>
            <button data-action="knowledge" data-tenant="${tenant.tenant_id}">Knowledge</button>
            <button data-action="rotate"    data-tenant="${tenant.tenant_id}">Rotate token</button>
            <button data-action="revoke"    data-tenant="${tenant.tenant_id}">Revoke token</button>
          </div>
          <div class="detail-panel">
            <h4></h4>
            <div class="panel-body"></div>
          </div>
        `;

        tenantCards.appendChild(card);
      }
    }

    // ── event delegation (ONE listener, never breaks on re-render) ────────

    tenantCards.addEventListener("click", async function (e) {
      const btn = e.target.closest("button[data-action]");
      if (!btn) return;

      const action   = btn.dataset.action;
      const tenantId = btn.dataset.tenant;
      const card     = btn.closest(".tenant-card");

      // Mark active card
      tenantCards.querySelectorAll(".tenant-card").forEach(c => c.classList.remove("active"));
      card.classList.add("active");

      const restore = setLoading(btn);

      try {

        if (action === "analytics") {
          const data = await apiGet("/scaffold-agent/admin/analytics/" + encodeURIComponent(tenantId));
          showPanel(card, "Analytics", `<pre>${JSON.stringify(data, null, 2)}</pre>`);
        }

        else if (action === "sessions") {
          const data = await apiGet("/scaffold-agent/admin/sessions/" + encodeURIComponent(tenantId));
          showPanel(card, "Sessions", `<pre>${JSON.stringify(data, null, 2)}</pre>`);
        }

        else if (action === "leads") {
          const data = await apiGet("/scaffold-agent/admin/leads/" + encodeURIComponent(tenantId));
          showPanel(card, "Leads", `<div class="leads">${buildLeadsHtml(data)}</div>`);
        }

        else if (action === "events") {
          const data = await apiGet("/scaffold-agent/admin/events/" + encodeURIComponent(tenantId));
          showPanel(card, "Events", `<pre>${JSON.stringify(data, null, 2)}</pre>`);
        }

        else if (action === "knowledge") {
          const data = await apiGet("/scaffold-agent/admin/knowledge/" + encodeURIComponent(tenantId));
          showPanel(card, "Knowledge", `<pre>${JSON.stringify(data, null, 2)}</pre>`);
        }

        else if (action === "rotate") {
          if (!confirm("Rotate token for " + tenantId + "? The current widget token will stop working.")) {
            return;
          }
          const data = await apiPost(
            "/scaffold-agent/admin/tenants/" + encodeURIComponent(tenantId) + "/rotate-token"
          );
          showPanel(card, "New widget token", `<pre>${data.new_widget_token}</pre>`);
          // Refresh tenant list to reflect new token state
          const refreshed = await apiGet("/scaffold-agent/admin/tenants");
          renderTenants(refreshed);
        }

        else if (action === "revoke") {
          if (!confirm("Revoke token for " + tenantId + "? The widget will stop working immediately.")) {
            return;
          }
          await apiPost(
            "/scaffold-agent/admin/tenants/" + encodeURIComponent(tenantId) + "/revoke-token"
          );
          showPanel(card, "Token status", `<pre>Token revoked for ${tenantId}</pre>`);
          const refreshed = await apiGet("/scaffold-agent/admin/tenants");
          renderTenants(refreshed);
        }

      } catch (err) {
        console.error("[admin]", action, tenantId, err);
        showPanel(card, "Error", `<pre style="color:#dc2626">${String(err)}</pre>`);
      } finally {
        restore();
      }
    });

    // ── load tenants button ───────────────────────────────────────────────

    if (loadTenantsBtn) {
      loadTenantsBtn.addEventListener("click", async function () {
        const restore = setLoading(loadTenantsBtn);
        try {
          const data = await apiGet("/scaffold-agent/admin/tenants");
          renderTenants(data);
        } catch (err) {
          console.error("[admin] load tenants:", err);
          tenantCards.innerHTML = `<div class='muted' style='color:#dc2626'>${String(err)}</div>`;
        } finally {
          restore();
        }
      });
    }

    console.log("Scaffold admin page loaded");
  });
</script>
  </body>
</html>
"""
