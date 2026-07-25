# Devil's Advocates

A disagreement engine for contested scientific claims. Give it a claim; it
retrieves real papers, splits the evidence by stance, has two Gemma advocates
debate from their own evidence, and a judge names the **crux** (it does not pick
a winner). Every claim carries provenance (DOI, title, year).

Gemma 4 Hackathon · 42 Paris · Track 03 — Context Engineering for SLMs.
See `docs/DEVILS_ADVOCATES_PRD.md` for the full spec and `docs/BUILD_NOTES.md`
for operational findings.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (deps are already locked in `uv.lock`)
- [Ollama](https://ollama.com) running locally with a Gemma 4 model:
  ```
  ollama pull gemma4:e4b        # required
  ollama pull gemma4:e2b        # optional — the real Track-03 tiering (see below)
  ```
- A one-time browser login to the Alien OpenAIRE MCP (free).

## Setup

1. Authorize retrieval (opens a browser once; token cached to `~/.devils_advocates/`):
   ```
   uv run python -m core.mcp_client openaire
   ```
   Prints `authorized · N tools` on success.

2. Sanity-check the orchestration logic (no model, no network):
   ```
   uv run python -m core.pipeline --selfcheck
   ```

## Run

```
GEMMA_MODEL=gemma4:e4b uv run python -m core.pipeline "does creatine improve cognition in healthy adults?"
```

`GEMMA_MODEL=gemma4:e4b` forces every role onto E4B — use this until you've
pulled E2B. Drop it to run the real tiering (E2B for extract/stance/advocate,
E4B for the judge).

## Live UI

Build the teammate's React UI once, then serve it with the debate API:

```
cd frontend
npm ci
npm run build
cd ..
uv run python -m api.server
```

Then open `http://127.0.0.1:8765`. The UI calls the real pipeline through
server-sent events; it does not use mocked results. The Python server serves
`frontend/dist` and the API from the same public port, so this is also the
production build sequence.

For frontend development, run the API and Vite in separate terminals:

```
uv run python -m api.server
cd frontend && npm run dev
```

### Example queries

Contested → a real two-sided debate:
```
"does creatine improve cognition in healthy adults?"
"intermittent fasting beats calorie restriction for fat loss"
"vitamin D supplementation reduces respiratory infections"
"time-restricted eating improves metabolic health"
```
Consensus → high asymmetry, refuses to fake a fight:
```
"smoking causes lung cancer"
```
Nonsense → guardrail, honest out-of-scope:
```
"how many windows are in paris"
```

## How it works

```
question → extract (claim + search query) → retrieve + enrich (OpenAIRE, live)
        → classify stance (SUPPORTS/REFUTES/UNRESOLVED/NEUTRAL)
        → partition evidence → FOR/AGAINST openings → cross-rebuttals
        → judge → disagreement brief (crux, resolver, asymmetry)
```

- **Partition on/off** is a config flag (`Config.shared_evidence`) — the
  Track-03 ablation runs the same pipeline with it flipped.
- **Model tier per role** is a config dict (`Config.tiers`) — swap "all E2B"
  (purity run) or "all bigger" (Track-02 fallback) with no code change.
- Citations are enforced in code: a claim citing evidence outside its own
  partition is dropped, not trusted.

## Layout

| File | Role |
|---|---|
| `core/schema.py` | Frozen data contract (`Snippet`, `Claim`, `Brief`, `Config`) |
| `core/pipeline.py` | Stream-first orchestration + `--selfcheck` |
| `core/retrieve.py` | Live OpenAIRE retrieval + full-abstract enrichment |
| `core/mcp_client.py` | OAuth'd MCP client (browser login, cached refresh token) |
| `core/llm.py` | The one seam to Gemma (Ollama today, Brev at deploy) |
