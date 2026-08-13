---
name: Gastos
description: Personal expense tracker PWA — iOS Liquid Glass over a violet-black gradient.
colors:
  bg-top-light: "#fdfcff"
  bg-mid-light: "#f2eefa"
  bg-bottom-light: "#e7e0f2"
  bg-top-dark: "#1a1230"
  bg-mid-dark: "#140d26"
  bg-bottom-dark: "#0a0a0f"
  coral-accent: "#ff6b35"
  coral-accent-dark: "#ff8a5b"
  amber-warning: "#b8720a"
  amber-warning-dark: "#ffb340"
  danger: "#d9483a"
  positive: "#1f8a53"
  positive-dark: "#34c98f"
  text-light: "#1c1230"
  text-dark: "#f5f3fa"
  cat-comida: "#c94570"
  cat-transporte: "#3d6fd4"
  cat-suscripciones: "#8a4fd4"
  cat-ocio: "#b347b8"
  cat-salud: "#1f9e8a"
  cat-hogar: "#5c5cd6"
typography:
  body:
    fontFamily: "-apple-system, system-ui, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "normal"
  amount-display:
    fontFamily: "-apple-system, system-ui, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "34px"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.02em"
rounded:
  pill: "999px"
  card: "20px"
  row: "14px"
spacing:
  sm: "8px"
  md: "14px"
  lg: "16px"
  xl: "20px"
components:
  primary-button:
    backgroundColor: "{colors.coral-accent}"
    textColor: "#ffffff"
    rounded: "{rounded.row}"
    padding: "14px"
  circular-action-primary:
    backgroundColor: "{colors.coral-accent}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    size: "52px"
---

# Design System: Gastos

## Overview

**Creative North Star: "Control Center for your wallet"**

Gastos is a single-user personal finance PWA, opened almost exclusively on
an iPhone home screen. The design commits to real iOS Liquid Glass —
`backdrop-filter` blur over a living gradient — rather than a flat card
system with an accent color, which is the category default this kind of
utility app almost always ships. The gradient (violet-black in dark mode,
white-to-lavender in light) exists specifically to give the glass something
real to refract; a flat white or flat black background under `blur()`
renders indistinguishable from no blur at all, which is what the first
attempt at this direction got wrong and what the gradient + halo fixes.

Blur is a budgeted resource, not a house style applied everywhere: it lives
only on fixed chrome (navbar, total card, segmented control, circular
action buttons, tab bar, sheet headers). Scrollable content — the expense
list — uses flat semi-transparent rows with **no** `backdrop-filter`,
because compositing blur under a long scrolling list is a real, measured
performance cost on Safari/iPhone, not a hypothetical one.

**Key Characteristics:**
- Real translucent material (`backdrop-filter: blur(20px) saturate(180%)`), never a gradient or box-shadow standing in for glass.
- A warm radial color halo behind fixed chrome so blur has texture to catch.
- Coral accent for the primary/positive action, amber for anything that needs the user's attention (`needs_review`).
- Flat rows in scrollable lists — glass is chrome, never content.
- System font throughout — this is an Operate-mode tool, not a marketing surface; the platform's own optical sizing beats a licensed display face here.

## Colors

Two complete palettes (light default, dark via `prefers-color-scheme` or an explicit `data-theme` override), never mixed.

### Primary
- **Coral** (`#ff6b35` light / `#ff8a5b` dark): reserved **exclusively for creation actions** — the "Añadir" quick action, its "+" icon, active tab, the alta-manual sheet's header tint ("this is new"). It does not double as a general-purpose "primary" color: a query action (Buscar) or a default progress state is not a creation action and does not get coral, even though both used to before this was tightened. Dark mode lightens it for contrast against the near-black ground.

### Secondary
- **Amber** (`#b8720a` light / `#ffb340` dark): reserved exclusively for `needs_review` and "approaching a limit" — the needs-review dot on a list row, the "Pendiente de revisión" pill, the amber accent dot on a detail sheet's title, the full amber header tint on the review-queue sheet, and a budget bar between 80–100% of its limit. Amber never appears for anything the user didn't flag as needing attention.
- **Positive** (`#1f8a53` light / `#34c98f` dark): the default/good state — a budget bar under 80% of its limit, the "spend went down" comparison badge. Semantic like amber/danger, not a second brand accent: it never appears as decoration or a hover state, only as "this number is fine."
- **Danger** (`#d9483a` light / `#ff6b6b` dark): a budget over its limit — both the bar fill and, since a bar alone is easy to miss scanning quickly, a full-card background/border tint on that category's card.

### Category (qualitative, not semantic)
Six of the seven expense categories carry a distinct hue, applied to their icon's stroke and a 20%-tinted background on the icon's glass tile — comida (rose `#c94570`/`#ff8fb8`), transporte (blue `#3d6fd4`/`#7ea6ff`), suscripciones (violet `#8a4fd4`/`#b98aff`), ocio (magenta `#b347b8`/`#e08aef`), salud (teal `#1f9e8a`/`#4fd9c0`), hogar (indigo `#5c5cd6`/`#9a9aff`). "Otros" stays neutral gray — it's the catch-all, it doesn't need an identity. This is a *qualitative* coding system (which category is this, at a glance) and lives in a completely different hue family from the four *semantic* colors above (coral/amber/positive/danger, which mean "creation," "attention," "fine," "problem") — see Named Rule below for why this doesn't reopen the "no second accent" door.

### Neutral
- **Violet-black gradient** (`#1a1230` → `#140d26` → `#0a0a0f`, dark): the page ground in dark mode, plus a soft violet radial halo (`rgba(168,116,255,0.3)`) behind fixed chrome — see Named Rule below.
- **White-lavender gradient** (`#fdfcff` → `#f2eefa` → `#e7e0f2`, light): the light-mode equivalent — deliberately *not* flat white (see Named Rule).
- **Text** (`#1c1230` light / `#f5f3fa` dark): both tinted from the violet hue, never pure gray — secondary/tertiary text is the same color at lower alpha, not a separate gray token.

### Named Rules
**The No Flat Ground Rule.** Neither theme's background is a single flat color. Glass needs a gradient (and a halo) beneath it to read as material; a flat ground under `backdrop-filter` is indistinguishable from no blur, which is exactly the failure the first version of this direction shipped and had to be corrected.

**The Amber-Means-Attention Rule.** Amber is the *only* color reserved for `needs_review`. It never appears as decoration, a second accent, or a hover state — its presence anywhere in the UI is always meaningful.

**The Coral-Means-Creation Rule.** Coral is not a general "primary" color — it fires only for creating something new (Añadir, the alta-manual sheet). A search button, a default progress bar, or any other action that isn't creation uses a neutral glass treatment or the appropriate semantic color instead, even if coral would have been the "safe" default before this was tightened.

**The Semantic-vs-Qualitative Rule.** Coral/amber/positive/danger *mean* something ("create," "attention," "fine," "problem") and there are exactly four of them, on purpose. Category colors *identify* something (which of the 7 categories is this) and there are six of them, in a hue family that shares no member with the semantic four — so a colored icon never gets mistaken for a status. Adding an 8th qualitative hue is fine if a category needs one; reusing coral/amber/positive/danger for a category, or adding a 5th semantic meaning, is not.

## Typography

**Body Font:** -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", sans-serif (system stack, no custom face)

**Character:** Plain platform-native type. This is a personal Operate-mode tool where scanning transaction rows quickly matters more than typographic personality — the system font already ships correct optical sizing for iOS, and a licensed display face would be a costume with no product reason behind it.

### Hierarchy
- **Amount display** (700, 34px, 1.05 line-height, -0.02em tracking): the total-card figure — the single most important number on the screen, `font-variant-numeric: tabular-nums` so it doesn't jitter between periods.
- **Title** (600, 17px): navbar and sheet-header titles.
- **Body** (500, 14.5–15px): merchant names, field values.
- **Label** (600, 12–13px, uppercase, 0.03–0.04em tracking): day-group headers, segmented control, category labels.

## Layout

Single-column mobile shell, `100dvh`, no desktop breakpoint — the product is used exclusively as an installed iPhone PWA (confirmed in PRODUCT.md; there is no desktop use case to design for). Fixed navbar (sticky top) and tab bar (fixed bottom) sandwich a scrollable middle region. Sheets (detail, alta manual, revisión) are full-screen overlays that slide in from the right, matching the existing swipe-back gesture already implemented in `app.js`. Spacing rhythm: 16–18px horizontal margins, 12–14px internal row padding, consistent across cards and sheets.

## Elevation & Depth

Hybrid: real optical depth from `backdrop-filter` blur (not a shadow standing in for it) on chrome, plus a soft, generously-blurred, y-offset shadow (`--shadow-card`) under the total card and circular buttons for lift. No hard, zero-offset, or neobrutalist shadows anywhere — this system was never pinned to that language.

### Shadow Vocabulary
- **Card lift** (`0 8px 28px -10px rgba(60,40,90,0.16)` light / `0 10px 34px -10px rgba(0,0,0,0.55)` dark): total card, circular action buttons, segmented-control thumb.

### Named Rules
**The Chrome-Only Blur Rule.** `backdrop-filter` is a budgeted effect, not a house style: navbar, total card, segmented control, circular buttons, tab bar, and sheet headers get it; the scrollable expense list never does. This is a performance constraint (Safari/iPhone scroll cost), not a taste preference — do not add blur to a new list or repeating row component without re-confirming the performance budget still allows it.

## Shapes

Two radius scales: **20px** for large fixed surfaces (total card, sheets' top corners), **14px** for rows and field groups, **999px (pill)** for the segmented control and badges. Circular action buttons are true circles (50% radius), not rounded squares — they read as physical buttons, not cards. Borders are always 1px, with the top edge a brighter tint than the sides/bottom (`--glass-border-top`) to fake the light-catching edge a real pane of glass would have.

## Components

### Buttons
- **Shape:** 14px radius (row scale) for CTA buttons; true circle for quick-action buttons.
- **Primary** (creation only — Añadir, Guardar gasto): solid coral fill, white/dark text depending on theme (`--accent-contrast`), 14px vertical padding.
- **Secondary** (a query, not a creation — Buscar): standard glass treatment (`--glass-fill` + blur), coral *text*, no solid fill. Same shape/padding as primary so the two read as siblings, not as different components — only the fill communicates "this doesn't create anything."
- **Circular quick-action:** glass circle (`--glass-fill` + blur), coral-filled variant for the primary "Añadir" action only; icon + label beneath, matching the reference banking-app quick-actions row.
- **Press feedback:** `scale(0.93–0.98)` on `:active` with the bounce spring curve (`cubic-bezier(0.34, 1.56, 0.64, 1)`) — a deliberate, momentum-flavored tap response per the apple-design skill's guidance to reserve bounce for interactions that carry momentum, not a decorative default.

### Cards / Containers
- **Corner Style:** 20px (total card), 14px (field groups, day groups).
- **Background:** `--glass-fill` (translucent) with `backdrop-filter: blur(20px) saturate(180%)` on fixed cards; flat `--glass-row` (no blur) on scrollable list rows.
- **Border:** 1px `--glass-border`, brighter on the top edge.

### Inputs / Fields
- **Style:** borderless, transparent background inside a glass `field-group` container; right-aligned value text (label left, value right — iOS Settings pattern).
- **Focus:** 2px coral outline, 2px offset.
- **Native `<input type="date">`:** kept native (no custom picker) — `color-scheme` bound to the current theme so the browser's own picker icon renders in the matching scheme, icon opacity lowered to sit at the same visual weight as the rest of the row's icons.

### Category icons (signature component)
Every category icon — list rows, search results, budget cards, recurring rows — is a small rounded-square glass tile: colored stroke + a 20%-tinted background of that category's color (see Colors > Category), never a flat gray tile with a flat gray glyph. "Otros" and any row without a clear category keep the original neutral gray tile — a missing color *is* information (it means "uncategorized" or "catch-all"), not an oversight to paper over.

### Progress bars (budget cards)
- **Fill color** follows spend, not decoration: `--positive` under 80% of the limit, `--warning` 80–100%, `--danger` over 100%.
- **No limit set → no bar at all**, not an empty or full-width one — a progress bar with no target communicates nothing real. Only the "`spent` gastado, sin límite" text line shows.
- **Over limit** additionally tints the whole card (`color-mix` background + border in `--danger`), not just the bar — a bar alone is easy to miss scanning a full screen of cards quickly; the card-level tint is what actually catches the eye.
- Animated via `transform: scaleX()` (compositor-only), never `width` — see Elevation & Depth's performance framing, same reasoning applies to any future animated-length element.

### Navigation
- **Tab bar:** glass, fixed bottom, active tab tinted coral. **Segmented control:** glass track with a sliding glass "thumb" (not a solid-color active state) that moves with the same critically-damped spring used elsewhere (`cubic-bezier(0.22, 1, 0.36, 1)`).

### Sheet differentiation (signature component)
Three sheet types carry different color treatment so the user reads "what kind of screen is this" before reading any text:
- **Alta manual** (`sheet-accent`): header tinted with the coral accent — "this is new."
- **Detalle de gasto** (default): neutral header; a small amber dot appears before the title *only* when `needs_review` is true — a single accent, not a takeover.
- **Cola de revisión** (`sheet-review`): the entire sheet header background is amber-tinted — every row inside is, by definition, something that needs attention.

## Do's and Don'ts

### Do:
- **Do** keep `backdrop-filter` limited to fixed chrome (navbar, total card, segmented control, circular buttons, tab bar, sheet headers) — never on repeating list rows.
- **Do** use amber exclusively for `needs_review`/"approaching a limit" states; never as a second decorative accent.
- **Do** use coral exclusively for creation actions; reach for `--positive`/neutral glass for anything else that used to default to coral out of habit.
- **Do** keep both theme gradients tonally varied (never flat white or flat black) so blur has something to refract.
- **Do** use the system font stack — this is an Operate surface, not a Persuade one.
- **Do** author new icons as SVG in the existing single-stroke (1.75px, round caps) style; never fall back to emoji.
- **Do** use the six `--cat-*` colors for category icons, consistently, everywhere a category icon appears — a category is coded the same color on every screen it shows up on.

### Don't:
- **Don't** add a second saturated *semantic* color alongside coral/amber/positive/danger — those four meanings stay fixed. (The six qualitative `--cat-*` category colors are a separate system and don't count against this — see Named Rules.)
- **Don't** apply blur to anything inside `.list-scroll` — that constraint exists because of a measured Safari/iPhone performance concern, not a style preference.
- **Don't** use a flat solid background for either theme; the gradient (and its halo) is load-bearing for the glass effect, not decoration.
- **Don't** introduce colored `border-left`/`border-right` accent stripes for state (e.g. a colored sidebar on a card) — sheet/state differentiation happens through background tint and small iconography, established above.
- **Don't** render a progress bar with no target (`limit_amount` null) — omit the bar entirely rather than show an empty or meaningless one.
