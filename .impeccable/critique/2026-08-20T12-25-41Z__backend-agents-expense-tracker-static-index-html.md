---
target: expense_tracker full app audit
total_score: 17
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 8
timestamp: 2026-08-20T12-25-41Z
slug: backend-agents-expense-tracker-static-index-html
---
# Gastos (expense_tracker) — Full-app critique (dual-agent)

Method: dual-agent (A: general-purpose design review · B: general-purpose technical audit+detector), run in parallel isolated worktrees against a live seeded instance.

## Design Health Score (Nielsen heuristics, Assessment A): 17/40 — Poor
1 Visibility of System Status: 2 · 2 Match System/Real World: 2 · 3 User Control/Freedom: 2 · 4 Consistency/Standards: 2 · 5 Error Prevention: 2 · 6 Recognition/Recall: 2 · 7 Flexibility/Efficiency: 1 · 8 Aesthetic/Minimalist: 2 · 9 Error Recovery: 1 · 10 Help/Documentation: 1

## Audit Health Score (technical, Assessment B): 13/20 — Acceptable
1 Accessibility: 2 · 2 Performance: 3 · 3 Theming: 3 · 4 Responsive: 2 · 5 Implementation Integrity: 3

## Implementation Integrity: PASS (coherent product-specific system; drift = documentation lag, not incoherence)

## Top priority issues (merged, by severity)
- P0: Review queue shows no amount/merchant/date on the screen designed to triage it (A)
- P1: --text-tertiary fails AA on every screen, both themes (B, 11 instances)
- P1: Keyboard focus enters 6 closed off-screen sheets, ~28 stops (B)
- P1: 20/20 form inputs have no programmatic label (B)
- P1: Light-mode primary buttons/back-buttons fail AA (2.17-3.85:1) (A+B agree)
- P1: Coral used for 7 non-creation actions, violating the app's own rule (A)
- P1: Presupuestos has no way to set a budget limit from the UI (A)
- P1: 9 control types under 44x44 at 375px width (B)
- P2: Calendar day-totals ignore the app's own "money in = green" rule (B, independently confirms A's calendar critique)
- P2: DESIGN.md never updated for Calendar/Bizum features (B)

Full findings list, personas, patterns, and positive findings: see conversation.
