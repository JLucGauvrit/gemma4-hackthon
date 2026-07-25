"""Live retrieval from OpenAIRE. Any claim, any domain (no fixtures).

search_research_products -> Snippet[] with full provenance. Abstracts carry the
stance signal; the stance classifier reads them next. medRxiv full-text depth is
enhancement #1 (not here yet).
"""

from __future__ import annotations

import asyncio
import json
import re

from core.mcp_client import session, tool_text
from core.schema import Snippet, Source

_STOP = set("the a an of for in on to and or is are be with without by from into "
            "does do can improve improves improved better best beats beat cause causes "
            "effect effects healthy adults people study vs than more less over".split())


def keywords(claim: str, n: int = 3) -> str:
    """OpenAIRE search is keyword-AND (more terms = fewer hits). Reduce the claim
    to a few salient content words. ponytail: heuristic; swap for an LLM term
    extractor if recall disappoints."""
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z-]+", claim.lower())
             if w not in _STOP and len(w) > 3]
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
    return " ".join(seen[:n]) or claim


def _unwrap(text: str) -> dict:
    """Tool payloads come back double-wrapped: {"result": "<json string>"}."""
    obj = json.loads(text)
    if isinstance(obj, dict) and isinstance(obj.get("result"), str):
        obj = json.loads(obj["result"])
    return obj


def _clean(text: str) -> str:
    """Strip JATS/HTML tags (abstracts come with <jats:p> etc.) + collapse space."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _to_snippet(sid: str, rec: dict) -> Snippet:
    date = rec.get("publication_date") or ""
    year = int(date[:4]) if date[:4].isdigit() else None
    src = Source(
        doi=rec.get("doi"),
        title=rec.get("title") or "(untitled)",
        authors=[a.get("name", "") for a in rec.get("authors", [])],
        year=year,
        venue=rec.get("journal") or rec.get("publisher"),
        license=rec.get("open_access_color"),
        retrieved_via="openaire",
    )
    # abstract is the stance-bearing text; fall back to title if missing
    text = _clean(rec.get("abstract") or "") or src.title
    return Snippet(id=sid, text=text, stance="NEUTRAL", confidence=0.0, source=src)


async def retrieve_openaire(query: str, limit: int) -> list[Snippet]:
    """`query` is already reduced keywords (from the extractor, or keywords())."""
    async with session("openaire") as s:
        res = await s.call_tool("openaire_search_research_products", {
            "query": query,
            "type": ["publication"],
            "page_size": limit,
            "sort_by": "relevance DESC",   # relevance, NOT influence — influence
                                           # surfaces famous-but-off-topic papers
            "detail": "full",
            "response_format": "json",
        })
        data = _unwrap(tool_text(res))
        results = data.get("data", {}).get("results", [])
    # keep only records with a usable abstract or title, drop pure dupes by DOI
    snippets, seen = [], set()
    for rec in results:
        doi = rec.get("doi")
        if doi in seen:
            continue
        seen.add(doi)
        snippets.append(_to_snippet(f"s{len(snippets) + 1}", rec))
    return snippets


async def enrich_full_abstracts(snips: list[Snippet]) -> int:
    """Upgrade truncated search abstracts to FULL abstracts via get_details.
    The search endpoint cuts abstracts at ~500 chars — right before the result
    sentence. The stance classifier and advocates both need the finding. Mutates
    in place; keeps the short version on failure. Returns the number upgraded."""
    targets = [s for s in snips if s.source.doi]
    if not targets:
        return 0

    async with session("openaire") as s:
        gate = asyncio.Semaphore(6)

        async def enrich_one(snip: Snippet) -> bool:
            try:
                async with gate:
                    res = await s.call_tool(
                        "openaire_get_research_product_details",
                        {"identifier": snip.source.doi, "response_format": "json"},
                    )
                abstract = _clean(_unwrap(tool_text(res)).get("data", {}).get("abstract") or "")
                if len(abstract) > len(snip.text):
                    snip.text = abstract
                    return True
            except Exception:
                pass  # network / parse hiccup — keep the truncated abstract
            return False

        upgraded = await asyncio.gather(*(enrich_one(snip) for snip in targets))
    return sum(upgraded)


if __name__ == "__main__":  # smoke: needs one browser login the first time
    import asyncio
    import sys

    claim = sys.argv[1] if len(sys.argv) > 1 else "creatine improves cognition in healthy adults"

    async def _smoke():
        q = keywords(claim)
        snips = await retrieve_openaire(q, 8)
        print(f"query keywords: {q!r} -> {len(snips)} snippets\n")
        for s in snips:
            print(f"[{s.id}] ({s.source.year}) {s.source.title[:70]}")
            print(f"      doi={s.source.doi}  {s.text[:100]}...")

    asyncio.run(_smoke())
