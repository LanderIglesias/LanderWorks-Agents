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
    calendarMonth: new Date().toISOString().slice(0, 7),
    calendarDays: [],
    calendarSelectedDate: null,
  };
  const SEARCH_PAGE_SIZE = 50;

  const $ = (sel) => document.querySelector(sel);
  const el = {
    viewMain: $("#view-main"),
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
    addCategory: $("#add-category"),
    addBizumHint: $("#add-bizum-hint"),
    viewCalendar: $("#view-calendar"),
    calendarGrid: $("#calendar-grid"),
    calendarMonthLabel: $("#calendar-month-label"),
    calendarPrevMonth: $("#calendar-prev-month"),
    calendarNextMonth: $("#calendar-next-month"),
    viewCalendarDay: $("#view-calendar-day"),
    calendarDayTitle: $("#calendar-day-title"),
    calendarDayExpenses: $("#calendar-day-expenses"),
    calendarDayNotes: $("#calendar-day-notes"),
    calendarNoteText: $("#calendar-note-text"),
    calendarNoteType: $("#calendar-note-type"),
    calendarNoteSave: $("#calendar-note-save"),
    calendarNoteError: $("#calendar-note-error"),
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
      const toggle = (e) => {
        if (e.target.closest(".budget-edit-row")) return;
        const category = card.dataset.budgetCategory;
        state.editingCategory = state.editingCategory === category ? null : category;
        renderBudgets();
        if (state.editingCategory) {
          const input = el.budgetsList.querySelector(`[data-limit-input="${category}"]`);
          input?.focus();
        }
      };
      card.addEventListener("click", toggle);
      // role="button" no da activación por teclado gratis como un
      // <button> real — .budget-card se queda como <div> a propósito
      // (ver comentario en budgetCardHtml: no puede anidar los botones
      // reales de .budget-edit-row dentro de un <button>), así que
      // Enter/Espacio hay que cablearlos a mano.
      card.addEventListener("keydown", (e) => {
        if (e.target.closest(".budget-edit-row")) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggle(e);
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
    const hasNoLimit = b.limit_amount === null || b.limit_amount === undefined;
    const metaText = hasNoLimit
      ? `${formatAmount(b.spent)} gastado, sin límite`
      : `${formatAmount(b.spent)} de ${formatAmount(b.limit_amount)}`;
    const editing = state.editingCategory === b.category;
    // Antes no había ninguna pista de que la tarjeta se pudiera tocar
    // para poner un límite — el toggle ya existía (ver el listener de
    // click más abajo), pero nada en pantalla lo indicaba.
    const setLimitHint =
      hasNoLimit && !editing ? `<div class="budget-set-limit-hint">Toca para poner un límite</div>` : "";
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

    // .budget-card sigue siendo un <div>, no un <button>: cuando está en
    // modo edición contiene botones reales (Guardar/Quitar) y anidar
    // <button> dentro de <button> es HTML inválido. role="button" +
    // tabindex + el keydown de más abajo le dan el mismo comportamiento
    // por teclado sin ese problema.
    return `
      <div
        class="budget-card ${barState === "over" ? "over" : ""}"
        data-budget-category="${b.category}"
        role="button"
        tabindex="0"
        aria-expanded="${editing}"
        aria-label="${CATEGORY_LABELS[b.category] || b.category}, ${metaText}${hasNoLimit ? ", toca para poner un límite" : ""}"
      >
        <div class="budget-card-head">
          <div class="budget-icon ${categoryIconClass(b.category)}"><svg class="icon" aria-hidden="true" focusable="false"><use href="#${icon}" /></svg></div>
          <div class="budget-name">${CATEGORY_LABELS[b.category] || b.category}</div>
        </div>
        ${barHtml}
        <div class="budget-meta ${barState === "over" ? "over" : ""}">${metaText}</div>
        ${exceededText}
        ${comparisonText}
        ${setLimitHint}
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
                  aria-label="Límite mensual para ${CATEGORY_LABELS[b.category] || b.category}"
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

  // ── Calendario ───────────────────────────────────────────────────────

  async function loadCalendarMonth() {
    el.calendarMonthLabel.textContent = monthLabel(state.calendarMonth);
    const res = await authFetch(`${API}/calendar?month=${state.calendarMonth}`);
    const data = await res.json();
    state.calendarDays = data.days;
    renderCalendarGrid();
  }

  // Semana empezando en lunes (L M X J V S D, ya en el marcado) — hay que
  // convertir el day-of-week de JS (0=domingo) al offset de columna
  // correspondiente (0=lunes).
  function _mondayFirstOffset(jsDay) {
    return (jsDay + 6) % 7;
  }

  function renderCalendarGrid() {
    if (state.calendarDays.length === 0) {
      el.calendarGrid.innerHTML = "";
      return;
    }
    const firstDate = new Date(`${state.calendarDays[0].date}T00:00:00`);
    const leadingBlanks = _mondayFirstOffset(firstDate.getDay());

    const cells = [];
    for (let i = 0; i < leadingBlanks; i++) {
      cells.push(`<div class="calendar-day-cell calendar-day-empty"></div>`);
    }
    for (const day of state.calendarDays) {
      const dayNum = Number(day.date.slice(-2));
      const hasExpenses = day.expenses.length > 0;
      const hasNotes = day.notes.length > 0;
      // Dinero entrando (Bizum) también en verde aquí — antes se quedaba
      // en gris terciario aunque ese mismo importe SÍ era verde en la
      // lista principal (.expense-amount.positive).
      const totalClass = day.total_day < 0 ? "calendar-day-total positive" : "calendar-day-total";
      cells.push(`
        <button
          class="calendar-day-cell ${hasExpenses ? "has-expenses" : ""}"
          data-date="${day.date}"
          aria-label="${dayNum}${hasExpenses ? `, ${formatAmount(day.total_day)}` : ""}${hasNotes ? ", con nota" : ""}"
        >
          <span class="calendar-day-number">${dayNum}</span>
          ${hasExpenses ? `<span class="${totalClass}">${formatAmount(day.total_day)}</span>` : ""}
          ${hasNotes ? `<svg class="icon calendar-day-pin" aria-hidden="true" focusable="false"><use href="#icon-pin" /></svg>` : ""}
        </button>`);
    }
    el.calendarGrid.innerHTML = cells.join("");

    el.calendarGrid.querySelectorAll("[data-date]").forEach((cell) => {
      cell.addEventListener("click", () => openCalendarDay(cell.dataset.date));
    });
  }

  function openCalendarDay(dateStr) {
    state.calendarSelectedDate = dateStr;
    const day = state.calendarDays.find((d) => d.date === dateStr);
    const d = new Date(`${dateStr}T00:00:00`);
    el.calendarDayTitle.textContent = `${d.getDate()} de ${MONTH_LABELS[d.getMonth()]}`;

    el.calendarDayExpenses.innerHTML =
      day.expenses.length === 0
        ? `<div class="empty-state">Sin gastos este día.</div>`
        : day.expenses.map(expenseRowHtml).join("");
    el.calendarDayExpenses.querySelectorAll("[data-expense-id]").forEach((row) => {
      row.addEventListener("click", () => openDetail(Number(row.dataset.expenseId)));
    });

    renderCalendarDayNotes(day.notes);

    el.calendarNoteText.value = "";
    el.calendarNoteType.value = "punctual";
    el.calendarNoteError.hidden = true;

    openSheet(el.viewCalendarDay);
  }

  function renderCalendarDayNotes(notes) {
    if (notes.length === 0) {
      el.calendarDayNotes.innerHTML = `<div class="empty-state">Sin notas este día.</div>`;
      return;
    }
    el.calendarDayNotes.innerHTML = notes
      .map(
        (n) => `
      <div class="calendar-note-row" data-note-id="${n.id}">
        <svg class="icon calendar-note-icon"><use href="#icon-pin" /></svg>
        <span class="calendar-note-text">${escapeHtml(n.text)}</span>
        ${n.recurring_day ? `<span class="calendar-note-recurring-tag">cada mes</span>` : ""}
        <button class="calendar-note-delete" data-delete-note-id="${n.id}">Borrar</button>
      </div>`
      )
      .join("");

    el.calendarDayNotes.querySelectorAll("[data-delete-note-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.deleteNoteId);
        if (!confirm("¿Borrar esta nota? Si es recurrente, desaparece de todos los meses.")) return;
        await authFetch(`${API}/calendar/notes/${id}`, { method: "DELETE" });
        await loadCalendarMonth();
        openCalendarDay(state.calendarSelectedDate);
      });
    });
  }

  el.calendarNoteSave.addEventListener("click", async () => {
    const text = el.calendarNoteText.value.trim();
    el.calendarNoteError.hidden = true;
    if (!text) return;

    const isRecurring = el.calendarNoteType.value === "recurring";
    const dateStr = state.calendarSelectedDate;
    const body = isRecurring
      ? { text, recurring_day: Number(dateStr.slice(-2)) }
      : { text, note_date: dateStr };

    const res = await authFetch(`${API}/calendar/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      el.calendarNoteError.textContent = "No se ha podido guardar la nota.";
      el.calendarNoteError.hidden = false;
      return;
    }
    await loadCalendarMonth();
    openCalendarDay(dateStr);
  });

  el.calendarPrevMonth.addEventListener("click", () => {
    state.calendarMonth = shiftMonth(state.calendarMonth, -1);
    loadCalendarMonth();
  });

  el.calendarNextMonth.addEventListener("click", () => {
    state.calendarMonth = shiftMonth(state.calendarMonth, 1);
    loadCalendarMonth();
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
    const merchantLabel = e.merchant || "Sin identificar";
    // <button>, no <div> — antes no era ni siquiera enfocable, así que
    // abrir el detalle de un gasto era imposible sin puntero. Sin
    // elementos interactivos anidados dentro (a diferencia de
    // .budget-card), así que aquí sí es un <button> real.
    return `
      <button class="expense-row" data-expense-id="${e.id}" aria-label="${escapeHtml(merchantLabel)}, ${e.category || "sin categorizar"}, ${formatAmount(e.amount)}${e.needs_review ? ", pendiente de revisión" : ""}">
        <div class="expense-icon ${categoryIconClass(e.category)}"><svg class="icon" aria-hidden="true" focusable="false"><use href="#${icon}" /></svg></div>
        <div class="expense-info">
          <div class="expense-merchant">${escapeHtml(merchantLabel)}</div>
          <div class="expense-category">${e.category || "Sin categorizar"}</div>
        </div>
        ${e.needs_review ? '<span class="needs-review-dot"></span>' : ""}
        <div class="expense-amount ${e.category === "bizum" ? "positive" : ""}">${formatAmount(e.amount)}</div>
      </button>`;
  }

  // Auditoría: la cola de Revisión antes no mostraba importe ni fecha en
  // la propia tarjeta — el usuario tenía que decidir "Confirmar" o
  // "Rechazar" sobre "Sin identificar / —", sin ningún dato real con el
  // que decidir. Ahora el importe es el elemento principal de la
  // tarjeta (mismo peso que un dato destacado), con la fecha al lado, y
  // el texto crudo del mensaje queda disponible como "ver original"
  // plegable en vez de ser la única fuente del dato.
  function renderReviewList() {
    if (state.reviewQueue.length === 0) {
      el.reviewList.innerHTML = `<div class="empty-state">Nada pendiente de revisión.</div>`;
      return;
    }
    el.reviewList.innerHTML = state.reviewQueue
      .map((e) => {
        const dateLabel = new Date(e.occurred_at).toLocaleDateString("es-ES", {
          day: "numeric",
          month: "short",
        });
        const merchantLabel = e.merchant || "Sin identificar";
        const rawExcerpt = e.raw_text
          ? `<details class="raw-disclosure">
               <summary>Ver mensaje original</summary>
               <div class="raw-text-block">${escapeHtml(e.raw_text)}</div>
             </details>`
          : "";
        return `
      <div class="field-group review-card" data-review-id="${e.id}">
        <div class="review-card-head">
          <span class="review-card-amount">${formatAmount(e.amount)}</span>
          <span class="review-card-date">${escapeHtml(dateLabel)}</span>
        </div>
        <div class="field-row">
          <span class="field-label">${escapeHtml(merchantLabel)}</span>
        </div>
        <label class="field-row">
          <span class="field-label">Categoría</span>
          <select
            class="review-category"
            data-review-id="${e.id}"
            aria-label="Categoría de ${escapeHtml(merchantLabel)}"
          >
            <option value="">Elegir categoría…</option>
            ${Object.keys(CATEGORY_ICONS)
              .map(
                (c) =>
                  `<option value="${c}" ${e.category === c ? "selected" : ""}>${CATEGORY_LABELS[c] || c}</option>`
              )
              .join("")}
          </select>
        </label>
        ${rawExcerpt}
        <div class="review-actions" style="padding: 10px 14px 14px">
          <button class="confirm" data-confirm-id="${e.id}" ${e.category ? "" : "disabled"}>Confirmar</button>
          <button data-open-id="${e.id}">Ver detalle</button>
          <button class="reject" data-reject-id="${e.id}">Rechazar</button>
        </div>
      </div>`;
      })
      .join("");

    // "Confirmar" solo se activa con categoría elegida — antes disparaba
    // sin ninguna categoría seleccionada (ver auditoría, prevención de
    // errores).
    el.reviewList.querySelectorAll(".review-category").forEach((select) => {
      select.addEventListener("change", () => {
        const btn = el.reviewList.querySelector(`[data-confirm-id="${select.dataset.reviewId}"]`);
        if (btn) btn.disabled = !select.value;
      });
    });

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
    el.addBizumHint.hidden = true;
    openSheet(el.viewAdd);
  });

  el.addCategory.addEventListener("change", () => {
    el.addBizumHint.hidden = el.addCategory.value !== "bizum";
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

  function openCalendar() {
    loadCalendarMonth();
    openSheet(el.viewCalendar);
  }

  document.querySelectorAll(".tabbar button[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.tab === "review") openReview();
      if (btn.dataset.tab === "budgets") openBudgets();
      if (btn.dataset.tab === "calendar") openCalendar();
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
        calendar: el.viewCalendar,
        "calendar-day": el.viewCalendarDay,
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

  // Antes de esto, cada hoja cerrada seguía "viva" — en el orden de
  // tabulación, en el árbol de accesibilidad y en el compositor — solo
  // oculta con transform. Un usuario de teclado que le daba a Tab entraba
  // en ~28 controles fantasma dentro de hojas invisibles. `inert` (nativo,
  // soportado en Safari/iOS desde 15.5) saca el contenido inerte del
  // orden de tabulación y del árbol de accesibilidad de una sola vez, sin
  // tocar el CSS de transición que ya existía.
  let openSheetCount = 0;
  let lastFocusedBeforeSheet = null;

  function openSheet(node) {
    lastFocusedBeforeSheet = document.activeElement;
    node.style.transform = "";
    node.classList.add("open");
    node.inert = false;
    openSheetCount += 1;
    el.viewMain.inert = true;
    // Mueve el foco dentro de la hoja — antes abrir una hoja no tocaba
    // el foco en absoluto, así que un usuario de teclado seguía
    // "dentro" de la pantalla principal, ahora inerte.
    const backButton = node.querySelector(".back-button");
    backButton?.focus();
  }

  function closeSheet(node) {
    node.classList.remove("open");
    node.style.transform = "";
    node.inert = true;
    openSheetCount = Math.max(0, openSheetCount - 1);
    if (openSheetCount === 0) {
      el.viewMain.inert = false;
      // Restaura el foco a quien abrió la hoja — sin esto, al cerrar el
      // foco cae al <body> y el usuario de teclado "pierde el sitio".
      if (lastFocusedBeforeSheet && document.contains(lastFocusedBeforeSheet)) {
        lastFocusedBeforeSheet.focus?.();
      }
    }
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
      // Excepción real, no teórica: la columna izquierda ("L", lunes) de
      // la cuadrícula del Calendario cae justo en esta franja (celda
      // centrada en x≈38 con el ancho de un iPhone) — confirmado con un
      // tap real que se lo comía el gesto de swipe en vez de abrir el
      // día. Cualquier target tocable dentro de la cuadrícula gana sobre
      // el gesto de cierre.
      if (e.target.closest(".calendar-day-cell")) return;
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

  [
    el.viewDetail,
    el.viewReview,
    el.viewAdd,
    el.viewBudgets,
    el.viewSearch,
    el.viewSettings,
    el.viewCalendar,
    el.viewCalendarDay,
  ].forEach(attachSwipeToClose);

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

  // Todas las hojas empiezan inertes — ninguna está abierta al cargar
  // (la de clave de acceso usa `hidden`, no `.sheet` normal, así que ya
  // queda fuera del árbol de accesibilidad por su cuenta).
  document.querySelectorAll(".sheet:not(.lock-screen)").forEach((sheet) => {
    sheet.inert = true;
  });

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
