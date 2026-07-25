# Status & Handoff

Where the build actually is, the decisions behind it, and what's next. Read this
+ `DEVILS_ADVOCATES_PRD.md` (spec) + `BUILD_NOTES.md` (MCP/retrieval facts) and
you're caught up. Last updated 2026-07-25.

## Current state — WORKING, fully live, three verdicts

`uv run python -m core.pipeline "<question>"` runs the whole spine end to end:
real Gemma (Ollama, E2B workers + E4B judge) over real OpenAIRE papers,
producing one of three sourced outcomes. No stubs remain.

Pipeline (all in `core/pipeline.py`, stream-first async generator):

```
intake (claim | clarify | out-of-scope)   ← interactive front gate
 → retrieve (OpenAIRE, live) → classify_stance (batched + backfill)
 → budget (partition, top-k/side) → route (3-way verdict)
     ├─ OUT_OF_SCOPE  (< min_evidence on-topic)      → honest refusal
     ├─ CONSENSUS     (lone dissenter / one-sided)   → sourced consensus + dissent
     └─ CONTESTED     → enrich → FOR ‖ AGAINST advocates → judge (crux) → Brief
```

**Demo triad — empirically verified (run through the live pipeline, not guessed):**

| Verdict | Question | Result |
|---|---|---|
| CONTESTED | does saturated fat intake increase cardiovascular disease risk? | 5/5, asymmetry 0.03 — balanced debate |
| CONSENSUS | does smoking cause lung cancer? | 5/1 → lone-dissenter rule; sourced "established by [s3][s5]" + dissent note |
| OUT_OF_SCOPE | how many windows are in Paris? | refused at intake, no retrieval |

Also verified CONTESTED: creatine→cognition (4/3), omega-3→CVD (5/5),
intermittent-fasting (leans FOR, one dissenter). ~30–45s/run at E2B/E4B tiers.

## Architecture decisions (locked — do not re-litigate)

1. **Stream-first.** `run()` yields typed events; `run_to_brief()` drains for
   notebook/eval. Two advocates fan into one stream via `_merge` (asyncio.Queue).
2. **Intake front gate** turns free text into a testable claim, asks ONE
   clarifying question if vague (interactive, `max_clarify=2` bounces), or
   refuses non-claims before burning retrieval + 3 model calls. Non-interactive
   callers (`ask=None`: eval, notebook) fall through to a best-guess `extract()`.
   Bounded for-loop, not a graph runtime — no LangGraph.
3. **Tri-state `verdict`** on the Brief (`route()`, a pure function):
   OUT_OF_SCOPE / CONSENSUS / CONTESTED. CONSENSUS is a positive sourced output,
   not a shrug — the consensus statement cites the papers that establish it.
4. **A lone dissenter is not a controversy.** Consensus fires when one side has
   ≥ `min_side` (2) papers and the other has ≤1 (or confidence-weighted
   asymmetry ≥ 0.85). This survives a single spurious stance classification —
   without it, settled claims like smoking wrongly showed as debates.
5. **Partition ON by default**, `Config.shared_evidence` flips it OFF. That flag
   IS the Track-03 ablation (run twice, diff).
6. **Tier-per-role is `Config.tiers`** (a dict). Default = E2B workers + E4B judge.
   `GEMMA_MODEL=gemma4:e4b` forces all-E4B (Track-02 fallback). No code change.
7. **OpenAIRE full abstracts** are the evidence (search → get_details). medRxiv
   full-text is the next source, not yet wired.
8. **Single judge** in v1 (no swap-and-merge yet).
9. **Provenance enforced in code** — a claim citing outside its partition is
   dropped (`_enforce_cites`), never trusted to the model's taste.

## Files

| File | Role |
|---|---|
| `core/schema.py` | Frozen contract + `Verdict` + `Config` (tiers, shared_evidence, min_evidence, min_side, stance_batch, top_k, max_clarify) |
| `core/pipeline.py` | Orchestration, intake loop, `route`, consensus branch, prompts, tolerant parsers, `--selfcheck` (pure logic) |
| `core/retrieve.py` | OpenAIRE search (relevance sort) + `enrich_full_abstracts` + JATS clean |
| `core/mcp_client.py` | OAuth'd MCP client; browser login once, refresh token cached |
| `core/llm.py` | Single Gemma seam (Ollama; `GEMMA_MODEL` override; `parse_json`) |

## Gotchas an agent WILL re-hit (hard-won)

- **Stance classification does NOT survive a big batch.** Gemma+Ollama JSON-mode
  collapses ~24 snippets in one call down to a SINGLE object — the other 23
  silently default NEUTRAL, both piles empty, and every real claim misroutes to
  OUT_OF_SCOPE. Fix (in place): classify in batches of `stance_batch` (6) and
  backfill any dropped id one-at-a-time (a 1-item prompt can't collapse). Do not
  revert to a single mega-batch.
- **Stance REFUTES recall needs spelling out.** Null / "no significant effect" /
  "did not improve" results are evidence AGAINST — the prompt says so explicitly.
  Without it the classifier calls them NEUTRAL and genuine debates look one-sided
  (creatine came back a false 5–0 before this).
- **Local models don't return the JSON shape you ask for.** Every parser is
  deliberately tolerant (`extract`, `_parse_claims`, `_normalize_stance`, intake,
  consensus, `judge`). Keep them tolerant — don't "clean up" into strict access.
- **Ollama `format:"json"` + `temperature:0`** is what keeps output parseable
  (still mildly non-deterministic across runs — smoking is 5/0 or 5/1, both
  route to CONSENSUS, so it's robust).
- **OpenAIRE search is keyword-AND** — cap the query to ~3 terms or it collapses
  to 0–1 results. `sort=relevance`, NOT influence.
- **Search abstracts are truncated ~500 chars**; `get_research_product_details`
  gives the full abstract. Advocates + consensus need it (`enrich_full_abstracts`).
- **The standalone app cannot use Claude's plugin MCP tools** — it has its own
  OAuth client (`mcp_client.py`). Tokens cached under `~/.devils_advocates/`.

## Next steps (priority order)

1. **Eval harness** — the partition on/off ablation (`shared_evidence` flipped)
   over ~30 frozen claims. Clears the Track-03 cap; scoring-critical. Now
   unblocked — the pipeline produces real splits. §8 of PRD.
2. **Streaming UI or notebook** — the events already stream (incl. `verdict`,
   `clarify`); needs a consumer. Notebook = reproducibility floor; SSE
   two-column UI + verdict banner = the wow demo.
3. **Cached-fallback + `mode` (LIVE/CACHED)** for demo reliability (deployment
   doc): live OpenAIRE is currently the only evidence path.
4. **Stance precision polish** — 18/24 land NEUTRAL on some claims; off-topic
   retrieval is the driver. keyword→vector two-step (BUILD_NOTES) if piles thin.
5. **Judge swap-and-merge** (§4.4) — position-bias guard, still a single call.

## Deferred (agreed, not lost)

medRxiv full-text · rebuttal round (PRD cut #1) · judge swap-and-merge ·
query-widening on thin retrieval (§9) · LLMLingua compression (P2) · Brev deploy.
