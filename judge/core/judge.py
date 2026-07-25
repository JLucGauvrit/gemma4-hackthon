"""Evidence Review Engine orchestration.

Deterministic code owns validation, provenance, deduplication, basic
methodological assessment, parsing, retries, and safe fallback behavior.
Gemma owns semantic evidence assessment and final synthesis.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Union
from urllib.parse import urlsplit, urlunsplit

from .gemma import GemmaAdapter, build_judge_prompt, build_retry_prompt
from .schema import (
    Claim,
    ClaimSupportAssessment,
    EvidenceSource,
    EvidenceStrength,
    FinalAnswer,
    ResearchAgentResult,
    SourceAssessment,
    SourceType,
    ValidationError,
)


_SOURCE_BASE = {
    SourceType.SYSTEMATIC_REVIEW: (0.88, 0.88, "high"),
    SourceType.META_ANALYSIS: (0.88, 0.88, "high"),
    SourceType.RANDOMIZED_TRIAL: (0.82, 0.78, "high"),
    SourceType.CONTROLLED_TRIAL: (0.74, 0.68, "moderate"),
    SourceType.OBSERVATIONAL_STUDY: (0.62, 0.38, "moderate"),
    SourceType.COHORT_STUDY: (0.66, 0.55, "moderate"),
    SourceType.CASE_CONTROL_STUDY: (0.60, 0.48, "moderate"),
    SourceType.CROSS_SECTIONAL_STUDY: (0.52, 0.35, "low"),
    SourceType.CLINICAL_GUIDELINE: (0.82, 0.65, "high"),
    SourceType.GOVERNMENT_SOURCE: (0.78, 0.55, "high"),
    SourceType.ACADEMIC_SOURCE: (0.68, 0.50, "moderate"),
    SourceType.MEDICAL_ORGANIZATION: (0.74, 0.55, "moderate"),
    SourceType.DATASET: (0.66, 0.48, "moderate"),
    SourceType.STATISTICS_REPORT: (0.64, 0.46, "moderate"),
    SourceType.EXPERT_ARTICLE: (0.46, 0.25, "context"),
    SourceType.NEWS_ARTICLE: (0.32, 0.16, "context"),
    SourceType.COMPANY_SOURCE: (0.28, 0.18, "commercial"),
    SourceType.BLOG: (0.20, 0.10, "anecdotal"),
    SourceType.FORUM: (0.12, 0.06, "anecdotal"),
    SourceType.SOCIAL_MEDIA: (0.10, 0.05, "anecdotal"),
    SourceType.OTHER: (0.25, 0.15, "unknown"),
}

_RESEARCH_TYPES = {
    SourceType.SYSTEMATIC_REVIEW,
    SourceType.META_ANALYSIS,
    SourceType.RANDOMIZED_TRIAL,
    SourceType.CONTROLLED_TRIAL,
    SourceType.OBSERVATIONAL_STUDY,
    SourceType.COHORT_STUDY,
    SourceType.CASE_CONTROL_STUDY,
    SourceType.CROSS_SECTIONAL_STUDY,
}
_GUIDANCE_TYPES = {
    SourceType.CLINICAL_GUIDELINE,
    SourceType.GOVERNMENT_SOURCE,
    SourceType.MEDICAL_ORGANIZATION,
}
_DATA_TYPES = {SourceType.DATASET, SourceType.STATISTICS_REPORT}
_SECONDARY_TYPES = {
    SourceType.EXPERT_ARTICLE,
    SourceType.NEWS_ARTICLE,
    SourceType.BLOG,
    SourceType.FORUM,
    SourceType.SOCIAL_MEDIA,
    SourceType.COMPANY_SOURCE,
}


def _normalize_token(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    doi = value.strip().lower()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi)
    return doi.rstrip(" .") or None


def _normalize_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return value.strip().lower().rstrip("/") or None
    if not parts.netloc:
        return value.strip().lower().rstrip("/") or None
    path = re.sub(r"/+", "/", parts.path).rstrip("/")
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, "", ""))


def _normalize_title(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower().replace("&", " and "))
    return " ".join(normalized.split()) or None


def source_identity(source: EvidenceSource) -> tuple[str, str]:
    """Return the deterministic identity key required by the Judge contract."""

    doi = _normalize_doi(source.doi)
    if doi:
        return ("doi", doi)
    title = _normalize_title(source.title)
    author_year_title = "|".join(
        filter(
            None,
            (
                _normalize_title(source.publisher_or_author),
                str(source.publication_year or ""),
                title,
            ),
        )
    )
    url = _normalize_url(source.url)
    if url:
        return ("url", url)
    if title and source.publisher_or_author and source.publication_year:
        return ("author_year_title", author_year_title)
    if title:
        return ("title", title)
    return ("source_id", source.source_id.strip().lower())


# Backward-compatible helper name.
study_identity = source_identity


def _source_identity_keys(source: EvidenceSource) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    doi = _normalize_doi(source.doi)
    url = _normalize_url(source.url)
    title = _normalize_title(source.title)
    author = _normalize_title(source.publisher_or_author)
    if doi:
        keys.append(("doi", doi))
    if url:
        keys.append(("url", url))
    if title and author and source.publication_year:
        keys.append(
            ("author_year_title", f"{author}|{source.publication_year}|{title}")
        )
    if title and not (doi or url):
        keys.append(("title", title))
    keys.append(("source_id", source.source_id.strip().lower()))
    return keys


def _prefer(current: Any, candidate: Any) -> Any:
    if current in (None, "", [], "unknown") and candidate not in (None, "", [], "unknown"):
        return deepcopy(candidate)
    return current


def deduplicate_sources(
    sources: Iterable[EvidenceSource],
) -> tuple[list[EvidenceSource], dict[str, str]]:
    """Deduplicate sources and return old-source-id -> canonical-source-id."""

    canonical_by_key: dict[tuple[str, str], EvidenceSource] = {}
    ordered: list[EvidenceSource] = []
    aliases: dict[str, str] = {}
    merge_fields = (
        "title",
        "url",
        "doi",
        "publisher_or_author",
        "publication_date",
        "publication_year",
        "topic",
        "population",
        "sample_size",
        "duration",
        "human_or_animal",
        "intervention",
        "comparison",
        "outcome_studied",
        "main_claim",
        "main_finding",
        "effect_direction",
        "data_or_method",
        "funding_or_conflicts",
        "evidence_excerpt",
        "references_original_source",
        "metadata_status",
    )
    for original in sources:
        item = deepcopy(original)
        keys = _source_identity_keys(item)
        target = next((canonical_by_key[key] for key in keys if key in canonical_by_key), None)
        if target is None:
            ordered.append(item)
            for key in keys:
                canonical_by_key[key] = item
            aliases[item.source_id] = item.source_id
            continue
        aliases[item.source_id] = target.source_id
        if item.source_id != target.source_id and item.source_id not in target.duplicate_source_ids:
            target.duplicate_source_ids.append(item.source_id)
        for field_name in merge_fields:
            setattr(target, field_name, _prefer(getattr(target, field_name), getattr(item, field_name)))
        target.limitations = list(dict.fromkeys(target.limitations + item.limitations))
        target.contributed_by = list(dict.fromkeys(target.contributed_by + item.contributed_by))
        for key in _source_identity_keys(target) + keys:
            canonical_by_key[key] = target
    return ordered, aliases


deduplicate_studies = deduplicate_sources


def assess_source(
    source: EvidenceSource, current_year: Optional[int] = None
) -> SourceAssessment:
    """Create a source-type-aware prior; Gemma performs semantic assessment."""

    current_year = current_year or datetime.now(timezone.utc).year
    credibility, methodology, tier = _SOURCE_BASE[source.source_type]
    flags: list[str] = []

    if source.human_or_animal and _normalize_token(source.human_or_animal) != "human":
        methodology -= 0.12
        flags.append("indirect_non_human_evidence")
    if source.source_type in _RESEARCH_TYPES:
        if source.sample_size is None:
            flags.append("sample_size_unknown")
        elif source.sample_size >= 500:
            methodology += 0.07
        elif source.sample_size >= 100:
            methodology += 0.03
        elif source.sample_size < 30:
            methodology -= 0.08
            flags.append("small_sample")
        if not source.duration:
            flags.append("duration_unknown")
        if not source.comparison and source.source_type in {
            SourceType.RANDOMIZED_TRIAL,
            SourceType.CONTROLLED_TRIAL,
        }:
            methodology -= 0.05
            flags.append("comparison_group_unknown")
    if not source.limitations:
        methodology -= 0.04
        flags.append("limitations_not_reported")
    if not source.funding_or_conflicts or _normalize_token(source.funding_or_conflicts) == "unknown":
        flags.append("conflict_of_interest_unknown")
    if source.publication_year is None:
        flags.append("publication_year_unknown")
    elif current_year - source.publication_year > 10:
        credibility -= 0.05
        flags.append("older_than_ten_years")
    if not source.evidence_excerpt:
        credibility -= 0.05
        flags.append("evidence_excerpt_missing")
    if source.source_type in _RESEARCH_TYPES | _GUIDANCE_TYPES and not source.population:
        flags.append("population_unknown")
    if source.source_type in _GUIDANCE_TYPES:
        if not source.data_or_method:
            methodology -= 0.08
            flags.append("evidence_review_process_unknown")
        if not source.references_original_source:
            flags.append("supporting_references_unknown")
    if source.source_type in _DATA_TYPES and not source.data_or_method:
        methodology -= 0.10
        flags.append("data_collection_method_unknown")
    if source.source_type in _SECONDARY_TYPES and not source.references_original_source:
        credibility -= 0.08
        flags.append("original_evidence_not_linked")
    if source.source_type == SourceType.COMPANY_SOURCE:
        credibility -= 0.08
        flags.append("commercial_interest")
        if not source.references_original_source:
            flags.append("company_only_evidence")
    if source.source_type in {
        SourceType.BLOG,
        SourceType.FORUM,
        SourceType.SOCIAL_MEDIA,
    }:
        flags.append("anecdotal_only")

    return SourceAssessment(
        source_id=source.source_id,
        credibility_score=round(min(1.0, max(0.0, credibility)), 2),
        methodological_score=round(min(1.0, max(0.0, methodology)), 2),
        source_tier=tier,
        flags=flags,
    )


assess_study = assess_source


def _validate_question(question: str) -> str:
    if not isinstance(question, str) or not question.strip():
        raise ValidationError("question must be a non-empty string")
    return question.strip()


def _coerce_agents(
    agents: Iterable[Union[ResearchAgentResult, Mapping[str, Any]]],
) -> list[ResearchAgentResult]:
    if isinstance(agents, (str, bytes, Mapping)):
        raise ValidationError("agents must be a list or iterable of agent objects")
    results = [
        item if isinstance(item, ResearchAgentResult) else ResearchAgentResult.from_dict(item, f"agents[{i}]")
        for i, item in enumerate(agents)
    ]
    if not results:
        raise ValidationError("agents must contain at least one research-agent result")
    ids = [agent.agent_id for agent in results]
    duplicates = sorted({agent_id for agent_id in ids if ids.count(agent_id) > 1})
    if duplicates:
        raise ValidationError(f"agent_id values must be unique; duplicates: {', '.join(duplicates)}")
    return results


def _remap_and_filter_claims(
    agents: list[ResearchAgentResult],
    aliases: dict[str, str],
    known_source_ids: set[str],
) -> tuple[list[Claim], list[dict[str, str]]]:
    accepted: list[Claim] = []
    rejected: list[dict[str, str]] = []
    for agent in agents:
        for original in agent.claims:
            claim = deepcopy(original)
            remapped = list(dict.fromkeys(aliases.get(source_id, source_id) for source_id in claim.source_ids))
            claim.source_ids = [source_id for source_id in remapped if source_id in known_source_ids]
            if not claim.source_ids:
                rejected.append({"claim_id": claim.claim_id, "reason": "no_valid_source_ids"})
                continue
            accepted.append(claim)
    return accepted, rejected


def _resolve_reference(
    reference: str,
    sources: list[EvidenceSource],
    aliases: dict[str, str],
) -> Optional[str]:
    if reference in aliases:
        return aliases[reference]
    normalized_doi = _normalize_doi(reference)
    normalized_url = _normalize_url(reference)
    for source in sources:
        if normalized_doi and normalized_doi == _normalize_doi(source.doi):
            return source.source_id
        if normalized_url and normalized_url == _normalize_url(source.url):
            return source.source_id
    return None


def detect_source_relationships(
    sources: list[EvidenceSource],
    aliases: dict[str, str],
) -> list[dict[str, str]]:
    """Identify duplicates, mirrors, secondary coverage, and circular chains."""

    relationships: list[dict[str, str]] = []
    for duplicate_id, canonical_id in aliases.items():
        if duplicate_id != canonical_id:
            relationships.append(
                {
                    "source_id": duplicate_id,
                    "related_source_id": canonical_id,
                    "relationship": "exact_duplicate",
                }
            )

    for index, source in enumerate(sources):
        source_title = _normalize_title(source.title)
        for other in sources[index + 1 :]:
            if (
                source_title
                and source_title == _normalize_title(other.title)
                and _normalize_url(source.url) != _normalize_url(other.url)
            ):
                relationships.append(
                    {
                        "source_id": other.source_id,
                        "related_source_id": source.source_id,
                        "relationship": "mirrored_page",
                    }
                )
        if source.references_original_source:
            target = _resolve_reference(source.references_original_source, sources, aliases)
            relationships.append(
                {
                    "source_id": source.source_id,
                    "related_source_id": target or "unknown",
                    "relationship": (
                        "secondary_article_discussing_original_source"
                        if target and target != source.source_id
                        else "unknown_relationship"
                    ),
                }
            )

    graph = {
        relationship["source_id"]: relationship["related_source_id"]
        for relationship in relationships
        if relationship["relationship"] == "secondary_article_discussing_original_source"
    }
    for start in graph:
        seen: set[str] = set()
        current = start
        while current in graph:
            if current in seen:
                relationships.append(
                    {
                        "source_id": start,
                        "related_source_id": current,
                        "relationship": "circular_citation_chain",
                    }
                )
                break
            seen.add(current)
            current = graph[current]
    return relationships


def _claim_warning_flags(
    claim: Claim, sources_by_id: dict[str, EvidenceSource]
) -> list[str]:
    flags: list[str] = []
    linked = [sources_by_id[source_id] for source_id in claim.source_ids]
    claim_type = _normalize_token(claim.claim_type)
    non_causal_types = {
        SourceType.OBSERVATIONAL_STUDY,
        SourceType.COHORT_STUDY,
        SourceType.CASE_CONTROL_STUDY,
        SourceType.CROSS_SECTIONAL_STUDY,
        SourceType.EXPERT_ARTICLE,
        SourceType.NEWS_ARTICLE,
        SourceType.COMPANY_SOURCE,
        SourceType.BLOG,
        SourceType.FORUM,
        SourceType.SOCIAL_MEDIA,
    }
    if claim_type == "causal" and linked and all(
        source.source_type in non_causal_types for source in linked
    ):
        flags.append("possible_correlation_as_causation")
    if any(not source.limitations for source in linked):
        flags.append("linked_source_limitations_missing")
    if any(not source.population for source in linked):
        flags.append("population_relevance_unknown")
    if linked and all(
        source.source_type
        in {SourceType.BLOG, SourceType.FORUM, SourceType.SOCIAL_MEDIA}
        for source in linked
    ):
        flags.append("anecdotal_evidence_only")
    if linked and all(source.source_type == SourceType.COMPANY_SOURCE for source in linked):
        flags.append("company_sources_only")
    if any(
        source.human_or_animal
        and _normalize_token(source.human_or_animal) != "human"
        for source in linked
    ):
        flags.append("animal_to_human_generalization_risk")
    return flags


def build_evidence_package(
    question: str,
    agents: Iterable[Union[ResearchAgentResult, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Validate and normalize all evidence before it reaches Gemma."""

    normalized_question = _validate_question(question)
    normalized_agents = _coerce_agents(agents)
    sources, aliases = deduplicate_sources(
        source for agent in normalized_agents for source in agent.sources
    )
    known_source_ids = {source.source_id for source in sources}
    claims, rejected = _remap_and_filter_claims(normalized_agents, aliases, known_source_ids)
    sources_by_id = {source.source_id: source for source in sources}

    assessments = [assess_source(source) for source in sources]
    relationships = detect_source_relationships(sources, aliases)
    return {
        "question": normalized_question,
        "raw_agent_conclusions": [
            {
                "agent_id": agent.agent_id,
                "perspective": agent.perspective,
                "overall_conclusion": agent.overall_conclusion or "unknown",
                "overall_confidence": agent.overall_confidence or "unknown",
            }
            for agent in normalized_agents
        ],
        "claims": [
            {
                **asdict(claim),
                "deterministic_warning_flags": _claim_warning_flags(claim, sources_by_id),
            }
            for claim in claims
        ],
        "sources": [source.to_dict(unknown_for_missing=True) for source in sources],
        "source_assessments": [assessment.to_dict() for assessment in assessments],
        "source_relationships": relationships,
        "provenance": {
            "input_source_count": sum(len(agent.sources) for agent in normalized_agents),
            "unique_source_count": len(sources),
            "duplicate_aliases": aliases,
            "rejected_claims": rejected,
        },
    }


def parse_final_answer(raw_response: str) -> FinalAnswer:
    if not isinstance(raw_response, str) or not raw_response.strip():
        raise ValidationError("model response must be a non-empty JSON string")
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"model response is malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return FinalAnswer.from_dict(parsed)


def fallback_answer(evidence_package: dict[str, Any]) -> FinalAnswer:
    """Fail closed when Gemma cannot produce valid structured output."""

    unique_count = evidence_package["provenance"]["unique_source_count"]
    reason = (
        f"{unique_count} unique cited sources were collected, but automated synthesis failed validation."
        if unique_count
        else "No valid cited sources were available for synthesis."
    )
    return FinalAnswer(
        direct_answer="The available evidence could not be synthesized reliably.",
        potential_benefits=[],
        potential_risks=[],
        who_may_benefit=[],
        who_should_be_cautious=[],
        conditions_that_change_the_answer=[],
        evidence_strength=EvidenceStrength.INSUFFICIENT,
        remaining_uncertainties=[
            "A validated evidence synthesis is unavailable.",
            "Missing source metadata and rejected claims may affect the conclusion.",
        ],
        why_this_conclusion=[reason],
        practical_conclusion=(
            "Do not use this result as personalized medical advice; review the cited evidence "
            "or consult a qualified health professional."
        ),
    )


class EvidenceReviewEngine:
    """Orchestrate deterministic evidence preparation and Gemma synthesis."""

    def __init__(self, gemma: GemmaAdapter):
        self.gemma = gemma

    def review(
        self,
        question: str,
        agents: Iterable[Union[ResearchAgentResult, Mapping[str, Any]]],
    ) -> FinalAnswer:
        evidence_package = build_evidence_package(question, agents)
        prompt = build_judge_prompt(evidence_package)
        try:
            first_response = self.gemma.generate(prompt)
        except Exception as exc:  # Model/runtime boundary must fail closed.
            first_response = ""
            first_error = ValidationError(
                f"Gemma generation failed: {type(exc).__name__}: {exc}"
            )
        else:
            try:
                return parse_final_answer(first_response)
            except ValidationError as exc:
                first_error = exc

        retry_prompt = build_retry_prompt(prompt, first_response, str(first_error))
        try:
            second_response = self.gemma.generate(retry_prompt)
            return parse_final_answer(second_response)
        except Exception:
            return fallback_answer(evidence_package)


def parse_claim_support(raw_response: str) -> list[ClaimSupportAssessment]:
    """Validate Gemma claim-support JSON for callers that run a separate pass."""

    if not isinstance(raw_response, str) or not raw_response.strip():
        raise ValidationError("claim-support response must be a non-empty JSON string")
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"claim-support response is malformed JSON at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(parsed, Mapping) or not isinstance(parsed.get("assessments"), list):
        raise ValidationError("claim-support response must contain an assessments list")
    return [
        ClaimSupportAssessment.from_dict(item, f"assessments[{index}]")
        for index, item in enumerate(parsed["assessments"])
    ]


def judge_evidence(
    question: str,
    agent_outputs: list[Union[ResearchAgentResult, Mapping[str, Any]]],
    llm_caller: GemmaAdapter,
) -> FinalAnswer:
    """Public functional API used by the application pipeline."""

    return EvidenceReviewEngine(llm_caller).review(question, agent_outputs)
