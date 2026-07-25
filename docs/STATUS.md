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
 → retrieve (OpenAIRE, live) → enrich full abstracts
 → classify_stance (4-way, batched + backfill + directional verification)
 → budget (partition, top-k/side) → route (4-way verdict)
     ├─ OUT_OF_SCOPE  (not a testable scientific claim) → honest refusal
     ├─ INSUFFICIENT_EVIDENCE (valid claim, weak/unresolved corpus) → honest refusal
     ├─ CONSENSUS     (lone dissenter / one-sided)   → sourced consensus + dissent
     └─ CONTESTED     → openings → cross-rebuttals → judge (crux) → Brief
```

**Demo triad — empirically verified (run through the live pipeline, not guessed):**

| Verdict | Question | Result |
|---|---|---|
| CONTESTED | does saturated fat intake increase cardiovascular disease risk? | 5/5, asymmetry 0.03 — balanced debate |
| CONSENSUS | does smoking cause lung cancer? | 5/1 → lone-dissenter rule; sourced "established by [s3][s5]" + dissent note |
| OUT_OF_SCOPE | how many windows are in Paris? | refused at intake, no retrieval |

Live retrieval/model output varies by run. Creatine→cognition is the regression
case for distinguishing direct null results from unresolved reviews; do not use
an old source count as a fixed demo fixture.

## Architecture decisions (locked — do not re-litigate)

1. **Stream-first.** `run()` yields typed events; `run_to_brief()` drains for
   notebook/eval. Two advocates fan into one stream via `_merge` (asyncio.Queue).
2. **Intake front gate** turns free text into a testable claim, asks ONE
   clarifying question if vague (interactive, `max_clarify=2` bounces), or
   refuses non-claims before burning retrieval + 3 model calls. Non-interactive
   callers (`ask=None`: eval, notebook) fall through to a best-guess `extract()`.
   Bounded for-loop, not a graph runtime — no LangGraph.
3. **Four-state `verdict`** on the Brief: OUT_OF_SCOPE is reserved for invalid
   inputs; INSUFFICIENT_EVIDENCE means the claim is valid but retrieval cannot
   support a debate or consensus; CONSENSUS and CONTESTED are sourced outputs.
4. **Stance and debate side are distinct.** SUPPORTS feeds FOR. REFUTES and
   UNRESOLVED feed AGAINST, but stay visibly distinct: unresolved evidence
   challenges accepting the claim without pretending a null effect was observed.
   NEUTRAL is reserved for genuinely off-topic material.
5. **Thin evidence is not consensus.** A one-sided pile needs at least
   `min_consensus_evidence` (4) direct SUPPORTS/REFUTES results. Unresolved
   reviews cannot establish consensus regardless of their count.
6. **Partition ON by default**, `Config.shared_evidence` flips it OFF. That flag
   IS the Track-03 ablation (run twice, diff).
7. **Tier-per-role is `Config.tiers`** (a dict). Default = E2B workers + E4B judge.
   `GEMMA_MODEL=gemma4:e4b` forces all-E4B (Track-02 fallback). No code change.
8. **OpenAIRE full abstracts** are fetched before stance classification. The
   search payload often ends before the result sentence.
9. **Advocates exchange one rebuttal round.** Each sees the opponent's opening
   claims but may still cite only its own evidence partition.
10. **Single judge** in v1 (no swap-and-merge yet).
11. **Provenance enforced in code** — a claim citing outside its partition is
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
- **Direct null and unresolved evidence are different.** A same-population null
  result is REFUTES. "Insufficient evidence" or mixed/low-quality literature is
  UNRESOLVED: it can challenge accepting the claim but cannot prove no effect.
- **Local models don't return the JSON shape you ask for.** Every parser is
  deliberately tolerant (`extract`, `_parse_claims`, `_normalize_stance`, intake,
  consensus, `judge`). Keep them tolerant — don't "clean up" into strict access.
- **Ollama `format:"json"` + `temperature:0`** is what keeps output parseable
  (still mildly non-deterministic across runs — smoking is 5/0 or 5/1, both
  route to CONSENSUS, so it's robust).
- **OpenAIRE search is keyword-AND** — cap the query to ~3 terms or it collapses
  to 0–1 results. `sort=relevance`, NOT influence.
- **Search abstracts are truncated ~500 chars**; `get_research_product_details`
  gives the full abstract. Classification must happen after
  `enrich_full_abstracts`, or it often misses the result sentence.
- **The standalone app cannot use Claude's plugin MCP tools** — it has its own
  OAuth client (`mcp_client.py`). Tokens cached under `~/.devils_advocates/`.

## Next steps (priority order)

1. **Eval harness** — the partition on/off ablation (`shared_evidence` flipped)
   over ~30 frozen claims. Clears the Track-03 cap; scoring-critical. Now
   unblocked — the pipeline produces real splits. §8 of PRD.
2. **Cached-fallback + `mode` (LIVE/CACHED)** for demo reliability (deployment
   doc): live OpenAIRE is currently the only evidence path.
3. **Stance precision polish** — many papers remain NEUTRAL or UNRESOLVED on
   some claims; off-topic retrieval is the driver. keyword→vector two-step
   (BUILD_NOTES) if piles thin.
4. **Judge swap-and-merge** (§4.4) — position-bias guard, still a single call.

## Deferred (agreed, not lost)

medRxiv full-text · judge swap-and-merge · query-widening on thin retrieval
(§9) · LLMLingua compression (P2) · Brev deploy.
