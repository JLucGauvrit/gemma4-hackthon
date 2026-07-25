"""Question-aware compression of retrieved abstracts, for the E2B stages.

An abstract carries one or two stance-bearing sentences (the finding) buried in
methods/background. Feeding whole abstracts to E2B for every snippet is what
drowns the small model. compress_snippets() keeps the sentences most relevant to
the CLAIM and always keeps numeric/statistical sentences, scored with E2B's own
prompt logprobs — the same served model that reasons downstream. Gemma
compresses for Gemma.

Contrastive score (LongLLMLingua, sentence-level): a sentence relevant to the
claim gets more predictable once the claim precedes it. Rank by that gain, keep
to a token budget. Absolute perplexity is noisy; the with/without difference
cancels the model's baseline noise — which matters here (see the French-vs-
English rank gap we measured).
"""
from __future__ import annotations

import asyncio
import os
import re

import httpx
import numpy as np

from core import llm
from core.schema import Config, Snippet, Source

_KEEP = re.compile(r"\d|%|\bp\s*[=<>]|\bCI\b|\bn\s*=|doi|et al", re.I)


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]


async def _prompt_logprobs(client, model, base_url, prompts: list[str]) -> list[list[float]]:
    """Per-token logprob of each prompt. No generation — prompt_logprobs only."""
    r = await client.post(f"{base_url}/completions", json={
        "model": model, "prompt": prompts,
        "max_tokens": 1, "temperature": 0, "prompt_logprobs": 0,
    })
    r.raise_for_status()
    data = r.json()
    if "choices" not in data:
        raise RuntimeError(data)  # surface vLLM errors instead of a KeyError
    return [[next(iter(d.values()))["logprob"] for d in ch["prompt_logprobs"] if d]
            for ch in data["choices"]]


def _select_indices(sents: list[str], score, forced: set[int], target_words: int) -> list[int]:
    """Forced (numeric/stat) sentences are ALWAYS kept, unconditionally; remaining
    budget is filled by score desc. A budget tight enough to fit only one ranked
    sentence must still not drop a second forced sentence — that's the bug a
    single combined budget+forced sort loop can hide when several sentences tie
    on the forced boost."""
    keep = set(forced)
    total = sum(len(sents[i].split()) for i in keep)
    for i in np.argsort(-np.asarray(score, dtype=float)):
        i = int(i)
        if i in keep:
            continue
        if total >= target_words:
            break
        keep.add(i)
        total += len(sents[i].split())
    return sorted(keep)


async def _compress_one(client, model, base_url, claim: str, text: str, budget: float) -> str:
    sents = _sentences(text)
    if len(sents) <= 2:
        return text  # nothing to gain
    prefix = f"Claim: {claim}\n\nContext: "
    bare = await _prompt_logprobs(client, model, base_url, sents)
    cond = await _prompt_logprobs(client, model, base_url, [prefix + s for s in sents])
    score = np.array([
        (np.mean(c[-len(b):]) - np.mean(b)) if b else -9.0
        for b, c in zip(bare, cond)
    ])
    forced = {i for i, s in enumerate(sents) if _KEEP.search(s)}
    target = max(1, int(len(text.split()) * budget))
    keep = _select_indices(sents, score, forced, target)
    return " ".join(sents[i] for i in keep)  # keeps original order


async def compress_snippets(claim: str, snips: list[Snippet], cfg: Config) -> dict:
    """Mutate snip.text in place when cfg.compress. Returns token metrics for meta."""
    if not cfg.compress:
        return {"compressed": False}
    model = llm._model_for("E2B")
    base_url = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")
    budget = cfg.compress_budget
    before = sum(len(s.text.split()) for s in snips)
    async with httpx.AsyncClient(timeout=180) as client:
        out = await asyncio.gather(*(
            _compress_one(client, model, base_url, claim, s.text, budget) for s in snips
        ))
    for s, text in zip(snips, out):
        s.text = text
    after = sum(len(s.text.split()) for s in snips)
    return {"compressed": True, "tokens_before": before, "tokens_after": after,
            "ratio": round(after / before, 3) if before else 1.0, "budget": budget}


# ---------------------------------------------------------------- self-check (offline)

def _selfcheck():
    """Pure-logic checks for the sentence selector — no model, no network.
    Separate from core.pipeline._selfcheck (which stays untouched)."""
    sents = ["Alpha finding is interesting today.", "Beta context sentence here now.",
             "Gamma had p=0.03 result.", "Delta had n=42 result.",
             "Epsilon closing remark right.", "Zeta unrelated aside."]
    score = np.array([5.0, 1.0, 0.5, 0.5, 0.2, 0.1])  # Alpha ranks highest before forcing
    forced = {2, 3}  # both numeric/stat sentences must survive regardless of budget

    # tight budget that would fit only ~1 ranked sentence without forcing
    keep = _select_indices(sents, score, forced, target_words=5)
    assert forced <= set(keep), f"forced sentences must ALWAYS be kept, got {keep}"
    assert keep == sorted(keep), "must preserve original sentence order"

    # no forced sentences: plain budget-limited top-k by score (Alpha=5.0, Beta=1.0)
    keep2 = _select_indices(sents, score, forced=set(), target_words=10)
    assert keep2 == [0, 1], f"expected top-2 scored sentences (0, 1), got {keep2}"

    # _KEEP regex matches the numeric/stat patterns the contract requires
    for s in ("n=42 participants", "p<0.05 significant", "a 12% increase",
              "95% CI reported", "Smith et al. 2020", "doi:10.1/x"):
        assert _KEEP.search(s), f"_KEEP must match: {s!r}"
    assert not _KEEP.search("a purely qualitative discussion"), "_KEEP must not over-match"

    print("squeeze selfcheck OK — forced-keep, order-preserving selection, _KEEP regex")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        # live smoke test: needs a running vLLM server (VLLM_BASE_URL / VLLM_MODEL*)
        claim = "creatine improves cognition in healthy adults"
        abstract = (
            "Creatine is a popular dietary supplement among athletes. "
            "It is synthesized endogenously from amino acids. "
            "In this randomized controlled trial, 45 healthy adults received "
            "5g/day of creatine monohydrate or placebo for 6 weeks. "
            "Working memory scores improved significantly in the creatine group "
            "(p=0.02, n=45). "
            "No adverse events were reported during the study period. "
            "These findings suggest creatine may support cognitive performance "
            "under conditions of sleep deprivation or high cognitive demand."
        )
        snip = Snippet(
            id="s1", text=abstract, stance="NEUTRAL", confidence=0.0,
            source=Source(None, "T", [], 2020, "J", None, "openaire"),
        )

        async def _smoke():
            cfg = Config(compress=True, compress_budget=0.4)
            result = await compress_snippets(claim, [snip], cfg)
            print("result:", result)
            print("compressed text:", snip.text)
            assert result["compressed"] is True
            assert result["tokens_before"] > result["tokens_after"], \
                "compression should shorten the abstract"
            assert re.search(r"p\s*=\s*0\.02", snip.text), \
                "the p-value sentence must survive compression"
            print("smoke OK")

        asyncio.run(_smoke())
