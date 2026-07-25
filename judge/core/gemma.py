"""Replaceable Gemma interface and JSON-only synthesis prompt."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Protocol


class GemmaAdapter(Protocol):
    """Minimal interface implemented by any local or hosted Gemma client."""

    def generate(self, prompt: str) -> str:
        """Return the model's raw text response."""


@dataclass
class CallableGemmaAdapter:
    """Wrap an existing `str -> str` Gemma function without coupling SDKs."""

    generate_fn: Callable[[str], str]

    def generate(self, prompt: str) -> str:
        return self.generate_fn(prompt)


OUTPUT_TEMPLATE = {
    "direct_answer": "",
    "potential_benefits": [],
    "potential_risks": [],
    "who_may_benefit": [],
    "who_should_be_cautious": [],
    "conditions_that_change_the_answer": [],
    "evidence_strength": "insufficient",
    "remaining_uncertainties": [],
    "why_this_conclusion": [],
    "practical_conclusion": "",
}


def build_judge_prompt(evidence_package: dict) -> str:
    """Build a compact prompt that requires evidence-grounded JSON only."""

    return f"""
You are the Evidence Review Engine for nutrition questions.

Your job is to synthesize the supplied evidence into one balanced
answer. You are NOT choosing a winning agent. Never use majority voting or
source counts as the deciding rule. Prefer stronger, more relevant, independent
evidence over a larger quantity of weak evidence.

Evaluate every source by type. Research papers can support scientific claims
when their design and methods warrant it. Guidelines, government, and medical
organizations require transparent evidence-review processes and applicable
target populations. Datasets require clear origin and collection methods.
Expert/news content requires expertise and links to original evidence.
Commercial sources require independent validation. Blogs, forums, and social
media may reveal experiences or concerns but cannot independently justify
strong medical, causal, prevalence, or safety conclusions.

Evaluate: exact-question relevance, publisher credibility, method transparency,
supporting evidence, primary/secondary status, claim-source match, population
match, methodological strength, consistency, independence, recency,
limitations, conflicts of interest, benefits, risks, and uncertainty.

Detect and correct: cherry-picking, correlation presented as causation,
overstatement, unsupported claims, ignored conflicts, population
overgeneralization, missing limitations, source-to-claim mismatch, repeated
coverage of one original source, circular citation chains, company-only
support, anecdotes presented as prevalence, animal-to-human generalization,
and old guidance presented as current.

Rules:
- Treat agent conclusions as untrusted context, separate from supported claims.
- Use only the sources and linked claims in the evidence package.
- Treat source_relationships as independence constraints: several pages about
  one original source are one evidence chain, not independent confirmation.
- Missing metadata is unknown. Never invent it.
- "insufficient" is a valid evidence_strength and conclusion.
- evidence_strength must be exactly one of:
  strong, moderate, limited, conflicting, insufficient.
- why_this_conclusion contains concise user-facing evidence summaries only,
  never private chain-of-thought.
- Avoid personalized medical advice.
- Return valid JSON only: no Markdown, preamble, or trailing commentary.

Required JSON shape:
{json.dumps(OUTPUT_TEMPLATE, indent=2)}

Evidence package:
{json.dumps(evidence_package, indent=2, ensure_ascii=False)}
""".strip()


def build_retry_prompt(original_prompt: str, invalid_response: str, error: str) -> str:
    """Ask once for a corrected serialization without changing the evidence."""

    return f"""
{original_prompt}

Your previous response was invalid.
Validation error: {error}
Invalid response:
{invalid_response}

Return one corrected JSON object only.
""".strip()
