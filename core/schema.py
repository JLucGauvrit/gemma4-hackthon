"""Shared contract. FROZEN — see PRD §7.0. Everyone codes against this.

Dataclasses (not pydantic) on purpose: zero deps, trivial to mock, and the
judge emits plain JSON we map in by hand anyway. asdict() gives us the mock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Stance = Literal["SUPPORTS", "REFUTES", "NEUTRAL"]

CruxType = Literal[
    "population", "methodology", "timeframe",
    "measured-construct", "effect-size", "none",
]

# The three things a question can turn out to be. Branches the whole pipeline
# and the UI: a debate, a sourced consensus, or an honest refusal.
Verdict = Literal["CONTESTED", "CONSENSUS", "OUT_OF_SCOPE"]


@dataclass
class Source:
    doi: str | None
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    license: str | None
    retrieved_via: str  # "openaire" | "biorxiv" | "medrxiv"


@dataclass
class Snippet:
    id: str  # short, stable — cited by this id
    text: str
    stance: Stance
    confidence: float
    source: Source


@dataclass
class Claim:
    text: str
    cites: list[str]  # snippet ids. EMPTY LIST => DROPPED before the judge.


@dataclass
class Turn:
    agent: Literal["FOR", "AGAINST"]
    round: int  # 0 = opening, 1 = rebuttal
    claims: list[Claim]


@dataclass
class Position:
    summary: str
    claims: list[Claim]
    sources: list[Source]


@dataclass
class Brief:
    claim: str
    position_for: Position
    position_against: Position
    crux: str
    crux_type: CruxType
    resolver: str
    asymmetry: float  # 0.0 even split … 1.0 one-sided
    transcript: list[Turn]
    meta: dict = field(default_factory=dict)  # latency, tokens, tiers, config
    verdict: Verdict = "CONTESTED"  # CONTESTED debate · CONSENSUS · OUT_OF_SCOPE


# Default tier per role (PRD §6). "all E2B" = Track-03 purity run; bump to E4B
# = Track-02 fallback. Both are just a different `tiers` dict — no code change.
DEFAULT_TIERS: dict[str, str] = {
    "extract": "E2B",
    "stance": "E2B",
    "advocate": "E2B",
    "judge": "E4B",
}


@dataclass
class Config:
    shared_evidence: bool = False   # False = partition ON (the debate). Flip for the ablation.
    tiers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TIERS))
    max_snippets: int = 24          # retrieved before classification
    stance_batch: int = 6           # snippets/stance call — Gemma collapses a big batch to 1 object
    top_k_per_side: int = 5         # kept per pile after classification
    min_evidence: int = 2           # SUPPORTS+REFUTES floor; below => out-of-scope (§9)
    min_side: int = 2               # a debate needs ≥ this on the weaker side; a lone
                                    # dissenter => CONSENSUS (robust to 1 stance misclassification)
    rebuttal: bool = False          # 1 rebuttal round — off in v1 (PRD cut #1)
    consensus_asymmetry: float = 0.85  # asymmetry ≥ this => CONSENSUS, not a debate (§9)
    max_clarify: int = 2            # intake clarify bounces before best-guess fallback
    compress: bool = False          # question-aware abstract compression before stance
    compress_budget: float = 0.4    # keep this fraction of each abstract's words
