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
- [vLLM](https://docs.vllm.ai/) serving a Gemma checkpoint through its
  OpenAI-compatible API. By default the application expects it at
  `http://localhost:8000/v1`.
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

## Docker

Docker Compose runs vLLM and the CLI application as separate services. Set
`VLLM_MODEL` to the Hugging Face identifier of the Gemma checkpoint to serve;
set `HUGGING_FACE_HUB_TOKEN` too if the model is gated. OAuth refresh tokens
are persisted in a named volume and are never copied into the image.

```bash
export VLLM_MODEL=<gemma-checkpoint-id>
docker compose up -d vllm
docker compose run --rm app python -m core.mcp_client openaire
docker compose up -d
```

The OAuth callback is bound to `127.0.0.1:8765` on the host, so authorize from
the same machine running Compose. The `vllm` service requests all available
NVIDIA GPUs; remove the `deploy.resources.reservations.devices` block when
running without NVIDIA Container Toolkit (inference will then use CPU).

Open WebUI is available at `http://localhost:3000`. It is preconfigured to use
the `app` service through its OpenAI-compatible API; select the
`devils-advocates` model in the model picker.

## OpenWebUI API

The `app` service exposes an OpenAI-compatible agent API at
`http://localhost:8001/v1`. Start it with the model server:

```bash
docker compose up -d vllm app
```

In OpenWebUI, add an OpenAI connection using `http://app:8001/v1` when it is
on the same Compose network (or `http://host.docker.internal:8001/v1` from a
separate OpenWebUI container). Select the `devils-advocates` model. The API
supports `GET /v1/models`, `POST /v1/chat/completions`, and SSE streaming.

## Run

```
VLLM_MODEL=your-gemma-checkpoint uv run python -m core.pipeline "does creatine improve cognition in healthy adults?"
```

`VLLM_MODEL` selects one checkpoint for every role, which is the recommended
deployment. To serve two models, set `VLLM_MODEL_E2B` and `VLLM_MODEL_E4B`;
`GEMMA_MODEL` still overrides both for one-off runs.

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
question → extract (claim + search query) → retrieve (OpenAIRE, live)
        → classify stance (SUPPORTS/REFUTES/NEUTRAL) → partition evidence
        → FOR advocate ‖ AGAINST advocate  (each sees only its own pile)
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
| `core/llm.py` | The one seam to Gemma via vLLM's OpenAI-compatible API |
