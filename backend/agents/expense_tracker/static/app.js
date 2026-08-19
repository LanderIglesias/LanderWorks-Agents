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
    // Dinero entrando, no un gasto — reutiliza el icono de flecha ya
    // existente (mismo que el indicador "bajó" de la comparativa) en vez
    // de añadir un SVG nuevo solo para esto.
    bizum: "icon-arrow-down",
  };
  const CATEGORY_LABELS = {
    comida: "Comida",
    transporte: "Transporte",
    suscripciones: "Suscripciones",
    ocio: "Ocio",
    salud: "Salud",
    hogar: "Hogar",
    otros: "Otros",
    bizum: "Bizum",
  };
  const MONTH_LABELS = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
  ];
  // "otros" se queda fuera a propósito — cajón de sastre sin identidad de
  // color propia, ver el comentario junto a los tokens --cat-* en app.css.
  const CATEGORIES_WITH_COLOR = new Set([
    "comida",
    "transporte",
    "suscripciones",
    "ocio",
    "salud",
    "hogar",
    "bizum",
  ]);

  function categoryIconClass(category) {
    return CATEGORIES_WITH_COLOR.has(category) ? `category-icon cat-${category}` : "";
  }

  const state = {
    granularity: "month",
    date: new Date().toISOString().slice(0, 10),
    expenses: [],
    reviewQueue: [],
    currentDetailId: null,
    budgetMonth: new Date().toISOString().slice(0, 7),
    budgets: [],
    previousMonthByCategory: {},
    editingCategory: null,
    searchActive: false,
    searchParams: null,
    searchResults: [],
    searchTotal: 0,
  };
  const SEARCH_PAGE_SIZE = 50;

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
    viewBudgets: $("#view-budgets"),
    budgetsList: $("#budgets-list"),
    recurringList: $("#recurring-list"),
    budgetsMonthLabel: $("#budgets-month-label"),
    budgetsPrevMonth: $("#budgets-prev-month"),
    budgetsNextMonth: $("#budgets-next-month"),
    comparisonBadge: $("#comparison-badge"),
    comparisonIcon: $("#comparison-icon"),
    comparisonPct: $("#comparison-pct"),
    searchToggle: $("#search-toggle"),
    viewSearch: $("#view-search"),
    searchQuery: $("#search-query"),
    searchCategory: $("#search-category"),
    searchDateFrom: $("#search-date-from"),
    searchDateTo: $("#search-date-to"),
    searchAmountMin: $("#search-amount-min"),
    searchAmountMax: $("#search-amount-max"),
    searchSubmit: $("#search-submit"),
    searchError: $("#search-error"),
    normalControls: $("#normal-controls"),
    resultsBar: $("#results-bar"),
    resultsCount: $("#results-count"),
    clearSearch: $("#clear-search"),
    loadMore: $("#load-more"),
    settingsToggle: $("#settings-toggle"),
    viewSettings: $("#view-settings"),
    resetConfirmInput: $("#reset-confirm-input"),
    resetConfirmBtn: $("#reset-confirm-btn"),
    resetError: $("#reset-error"),
    resetSuccess: $("#reset-success"),
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

    // La comparativa mes a mes solo tiene sentido en la vista "Mes" — en
    // día/año no hay un "mes anterior" claro con el que compararse.
    if (state.granularity === "month") {
      const month = state.date.slice(0, 7);
      const compRes = await authFetch(`${API}/expenses/comparison?month=${month}`);
      const comparison = await compRes.json();
      renderComparisonBadge(comparison.variacion_pct);
    } else {
      el.comparisonBadge.hidden = true;
    }
  }

  // Umbral de "esto merece un aviso": subir el gasto no es automáticamente
  // malo (puede ser una compra planeada), así que solo una subida por
  // encima de este umbral se marca en ámbar — una subida moderada se
  // queda en gris neutro, sin juicio de valor.
  const COMPARISON_ALERT_THRESHOLD_PCT = 20;

  function renderComparisonBadge(variacionPct) {
    if (variacionPct === null || variacionPct === undefined) {
      el.comparisonBadge.hidden = true;
      return;
    }
    const isDown = variacionPct < 0;
    el.comparisonBadge.hidden = false;
    el.comparisonBadge.classList.toggle("down", isDown);
    el.comparisonBadge.classList.toggle("up-alert", !isDown && variacionPct > COMPARISON_ALERT_THRESHOLD_PCT);
    el.comparisonIcon.querySelector("use").setAttribute("href", isDown ? "#icon-arrow-down" : "#icon-arrow-up");
    el.comparisonPct.textContent = `${Math.abs(variacionPct).toFixed(0)}%`;
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

  // ── Búsqueda y filtros ───────────────────────────────────────────────

  function buildSearchParams(offset) {
    const params = new URLSearchParams();
    const query = el.searchQuery.value.trim();
    if (query) params.set("query", query);
    if (el.searchCategory.value) params.set("category", el.searchCategory.value);
    if (el.searchDateFrom.value) params.set("date_from", el.searchDateFrom.value);
    if (el.searchDateTo.value) params.set("date_to", el.searchDateTo.value);
    if (el.searchAmountMin.value) params.set("amount_min", el.searchAmountMin.value);
    if (el.searchAmountMax.value) params.set("amount_max", el.searchAmountMax.value);
    params.set("limit", SEARCH_PAGE_SIZE);
    params.set("offset", offset || 0);
    return params;
  }

  async function runSearch() {
    el.searchError.hidden = true;
    const params = buildSearchParams(0);
    const res = await authFetch(`${API}/expenses/search?${params.toString()}`);

    if (res.status === 422) {
      const data = await res.json();
      const message = Array.isArray(data.detail)
        ? data.detail.map((d) => d.msg).join(", ")
        : data.detail;
      el.searchError.textContent = message || "Filtros inválidos.";
      el.searchError.hidden = false;
      return;
    }

    const data = await res.json();
    state.searchActive = true;
    state.searchParams = params;
    state.searchResults = data.expenses;
    state.searchTotal = data.total;
    closeSheet(el.viewSearch);
    enterSearchMode();
  }

  async function loadMoreResults() {
    const params = new URLSearchParams(state.searchParams);
    params.set("offset", state.searchResults.length);
    const res = await authFetch(`${API}/expenses/search?${params.toString()}`);
    const data = await res.json();
    state.searchResults = state.searchResults.concat(data.expenses);
    renderSearchResults();
  }

  function enterSearchMode() {
    el.normalControls.hidden = true;
    el.resultsBar.hidden = false;
    renderSearchResults();
  }

  function exitSearchMode() {
    state.searchActive = false;
    state.searchResults = [];
    state.searchParams = null;
    el.normalControls.hidden = false;
    el.resultsBar.hidden = true;
    el.loadMore.hidden = true;
    loadExpenses();
  }

  function renderSearchResults() {
    const count = state.searchTotal;
    el.resultsCount.textContent = `${count} resultado${count === 1 ? "" : "s"}`;
    renderExpenseList(state.searchResults, "Sin resultados con estos filtros.");
    el.loadMore.hidden = state.searchResults.length >= state.searchTotal;
  }

  // Tras editar/confirmar un gasto hay que refrescar la vista que esté
  // realmente en pantalla — si no, editar un gasto mientras se ven
  // resultados de búsqueda volvería silenciosamente a la lista normal
  // (loadExpenses reemplazaría el DOM) sin restaurar normal-controls ni
  // ocultar la barra de resultados, dejando la UI inconsistente.
  async function refreshExpenseView() {
    if (state.searchActive) {
      const params = new URLSearchParams(state.searchParams);
      params.set("offset", 0);
      params.set("limit", Math.max(state.searchResults.length, SEARCH_PAGE_SIZE));
      const res = await authFetch(`${API}/expenses/search?${params.toString()}`);
      const data = await res.json();
      state.searchResults = data.expenses;
      state.searchTotal = data.total;
      renderSearchResults();
    } else {
      await loadExpenses();
    }
  }

  el.searchToggle.addEventListener("click", () => {
    el.searchError.hidden = true;
    openSheet(el.viewSearch);
  });

  el.searchSubmit.addEventListener("click", runSearch);
  el.clearSearch.addEventListener("click", exitSearchMode);
  el.loadMore.addEventListener("click", loadMoreResults);

  // ── Presupuestos ─────────────────────────────────────────────────────

  function monthLabel(monthStr) {
    const [year, month] = monthStr.split("-").map(Number);
    return `${MONTH_LABELS[month - 1]} ${year}`;
  }

  function shiftMonth(monthStr, delta) {
    const [year, month] = monthStr.split("-").map(Number);
    const d = new Date(year, month - 1 + delta, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }

  async function loadBudgets() {
    el.budgetsMonthLabel.textContent = monthLabel(state.budgetMonth);
    const [budgetsRes, comparisonRes, recurringRes] = await Promise.all([
      authFetch(`${API}/budgets?month=${state.budgetMonth}`),
      authFetch(`${API}/expenses/comparison?month=${state.budgetMonth}`),
      authFetch(`${API}/expenses/recurring`),
    ]);
    state.budgets = await budgetsRes.json();
    const comparison = await comparisonRes.json();
    state.previousMonthByCategory = Object.fromEntries(
      comparison.por_categoria.map((c) => [c.category, c.anterior])
    );
    state.editingCategory = null;
    renderBudgets();
    renderRecurring(await recurringRes.json());
  }

  function renderRecurring(items) {
    if (items.length === 0) {
      el.recurringList.innerHTML = `<div class="empty-state">Aún no hay suficiente historial para detectar recurrentes — necesitas 3 meses de datos.</div>`;
      return;
    }

    const totalEstimate = items.reduce((sum, r) => sum + r.total_monthly_estimate, 0);
    const rows = items
      .map((r) => {
        const amounts = r.occurrences.map((o) => o.amount);
        const min = Math.min(...amounts);
        const max = Math.max(...amounts);
        const amountText =
          min === max ? `${formatAmount(r.amount_avg)} cada mes` : `${formatAmount(min)} - ${formatAmount(max)}`;
        // El backend no devuelve categoría por grupo recurrente (podría
        // ni tener una única categoría consistente) — icono genérico de
        // "recurrente" con el color de suscripciones, ya que en la
        // práctica el 99% de lo detectado aquí SON suscripciones. Ver
        // spec: fallback explícitamente permitido si no aplica categoría.
        return `
          <div class="recurring-row">
            <div class="recurring-icon category-icon cat-suscripciones"><svg class="icon"><use href="#icon-repeat" /></svg></div>
            <div class="recurring-info">
              <span class="recurring-name">${escapeHtml(r.merchant_representative)}</span>
            </div>
            <span class="recurring-amount">${amountText}</span>
          </div>`;
      })
      .join("");

    el.recurringList.innerHTML = `
      ${rows}
      <div class="recurring-total">
        <span>Total mensual estimado</span>
        <span>${formatAmount(totalEstimate)}</span>
      </div>`;
  }

  function budgetBarState(spent, limitAmount) {
    if (limitAmount === null || limitAmount === undefined) return "";
    const ratio = limitAmount > 0 ? spent / limitAmount : spent > 0 ? 1 : 0;
    if (ratio > 1) return "over";
    if (ratio >= 0.8) return "warning";
    return "";
  }

  function renderBudgets() {
    el.budgetsList.innerHTML = state.budgets.map(budgetCardHtml).join("");

    el.budgetsList.querySelectorAll("[data-budget-category]").forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.closest(".budget-edit-row")) return;
        const category = card.dataset.budgetCategory;
        state.editingCategory = state.editingCategory === category ? null : category;
        renderBudgets();
        if (state.editingCategory) {
          const input = el.budgetsList.querySelector(`[data-limit-input="${category}"]`);
          input?.focus();
        }
      });
    });

    el.budgetsList.querySelectorAll("[data-save-category]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const category = btn.dataset.saveCategory;
        const input = el.budgetsList.querySelector(`[data-limit-input="${category}"]`);
        await saveBudget(category, input.value ? Number(input.value) : null);
      });
    });

    el.budgetsList.querySelectorAll("[data-clear-category]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await saveBudget(btn.dataset.clearCategory, null);
      });
    });
  }

  async function saveBudget(category, limitAmount) {
    await authFetch(`${API}/budgets/${category}?month=${state.budgetMonth}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit_amount: limitAmount }),
    });
    await loadBudgets();
  }

  function budgetCardHtml(b) {
    const icon = CATEGORY_ICONS[b.category] || "icon-box";
    const barState = budgetBarState(b.spent, b.limit_amount);
    const pct = b.limit_amount ? Math.min(100, Math.round((b.spent / b.limit_amount) * 100)) : 0;
    const metaText =
      b.limit_amount === null || b.limit_amount === undefined
        ? `${formatAmount(b.spent)} gastado, sin límite`
        : `${formatAmount(b.spent)} de ${formatAmount(b.limit_amount)}`;
    const editing = state.editingCategory === b.category;
    const previous = state.previousMonthByCategory[b.category];
    // Solo el dato de referencia, sin barra ni gráfico adicional — ver
    // spec. previous puede ser 0 (categoría sin gasto el mes pasado);
    // se muestra igual, es información real, no un hueco que ocultar.
    const comparisonText =
      previous === undefined ? "" : `<div class="budget-comparison">${formatAmount(previous)} el mes pasado</div>`;

    // Excedido en texto explícito, no solo color/tinte de la tarjeta —
    // accesibilidad para daltonismo rojo-verde (ver spec).
    const exceededText =
      barState === "over" ? `<div class="budget-exceeded">Excedido en ${formatAmount(b.spent - b.limit_amount)}</div>` : "";

    // Sin límite fijado, sin barra — una barra sin objetivo no comunica
    // nada real, ver spec.
    const barHtml =
      b.limit_amount === null || b.limit_amount === undefined
        ? ""
        : `<div class="budget-bar"><div class="budget-bar-fill ${barState}" style="transform: scaleX(${pct / 100})"></div></div>`;

    return `
      <div class="budget-card ${barState === "over" ? "over" : ""}" data-budget-category="${b.category}">
        <div class="budget-card-head">
          <div class="budget-icon ${categoryIconClass(b.category)}"><svg class="icon"><use href="#${icon}" /></svg></div>
          <div class="budget-name">${CATEGORY_LABELS[b.category] || b.category}</div>
        </div>
        ${barHtml}
        <div class="budget-meta ${barState === "over" ? "over" : ""}">${metaText}</div>
        ${exceededText}
        ${comparisonText}
        ${
          editing
            ? `<div class="budget-edit-row">
                <input
                  type="number"
                  step="0.01"
                  inputmode="decimal"
                  placeholder="Límite (€)"
                  value="${b.limit_amount ?? ""}"
                  data-limit-input="${b.category}"
                />
                <button data-save-category="${b.category}">Guardar</button>
                ${
                  b.limit_amount
                    ? `<button class="clear" data-clear-category="${b.category}">Quitar</button>`
                    : ""
                }
              </div>`
            : ""
        }
      </div>`;
  }

  el.budgetsPrevMonth.addEventListener("click", () => {
    state.budgetMonth = shiftMonth(state.budgetMonth, -1);
    loadBudgets();
  });

  el.budgetsNextMonth.addEventListener("click", () => {
    state.budgetMonth = shiftMonth(state.budgetMonth, 1);
    loadBudgets();
  });

  // ── Render ───────────────────────────────────────────────────────────

  function renderExpenseList(items, emptyText) {
    items = items || state.expenses;
    emptyText = emptyText || "Sin gastos en este periodo.";

    if (items.length === 0) {
      el.expenseList.innerHTML = `<div class="empty-state">${emptyText}</div>`;
      return;
    }

    const groups = new Map();
    for (const e of items) {
      const key = e.occurred_at.slice(0, 10);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(e);
    }

    let html = "";
    for (const [dateKey, dayItems] of groups) {
      html += `<div class="day-group"><div class="day-label">${dayLabel(dateKey)}</div>`;
      for (const e of dayItems) {
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
        <div class="expense-icon ${categoryIconClass(e.category)}"><svg class="icon"><use href="#${icon}" /></svg></div>
        <div class="expense-info">
          <div class="expense-merchant">${escapeHtml(e.merchant || "Sin identificar")}</div>
          <div class="expense-category">${e.category || "Sin categorizar"}</div>
        </div>
        ${e.needs_review ? '<span class="needs-review-dot"></span>' : ""}
        <div class="expense-amount ${e.category === "bizum" ? "positive" : ""}">${formatAmount(e.amount)}</div>
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
          <button class="reject" data-reject-id="${e.id}">Rechazar</button>
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
        await Promise.all([loadReviewQueue(), refreshExpenseView()]);
      });
    });

    el.reviewList.querySelectorAll("[data-open-id]").forEach((btn) => {
      btn.addEventListener("click", () => openDetail(Number(btn.dataset.openId)));
    });

    el.reviewList.querySelectorAll("[data-reject-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.rejectId);
        if (!confirm("¿Rechazar y eliminar este gasto? No se puede deshacer.")) return;
        await authFetch(`${API}/expenses/${id}`, { method: "DELETE" });
        await Promise.all([loadReviewQueue(), refreshExpenseView()]);
      });
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
    await Promise.all([refreshExpenseView(), loadReviewQueue()]);
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
    await refreshExpenseView();
  });

  // ── Tabs ─────────────────────────────────────────────────────────────

  function openReview() {
    loadReviewQueue();
    openSheet(el.viewReview);
  }

  function openBudgets() {
    loadBudgets();
    openSheet(el.viewBudgets);
  }

  document.querySelectorAll(".tabbar button[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.tab === "review") openReview();
      if (btn.dataset.tab === "budgets") openBudgets();
    });
  });

  el.quickReview.addEventListener("click", openReview);

  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = {
        review: el.viewReview,
        detail: el.viewDetail,
        add: el.viewAdd,
        budgets: el.viewBudgets,
        search: el.viewSearch,
        settings: el.viewSettings,
      }[btn.dataset.close];
      closeSheet(target);
    });
  });

  // ── Ajustes: reset destructivo ──────────────────────────────────────
  //
  // Fricción intencional: el botón solo se activa cuando el texto escrito
  // coincide EXACTAMENTE con "BORRAR" (no una confirmación sí/no).

  el.settingsToggle.addEventListener("click", () => {
    el.resetConfirmInput.value = "";
    el.resetConfirmBtn.disabled = true;
    el.resetError.hidden = true;
    el.resetSuccess.hidden = true;
    openSheet(el.viewSettings);
  });

  el.resetConfirmInput.addEventListener("input", () => {
    el.resetConfirmBtn.disabled = el.resetConfirmInput.value !== "BORRAR";
  });

  el.resetConfirmBtn.addEventListener("click", async () => {
    el.resetError.hidden = true;
    el.resetSuccess.hidden = true;
    const res = await authFetch(`${API}/expenses/reset-all`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: el.resetConfirmInput.value }),
    });
    if (!res.ok) {
      el.resetError.textContent = "No se ha podido completar el borrado.";
      el.resetError.hidden = false;
      return;
    }
    el.resetSuccess.hidden = false;
    el.resetConfirmInput.value = "";
    el.resetConfirmBtn.disabled = true;
    await Promise.all([refreshExpenseView(), loadReviewQueue()]);
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

  [el.viewDetail, el.viewReview, el.viewAdd, el.viewBudgets, el.viewSearch, el.viewSettings].forEach(
    attachSwipeToClose
  );

  // ── Altura real de viewport (bug de WebKit en carga en frío) ─────────
  //
  // Confirmado en dispositivo (iPhone 16 Pro, iOS 26.6.1): en la carga en
  // frío, Safari no calcula bien la altura real del viewport ni
  // safe-area-inset-bottom hasta que ocurre un recálculo de layout real
  // (desaparece al rotar y volver) — 100dvh por sí solo no basta porque
  // el bug está en el propio cálculo de WebKit, no en qué unidad CSS se
  // usa. Se fuerza el recálculo desde JS: --real-vh se escribe con
  // window.visualViewport.height (más fiable que innerHeight en iOS) y
  // #app la usa como altura en cuanto está disponible, con 100dvh como
  // valor inicial mientras tanto (ver app.css).
  function syncRealViewportHeight() {
    const height = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    document.documentElement.style.setProperty("--real-vh", `${height}px`);
  }

  syncRealViewportHeight();
  document.addEventListener("DOMContentLoaded", syncRealViewportHeight);
  window.addEventListener("pageshow", syncRealViewportHeight);
  window.addEventListener("resize", syncRealViewportHeight);
  window.addEventListener("orientationchange", syncRealViewportHeight);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", syncRealViewportHeight);
    window.visualViewport.addEventListener("scroll", syncRealViewportHeight);
  }
  // El bug de WebKit a veces necesita un tick extra después del primer
  // paint para que visualViewport.height ya sea el valor correcto — los
  // listeners de arriba no bastan si el propio primer valor que reportan
  // ya viene mal.
  setTimeout(syncRealViewportHeight, 120);

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
