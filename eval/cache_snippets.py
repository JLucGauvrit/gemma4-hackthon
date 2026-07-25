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
