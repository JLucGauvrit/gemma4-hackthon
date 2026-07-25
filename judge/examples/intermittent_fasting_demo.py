"""Executable offline Judge demo using intermittent-fasting evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import CallableGemmaAdapter, EvidenceReviewEngine


AGENT_RESULTS = [
    {
        "agent_id": "benefits_agent",
        "perspective": "potential_benefits",
        "overall_conclusion": "Intermittent fasting may support weight management.",
        "claims": [
            {
                "claim_id": "benefit_1",
                "claim": "Intermittent fasting may support modest weight loss.",
                "claim_type": "causal",
                "confidence": "moderate",
                "source_ids": ["study_1"],
            }
        ],
        "sources": [
            {
                "source_id": "study_1",
                "source_type": "randomized_trial",
                "title": "Time-restricted eating compared with daily calorie restriction",
                "doi": "10.0000/demo.if.1",
                "publisher_or_author": "Demo research group",
                "publication_date": "2023-05-10",
                "population": "Adults with overweight",
                "sample_size": 250,
                "duration": "12 weeks",
                "human_or_animal": "human",
                "intervention": "16:8 time-restricted eating",
                "comparison": "continuous calorie restriction",
                "outcome_studied": "weight loss",
                "main_finding": "Both groups experienced modest weight loss.",
                "effect_direction": "mixed",
                "limitations": ["Short study duration"],
                "funding_or_conflicts": "unknown",
                "evidence_excerpt": "Both dietary approaches produced modest weight loss.",
                "metadata_status": "reported",
            }
        ],
    },
    {
        "agent_id": "risks_agent",
        "perspective": "potential_risks",
        "overall_conclusion": "The eating pattern may be difficult or unsuitable for some people.",
        "claims": [
            {
                "claim_id": "risk_1",
                "claim": "Some participants report hunger and adherence difficulty.",
                "claim_type": "observational",
                "confidence": "moderate",
                "source_ids": ["study_1_duplicate"],
            }
        ],
        "sources": [
            {
                "source_id": "study_1_duplicate",
                "source_type": "randomized_trial",
                "title": "Time-restricted eating compared with daily calorie restriction",
                "url": "https://example.org/demo-study?tracking=duplicate",
                "doi": "https://doi.org/10.0000/DEMO.IF.1",
                "publisher_or_author": "Demo research group",
                "publication_date": "2023-05-10",
                "population": "Adults with overweight",
                "sample_size": 250,
                "duration": "12 weeks",
                "human_or_animal": "human",
                "outcome_studied": "adherence and weight loss",
                "main_finding": "Adherence varied between participants.",
                "limitations": ["Short study duration"],
                "funding_or_conflicts": "unknown",
                "evidence_excerpt": "Adherence and hunger responses varied.",
            }
        ],
    },
]


DEMO_MODEL_OUTPUT = {
    "direct_answer": (
        "Intermittent fasting may help some adults manage weight, but the supplied "
        "evidence does not show that it is universally beneficial or clearly superior "
        "to continuous calorie restriction."
    ),
    "potential_benefits": [
        "May support modest weight loss when the eating window reduces total energy intake.",
        "May offer a simple schedule for adults who prefer time-based structure.",
    ],
    "potential_risks": [
        "Hunger and adherence difficulty may occur.",
        "The available evidence does not establish safety for all populations.",
    ],
    "who_may_benefit": [
        "Some adults with overweight who prefer a structured eating schedule."
    ],
    "who_should_be_cautious": [
        "People whose health conditions or medication schedules make fasting risky."
    ],
    "conditions_that_change_the_answer": [
        "Fasting protocol and total energy intake.",
        "Health status, medication use, food quality, and sustainability.",
    ],
    "evidence_strength": "limited",
    "remaining_uncertainties": [
        "Long-term outcomes are not established by the supplied short-duration study.",
        "Applicability beyond adults with overweight is uncertain.",
    ],
    "why_this_conclusion": [
        "The cited randomized trial is relevant but short in duration.",
        "The comparison group also experienced modest weight loss.",
        "The two agents cited the same underlying study, so it is counted once.",
    ],
    "practical_conclusion": (
        "Intermittent fasting can be one dietary option, but sustainability and individual "
        "health context matter; people with relevant medical risks should seek clinical guidance."
    ),
}


def demo_generate(_: str) -> str:
    """Stand-in for Gemma so the demo is executable without model infrastructure."""

    return json.dumps(DEMO_MODEL_OUTPUT)


def main() -> None:
    judge = EvidenceReviewEngine(CallableGemmaAdapter(demo_generate))
    answer = judge.review("Is intermittent fasting beneficial?", AGENT_RESULTS)
    print(json.dumps(answer.to_dict(), indent=2))


if __name__ == "__main__":
    main()
