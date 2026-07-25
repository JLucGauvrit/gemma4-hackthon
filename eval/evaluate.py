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
        mean_tok = sum(r["tokens"] for r in cfg_rows) / len(cfg_rows) if cfg_rows else float("nan")
        mean_lat = sum(r["latency_s"] for r in cfg_rows) / len(cfg_rows) if cfg_rows else float("nan")
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
