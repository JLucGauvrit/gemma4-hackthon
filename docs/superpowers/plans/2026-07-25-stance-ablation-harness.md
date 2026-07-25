# Stance-Feeding Ablation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an eval harness that isolates ONE variable — how abstracts are
fed to the E2B stance stage (`core.pipeline.classify_stance`) — across three
configs (raw / truncated / compressed) at equal token budget, over 12
hand-written claims with human-supplied gold stance labels.

**Architecture:** A one-time cache step (`eval/cache_snippets.py`) hits
OpenAIRE live retrieval + full-abstract enrichment once per claim and freezes
the result to `eval/labels/<id>.json` with a `gold_stance: null` field for a
human to fill in. A second step (`eval/evaluate.py`) never touches the
network again — it loads the cached+labeled snippets, runs
`classify_stance` three times per claim (raw text / word-truncated text /
`compress_snippets`-compressed text) against a live vLLM endpoint, scores
stance accuracy against the human labels, and reports token cost + latency
per config. Token counts come from the real `usage.prompt_tokens` vLLM
reports per call, captured via a new opt-in, task-safe hook on
`core.llm.generate` — not an approximated word/char count.

**Tech Stack:** Python 3.12, existing repo deps only (no new dependencies:
stdlib `json`/`copy`/`contextvars`/`dataclasses`/`pathlib`, plus the
project's own `core.llm`, `core.pipeline`, `core.squeeze`, `core.retrieve`,
`core.schema`).

## Global Constraints

- Reuse `core.pipeline.classify_stance`, `core.squeeze.compress_snippets`,
  `core.llm._model_for` as-is — do not reimplement stance classification or
  compression logic.
- No new `Snippet` dataclass fields beyond what's serialized to the eval JSON
  (`gold_stance` lives only in the JSON file, never added to the dataclass).
- Cache OpenAIRE results to disk so `eval/evaluate.py` re-runs never hit the
  network.
- Temperature 0 everywhere — already hardcoded in `core.llm.generate`
  (`"temperature": 0`); nothing to change there.
- Process claims in fixed `id` order (sorted ascending) in both scripts.
- `eval/cache_snippets.py` must never overwrite an existing
  `eval/labels/<id>.json` (a human may have started labeling it).
- `compress_snippets` mutates `Snippet.text` in place — every config in
  `evaluate.py` must start from an independent `copy.deepcopy` of the cached
  rows, never a shared list/objects.
- `truncated`'s per-snippet word budget must equal what the `compressed` run
  actually produced for that snippet id (not a fixed character count) — so
  `compressed` must run before `truncated` is computed, even though the
  printed/written row order is raw → truncated → compressed.

---

### Task 1: Task-safe token-usage capture in `core/llm.py`

**Files:**
- Modify: `core/llm.py`

**Interfaces:**
- Consumes: nothing new — vLLM's OpenAI-compatible `/chat/completions`
  response already includes `usage.prompt_tokens` / `usage.completion_tokens`
  (currently discarded by `generate()`).
- Produces: `llm.capture_usage()` — a context manager. `with llm.capture_usage()
  as records:` runs a block; `records` (a `list[dict]`, each
  `{"role": str, "tier": str, "prompt_tokens": int, "completion_tokens": int}`)
  is populated with one entry per `generate()` call made anywhere inside the
  block — including calls made inside `asyncio.gather`-spawned tasks (e.g.
  `classify_stance`'s batched + backfill calls), since each `asyncio.Task`
  copies the current `contextvars.Context` at creation and therefore shares
  the same underlying `records` list object. Existing `generate()` signature,
  return type, and behavior are unchanged when no `capture_usage` block is
  active (default sink is `None` — a no-op check, zero behavior change for
  the pipeline/API/UI callers).

- [ ] **Step 1: Add the `ContextVar` and `capture_usage` context manager**

Add near the top of `core/llm.py`, after the existing imports:

```python
import contextvars

_usage_sink: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "_usage_sink", default=None)


class capture_usage:
    """Context manager for eval harnesses: collect per-call token usage from
    every generate() call made inside the block, including ones spawned as
    concurrent asyncio tasks (e.g. classify_stance's gather'd batches) — a
    plain module-level list would race across those; each Task instead gets
    its own copy of this ContextVar binding pointing at the SAME list object,
    so appends land safely without a lock (asyncio has no preemption mid-call)."""

    def __enter__(self) -> list[dict]:
        self.records: list[dict] = []
        self._token = _usage_sink.set(self.records)
        return self.records

    def __exit__(self, *exc) -> None:
        _usage_sink.reset(self._token)
```

- [ ] **Step 2: Record usage inside `generate()` when a sink is active**

In `generate()`, replace:

```python
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
```

with:

```python
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        sink = _usage_sink.get()
        if sink is not None:
            usage = data.get("usage") or {}
            sink.append({
                "role": role, "tier": tier,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            })
        return data["choices"][0]["message"]["content"]
```

- [ ] **Step 3: Sanity-check with the existing self-check (no model/network)**

Run: `uv run python -m core.pipeline --selfcheck`
Expected: `selfcheck OK — ...` (unchanged — this step only touches `llm.py`,
which the self-check doesn't exercise, but confirms nothing else broke on
import).

- [ ] **Step 4: Commit**

```bash
git add core/llm.py
git commit -m "feat: add task-safe token-usage capture hook to llm.generate"
```

---

### Task 2: `eval/claims.jsonl` — 12 hand-written claims

**Files:**
- Create: `eval/claims.jsonl`

**Interfaces:**
- Produces: one JSON object per line, `{"id": "c01", "claim": "<text>"}`,
  ids `c01`..`c12` in file order (also the fixed processing order both eval
  scripts must sort by). Consumed by `eval/cache_snippets.py` and
  `eval/evaluate.py`.

- [ ] **Step 1: Write the file**

Mix of contested / consensus / out-of-scope claims, plain English, one per
line:

```jsonl
{"id":"c01","claim":"creatine improves cognition in healthy adults"}
{"id":"c02","claim":"smoking causes lung cancer"}
{"id":"c03","claim":"vitamin C supplementation prevents the common cold"}
{"id":"c04","claim":"the earth is flat"}
{"id":"c05","claim":"intermittent fasting causes more weight loss than continuous calorie restriction"}
{"id":"c06","claim":"the MMR vaccine causes autism"}
{"id":"c07","claim":"meditation reduces symptoms of anxiety"}
{"id":"c08","claim":"red meat consumption increases colorectal cancer risk"}
{"id":"c09","claim":"what is the best pizza topping"}
{"id":"c10","claim":"screen time before bed disrupts sleep quality"}
{"id":"c11","claim":"power posing increases testosterone and reduces cortisol"}
{"id":"c12","claim":"how many moons does Jupiter have"}
```

- [ ] **Step 2: Commit**

```bash
git add eval/claims.jsonl
git commit -m "feat: add 12 hand-written claims for stance-feeding ablation"
```

---

### Task 3: `eval/cache_snippets.py`

**Files:**
- Create: `eval/cache_snippets.py`
- Create (at runtime, not checked in): `eval/labels/<id>.json`

**Interfaces:**
- Consumes: `eval/claims.jsonl` (Task 2); `core.retrieve.keywords(claim, n=3)
  -> str`, `core.retrieve.retrieve_openaire(query, limit) -> list[Snippet]`,
  `core.retrieve.enrich_full_abstracts(snips) -> None` (mutates in place),
  `core.schema.Config` (for `.max_snippets`, default 24).
- Produces: `eval/labels/<id>.json` = JSON list of
  `{**asdict(Snippet), "gold_stance": None}` — i.e. every `Snippet` field
  (`id`, `text`, `stance`, `confidence`, `source`) plus one new
  human-editable key. Consumed by `eval/evaluate.py` (Task 4).

- [ ] **Step 1: Write `eval/cache_snippets.py`**

```python
"""One-time cache: retrieve + enrich OpenAIRE snippets for every claim in
eval/claims.jsonl, freeze them to eval/labels/<id>.json with an added
gold_stance: null field for a human to fill in (SUPPORTS/REFUTES/NEUTRAL).

This is the only step in the ablation harness that touches the network.
Never overwrites a labels file that already exists — a human may have
started filling it in. Needs OpenAIRE already authorized (see
`uv run python -m core.mcp_client openaire`).
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from core.retrieve import enrich_full_abstracts, keywords, retrieve_openaire
from core.schema import Config

ROOT = Path(__file__).parent
CLAIMS_PATH = ROOT / "claims.jsonl"
LABELS_DIR = ROOT / "labels"


def _load_claims() -> list[dict]:
    rows = [json.loads(line) for line in CLAIMS_PATH.read_text().splitlines() if line.strip()]
    return sorted(rows, key=lambda r: r["id"])


async def _cache_one(claim_id: str, claim: str, cfg: Config) -> None:
    out_path = LABELS_DIR / f"{claim_id}.json"
    if out_path.exists():
        print(f"  skip  {claim_id}  (labels file already exists)")
        return
    query = keywords(claim)
    snips = await retrieve_openaire(query, cfg.max_snippets)
    await enrich_full_abstracts(snips)
    rows = [{**asdict(s), "gold_stance": None} for s in snips]
    out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(f"  cache {claim_id}  {len(rows)} snippets  query={query!r}")


async def main() -> None:
    LABELS_DIR.mkdir(exist_ok=True)
    cfg = Config()
    for row in _load_claims():
        await _cache_one(row["id"], row["claim"], cfg)
    print(f"\nDone. Fill gold_stance in {LABELS_DIR}/*.json (SUPPORTS/REFUTES/NEUTRAL),"
          " then run eval/evaluate.py.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it against live OpenAIRE**

Run: `uv run python -m eval.cache_snippets`
Expected: prints one `cache c0N  <n> snippets  query='...'` line per claim
(or `skip` on re-run), and `eval/labels/c01.json` .. `eval/labels/c12.json`
exist, each a JSON list of snippet objects with `"gold_stance": null`.

- [ ] **Step 3: Spot-check one output file**

Run: `python -c "import json; d=json.load(open('eval/labels/c01.json')); print(len(d), d[0].keys())"`
Expected: a positive snippet count and
`dict_keys(['id', 'text', 'stance', 'confidence', 'source', 'gold_stance'])`.

- [ ] **Step 4: Commit**

```bash
git add eval/cache_snippets.py
git commit -m "feat: add OpenAIRE snippet caching script for stance ablation eval"
```

(`eval/labels/*.json` are generated data, not source — do not commit them
here; leave that decision to the user once real labels are filled in.)

---

### Task 4: `eval/evaluate.py`

**Files:**
- Create: `eval/evaluate.py`
- Create (at runtime, not checked in): `eval/results.jsonl`

**Interfaces:**
- Consumes: `eval/claims.jsonl` (Task 2), `eval/labels/<id>.json` (Task 3),
  `core.llm.capture_usage()` (Task 1), `core.pipeline.classify_stance(claim,
  snips, cfg) -> list[Snippet]` (mutates + returns `snips`, sets
  `.stance`/`.confidence`), `core.squeeze.compress_snippets(claim, snips,
  cfg) -> dict` (mutates `snips[i].text` in place when `cfg.compress`),
  `core.schema.Config`, `core.schema.Snippet`, `core.schema.Source`.
- Produces: `eval/results.jsonl` (one row per claim per config:
  `{"claim_id", "config", "accuracy" (float or null), "n_labeled",
  "n_snippets", "tokens", "latency_s"}`) and a printed 3-row summary table
  (mean accuracy / mean tokens / mean latency per config) to stdout.

- [ ] **Step 1: Write `eval/evaluate.py`**

```python
"""Ablation: how abstracts are fed to core.pipeline.classify_stance's E2B
stance stage, at equal per-snippet token/word budget across three configs —
raw / truncated / compressed. Reuses classify_stance and compress_snippets
unmodified; only the input Snippet.text differs per config.

Needs eval/labels/<id>.json already cached (eval/cache_snippets.py) and
human-filled gold_stance values, plus a live vLLM endpoint (same env as the
rest of the pipeline: VLLM_MODEL / VLLM_MODEL_E2B, VLLM_BASE_URL).
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from pathlib import Path

from core import llm
from core.pipeline import classify_stance
from core.schema import Config, Snippet, Source
from core.squeeze import compress_snippets

ROOT = Path(__file__).parent
CLAIMS_PATH = ROOT / "claims.jsonl"
LABELS_DIR = ROOT / "labels"
RESULTS_PATH = ROOT / "results.jsonl"

CONFIG_NAMES = ("raw", "truncated", "compressed")


def _load_claims() -> list[dict]:
    rows = [json.loads(line) for line in CLAIMS_PATH.read_text().splitlines() if line.strip()]
    return sorted(rows, key=lambda r: r["id"])


def _load_rows(claim_id: str) -> list[dict] | None:
    path = LABELS_DIR / f"{claim_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _to_snippets(rows: list[dict]) -> list[Snippet]:
    return [Snippet(id=r["id"], text=r["text"], stance=r["stance"],
                    confidence=r["confidence"], source=Source(**r["source"]))
            for r in rows]


def _word_truncate(text: str, n_words: int) -> str:
    return " ".join(text.split()[:n_words])


def _accuracy(snips: list[Snippet], gold: dict[str, str]) -> tuple[float | None, int]:
    labeled = [(s, gold[s.id]) for s in snips if gold.get(s.id)]
    if not labeled:
        return None, 0
    correct = sum(1 for s, g in labeled if s.stance == g)
    return correct / len(labeled), len(labeled)


async def _run_stance(claim: str, snips: list[Snippet], cfg: Config) -> dict:
    with llm.capture_usage() as usage:
        t0 = time.perf_counter()
        await classify_stance(claim, snips, cfg)
        latency = time.perf_counter() - t0
    tokens = sum(u["prompt_tokens"] for u in usage)
    return {"tokens": tokens, "latency_s": round(latency, 3)}


async def _evaluate_claim(claim_id: str, claim: str, rows: list[dict]) -> list[dict]:
    gold = {r["id"]: r["gold_stance"] for r in rows if r.get("gold_stance")}
    n_snippets = len(rows)

    # compressed FIRST — truncated's word budget must match what it produced
    compressed = _to_snippets(copy.deepcopy(rows))
    compress_cfg = Config()
    compress_cfg.compress = True
    compress_cfg.compress_budget = 0.4
    await compress_snippets(claim, compressed, compress_cfg)
    word_budgets = {s.id: len(s.text.split()) for s in compressed}
    compressed_metrics = await _run_stance(claim, compressed, compress_cfg)

    raw = _to_snippets(copy.deepcopy(rows))
    raw_metrics = await _run_stance(claim, raw, Config())

    truncated = _to_snippets(copy.deepcopy(rows))
    for s in truncated:
        s.text = _word_truncate(s.text, word_budgets.get(s.id, len(s.text.split())))
    truncated_metrics = await _run_stance(claim, truncated, Config())

    out = []
    for name, snips, metrics in (
        ("raw", raw, raw_metrics),
        ("truncated", truncated, truncated_metrics),
        ("compressed", compressed, compressed_metrics),
    ):
        acc, n_labeled = _accuracy(snips, gold)
        out.append({
            "claim_id": claim_id, "config": name,
            "accuracy": acc, "n_labeled": n_labeled, "n_snippets": n_snippets,
            **metrics,
        })
    return out


def _print_summary(rows: list[dict]) -> None:
    print(f"\n{'config':<12}{'mean accuracy':<16}{'mean tokens':<14}{'mean latency_s':<16}")
    for name in CONFIG_NAMES:
        cfg_rows = [r for r in rows if r["config"] == name]
        accs = [r["accuracy"] for r in cfg_rows if r["accuracy"] is not None]
        mean_acc = sum(accs) / len(accs) if accs else float("nan")
        mean_tok = sum(r["tokens"] for r in cfg_rows) / len(cfg_rows)
        mean_lat = sum(r["latency_s"] for r in cfg_rows) / len(cfg_rows)
        print(f"{name:<12}{mean_acc:<16.3f}{mean_tok:<14.1f}{mean_lat:<16.3f}")


async def main() -> None:
    all_rows: list[dict] = []
    for c in _load_claims():
        rows = _load_rows(c["id"])
        if rows is None:
            print(f"  skip  {c['id']}  (no eval/labels/{c['id']}.json — run cache_snippets.py first)")
            continue
        print(f"  eval  {c['id']}  {c['claim']!r}")
        all_rows.extend(await _evaluate_claim(c["id"], c["claim"], rows))

    with RESULTS_PATH.open("w") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")

    _print_summary(all_rows)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Confirm `core.schema.Config` accepts ad-hoc `compress` /
  `compress_budget` attributes**

`Config` is a plain (non-frozen, non-`__slots__`) `@dataclass`, so
`compress_cfg.compress = True` after construction is legal Python — matches
`core/squeeze.py`'s own `getattr(cfg, "compress", False)` /
`getattr(cfg, "compress_budget", 0.4)` pattern, which exists precisely
because `Config` doesn't declare those fields. No changes needed to
`core/schema.py`.

- [ ] **Step 3: Dry-run with a tiny hand-built fixture (no network, no model)**

This checks the accuracy/word-truncation/reporting logic in isolation before
spending real vLLM calls. Run:

```bash
python - <<'EOF'
from eval.evaluate import _accuracy, _word_truncate
from core.schema import Snippet, Source

src = Source(None, "t", [], 2020, "j", None, "openaire")
snips = [Snippet("s1", "x", "SUPPORTS", 0.9, src), Snippet("s2", "x", "REFUTES", 0.9, src)]
gold = {"s1": "SUPPORTS", "s2": "SUPPORTS"}
acc, n = _accuracy(snips, gold)
assert (acc, n) == (0.5, 2), (acc, n)
assert _word_truncate("a b c d e", 3) == "a b c"
print("evaluate.py pure-logic checks OK")
EOF
```

Expected: `evaluate.py pure-logic checks OK`.

- [ ] **Step 4: Full run against live vLLM + cached labels**

Requires: `eval/cache_snippets.py` already run (Task 3), at least a few
`gold_stance` values hand-filled in `eval/labels/*.json`, and a running vLLM
endpoint (`VLLM_BASE_URL` / `VLLM_MODEL` set, e.g. via `docker compose up
-d`).

Run: `uv run python -m eval.evaluate`
Expected: an `eval  cNN  '<claim>'` line per claim, then a 3-row summary
table (`raw` / `truncated` / `compressed`, each with mean accuracy / mean
tokens / mean latency_s), and `eval/results.jsonl` written with one row per
claim per config.

- [ ] **Step 5: Commit**

```bash
git add eval/evaluate.py
git commit -m "feat: add three-config stance-feeding ablation evaluator"
```

---

## Self-Review Notes

- **Spec coverage:** claims.jsonl (Task 2) · cache_snippets.py writing
  `asdict` + `gold_stance: null`, skip-if-exists (Task 3) · evaluate.py's
  three configs at equal token budget, deepcopy-per-config, compressed-before
  -truncated ordering, accuracy/tokens/latency recording, results.jsonl +
  summary table, fixed id order, temperature 0 (already in `llm.generate`)
  (Task 4) · reuse of `classify_stance`/`compress_snippets`/`_model_for`
  throughout · real (not approximated) token counts via Task 1's usage hook.
- **Type consistency:** `_run_stance` returns `{"tokens": int, "latency_s":
  float}`, consumed identically in `_evaluate_claim`'s three call sites.
  `_accuracy` returns `(float | None, int)` everywhere it's used.
- **No placeholders:** every step has literal code, not a description of
  code.
