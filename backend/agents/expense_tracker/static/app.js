// app.js — Expense Tracker PWA (vanilla JS, sin build step, como el resto del repo)
(() => {
  const API = "/expense-tracker";
  const TOKEN_KEY = "expense_tracker_token";
  const THEME_KEY = "expense_tracker_theme";
  const CATEGORY_ICONS = {
    comida: "icon-food",
    transporte: "icon-transport",
    suscripciones: "icon-repeat",
    ocio: "icon-play",
    salud: "icon-cross",
    hogar: "icon-home",
    otros: "icon-box",
  };

  const state = {
    granularity: "month",
    date: new Date().toISOString().slice(0, 10),
    expenses: [],
    reviewQueue: [],
    currentDetailId: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const el = {
    granularitySwitch: $("#granularity-switch"),
    totalAmount: $("#total-amount"),
    totalMeta: $("#total-meta"),
    expenseList: $("#expense-list"),
    reviewList: $("#review-list"),
    reviewBadge: $("#review-badge"),
    fabAdd: $("#fab-add"),
    viewReview: $("#view-review"),
    viewDetail: $("#view-detail"),
    viewAdd: $("#view-add"),
    viewLock: $("#view-lock"),
    lockToken: $("#lock-token"),
    lockSave: $("#lock-save"),
    lockError: $("#lock-error"),
    themeToggle: $("#theme-toggle"),
    themeToggleIcon: $("#theme-toggle-icon"),
    granularityThumb: $("#granularity-thumb"),
    quickReview: $("#quick-review"),
    quickReviewBadge: $("#quick-review-badge"),
  };

  // ── Tema claro/oscuro manual ──────────────────────────────────────────
  //
  // Independiente de prefers-color-scheme del sistema: una vez el usuario
  // elige, se guarda en localStorage y gana siempre (ver app.css, los
  // tokens bajo :root[data-theme="dark"] pisan a los de la media query).

  function effectiveTheme() {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(theme) {
    if (theme) {
      document.documentElement.dataset.theme = theme;
    } else {
      delete document.documentElement.dataset.theme;
    }
    // El icono muestra la acción (a qué modo se pasaría al tocar), no el
    // estado actual — convención habitual de botón de toggle.
    const current = theme || effectiveTheme();
    const nextIcon = current === "dark" ? "#icon-sun" : "#icon-moon";
    el.themeToggleIcon.querySelector("use").setAttribute("href", nextIcon);
  }

  applyTheme(localStorage.getItem(THEME_KEY));

  el.themeToggle.addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });

  // ── Clave de acceso ──────────────────────────────────────────────────
  //
  // Los endpoints de lectura/edición requieren Authorization: Bearer
  // <token> (ver security.py::verify_app_token). Aquí solo hay un humano
  // tecleando en el momento (a diferencia del webhook de Atajos), así que
  // basta pedir la clave una vez y guardarla en localStorage.

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function authHeaders() {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  function showLock() {
    el.viewLock.hidden = false;
    el.viewLock.classList.add("open");
  }

  function hideLock() {
    el.viewLock.classList.remove("open");
    el.viewLock.hidden = true;
  }

  // Envoltorio de fetch para todas las llamadas autenticadas: si el token
  // guardado ya no es válido (rotado en el servidor), lo borra y vuelve a
  // pedir la clave en vez de dejar la PWA en un estado roto silenciosamente.
  async function authFetch(url, options = {}) {
    const res = await fetch(url, {
      ...options,
      headers: { ...(options.headers || {}), ...authHeaders() },
    });
    if (res.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      showLock();
      throw new Error("unauthorized");
    }
    return res;
  }

  async function attemptLogin() {
    const token = el.lockToken.value.trim();
    if (!token) return;
    el.lockError.hidden = true;
    localStorage.setItem(TOKEN_KEY, token);

    const res = await fetch(`${API}/expenses/review`, {
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => null);

    if (!res || res.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      el.lockError.hidden = false;
      return;
    }

    hideLock();
    loadExpenses();
    loadReviewQueue();
  }

  el.lockSave.addEventListener("click", attemptLogin);
  el.lockToken.addEventListener("keydown", (e) => {
    if (e.key === "Enter") attemptLogin();
  });

  // ── Formateo ─────────────────────────────────────────────────────────

  const eur = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });

  function formatAmount(value) {
    if (value === null || value === undefined) return "—";
    return eur.format(value);
  }

  function dayLabel(dateStr) {
    const d = new Date(dateStr);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    const sameDay = (a, b) =>
      a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    if (sameDay(d, today)) return "Hoy";
    if (sameDay(d, yesterday)) return "Ayer";
    return d.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
  }

  // ── Carga de datos ───────────────────────────────────────────────────

  async function loadExpenses() {
    el.totalMeta.textContent = "Cargando…";
    const res = await authFetch(`${API}/expenses?granularity=${state.granularity}&date=${state.date}`);
    const data = await res.json();
    state.expenses = data.expenses || [];
    el.totalAmount.textContent = formatAmount(data.total);
    el.totalMeta.textContent = `${data.count} transacción${data.count === 1 ? "" : "es"}`;
    renderExpenseList();
  }

  async function loadReviewQueue() {
    const res = await authFetch(`${API}/expenses/review`);
    state.reviewQueue = await res.json();
    const count = state.reviewQueue.length;
    el.reviewBadge.hidden = count === 0;
    el.reviewBadge.textContent = count;
    el.quickReviewBadge.hidden = count === 0;
    el.quickReviewBadge.textContent = count;
    renderReviewList();
  }

  // ── Render ───────────────────────────────────────────────────────────

  function renderExpenseList() {
    if (state.expenses.length === 0) {
      el.expenseList.innerHTML = `<div class="empty-state">Sin gastos en este periodo.</div>`;
      return;
    }

    const groups = new Map();
    for (const e of state.expenses) {
      const key = e.occurred_at.slice(0, 10);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(e);
    }

    let html = "";
    for (const [dateKey, items] of groups) {
      html += `<div class="day-group"><div class="day-label">${dayLabel(dateKey)}</div>`;
      for (const e of items) {
        html += expenseRowHtml(e);
      }
      html += `</div>`;
    }
    el.expenseList.innerHTML = html;

    el.expenseList.querySelectorAll("[data-expense-id]").forEach((row) => {
      row.addEventListener("click", () => openDetail(Number(row.dataset.expenseId)));
    });
  }

  function expenseRowHtml(e) {
    const icon = CATEGORY_ICONS[e.category] || "icon-box";
    return `
      <div class="expense-row" data-expense-id="${e.id}">
        <div class="expense-icon"><svg class="icon"><use href="#${icon}" /></svg></div>
        <div class="expense-info">
          <div class="expense-merchant">${escapeHtml(e.merchant || "Sin identificar")}</div>
          <div class="expense-category">${e.category || "Sin categorizar"}</div>
        </div>
        ${e.needs_review ? '<span class="needs-review-dot"></span>' : ""}
        <div class="expense-amount">${formatAmount(e.amount)}</div>
      </div>`;
  }

  function renderReviewList() {
    if (state.reviewQueue.length === 0) {
      el.reviewList.innerHTML = `<div class="empty-state">Nada pendiente de revisión.</div>`;
      return;
    }
    el.reviewList.innerHTML = state.reviewQueue
      .map(
        (e) => `
      <div class="field-group" data-review-id="${e.id}">
        <div class="field-row">
          <span class="field-label">${escapeHtml(e.merchant || "Sin identificar")}</span>
          <span>${formatAmount(e.amount)}</span>
        </div>
        <div class="field-row">
          <select class="review-category" data-review-id="${e.id}">
            <option value="">Elegir categoría…</option>
            ${Object.keys(CATEGORY_ICONS)
              .map((c) => `<option value="${c}" ${e.category === c ? "selected" : ""}>${c}</option>`)
              .join("")}
          </select>
        </div>
        <div class="review-actions" style="padding: 10px 14px 14px">
          <button class="confirm" data-confirm-id="${e.id}">Confirmar</button>
          <button data-open-id="${e.id}">Ver detalle</button>
        </div>
      </div>`
      )
      .join("");

    el.reviewList.querySelectorAll("[data-confirm-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.confirmId);
        const select = el.reviewList.querySelector(`.review-category[data-review-id="${id}"]`);
        const category = select.value || undefined;
        await authFetch(`${API}/expenses/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, needs_review: false }),
        });
        await Promise.all([loadReviewQueue(), loadExpenses()]);
      });
    });

    el.reviewList.querySelectorAll("[data-open-id]").forEach((btn) => {
      btn.addEventListener("click", () => openDetail(Number(btn.dataset.openId)));
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Selector día / mes / año ─────────────────────────────────────────

  const granularityButtons = Array.from(el.granularitySwitch.querySelectorAll("button[data-granularity]"));

  el.granularitySwitch.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-granularity]");
    if (!btn) return;
    granularityButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    el.granularityThumb.style.transform = `translateX(${granularityButtons.indexOf(btn) * 100}%)`;
    state.granularity = btn.dataset.granularity;
    loadExpenses();
  });

  // ── Detalle de gasto ─────────────────────────────────────────────────

  async function openDetail(id) {
    const res = await authFetch(`${API}/expenses/${id}`);
    if (!res.ok) return;
    const e = await res.json();
    state.currentDetailId = id;

    $("#detail-merchant").value = e.merchant || "";
    $("#detail-amount").value = e.amount ?? "";
    $("#detail-category").value = e.category || "";
    $("#detail-source").textContent = e.merged_source ? `${e.source} + ${e.merged_source}` : e.source;
    $("#detail-date").textContent = new Date(e.occurred_at).toLocaleString("es-ES");
    $("#detail-review-row").hidden = !e.needs_review;
    el.viewDetail.classList.toggle("sheet-warning", !!e.needs_review);

    const rawGroup = $("#detail-raw-group");
    if (e.raw_text) {
      rawGroup.hidden = false;
      $("#detail-raw-text").textContent = e.raw_text;
    } else {
      rawGroup.hidden = true;
    }

    openSheet(el.viewDetail);
  }

  $("#detail-save").addEventListener("click", async () => {
    if (state.currentDetailId === null) return;
    await authFetch(`${API}/expenses/${state.currentDetailId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merchant: $("#detail-merchant").value || undefined,
        amount: $("#detail-amount").value ? Number($("#detail-amount").value) : undefined,
        category: $("#detail-category").value || undefined,
      }),
    });
    closeSheet(el.viewDetail);
    await Promise.all([loadExpenses(), loadReviewQueue()]);
  });

  // ── Alta manual ──────────────────────────────────────────────────────

  el.fabAdd.addEventListener("click", () => {
    $("#add-merchant").value = "";
    $("#add-amount").value = "";
    $("#add-category").value = "";
    $("#add-date").value = new Date().toISOString().slice(0, 16);
    openSheet(el.viewAdd);
  });

  $("#add-save").addEventListener("click", async () => {
    const merchant = $("#add-merchant").value.trim();
    const amount = Number($("#add-amount").value);
    if (!merchant || !amount) return;
    await authFetch(`${API}/expenses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merchant,
        amount,
        currency: "EUR",
        occurred_at: new Date($("#add-date").value || Date.now()).toISOString(),
        category: $("#add-category").value || undefined,
      }),
    });
    closeSheet(el.viewAdd);
    await loadExpenses();
  });

  // ── Tabs ─────────────────────────────────────────────────────────────

  function openReview() {
    loadReviewQueue();
    openSheet(el.viewReview);
  }

  document.querySelectorAll(".tabbar button[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.tab === "review") openReview();
    });
  });

  el.quickReview.addEventListener("click", openReview);

  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = { review: el.viewReview, detail: el.viewDetail, add: el.viewAdd }[btn.dataset.close];
      closeSheet(target);
    });
  });

  // ── Apertura/cierre de sheets + swipe-to-close con momentum ─────────
  //
  // Sigue apple-design: la sheet se mueve 1:1 con el dedo desde el
  // pointerdown (no solo al soltar), y al soltar se decide cerrar o
  // volver a su sitio según la VELOCIDAD del gesto, no solo la posición
  // final — igual que un swipe-back nativo de iOS.

  function openSheet(node) {
    node.style.transform = "";
    node.classList.add("open");
  }

  function closeSheet(node) {
    node.classList.remove("open");
    node.style.transform = "";
  }

  function attachSwipeToClose(node) {
    let startX = 0;
    let currentX = 0;
    let lastX = 0;
    let lastT = 0;
    let velocity = 0;
    let dragging = false;
    const width = () => node.getBoundingClientRect().width;

    node.addEventListener("pointerdown", (e) => {
      if (!node.classList.contains("open")) return;
      // Solo iniciamos el gesto cerca del borde izquierdo, como un
      // swipe-back de iOS — evita robar taps en el resto del contenido.
      if (e.clientX > 40) return;
      startX = e.clientX;
      lastX = e.clientX;
      lastT = performance.now();
      dragging = true;
      node.classList.add("dragging");
      node.setPointerCapture(e.pointerId);
    });

    node.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      currentX = e.clientX;
      const now = performance.now();
      const dt = now - lastT;
      if (dt > 0) velocity = ((e.clientX - lastX) / dt) * 1000; // px/s
      lastX = e.clientX;
      lastT = now;

      const delta = Math.max(0, currentX - startX);
      node.style.transform = `translateX(${delta}px)`;
    });

    function finish(e) {
      if (!dragging) return;
      dragging = false;
      node.classList.remove("dragging");

      const delta = Math.max(0, lastX - startX);
      const projected = delta + velocity * 0.15; // proyección simple de hacia dónde va el gesto

      if (projected > width() * 0.4 || velocity > 500) {
        node.style.transform = `translateX(${width()}px)`;
        setTimeout(() => closeSheet(node), 200);
      } else {
        node.style.transform = "";
      }
    }

    node.addEventListener("pointerup", finish);
    node.addEventListener("pointercancel", finish);
  }

  [el.viewDetail, el.viewReview, el.viewAdd].forEach(attachSwipeToClose);

  // ── Init ─────────────────────────────────────────────────────────────

  const initialGranularityIndex = granularityButtons.findIndex((b) => b.classList.contains("active"));
  if (initialGranularityIndex > 0) {
    el.granularityThumb.style.transition = "none";
    el.granularityThumb.style.transform = `translateX(${initialGranularityIndex * 100}%)`;
    requestAnimationFrame(() => {
      el.granularityThumb.style.transition = "";
    });
  }

  if (getToken()) {
    loadExpenses();
    loadReviewQueue();
  } else {
    showLock();
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register(`${API}/service-worker.js`, { scope: `${API}/` }).catch(() => {});
  }
})();
