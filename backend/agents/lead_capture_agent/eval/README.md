# Lead Capture evaluation

Scripted visitors against the real engine: does the agent send the lead when it should, and never when it shouldn't? A small second block checks whether it admits what the tenant's knowledge doesn't cover.

Design: `portfolio/docs/superpowers/specs/2026-11-26-lead-capture-eval-design.md`.

## How to run

From the AI-Portfolio root, with the AI-Portfolio venv active. `run_eval` reads `ANTHROPIC_API_KEY` from `AI-Portfolio/.env`, then removes the Langfuse keys:

```bash
python -m backend.agents.lead_capture_agent.eval.run_eval --pilot     # P1 once; check plumbing, then delete the file
python -m backend.agents.lead_capture_agent.eval.run_eval --runs 5    # 6 profiles × 5 = 30 conversations, 5 questions × 5 = 25 answers
python -m backend.agents.lead_capture_agent.eval.report backend/agents/lead_capture_agent/eval/results/<stamp>.json
```

`report` reads `<stamp>.review.json` if it exists and writes `<stamp>.summary.json`, the file the portfolio snapshots.

## What it measures

- **Lead sent correctly** (no judge). Each script in `scripts.json` fixes its outcome before the run: `send` (P1, P6, with the first turn at which a send is allowed) or `no_send` (P2–P5). Every conversation gets exactly one category: correct · premature (sent before the confirmation turn) · false negative · false positive.
- **Duplicate deliveries**: turns that end with the step at `send`. The streaming endpoint (`api.py`, `on_complete`) delivers the lead whenever the step is `send` and never moves it to `DONE`, so the eval carries the state the same way and counts every such turn. Only P6 has a visitor turn after the send.
- **Marker leaked** to the visitor, **greeting in English**, and the **first turn that mentions an email** (an observation, not graded).
- **Faithfulness**: 5 questions the knowledge doesn't answer (`faithfulness.json`). Lander labels each answer `admits` / `hedged` / `invents`. An automatic pre-pass only flags figures and capitalised names that are not in the knowledge.

## Decisions (confirmed by Lander, 2026-11-26)

- **English scripts**, although the knowledge is in Spanish: the case-study page is in English. The agent translates.
- **5 runs** of each script and question. With Haiku it costs cents, and with fewer conversations a single miss would weigh too much.
- **Greeting fixed before the run.** The greeting used to be hard-coded "en español". The widget now sends `navigator.language`, and the eval asks for the greeting with `lang="en"`.
- **Premature is its own category**, not folded into false positives.
- **A lead with the wrong email is a false negative, because the tenant receives an unusable lead.**
- **State mirrors the streaming endpoint** (the step stays `send` after a delivery), which is what exposes duplicate deliveries.
- **Raw reply without touching the engine.** The engine strips `<<<SEND_LEAD>>>` before anything leaves it, so `run_eval.py` wraps the Anthropic client it hands the engine and records the raw streamed text. That is what lets a reviewer tell, in P5, whether the agent complied or quoted the marker while refusing. A quoted marker still counts as a send, because the product would send.
- **Model** `claude-haiku-4-5-20251001`, as the engine sets it. Temperature is not set by the engine, so the API default (1.0) applies, as in production.
- **SDK version recorded.** `requirements.txt` pins `anthropic==0.41.0` but the local venv has a newer SDK. The version actually used goes in `meta.anthropic_version`. The model and the prompt are the same either way.
- **No Langfuse, Resend or SQLite.** `run_eval.py` removes the Langfuse keys from its environment, so the run adds no traces to the real project.

## Freeze rule

`scripts.json` and `faithfulness.json` are frozen before the first full run. One pilot conversation is allowed and discarded. After the full run, a script may change only if it is broken (a typo, a malformed email), never because of what the agent answered. Any change is logged below and the full run is redone.

## Human review

Only two things are reviewed by hand. The primary metric stays automatic.

1. **Desync overrides.** A conversation becomes `not_applicable` when the fixed turns no longer make sense as replies *and* that changes the outcome. The automatic category is kept, and the reviewed figures are reported next to it.
2. **Faithfulness labels**, plus `p5_quoted`: the P5 false positives where the raw reply shows the agent quoted the marker while refusing.

### Desync overrides

_None yet._

### Script changes after freeze

_None._
