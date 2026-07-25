# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Devil's Advocates: a disagreement engine for contested scientific claims. Given
a claim, it retrieves real papers from OpenAIRE, splits the evidence by stance
(SUPPORTS/REFUTES/NEUTRAL), has two Gemma "advocates" debate from their own
disjoint evidence pile, and a judge names the **crux** — it never picks a
winner. Built for the Gemma 4 Hackathon (42 Paris, Track 03 — Context
Engineering for SLMs). Read `docs/STATUS.md` first for current state and
locked architecture decisions; `docs/DEVILS_ADVOCATES_PRD.md` is the full spec;
`docs/BUILD_NOTES.md` has hard-won operational facts about the OpenAIRE/medRxiv
MCPs that aren't in the PRD.

## Commands

- `uv sync` — install locked dependencies.
- `uv run python -m core.pipeline --selfcheck` — offline pure-logic self-check
  (partition, cite enforcement, asymmetry, guardrail, routing, query cleaning).
  No model, no network. Run this before submitting any pipeline/schema change.
- `uv run python -m core.mcp_client openaire` — one-time browser OAuth login for
  live retrieval; refresh token cached under `~/.devils_advocates/`. Must be run
  once before any live (non-selfcheck) pipeline run.
- `uv run python -m core.pipeline "<claim>"` — end-to-end CLI run against a real
  vLLM/Gemma endpoint and live OpenAIRE. Needs `VLLM_MODEL` (or
  `VLLM_MODEL_E2B`/`VLLM_MODEL_E4B`) set and OpenAIRE already authorized.
- `uv run python -m api.server` — serve the dependency-free live SSE UI at
  `http://127.0.0.1:8765` (real pipeline events, no mocked results).
- `uv run python -m core.retrieve "<claim>"` — smoke-test OpenAIRE retrieval
  alone (needs prior OpenAIRE auth).
- `docker compose up -d` — run vLLM + agent API + Open WebUI together. Copy
  `.env.example` to `.env` first and set `VLLM_MODEL` (and `HF_TOKEN` if the
  model is gated). Then `docker compose run --rm app python -m core.mcp_client openaire`
  to authorize (OAuth callback binds to `127.0.0.1:8765` on the host — authorize
  from the same machine running Compose).

There is no separate test directory, formatter, or linter configured. Extend
`core.pipeline._selfcheck()` when changing pure logic (citation enforcement,
partitioning, asymmetry, the routing guardrail); keep new checks deterministic
and offline. Only run a live claim end-to-end when a change touches retrieval,
OAuth, or model prompting.

## Architecture

Everything funnels through the async generator `core.pipeline.run()`, which
yields typed dict events as each stage completes (`claim_text`, `snippet`,
`stance`, `partition`, `turn_claim`, `violation`, `crux`, terminal `brief`, and
a `verdict` of `CONTESTED`/`CONSENSUS`/`OUT_OF_SCOPE`). `run_to_brief()` drains
the stream into a single `Brief` dataclass for non-streaming callers (eval,
notebook, the OpenAI-facade API).

Pipeline stages, in order:

```
intake (claim | clarify | out-of-scope)   ← interactive front gate
 → retrieve (OpenAIRE, live) → classify_stance (batched + backfill)
 → budget (partition, top-k/side) → route (3-way verdict)
     ├─ OUT_OF_SCOPE  (< min_evidence on-topic)      → honest refusal
     ├─ CONSENSUS     (lone dissenter / one-sided)   → sourced consensus + dissent
     └─ CONTESTED     → enrich → FOR ‖ AGAINST advocates → judge (crux) → Brief
```

Two advocates run concurrently and are fanned into one ordered stream by
`_merge()` (an `asyncio.Queue`-based combinator local to `pipeline.py`).

### Module map

| File | Role |
|---|---|
| `core/schema.py` | Frozen data contract (`Snippet`, `Claim`, `Brief`, `Config`) — dataclasses, not pydantic, by design |
| `core/pipeline.py` | The orchestration spine: intake loop, all stage functions, prompts, tolerant response parsers, `route()`, `--selfcheck` |
| `core/retrieve.py` | Live OpenAIRE retrieval + `enrich_full_abstracts` (search truncates abstracts to ~500 chars; `get_research_product_details` returns the full text needed for advocacy) |
| `core/mcp_client.py` | Standalone OAuth'd MCP client for the Alien research servers (openaire/medrxiv/biorxiv). This is a separate OAuth client from any Claude Code plugin — the standalone app cannot reuse Claude's plugin MCP tools |
| `core/llm.py` | The one seam to Gemma, via vLLM's OpenAI-compatible `/chat/completions` API. All model calls across the pipeline go through `llm.generate(role, prompt, tier=...)` |
| `core/api.py` | OpenAI-compatible chat-completions facade (`/v1/chat/completions`, `/v1/models`) so OpenWebUI (or any OpenAI client) can talk to the pipeline; renders a `Brief` to markdown. This is what Docker Compose runs by default (`python -m core.api`) |
| `api/server.py` | Separate, dependency-free HTTP server for the live demo UI: serves static files from `ui/` and streams pipeline events over SSE at `GET /api/run`. Not the same service as `core/api.py` |
| `ui/` | Plain HTML/CSS/JS frontend (no framework, no build step) consumed by `api/server.py`'s SSE stream |

### Key design decisions (treat as locked unless the user says otherwise — see `docs/STATUS.md` §"Architecture decisions")

- **Stream-first.** Prefer extending `run()`'s event stream over adding
  non-streaming return paths.
- **Partition is the whole point.** `Config.shared_evidence=False` (default)
  gives each advocate a disjoint evidence pile; flipping it to `True` is the
  Track-03 ablation, not a bug to "fix". Don't let the two piles overlap by
  accident.
- **Citations are enforced in code, not trusted to the model.** `_enforce_cites`
  drops any claim citing evidence outside its own partition, and drops the
  whole claim if nothing valid remains. Keep this enforcement in code if you
  touch the advocate stage.
- **Tri-state verdict is intentional.** `route()` is a pure function (pinned by
  `_selfcheck`) implementing: too little evidence → `OUT_OF_SCOPE`; one side
  with ≥`min_side` papers and the other with a lone dissenter (or asymmetry ≥
  `consensus_asymmetry`) → `CONSENSUS` (a positive, sourced statement — not a
  shrug); otherwise → `CONTESTED`. This "lone dissenter is not a controversy"
  rule is what keeps settled claims (e.g. smoking → cancer) from misrouting to
  a fake debate.
- **Model tier per role is data, not code.** `Config.tiers` (default: E2B for
  extract/stance/advocate, E4B for judge) selects the served model per pipeline
  role via `VLLM_MODEL_E2B`/`VLLM_MODEL_E4B`; `GEMMA_MODEL` forces one model for
  every role. Swapping tiers should never require a code change.
- **Parsers must stay tolerant.** Local/small models do not reliably return the
  exact JSON shape requested. `llm.parse_json`, `_parse_claims`,
  `_normalize_stance`, and the intake/consensus/judge parsers all
  defensively accept lists, single objects, or `{id: value}` mappings, and
  strip code fences / stray prose. Don't "clean up" these into strict parsing.
- **Stance classification must stay batched, not one mega-call.** Gemma+Ollama
  JSON-mode collapses a ~24-item batch into a single object, silently
  defaulting the other 23 snippets to NEUTRAL and misrouting real claims to
  `OUT_OF_SCOPE`. `classify_stance` batches by `Config.stance_batch` (6) and
  backfills any id the model dropped one-at-a-time. Do not revert to one big
  batch.
- **REFUTES must include null results.** The stance prompt explicitly tells the
  classifier that "no significant effect" / failed replication counts as
  REFUTES, not NEUTRAL — without this, genuine debates undercount evidence
  against the claim.
- **OpenAIRE search is keyword-AND.** Queries are capped to 3 terms
  (`_clean_query`, `retrieve.keywords`) — more terms collapse results toward
  zero, the opposite of a typical search engine. Sort by `relevance`, not
  `influence` (influence surfaces famous-but-off-topic papers).

## Environment variables

| Var | Purpose |
|---|---|
| `VLLM_BASE_URL` | vLLM OpenAI-compatible base URL (default `http://localhost:8000/v1`) |
| `VLLM_MODEL` | Served model name used for every tier unless overridden |
| `VLLM_MODEL_E2B` / `VLLM_MODEL_E4B` | Per-tier override; both default to `VLLM_MODEL` |
| `GEMMA_MODEL` | Forces every role onto one model regardless of tier (one-off runs) |
| `VLLM_API_KEY` | Optional bearer token for the vLLM endpoint |
| `DA_TOKEN_DIR` | Where OAuth tokens are cached (default `~/.devils_advocates/`) |
| `DA_CALLBACK_PORT` / `DA_CALLBACK_BIND_HOST` | Local OAuth callback server (default port 8765, bind `localhost`) |
| `HF_TOKEN` | Hugging Face token, needed if the served checkpoint (e.g. `google/gemma-3-4b-it`) is gated |

## Conventions

- Four-space indentation, type annotations, `snake_case` functions/variables,
  `PascalCase` dataclasses, concise module/function docstrings — match nearby
  code.
- `core.schema` is a frozen shared contract: add or change fields only when
  every pipeline stage that touches them is updated together.
- Keep all model calls behind `core.llm.generate`; don't add provider-specific
  calls elsewhere in orchestration code.
- Commit subjects follow Conventional Commits style (`feat:`, `fix:`, `docs:`,
  `chore:`) with a focused imperative subject.
- Never commit OAuth refresh tokens, local model-server configuration, or
  credentials — the MCP client intentionally caches auth outside the repo.
