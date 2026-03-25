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
        <pre id="tenantsOut" style="display:none">(not loaded)</pre>
        <div id="tenantCards" class="tenant-list"></div>
      </div>

      <div class="card">
        <h2>Tenant details</h2>
        <div class="row">
          <input id="tenantId" style="width:260px" placeholder="tenant_id" />
          <button id="loadAnalytics">Load analytics</button>
          <button id="loadSessions">Load sessions</button>
          <button id="loadLeads">Load leads</button>
        </div>
        <h3>Analytics</h3>
        <pre id="analyticsOut">(not loaded)</pre>
        <h3>Sessions</h3>
        <pre id="sessionsOut" style="display:none">(not loaded)</pre>

        <h3>Leads</h3>
        <div id="leadsOut" class="leads"></div>
        <h3>Events</h3>
        <pre id="eventsOut">(not loaded)</pre>
        <h3>Knowledge</h3>
        <pre id="knowledgeOut">(not loaded)</pre>
      </div>
    </div>

    <script>
  document.addEventListener("DOMContentLoaded", function () {
    const baseUrlEl = document.getElementById("baseUrl");
    const adminTokenEl = document.getElementById("adminToken");
    const tenantIdEl = document.getElementById("tenantId");

    const tenantsOut = document.getElementById("tenantsOut");
    const tenantCards = document.getElementById("tenantCards");
    const analyticsOut = document.getElementById("analyticsOut");
    const sessionsOut = document.getElementById("sessionsOut");
    const leadsOut = document.getElementById("leadsOut");

    const loadTenantsBtn = document.getElementById("loadTenants");
    const loadAnalyticsBtn = document.getElementById("loadAnalytics");
    const loadSessionsBtn = document.getElementById("loadSessions");
    const loadLeadsBtn = document.getElementById("loadLeads");

    baseUrlEl.value = window.location.origin;

    function fmtTs(ts) {
      if (!ts) return "-";
      try {
        return new Date(ts * 1000).toLocaleString();
      } catch (e) {
        return String(ts);
      }
    }

    async function apiGet(path) {
      const base = (baseUrlEl.value || "").replace(/\/+$/, "");
      const token = (adminTokenEl.value || "").trim();

      const res = await fetch(base + path, {
        method: "GET",
        headers: {
          "X-Admin-Token": token
        }
      });

      const text = await res.text();

      if (!res.ok) {
        throw new Error(text || ("HTTP " + res.status));
      }

      try {
        return JSON.parse(text);
      } catch (e) {
        return text;
      }
    }

    async function apiPost(path) {
      const base = (baseUrlEl.value || "").replace(/\/+$/, "");
      const token = (adminTokenEl.value || "").trim();

      const res = await fetch(base + path, {
        method: "POST",
        headers: {
          "X-Admin-Token": token
        }
      });

      const text = await res.text();

      if (!res.ok) {
        throw new Error(text || ("HTTP " + res.status));
      }

      try {
        return JSON.parse(text);
      } catch (e) {
        return text;
      }
    }

    function renderLeads(data) {
      leadsOut.innerHTML = "";

      const leads = (data && data.leads) || [];
      if (!leads.length) {
        leadsOut.innerHTML = "<div class='muted'>No leads found.</div>";
        return;
      }

      for (const lead of leads) {
        const card = document.createElement("div");
        card.className = "lead-card";

        card.innerHTML = `
          <div class="lead-head">
            <div class="lead-title">Lead #${lead.id}</div>
            <div class="lead-created">${fmtTs(lead.created_at)}</div>
          </div>
          <div class="lead-line lead-email"><strong>Email:</strong> ${lead.email || "-"}</div>
          <div class="lead-line lead-topic"><strong>Topic:</strong> ${lead.topic || "-"}</div>
          <div class="lead-summary">${lead.summary || "-"}</div>
        `;

        leadsOut.appendChild(card);
      }
    }

    async function loadAnalyticsForTenant(tenantId) {
      const data = await apiGet("/scaffold-agent/admin/analytics/" + encodeURIComponent(tenantId));
      analyticsOut.textContent = JSON.stringify(data, null, 2);
    }

    async function loadSessionsForTenant(tenantId) {
      const data = await apiGet("/scaffold-agent/admin/sessions/" + encodeURIComponent(tenantId));
      sessionsOut.textContent = JSON.stringify(data, null, 2);
    }

    async function loadLeadsForTenant(tenantId) {
      const data = await apiGet("/scaffold-agent/admin/leads/" + encodeURIComponent(tenantId));
      renderLeads(data);
    }
    
    async function loadEventsForTenant(tenantId) {
      const data = await apiGet("/scaffold-agent/admin/events/" + encodeURIComponent(tenantId));
      const out = document.getElementById("eventsOut");
      out.textContent = JSON.stringify(data, null, 2);
    }
    
    async function loadKnowledgeForTenant(tenantId) {
    const data = await apiGet("/scaffold-agent/admin/knowledge/" + encodeURIComponent(tenantId));
    const out = document.getElementById("knowledgeOut");
    out.textContent = JSON.stringify(data, null, 2);
    }

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

        const allowed = (tenant.allowed_origins || []).join(", ") || "-";
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
            <button data-action="use" data-tenant="${tenant.tenant_id}">Use</button>
            <button data-action="analytics" data-tenant="${tenant.tenant_id}">Analytics</button>
            <button data-action="sessions" data-tenant="${tenant.tenant_id}">Sessions</button>
            <button data-action="leads" data-tenant="${tenant.tenant_id}">Leads</button>
            <button data-action="events" data-tenant="${tenant.tenant_id}">Events</button>
            <button data-action="knowledge" data-tenant="${tenant.tenant_id}">Knowledge</button>
            <button data-action="rotate" data-tenant="${tenant.tenant_id}">Rotate token</button>
            <button data-action="revoke" data-tenant="${tenant.tenant_id}">Revoke token</button>
          </div>
        `;

        tenantCards.appendChild(card);
      }

      tenantCards.querySelectorAll("button[data-action]").forEach((btn) => {
        btn.addEventListener("click", async function () {
          const tenantId = btn.getAttribute("data-tenant");
          const action = btn.getAttribute("data-action");
          tenantIdEl.value = tenantId;

          try {
            if (action === "use") {
              return;
            }

            if (action === "analytics") {
              await loadAnalyticsForTenant(tenantId);
              return;
            }

            if (action === "sessions") {
              await loadSessionsForTenant(tenantId);
              return;
            }

            if (action === "leads") {
              await loadLeadsForTenant(tenantId);
              return;
            }
            
            if (action === "events") {
              await loadEventsForTenant(tenantId);
              return;
            }
            
            if (action === "knowledge") {
              await loadKnowledgeForTenant(tenantId);
              return;
            }

            if (action === "rotate") {
              const data = await apiPost("/scaffold-agent/admin/tenants/" + encodeURIComponent(tenantId) + "/rotate-token");
              alert("New widget token for " + tenantId + ":\n\n" + data.new_widget_token);

              const refreshed = await apiGet("/scaffold-agent/admin/tenants");
              tenantsOut.textContent = JSON.stringify(refreshed, null, 2);
              renderTenants(refreshed);
              return;
            }

            if (action === "revoke") {
              await apiPost("/scaffold-agent/admin/tenants/" + encodeURIComponent(tenantId) + "/revoke-token");
              alert("Token revoked for " + tenantId);

              const refreshed = await apiGet("/scaffold-agent/admin/tenants");
              tenantsOut.textContent = JSON.stringify(refreshed, null, 2);
              renderTenants(refreshed);
              return;
            }
          } catch (e) {
            console.error(e);
            alert(String(e));
          }
        });
      });
    }

    if (loadTenantsBtn) {
      loadTenantsBtn.addEventListener("click", async function () {
        try {
          tenantsOut.textContent = "Loading...";
          const data = await apiGet("/scaffold-agent/admin/tenants");
          tenantsOut.textContent = JSON.stringify(data, null, 2);
          renderTenants(data);
        } catch (e) {
          console.error(e);
          tenantsOut.textContent = String(e);
          tenantCards.innerHTML = "";
          alert("Load tenants failed: " + String(e));
        }
      });
    }

    if (loadAnalyticsBtn) {
      loadAnalyticsBtn.addEventListener("click", async function () {
        try {
          const tenantId = (tenantIdEl.value || "").trim();
          await loadAnalyticsForTenant(tenantId);
        } catch (e) {
          console.error(e);
          analyticsOut.textContent = String(e);
        }
      });
    }

    if (loadSessionsBtn) {
      loadSessionsBtn.addEventListener("click", async function () {
        try {
          const tenantId = (tenantIdEl.value || "").trim();
          await loadSessionsForTenant(tenantId);
        } catch (e) {
          console.error(e);
          sessionsOut.textContent = String(e);
        }
      });
    }

    if (loadLeadsBtn) {
      loadLeadsBtn.addEventListener("click", async function () {
        try {
          const tenantId = (tenantIdEl.value || "").trim();
          await loadLeadsForTenant(tenantId);
        } catch (e) {
          console.error(e);
          leadsOut.innerHTML = String(e);
        }
      });
    }

    console.log("Scaffold admin page loaded");
  });
</script>
  </body>
</html>
"""
