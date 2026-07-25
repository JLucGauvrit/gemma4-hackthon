"""Devil's Advocates — stream-first orchestration spine.

`run()` is an async generator yielding typed events as each stage completes;
`run_to_brief()` drains it into a Brief for the notebook / eval. All model calls
go through `llm.generate` (Gemma via Ollama; Brev at deploy). Retrieval is live
OpenAIRE. The self-check covers the pure logic (enforcement, budgeting, the
partition toggle, asymmetry, guardrail) with no model or network.

Event shapes (dicts with a "type"):
  {"type": "claim_text", "claim": str}
  {"type": "snippet", "snippet": Snippet}
  {"type": "stance", "id": str, "stance": Stance}
  {"type": "partition", "for": [id...], "against": [id...]}
  {"type": "turn_claim", "side": "FOR"|"AGAINST", "round": int, "claim": Claim}
  {"type": "violation", "side": ..., "claim": str, "reason": str}
  {"type": "crux", "crux": str, "crux_type": CruxType, "resolver": str}
  {"type": "brief", "brief": Brief}          # terminal event
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from typing import AsyncIterator

from core import llm
from core.schema import (
    Brief, Claim, Config, Position, Snippet, Source, Stance, Turn,
)

# ---------------------------------------------------------------- stages

async def extract(question: str, cfg: Config) -> tuple[str, str]:
    """Free text -> (testable claim, OpenAIRE search query). One E2B call.
    The query must include disambiguating terms (e.g. 'supplementation') so the
    search doesn't drift to unrelated papers that merely share a word."""
    raw = await llm.generate(
        "extract", tier=cfg.tiers["extract"],
        prompt=(f"Question: {question}\n"
                'Return JSON {"claim": "<one testable scientific claim>", '
                '"query": "<2-3 space-separated search keywords, incl. a '
                'disambiguating term like supplementation>"}. '
                "query MUST be a single string, not a list."),
    )
    d = llm.parse_json(raw)
    q = d["query"]
    if isinstance(q, list):                       # models wander — coerce shape
        q = " ".join(str(x) for x in q)
    q = " ".join(str(q).split()[:3])              # cap to 3 AND-terms — OpenAIRE AND
    return str(d["claim"]), q                      # search collapses on too many terms


async def retrieve(query: str, cfg: Config) -> list[Snippet]:
    """Live OpenAIRE retrieval (needs one browser login the first time)."""
    from core.retrieve import retrieve_openaire
    return await retrieve_openaire(query, cfg.max_snippets)


async def classify_stance(claim: str, snips: list[Snippet], cfg: Config) -> list[Snippet]:
    """3-way stance of each abstract vs the claim. One batched E2B call."""
    raw = await llm.generate(
        "stance", tier=cfg.tiers["stance"],
        prompt=_stance_prompt(claim, snips),
    )
    by_id = {d["id"]: d for d in _normalize_stance(llm.parse_json(raw))}
    for s in snips:
        d = by_id.get(s.id, {})
        s.stance = d.get("stance", "NEUTRAL")
        # models often omit confidence — default by whether they took a side
        s.confidence = float(d.get("confidence", 0.7 if s.stance != "NEUTRAL" else 0.3))
    return snips


def _normalize_stance(parsed) -> list[dict]:
    """Accept the shapes a model actually emits: a list, a single object, or a
    {id: stance} / {id: {...}} mapping."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        if "id" in parsed:                       # single {"id","stance"}
            return [parsed]
        return [{"id": k, **(v if isinstance(v, dict) else {"stance": v})}
                for k, v in parsed.items()]      # {id: stance} mapping
    return []


def budget(snips: list[Snippet], cfg: Config) -> tuple[list[Snippet], list[Snippet]]:
    """Top-k per side by confidence. partition ON (default) => disjoint piles.
    shared_evidence => both advocates get the SAME full pile (the ablation)."""
    def top(stance: Stance) -> list[Snippet]:
        pool = [s for s in snips if s.stance == stance]
        return sorted(pool, key=lambda s: s.confidence, reverse=True)[: cfg.top_k_per_side]

    if cfg.shared_evidence:                       # partition OFF — control
        shared = top("SUPPORTS") + top("REFUTES")
        return shared, shared
    return top("SUPPORTS"), top("REFUTES")        # partition ON — the debate


def _enforce_cites(claim: Claim, allowed: set[str]) -> tuple[Claim | None, str | None]:
    """Provenance enforced in code (§4.3), not by the model's taste.
    Drop cites outside the partition; drop the whole claim if nothing is left."""
    kept = [c for c in claim.cites if c in allowed]
    dropped = [c for c in claim.cites if c not in allowed]
    if not kept:
        return None, f"no valid citation (had {claim.cites})"
    reason = f"dropped out-of-partition cites {dropped}" if dropped else None
    return Claim(text=claim.text, cites=kept), reason


async def advocate(side: str, claim: str, partition: list[Snippet], rnd: int,
                   cfg: Config, opponent: list[Claim] | None = None) -> AsyncIterator[dict]:
    """One stance-locked advocate. Yields its (enforced) claims as events."""
    allowed = {s.id for s in partition}
    raw = await llm.generate(
        "advocate", tier=cfg.tiers["advocate"],
        prompt=_advocate_prompt(side, claim, partition, opponent),
    )
    for c in _parse_claims(raw):
        kept, reason = _enforce_cites(c, allowed)
        if kept is None:
            yield {"type": "violation", "side": side, "claim": c.text, "reason": reason}
            continue
        if reason:
            yield {"type": "violation", "side": side, "claim": c.text, "reason": reason}
        yield {"type": "turn_claim", "side": side, "round": rnd, "claim": kept}


async def judge(claim: str, transcript: list[Turn], for_pile: list[Snippet],
                against_pile: list[Snippet], cfg: Config) -> dict:
    """Names the crux; does NOT pick a winner. v1 = single call (swap later)."""
    raw = await llm.generate(
        "judge", tier=cfg.tiers["judge"],
        prompt=_judge_prompt(claim, transcript),
    )
    d = llm.parse_json(raw)
    if isinstance(d, list):
        d = d[0] if d else {}
    ct = d.get("crux_type", "none")
    valid = {"population", "methodology", "timeframe",
             "measured-construct", "effect-size", "none"}
    return {
        "crux": str(d.get("crux", "")),
        "crux_type": ct if ct in valid else "none",
        "resolver": str(d.get("resolver", "")),
        "asymmetry": _asymmetry(for_pile, against_pile),
    }


def _asymmetry(for_pile: list[Snippet], against_pile: list[Snippet]) -> float:
    """0.0 even split … 1.0 one-sided. Weighted by classifier confidence."""
    wf = sum(s.confidence for s in for_pile)
    wa = sum(s.confidence for s in against_pile)
    return 0.0 if wf + wa == 0 else abs(wf - wa) / (wf + wa)


# ---------------------------------------------------------------- orchestration

async def run(question: str, cfg: Config | None = None) -> AsyncIterator[dict]:
    cfg = cfg or Config()
    t0 = time.perf_counter()

    claim, query = await extract(question, cfg)
    yield {"type": "claim_text", "claim": claim, "query": query}

    snips = await retrieve(query, cfg)
    for s in snips:
        yield {"type": "snippet", "snippet": s}

    snips = await classify_stance(claim, snips, cfg)
    for s in snips:
        yield {"type": "stance", "id": s.id, "stance": s.stance}

    for_pile, against_pile = budget(snips, cfg)
    yield {"type": "partition",
           "for": [s.id for s in for_pile], "against": [s.id for s in against_pile]}

    # Out-of-scope guardrail (§9): not enough on-topic evidence to stage a debate.
    on_topic = len(for_pile) + len(against_pile)
    if on_topic < cfg.min_evidence:
        yield {"type": "out_of_scope", "on_topic": on_topic}
        yield {"type": "brief", "brief": Brief(
            claim=claim,
            position_for=Position("", [], []), position_against=Position("", [], []),
            crux="Not enough on-topic evidence to construct a debate — this may not "
                 "be a contested scientific claim.",
            crux_type="none",
            resolver="Try a specific, testable scientific claim.",
            asymmetry=1.0, transcript=[],
            meta={"latency_s": round(time.perf_counter() - t0, 3),
                  "tiers": cfg.tiers, "out_of_scope": True, "on_topic": on_topic})}
        return

    # Upgrade the partitioned snippets to FULL abstracts before the advocates
    # argue — the search endpoint truncates before the result sentence.
    from core.retrieve import enrich_full_abstracts
    await enrich_full_abstracts(for_pile + against_pile)
    yield {"type": "enriched", "count": len(for_pile) + len(against_pile)}

    # Two advocates stream in parallel, interleaved into one event stream.
    for_claims: list[Claim] = []
    against_claims: list[Claim] = []
    streams = [
        advocate("FOR", claim, for_pile, 0, cfg),
        advocate("AGAINST", claim, against_pile, 0, cfg),
    ]
    async for ev in _merge(streams):
        if ev["type"] == "turn_claim":
            (for_claims if ev["side"] == "FOR" else against_claims).append(ev["claim"])
        yield ev

    transcript = [
        Turn(agent="FOR", round=0, claims=for_claims),
        Turn(agent="AGAINST", round=0, claims=against_claims),
    ]

    verdict = await judge(claim, transcript, for_pile, against_pile, cfg)
    yield {"type": "crux", "crux": verdict["crux"],
           "crux_type": verdict["crux_type"], "resolver": verdict["resolver"]}

    brief = Brief(
        claim=claim,
        position_for=Position("", for_claims, [s.source for s in for_pile]),
        position_against=Position("", against_claims, [s.source for s in against_pile]),
        crux=verdict["crux"], crux_type=verdict["crux_type"], resolver=verdict["resolver"],
        asymmetry=verdict["asymmetry"], transcript=transcript,
        meta={"latency_s": round(time.perf_counter() - t0, 3),
              "tiers": cfg.tiers, "shared_evidence": cfg.shared_evidence},
    )
    yield {"type": "brief", "brief": brief}


async def run_to_brief(question: str, cfg: Config | None = None) -> Brief:
    """Drain the stream, return the final Brief. For notebook + eval."""
    brief = None
    async for ev in run(question, cfg):
        if ev["type"] == "brief":
            brief = ev["brief"]
    assert brief is not None, "pipeline ended without a brief"
    return brief


async def _merge(aiters: list[AsyncIterator[dict]]) -> AsyncIterator[dict]:
    """Fan two+ async generators into one stream, order = arrival."""
    q: asyncio.Queue = asyncio.Queue()

    async def drain(ai):
        try:
            async for x in ai:
                await q.put(("item", x))
        finally:
            await q.put(("done", None))

    tasks = [asyncio.create_task(drain(ai)) for ai in aiters]
    remaining = len(tasks)
    while remaining:
        kind, x = await q.get()
        if kind == "done":
            remaining -= 1
        else:
            yield x
    await asyncio.gather(*tasks)


# ---------------------------------------------------------------- prompts (real backend)

def _advocate_prompt(side, claim, partition, opponent):
    ev = "\n".join(f"[{s.id}] {s.text}" for s in partition)
    opp = "" if not opponent else "\nOpponent claims (rebut, do not cite their evidence):\n" + \
        "\n".join(f"- {c.text}" for c in opponent)
    return (f"You argue {side} the claim: {claim}\n"
            f"Make 2-3 short claims, each grounded in the evidence below. Cite ONLY "
            f"these snippet ids using the bare id (e.g. s1). Every claim needs ≥1 "
            f"cite. Argue the strongest {side} case the evidence allows.\n{ev}{opp}\n"
            'Return a JSON list ONLY: [{"text": "<claim>", "cites": ["s1"]}]')


def _stance_prompt(claim, snips):
    items = "\n".join(f'[{s.id}] {s.text[:600]}' for s in snips)
    return (f"Claim: {claim}\nClassify each snippet's stance toward THIS claim. "
            "SUPPORTS = evidence the claim is true; REFUTES = evidence it is false; "
            "NEUTRAL = not about this claim's intervention/outcome (mark off-topic "
            f"snippets NEUTRAL).\n{items}\n"
            'Return a JSON list: [{"id": "s1", "stance": "SUPPORTS", "confidence": 0.8}]')


def _judge_prompt(claim, transcript):
    return (f"Claim: {claim}\nTranscript: {transcript}\n"
            "Identify the crux (where the sides diverge). Do NOT pick a winner.\n"
            'Return JSON: {"crux": "...", "crux_type": "population|methodology|'
            'timeframe|measured-construct|effect-size|none", "resolver": "..."}')


_CLAIM_KEYS = ("text", "argument", "claim", "statement")
_CITE_KEYS = ("cites", "citations", "sources", "ids")


def _norm_cite(x) -> str:
    """'[s12]' / ' s12 ' / 's12.' -> 's12'. Models format cites loosely."""
    m = re.search(r"[sS]\d+", str(x))
    return m.group(0).lower() if m else ""


def _parse_claims(raw: str) -> list[Claim]:
    """Tolerant to the shapes models emit: list or single object; claim text
    under text/argument/claim; cites under cites/citations and bracket-wrapped."""
    parsed = llm.parse_json(raw)
    if isinstance(parsed, dict):
        if any(k in parsed for k in _CLAIM_KEYS):     # a single claim object
            parsed = [parsed]
        else:                                          # {"claims":[...]} etc.
            parsed = next((v for v in parsed.values() if isinstance(v, list)), [])
    out = []
    for c in parsed:
        if not isinstance(c, dict):
            continue
        text = next((c[k] for k in _CLAIM_KEYS if c.get(k)), None)
        if not text:
            continue
        raw_cites = next((c[k] for k in _CITE_KEYS if c.get(k)), [])
        if isinstance(raw_cites, str):
            raw_cites = [raw_cites]
        cites = [n for n in (_norm_cite(x) for x in raw_cites) if n]
        out.append(Claim(text=str(text), cites=cites))
    return out


# ---------------------------------------------------------------- entry + self-check

async def _main(question: str):
    async for ev in run(question):
        if ev["type"] == "brief":
            b = ev["brief"]
            print(f"\nCLAIM   {b.claim}")
            print(f"FOR     {len(b.position_for.claims)} claims · {len(b.position_for.sources)} sources")
            print(f"AGAINST {len(b.position_against.claims)} claims · {len(b.position_against.sources)} sources")
            print(f"CRUX    [{b.crux_type}] {b.crux}")
            print(f"RESOLVE {b.resolver}")
            print(f"ASYMM   {b.asymmetry:.2f}   meta={b.meta}")
        elif ev["type"] == "turn_claim":
            c = ev["claim"]
            print(f"  {ev['side']:<7} {c.text}  cites={c.cites}")
        elif ev["type"] == "violation":
            print(f"  DROP    {ev['side']} '{ev['claim']}' — {ev['reason']}")
        elif ev["type"] == "out_of_scope":
            print(f"  OUT OF SCOPE — only {ev['on_topic']} on-topic sources; refusing to fake a debate")


def _selfcheck():
    """Pure-logic checks — no model, no network. Guards the enforcement,
    budgeting, asymmetry and guardrail that make the debate honest."""
    def snip(sid, stance, conf):
        return Snippet(sid, "x", stance, conf,
                       Source(f"10/{sid}", "T", [], 2020, "J", None, "openaire"))

    snips = [snip("s1", "SUPPORTS", 0.9), snip("s2", "SUPPORTS", 0.8),
             snip("s3", "REFUTES", 0.7), snip("s4", "NEUTRAL", 0.2)]

    # partition ON => SUPPORTS to FOR, REFUTES to AGAINST, disjoint, NEUTRAL dropped
    f, a = budget(snips, Config())
    assert {s.id for s in f} == {"s1", "s2"} and {s.id for s in a} == {"s3"}, "partition split wrong"
    assert {s.id for s in f}.isdisjoint({s.id for s in a}), "piles must be disjoint"

    # ablation flag => both advocates get the SAME pile
    sf, sa = budget(snips, Config(shared_evidence=True))
    assert [s.id for s in sf] == [s.id for s in sa] and sf, "shared_evidence must share the pile"

    # citation enforced in code: out-of-partition cite dropped; no-valid-cite claim killed
    kept, _ = _enforce_cites(Claim("t", ["s1", "s99"]), {"s1"})
    assert kept and kept.cites == ["s1"], "out-of-partition cite must be dropped"
    dead, _ = _enforce_cites(Claim("t", ["s99"]), {"s1"})
    assert dead is None, "claim with no valid cite must be dropped"

    # asymmetry: uneven piles > 0, balanced == 0
    assert _asymmetry(f, a) > 0, "uneven piles => asymmetry > 0"
    assert _asymmetry([snip("a", "SUPPORTS", 1.0)], [snip("b", "REFUTES", 1.0)]) < 1e-9, "balanced => 0"

    # guardrail: all-NEUTRAL evidence falls below the on-topic floor
    gf, ga = budget([snip("n1", "NEUTRAL", 0.1)], Config())
    assert len(gf) + len(ga) < Config().min_evidence, "all-neutral must trip the guardrail"

    print("selfcheck OK — budget split, disjoint, ablation, cite-enforce, asymmetry, guardrail")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else "does creatine improve cognition?"))
