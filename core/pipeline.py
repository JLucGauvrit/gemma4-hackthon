"""Devil's Advocates — stream-first orchestration spine.

`run()` is an async generator yielding typed events as each stage completes;
`run_to_brief()` drains it into a Brief for the notebook / eval. All model calls
go through `llm.generate` (Gemma via Ollama; Brev at deploy). Retrieval is live
OpenAIRE. The self-check covers the pure logic (enforcement, budgeting, the
partition toggle, asymmetry, guardrail) with no model or network.

Event shapes (dicts with a "type"):
  {"type": "phase", "phase": "opening"|"rebuttal"|"judging"}
  {"type": "claim_text", "claim": str}
  {"type": "snippet", "snippet": Snippet}
  {"type": "stance", "id": str, "stance": Stance, "confidence": float, "reason": str}
  {"type": "partition", "for": [id...], "against": [id...]}
  {"type": "turn_claim", "side": "FOR"|"AGAINST", "round": int, "claim": Claim}
  {"type": "violation", "side": ..., "claim": str, "reason": str}
  {"type": "insufficient_evidence", "on_topic": int, "reason": str}
  {"type": "crux", "crux": str, "crux_type": CruxType, "resolver": str}
  {"type": "brief", "brief": Brief}          # terminal event
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from typing import AsyncIterator, Awaitable, Callable

from core import llm
from core.schema import (
    Brief, Claim, Config, Position, Snippet, Source, Stance, Turn, Verdict,
)

Ask = Callable[[str], Awaitable[str]]  # intake's way to ask the user back (interactive)

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
    return str(d["claim"]), _clean_query(d["query"])  # OpenAIRE AND collapses on >3 terms


async def intake_decide(text: str, cfg: Config) -> dict:
    """Front gate: is this a testable scientific claim, a vague topic that needs
    one clarifying question, or not science at all? One E2B call, tagged union.
    Kills 'how many windows in Paris' before it burns retrieval + 3 model calls."""
    raw = await llm.generate(
        "extract", tier=cfg.tiers["extract"], prompt=_intake_prompt(text))
    d = llm.parse_json(raw)
    if isinstance(d, list):
        d = d[0] if d else {}
    return d if isinstance(d, dict) else {}


async def summarize_consensus(claim: str, dominant: list[Snippet],
                              dominant_stance: Stance, cfg: Config) -> dict:
    """When the evidence is one-sided, say so — and source it. Not 'won't fake a
    fight': a positive verdict ('established by [s1][s2]…') plus any real dissent."""
    raw = await llm.generate(
        "judge", tier=cfg.tiers["judge"],
        prompt=_consensus_prompt(claim, dominant, dominant_stance))
    d = llm.parse_json(raw)
    if isinstance(d, list):
        d = d[0] if d else {}
    d = d if isinstance(d, dict) else {}
    return {"statement": str(d.get("statement", "")), "dissent": str(d.get("dissent", ""))}


async def retrieve(query: str, cfg: Config) -> list[Snippet]:
    """Live OpenAIRE retrieval (needs one browser login the first time)."""
    from core.retrieve import retrieve_openaire
    return await retrieve_openaire(query, cfg.max_snippets)


async def classify_stance(claim: str, snips: list[Snippet], cfg: Config) -> list[Snippet]:
    """4-way stance of each abstract vs the claim, in small parallel batches.

    One mega-batch is the trap: Gemma+Ollama JSON-mode collapses ~24 items to a
    single object, so 23 snippets silently default NEUTRAL and every real claim
    misroutes to OUT_OF_SCOPE. Fix: batch small, then backfill any id the model
    dropped by re-asking it alone (a 1-item prompt can't collapse). Directional
    labels are also rechecked one-at-a-time because false positives determine the
    partition and can manufacture a consensus."""
    async def classify(batch: list[Snippet]) -> dict[str, dict]:
        if not batch:
            return {}
        raw = await llm.generate("stance", tier=cfg.tiers["stance"],
                                 prompt=_stance_prompt(claim, batch))
        return {d["id"]: d for d in _normalize_stance(llm.parse_json(raw))
                if isinstance(d, dict) and d.get("id")}

    n = max(1, cfg.stance_batch)
    by_id: dict[str, dict] = {}
    for res in await asyncio.gather(*(classify(snips[i:i + n]) for i in range(0, len(snips), n))):
        by_id.update(res)
    # backfill dropped ids one-at-a-time (reliable — nothing to truncate)
    missing = [s for s in snips if s.id not in by_id]
    for res in await asyncio.gather(*(classify([s]) for s in missing)):
        by_id.update(res)

    directional = [
        s for s in snips
        if by_id.get(s.id, {}).get("stance") in {"SUPPORTS", "REFUTES"}
    ]
    for res in await asyncio.gather(*(classify([s]) for s in directional)):
        by_id.update(res)

    valid = {"SUPPORTS", "REFUTES", "UNRESOLVED", "NEUTRAL"}
    for s in snips:
        d = by_id.get(s.id, {})
        st = d.get("stance", "NEUTRAL")
        s.stance = st if st in valid else "NEUTRAL"
        # models often omit confidence — default by whether they took a side
        s.confidence = float(d.get("confidence", 0.7 if s.stance != "NEUTRAL" else 0.3))
        s.stance_reason = str(d.get("reason", "")).strip()
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
    Unresolved evidence challenges accepting the claim but remains visibly distinct
    from direct refutation. shared_evidence gives both advocates the same full pile."""
    def top(stances: set[Stance]) -> list[Snippet]:
        pool = [s for s in snips if s.stance in stances]
        return sorted(pool, key=lambda s: s.confidence, reverse=True)[: cfg.top_k_per_side]

    if cfg.shared_evidence:                       # partition OFF — control
        shared = top({"SUPPORTS"}) + top({"REFUTES", "UNRESOLVED"})
        return shared, shared
    return top({"SUPPORTS"}), top({"REFUTES", "UNRESOLVED"})


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


def route(for_n: int, against_n: int, asymmetry: float, cfg: Config) -> Verdict:
    """The post-retrieval branch, as a pure function so the self-check can pin it.
    Too little evidence => refuse. A real body of evidence on one side with at
    most a lone dissenter on the other (or a very lopsided confidence weight) =>
    consensus. Two independent papers each side => debate. The lone-dissenter
    rule is what survives a single spurious stance classification."""
    if for_n + against_n < cfg.min_evidence:
        return "INSUFFICIENT_EVIDENCE"
    lo, hi = min(for_n, against_n), max(for_n, against_n)
    if lo < cfg.min_side and hi < cfg.min_consensus_evidence and lo != hi:
        return "INSUFFICIENT_EVIDENCE"
    if asymmetry >= cfg.consensus_asymmetry or lo < cfg.min_side <= hi:
        return "CONSENSUS"
    return "CONTESTED"


# ---------------------------------------------------------------- orchestration

async def run(question: str, cfg: Config | None = None,
              ask: Ask | None = None) -> AsyncIterator[dict]:
    """`ask` (interactive) lets intake bounce a clarifying question back to the
    user. None => non-interactive (CLI --no-ask, eval, notebook): intake never
    blocks; a would-be CLARIFY falls through to a best-guess extract()."""
    cfg = cfg or Config()
    t0 = time.perf_counter()

    # --- intake: turn free text into a testable claim, or clarify, or refuse ---
    # ponytail: a bounded bounce loop, not a graph runtime — LangGraph would add a
    # dependency and a state machine to wrap a 2-iteration for-loop. Skip it.
    convo, claim, query = question, None, None
    for attempt in range(cfg.max_clarify + 1):
        d = await intake_decide(convo, cfg)
        verdict = str(d.get("verdict", "")).upper()
        if verdict == "OUT_OF_SCOPE":
            yield {"type": "verdict", "verdict": "OUT_OF_SCOPE"}
            yield {"type": "brief", "brief": _oos_brief(
                question, str(d.get("reason") or "Not a testable scientific claim."),
                t0, cfg)}
            return
        if verdict == "CLAIM" and d.get("claim"):
            claim, query = str(d["claim"]), _clean_query(d.get("query", ""))
            break
        # CLARIFY (or a malformed reply). Ask the user once, unless we can't/are out
        # of rounds — then extract() a best-guess claim rather than hang.
        q = str(d.get("question") or "Can you restate that as a specific, testable claim?")
        if ask is None or attempt == cfg.max_clarify:
            claim, query = await extract(convo, cfg)
            break
        yield {"type": "clarify", "question": q}
        convo = f"{convo}\nUser clarification: {await ask(q)}"

    yield {"type": "claim_text", "claim": claim, "query": query}

    snips = await retrieve(query, cfg)
    # Search results are often truncated before the result sentence. Classification
    # must see the full abstract; enriching only after partitioning makes the stance
    # decision from an introduction and then locks that mistake into both piles.
    from core.retrieve import enrich_full_abstracts
    enriched = await enrich_full_abstracts(snips)
    yield {"type": "enriched", "count": enriched or 0}
    for s in snips:
        yield {"type": "snippet", "snippet": s}

    snips = await classify_stance(claim, snips, cfg)
    for s in snips:
        yield {
            "type": "stance",
            "id": s.id,
            "stance": s.stance,
            "confidence": s.confidence,
            "reason": s.stance_reason,
        }

    for_pile, against_pile = budget(snips, cfg)
    yield {"type": "partition",
           "for": [s.id for s in for_pile], "against": [s.id for s in against_pile]}

    # Three-way branch on what the evidence actually looks like (§9).
    on_topic = len(for_pile) + len(against_pile)
    asymmetry = _asymmetry(for_pile, against_pile)
    verdict = route(len(for_pile), len(against_pile), asymmetry, cfg)
    oos_reason = (
        "Not enough directional or unresolved evidence to construct a sourced "
        "debate from this retrieval."
    )
    if verdict == "CONSENSUS":
        dom_is_for = sum(s.confidence for s in for_pile) >= sum(
            s.confidence for s in against_pile
        )
        dominant = for_pile if dom_is_for else against_pile
        direct_stance = "SUPPORTS" if dom_is_for else "REFUTES"
        direct_count = sum(s.stance == direct_stance for s in dominant)
        if direct_count < cfg.min_consensus_evidence:
            verdict = "INSUFFICIENT_EVIDENCE"
            oos_reason = (
                "The retrieved evidence is predominantly unresolved; it does not "
                "contain enough direct results to claim scientific consensus."
            )
    yield {"type": "verdict", "verdict": verdict}

    if verdict == "INSUFFICIENT_EVIDENCE":
        yield {
            "type": "insufficient_evidence",
            "on_topic": on_topic,
            "reason": oos_reason,
        }
        yield {"type": "brief", "brief": _oos_brief(
            claim, oos_reason, t0, cfg, on_topic,
            resolver=(
                "Broaden retrieval or add direct intervention results before "
                "asking the advocates to take sides."
            ),
            verdict="INSUFFICIENT_EVIDENCE")}
        return

    if verdict == "CONSENSUS":
        # One-sided evidence: report the sourced consensus + any real dissent.
        # Weighted-heavier pile is the consensus direction.
        dom_is_for = sum(s.confidence for s in for_pile) >= sum(s.confidence for s in against_pile)
        dominant = for_pile if dom_is_for else against_pile
        minority = against_pile if dom_is_for else for_pile
        dom_stance: Stance = "SUPPORTS" if dom_is_for else "REFUTES"
        c = await summarize_consensus(claim, dominant, dom_stance, cfg)
        yield {"type": "crux", "crux": c["statement"], "crux_type": "none",
               "resolver": c["dissent"]}
        dom_pos = Position(c["statement"], [], [s.source for s in dominant])
        min_pos = Position(c["dissent"], [], [s.source for s in minority])
        yield {"type": "brief", "brief": Brief(
            claim=claim,
            position_for=dom_pos if dom_is_for else min_pos,
            position_against=min_pos if dom_is_for else dom_pos,
            crux=c["statement"], crux_type="none", resolver=c["dissent"],
            asymmetry=asymmetry, transcript=[],
            meta={"latency_s": round(time.perf_counter() - t0, 3), "tiers": cfg.tiers,
                  "shared_evidence": cfg.shared_evidence, "dominant": dom_stance},
            verdict="CONSENSUS")}
        return

    # Two advocates stream in parallel, interleaved into one event stream.
    for_claims: list[Claim] = []
    against_claims: list[Claim] = []
    yield {"type": "phase", "phase": "opening"}
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

    if cfg.rebuttal:
        for_rebuttals: list[Claim] = []
        against_rebuttals: list[Claim] = []
        yield {"type": "phase", "phase": "rebuttal"}
        rebuttal_streams = [
            advocate("FOR", claim, for_pile, 1, cfg, opponent=against_claims),
            advocate("AGAINST", claim, against_pile, 1, cfg, opponent=for_claims),
        ]
        async for ev in _merge(rebuttal_streams):
            if ev["type"] == "turn_claim":
                (for_rebuttals if ev["side"] == "FOR" else against_rebuttals).append(
                    ev["claim"]
                )
            yield ev
        transcript.extend([
            Turn(agent="FOR", round=1, claims=for_rebuttals),
            Turn(agent="AGAINST", round=1, claims=against_rebuttals),
        ])

    yield {"type": "phase", "phase": "judging"}
    v = await judge(claim, transcript, for_pile, against_pile, cfg)
    yield {"type": "crux", "crux": v["crux"],
           "crux_type": v["crux_type"], "resolver": v["resolver"]}

    brief = Brief(
        claim=claim,
        position_for=Position("", for_claims, [s.source for s in for_pile]),
        position_against=Position("", against_claims, [s.source for s in against_pile]),
        crux=v["crux"], crux_type=v["crux_type"], resolver=v["resolver"],
        asymmetry=v["asymmetry"], transcript=transcript,
        meta={"latency_s": round(time.perf_counter() - t0, 3),
              "tiers": cfg.tiers, "shared_evidence": cfg.shared_evidence},
        verdict="CONTESTED",
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


# ---------------------------------------------------------------- helpers

def _clean_query(q) -> str:
    """Models emit query as a list or an over-long string; OpenAIRE is keyword-AND
    so cap to 3 terms. Shared by extract() and intake()."""
    if isinstance(q, list):
        q = " ".join(str(x) for x in q)
    return " ".join(str(q).split()[:3])


def _oos_brief(claim: str, reason: str, t0: float, cfg: Config, on_topic: int = 0,
               resolver: str = "Try a specific, testable scientific claim.",
               verdict: Verdict = "OUT_OF_SCOPE") -> Brief:
    """The OUT_OF_SCOPE Brief — reached from intake (not a claim) or the post-
    retrieval floor (a claim, but no evidence). Same shape either way."""
    return Brief(
        claim=claim,
        position_for=Position("", [], []), position_against=Position("", [], []),
        crux=reason, crux_type="none",
        resolver=resolver,
        asymmetry=1.0, transcript=[],
        meta={"latency_s": round(time.perf_counter() - t0, 3),
              "tiers": cfg.tiers,
              "out_of_scope": verdict == "OUT_OF_SCOPE",
              "insufficient_evidence": verdict == "INSUFFICIENT_EVIDENCE",
              "on_topic": on_topic},
        verdict=verdict,
    )


# ---------------------------------------------------------------- prompts (real backend)

def _intake_prompt(text):
    return (f"Input: {text}\n"
            "Decide if this is a testable scientific claim we can debate from "
            "published research. Return JSON, exactly one of:\n"
            '{"verdict":"CLAIM","claim":"<one testable scientific claim>",'
            '"query":"<2-3 search keywords incl. a disambiguating term like '
            'supplementation>"}\n'
            '{"verdict":"CLARIFY","question":"<one short question to pin it to a '
            'specific claim>"}\n'
            '{"verdict":"OUT_OF_SCOPE","reason":"<why this is not a scientific claim>"}\n'
            "Rules: CLAIM only if there is a clear intervention/factor AND an "
            "outcome. A bare topic or single word (e.g. 'creatine') => CLARIFY. "
            "Not about science/health/research at all (e.g. counting windows, "
            "opinions, trivia) => OUT_OF_SCOPE. query MUST be a single string.")


def _consensus_prompt(claim, snips, dominant_stance):
    ev = "\n".join(f"[{s.id}] {s.text}" for s in snips)
    direction = "supports" if dominant_stance == "SUPPORTS" else "refutes"
    return (f"Claim: {claim}\nThe evidence below overwhelmingly {direction} this "
            f"claim — this is not a live controversy.\n{ev}\n"
            "State the consensus in 1-2 sentences, grounded in this evidence, and "
            "cite the snippet ids that establish it. Note any minor dissent or "
            "still-open parameter, or say there is none.\n"
            'Return JSON: {"statement":"<consensus, citing ids like [s1]>",'
            '"dissent":"<minor dissent / open parameter, or \'none\'>"}')


def _advocate_prompt(side, claim, partition, opponent):
    ev = "\n".join(f"[{s.id}] ({s.stance}) {s.text}" for s in partition)
    if opponent:
        task = (
            "Respond directly to the opponent's claims. Identify the specific point "
            "their evidence does not establish, while citing only your own evidence."
        )
        opp = "\nOpponent opening claims:\n" + "\n".join(
            f"- {c.text}" for c in opponent
        )
    else:
        task = f"Present the strongest opening case {side} the claim."
        opp = ""
    uncertainty_rule = (
        " An UNRESOLVED source supports withholding acceptance of the claim; it does "
        "NOT show no effect. Describe that distinction explicitly."
        if side == "AGAINST"
        else ""
    )
    return (f"You argue {side} the claim: {claim}\n"
            f"{task}{uncertainty_rule}\n"
            f"Make 1-2 short claims, each grounded in the evidence below. Cite ONLY "
            f"these snippet ids using the bare id (e.g. s1). Every claim needs ≥1 "
            f"cite. Do not overstate what the population or result establishes.\n"
            f"{ev}{opp}\n"
            'Return a JSON list ONLY: [{"text": "<claim>", "cites": ["s1"]}]')


def _stance_prompt(claim, snips):
    items = "\n".join(f'[{s.id}] {s.text[:600]}' for s in snips)
    return (f"Claim: {claim}\nClassify each snippet's stance toward THIS claim.\n"
            "SUPPORTS = a positive effect in the claimed direction. A result in a "
            "narrower population supports only that subgroup; lower confidence when "
            "the claim names a broader population.\n"
            "REFUTES = a direct null, opposite, or harmful result for the SAME "
            "intervention, outcome, and claimed population. 'No significant effect', "
            "'no benefit', 'did not improve', or a failed replication can REFUTE when "
            "they report an actual result, not merely a lack of research.\n"
            "UNRESOLVED = on-topic but epistemically unresolved. Reviews saying "
            "INSUFFICIENT evidence, too few/low-quality studies, mixed findings, or "
            "that no conclusion can be drawn do not show the claim true or false. "
            "They are UNRESOLVED, not REFUTES.\n"
            "NEUTRAL = genuinely off-topic: a different intervention or outcome.\n"
            f"{items}\n"
            "Give one short reason quoting or closely paraphrasing the result that "
            "determined the label.\n"
            'Return a JSON list: [{"id":"s1","stance":"SUPPORTS",'
            '"confidence":0.8,"reason":"reported improved memory in healthy adults"}]')


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

async def _cli_ask(question: str) -> str:
    """Interactive clarify for the terminal — input() off the event loop."""
    print(f"\n  CLARIFY  {question}")
    return await asyncio.to_thread(input, "  > ")


async def _main(question: str, interactive: bool = True):
    async for ev in run(question, ask=_cli_ask if interactive else None):
        if ev["type"] == "verdict":
            print(f"\nVERDICT {ev['verdict']}")
        elif ev["type"] == "brief":
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
        elif ev["type"] in {"out_of_scope", "insufficient_evidence"}:
            print(f"  ({ev['on_topic']} on-topic items — {ev['reason']})")


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

    # three-way route: too little => OOS, lone-dissenter/one-sided => CONSENSUS, else debate
    cfg = Config()
    assert route(1, 0, 0.0, cfg) == "INSUFFICIENT_EVIDENCE", "below evidence floor must refuse"
    assert route(2, 0, 1.0, cfg) == "INSUFFICIENT_EVIDENCE", "thin one-sided evidence is not consensus"
    assert route(5, 5, 0.03, cfg) == "CONTESTED", "both sides well-represented => debate"
    assert route(4, 3, 0.21, cfg) == "CONTESTED", "≥2 on the minority side => debate"
    assert route(5, 1, 0.62, cfg) == "CONSENSUS", "a lone dissenter is not a controversy"
    assert route(5, 0, 1.0, cfg) == "CONSENSUS", "empty side => consensus"
    assert route(1, 1, 0.0, cfg) == "CONTESTED", "balanced even if tiny => not consensus"
    assert route(5, 5, cfg.consensus_asymmetry, cfg) == "CONSENSUS", "asymmetry override still fires"

    # query cleaning: list coerced, capped to 3 AND-terms (OpenAIRE collapses beyond)
    assert _clean_query(["a", "b", "c", "d"]) == "a b c", "query must coerce+cap to 3"

    print("selfcheck OK — budget, disjoint, ablation, cite-enforce, asymmetry, guardrail, route, query")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else "does creatine improve cognition?"))
