# RAG PDF Chat Agent: Claude Haiku 4.5 (API) vs local models with Ollama

Same PDF, same index, same 30 questions, four answer models. The question: can a local model on a
consumer GPU replace the API model in this agent's RAG pipeline?

**Result, on this hardware, document and question set:**

- **qwen3:14b with thinking gets the same grade as Claude Haiku 4.5 on every one of the 29 evaluable
  questions** (blind grading by Claude Sonnet), at about 3.3× Haiku's median latency (5.01 s vs 1.54 s).
- **Without thinking, qwen3:14b loses 3 questions clearly and 1 partly** to Haiku (Q11, Q21, Q28; Q19),
  and is faster than the API call (median 1.29 s vs 1.54 s).
- **The grades don't see everything.** In the one question where retrieval missed the answer (Q8),
  only Haiku stayed faithful to the context in all three runs. See [Q8](#q8-faithfulness-that-the-grades-dont-see).

## What was compared

| Configuration | Model | Temperature | Runs per question |
|---|---|---|---|
| Haiku (API) | `claude-haiku-4-5-20251001` | 0 | 3 |
| qwen3:14b (local) | `qwen3:14b` via Ollama | 0 | 3 |
| qwen3:14b + thinking (local) | `qwen3:14b` via Ollama, reasoning on | 0.6 | 3 |
| llama3.2:3b (local) | `llama3.2:3b` via Ollama | 0 | 1 |

- Temperature 0 everywhere so the configurations are comparable. Two exceptions:
  - Thinking runs at 0.6, because the Qwen3 model card says "DO NOT use greedy decoding" in thinking mode.
  - **Declared deviation:** Qwen3 recommends 0.7 without thinking as well; we used 0 to keep it
    comparable with Haiku.
- llama3.2:3b is a low-capacity reference (1 run) and is reported [separately](#low-capacity-reference-llama323b),
  not in the main comparison.

## Setup

- **RAG:** Chroma, `bge-m3` embeddings (via Ollama), chunk size 1000, overlap 200, top-k 4.
  A single index is built once and shared by all configurations, so retrieval is identical for all of them.
- **Ollama:** `num_ctx` 8192 for the local models; thinking gets an extra 4096-token output budget.
- **Hardware:** NVIDIA RTX 4080 (16 GB), Windows 11. Ollama 0.40.12.
- **Packages:** langchain-core 1.2.23, langchain-anthropic 1.4.0, langchain-ollama 1.1.0
  (recorded in the results JSON).
- **Production differs:** the agent uses OpenAI embeddings in production. Those currently fail
  (HTTP 429, no credit), so this evaluation uses `bge-m3` for every configuration. Results describe
  the answer models on a `bge-m3` index, not the production pipeline end to end.

## The question set

[questions.json](questions.json): 30 questions about the *Memoria de actividades 2025* of the
Federación Española de Fibrosis Quística (25-page PDF, in Spanish). `run_eval.py` downloads the PDF
into `eval/data/` (gitignored) and checks its sha256.

Ten question types, chosen to probe different failure modes:

| Type | n | | Type | n |
|---|---|---|---|---|
| dato_exacto (exact fact) | 6 | | premisa_falsa (false premise) | 3 |
| parafrasis (paraphrased question) | 4 | | idioma_cruzado (question in another language) | 3 |
| resumen_abierto (open summary) | 4 | | no_en_documento (not in the document) | 2 |
| cifra_con_trampa (figure with a trap) | 3 | | lista_sintesis (list synthesis) | 1 |
| multi_salto (multi-hop) | 3 | | calculo (calculation) | 1 |

## How answers were graded

1. **Automatic rule** (`run_eval.py`): the answer must contain every expected figure (compared without
   thousands or decimal separators) and one alternative of every expected term (compared without accents
   or case). Refusing ("I didn't find that information") counts as correct only on questions that expect it.
2. **Blind grading by Claude Sonnet** (`blind.py`): identical answers are merged (146 unique answers out
   of 300). They are shuffled with a fixed seed and shown to the grader without the configuration, the
   automatic grade or the retrieved chunks, only the question, the expected answer and the answer.
   The rubric is embedded in `blind_<stamp>.json`. It has its own rules for `no_en_documento` and
   `premisa_falsa`, and two flags that don't change the grade:
   - `extra_claims`: the answer adds content that isn't in the expected answer.
   - `rounding_only`: the only difference from the expected answer is rounding or format.

   A key file maps each unique answer back to every (configuration, run) that produced it.
3. **Family-bias check** (`grades_report.py`): for each configuration, how often Sonnet graded above
   or below the automatic rule. Sonnet and Haiku are both Claude models, so this checks whether Sonnet
   favours Haiku.
4. **Human review** of the borderline cases (Q8, Q17, Q29, Q30). **Pending.**

**Retrieval metrics** (computed once per question; they don't depend on the answer model):

- *Recall@4 by page:* every question with an expected page retrieves it, except Q27 (3 of 4 pages).
- *Figures in context:* the expected figures appear in the retrieved chunks for every question where
  this is measured, except Q8 (0 of 1).

## Results

Valid run: `results/results_20261028_102533.json` (GPU otherwise idle). Grades are counted per
**appearance** (question × run); the three runs of a question are not independent, so differences
are discussed per question [below](#where-haiku-and-qwen3-differ).

| Configuration | Sonnet blind grade c / p / i | Automatic rule c / p / i | Latency mean / median / max (s) | Cold start (s) |
|---|---|---|---|---|
| Haiku (API) | **75** / 9 / 3 | 84 / 0 / 3 | 1.75 / 1.54 / 2.76 | 3.71 |
| qwen3:14b (local) | **66** / 9 / 12 | 69 / 6 / 12 | 1.44 / **1.29** / 3.43 | 18.56 |
| qwen3:14b + thinking (local) | **75** / 9 / 3 | 82 / 2 / 3 | 5.37 / 5.01 / 14.59 | 15.39 |

c / p / i = correct / partial / incorrect, n = 87 per configuration (29 questions × 3 runs). Latency
covers all 30 questions (n = 90). It doesn't include the cold start, which is measured on a separate
warm-up call before the questions.

Q29 is excluded from the grade columns because the grader was inconsistent on it and its expected
answer is ambiguous (see [Limitations](#limitations)). With Q29 included (n = 90), Sonnet gives Haiku
78/9/3, qwen3:14b 66/12/12 and thinking 77/10/3. Excluding Q29 doesn't change the comparison with
qwen3:14b, but it turns thinking's 1-answer gap into a tie with Haiku.

Reproduce the grade columns:

```bash
python -m backend.agents.rag_pdf_agent.eval.grades_report backend/agents/rag_pdf_agent/eval/results/results_20261028_102533.json --exclude 29
```

**Other measurements:**

- **No truncation:** every answer ended normally (`end_turn` for Haiku, `stop` for Ollama). The largest
  input + output was 2,095 tokens, well under the 8,192 context.
- **VRAM:** Ollama reports (`size_vram` in `/api/ps`, measured separately; not stored in the results
  JSON) 10,003 MiB for qwen3:14b (the same with and without thinking, 8192 context) and 2,974 MiB for
  llama3.2:3b. In the run, total GPU memory in use rose by 10,297 / 3,237 MiB over a baseline of
  1,924–1,954 MiB, slightly more than `size_vram`, as expected. On Windows (WDDM),
  `nvidia-smi --query-compute-apps` reports `[N/A]` per process; the Windows counter
  "GPU Process Memory\Dedicated Usage" does give per-process memory.
- **Temperature 0 is not deterministic:** answers differed between runs on 2 of 30 questions for
  Haiku and 2 for qwen3:14b. Thinking (temperature 0.6) differed on 22 of 30.

## Where Haiku and qwen3 differ

Counted per question, from `grades_report.py --diff` (Sonnet's grade in each run):

| Question | Type | qwen3:14b | Haiku | What happened |
|---|---|---|---|---|
| Q11 | calculo | i i i | c c c | qwen gives one of the two figures as the total and doesn't add them |
| Q19 | parafrasis | i i i | p p p | qwen answers "No encontré esa información"; Haiku also says so, then gives the 38 professionals |
| Q21 | premisa_falsa | i i i | c c c | see below |
| Q28 | resumen_abierto | p p p | c c c | qwen leaves out part of the list |

Thinking against Haiku: no differences. Q27 and Q30 don't separate the models: Sonnet grades all three
main configurations partial on both.

**Q21: refusing a false premise whose answer is in the document.** The question asks why the
IX National Congress was cancelled. It wasn't: it took place in Málaga on 15–16 November, and the page
with that fact was retrieved. qwen3:14b and llama3.2:3b answer only "No encontré esa información en el
documento". Haiku and thinking start with the same sentence but then correct the premise. Q21 is a
different failure from Q19: Q19 is an unnecessary refusal on an ordinary question.

## Q8: faithfulness that the grades don't see

Q8 asks for the 2025 financial result (36,048.41 €). Retrieval finds page 11 but not the chunk with the
result (figures in context: 0 of 1). Against the expected answer, all four configurations are incorrect.
Reading the full answers next to the context tells a different story:

| Configuration | What it says | Runs that are faithful to the context |
|---|---|---|
| Haiku | Gives 237,294.59 € *as income* and says the document gives no expenses or net result | 3 of 3 |
| qwen3:14b | "El resultado económico de 2025 fue de 237.294,59€ en ingresos": the income passes as the result | 0 of 3 |
| thinking | Calls the income the result; in 1 run it adds that expenses and net profit aren't mentioned | 1 of 3 |
| llama3.2:3b | Gives the income as income, without warning that the result is missing | — (doesn't misstate, doesn't warn) |

Contrast with **Q17**, which asks for the same figure in other words ("how much money was left over").
There the chunk *is* retrieved, and every configuration answers 36,048.41 € except llama3.2:3b, which
invents a subtraction of two income figures (240,650.44 − 237,294.59 = 3,355.85 €).

Neither the automatic rule nor Sonnet captures Q8, because both compare the answer with the expected
answer, not with the retrieved context. Judging faithfulness means reading the whole answer with the
context in front of you. That is why human review is part of the method and not optional.

Q8 is also the only clear retrieval failure in the set, and the case that best separates the models on
faithfulness.

## The grader

- **No family bias detected.** Excluding Q29, Sonnet was stricter with Haiku than with qwen3:14b. It
  graded Haiku below the automatic rule 9 times and above it 0 times; for qwen3:14b, 3 below and 0 above.
  With Q29 included, Haiku has 3 upgrades, all from Q29. `rounding_only` was 0 for every configuration.
- **Inconsistency between batches on Q29.** The answers were graded in three batches. Answers with the
  same omissions were graded partial in batches 1 and 3 and correct in batch 2. Q29 is therefore
  excluded from the grades and left for human review. Separately, its expected answer includes the
  campaign slogan, which is arguably not an "activity". That's a problem with the question set, not
  with the grader.
- **Extra content is not invention.** 45 of Haiku's 87 graded answers (16 unique answers) add facts
  that aren't in the expected answer. All of them were checked against the PDF text, and none were invented.
- **Q30:** page 24 lists "El trasplante en Fibrosis Quística" (2004, no. 6) and (2025, no. 25), so the
  expected answer is correct. No. 25 may be the same updated transplant manual mentioned on page 6;
  that ambiguity is unresolved.

## Low-capacity reference: llama3.2:3b

One run per question (n = 29 without Q29): Sonnet 20 / 2 / 7, automatic rule 20 / 2 / 7. Latency
0.86 / 0.78 / 1.40 s (mean / median / max), cold start 8.10 s. Against Haiku it differs on 8 questions
(Q6, Q17, Q19, Q20, Q21, Q25, Q27, Q28), including the invented subtraction in Q17.

## What this experiment suggests

On this hardware (RTX 4080, 16 GB), this document (a 25-page Spanish PDF) and this question set
(30 questions, 10 types), a 14B local model with thinking matches the API model on grader-assigned
quality, at about 3.3× the median latency. Without thinking, the local model is slightly faster than
the API and loses 3 questions clearly and 1 partly. Nothing here tests whether this holds for other
documents, languages or hardware. The setup uses a single document, a single language and a single
machine, and that is the main limitation.

## Limitations

- **n = 30 questions, one PDF.** The 3 runs of a question are not independent, so the unit of comparison
  is the question, not the appearance.
- **The grader is from Haiku's family.** Mitigated by the bias check, which came out negative.
- **Grader drift between batches** on Q29.
- **Temperature deviation** for qwen3:14b without thinking (0 instead of the recommended 0.7).
- **Temperature 0 is not deterministic** (see Results).
- **Discarded run.** The 2026-10-27 run (`results_20261027_130208_contaminated.json`) was discarded for
  GPU contention (a game open on the GPU during the local part). Between that run and the valid one,
  Ollama also changed (0.40.11 → 0.40.12). The faster local latency in the valid run can't be
  attributed to either change on its own.
- **Cold start not isolated.** qwen3:14b's cold start was 4.7–4.9 s in the pilots, 6.08 s on 10-27 and
  18.56 s on 10-28. The cause is not known.
- **Embeddings differ from production** (OpenAI in production, currently failing; `bge-m3` here).
- **Package mismatch:** the repo's `requirements.txt` pins `langchain-core==0.3.30`; the evaluation
  ran with 1.2.23 ([requirements.txt](requirements.txt) for the experiment says so). Out of scope here.
- **min_p not set explicitly.** Qwen3 recommends min_p = 0 in thinking mode. We relied on Ollama's
  default (0.0), taken from the documentation on Ollama's main branch rather than checked against the
  installed version.
- **Human review pending** for Q8, Q17, Q29 and Q30.

## Reproducing it

Requires Ollama running locally with `qwen3:14b`, `llama3.2:3b` and `bge-m3`, an Anthropic API key,
and the experiment's extra dependencies ([requirements.txt](requirements.txt)). From the repo root:

```bash
# 1. Run the 4 configurations (writes results_<stamp>.json and review_<stamp>.csv)
python -m backend.agents.rag_pdf_agent.eval.run_eval --repeats 3

# 2. Blind export for the grader (writes blind_<stamp>.json and blind_key_<stamp>.json)
python -m backend.agents.rag_pdf_agent.eval.blind backend/agents/rag_pdf_agent/eval/results/results_<stamp>.json

# 3. Grade blind_<stamp>.json with an LLM following its embedded rubric -> grades_<stamp>.json

# 4. Per-configuration grades, bias check, and per-question differences
python -m backend.agents.rag_pdf_agent.eval.grades_report backend/agents/rag_pdf_agent/eval/results/results_<stamp>.json --exclude 29
python -m backend.agents.rag_pdf_agent.eval.grades_report backend/agents/rag_pdf_agent/eval/results/results_<stamp>.json --exclude 29 --diff "qwen3:14b (local)" "claude-haiku-4.5 (API)"
```

Files in [results/](results/):

| File | What it is |
|---|---|
| `results_20261028_102533.json` | **Valid run**: answers, automatic grade, latency, VRAM, tokens, stop reason, retrieval metrics and retrieved chunks |
| `review_20261028_102533.csv` | The same run, flattened for manual review |
| `blind_…`, `blind_key_…`, `grades_20261028_102533.json` | Blind grading by Sonnet (146 unique answers) |
| `results_20261027_130208_contaminated.json` (+ CSV) | Discarded run (GPU contention) |
| `pilot_*` | Pilots before temperature was fixed |
