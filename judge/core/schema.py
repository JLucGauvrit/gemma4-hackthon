"""Typed data contracts for research-agent inputs and Judge outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from datetime import date
from typing import Any, Mapping, Optional


class ValidationError(ValueError):
    """Raised when an agent payload or model response violates its contract."""


class EvidenceStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    LIMITED = "limited"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"


class SourceType(str, Enum):
    SYSTEMATIC_REVIEW = "systematic_review"
    META_ANALYSIS = "meta_analysis"
    RANDOMIZED_TRIAL = "randomized_trial"
    CONTROLLED_TRIAL = "controlled_trial"
    OBSERVATIONAL_STUDY = "observational_study"
    COHORT_STUDY = "cohort_study"
    CASE_CONTROL_STUDY = "case_control_study"
    CROSS_SECTIONAL_STUDY = "cross_sectional_study"
    CLINICAL_GUIDELINE = "clinical_guideline"
    GOVERNMENT_SOURCE = "government_source"
    ACADEMIC_SOURCE = "academic_source"
    MEDICAL_ORGANIZATION = "medical_organization"
    DATASET = "dataset"
    STATISTICS_REPORT = "statistics_report"
    EXPERT_ARTICLE = "expert_article"
    NEWS_ARTICLE = "news_article"
    COMPANY_SOURCE = "company_source"
    BLOG = "blog"
    FORUM = "forum"
    SOCIAL_MEDIA = "social_media"
    OTHER = "other"


class ClaimSupport(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NOT_SUPPORTED = "not_supported"
    UNCLEAR = "unclear"


def _required_string(data: Mapping[str, Any], field_name: str, path: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{path}.{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(data: Mapping[str, Any], field_name: str, path: str) -> Optional[str]:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{path}.{field_name} must be a string or null")
    return value.strip() or None


def _optional_int(data: Mapping[str, Any], field_name: str, path: str) -> Optional[int]:
    value = data.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{path}.{field_name} must be a non-negative integer or null")
    return value


def _optional_date(data: Mapping[str, Any], field_name: str, path: str) -> Optional[str]:
    value = _optional_string(data, field_name, path)
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValidationError(
            f"{path}.{field_name} must be an ISO date in YYYY-MM-DD format"
        ) from exc


def _string_list(data: Mapping[str, Any], field_name: str, path: str) -> list[str]:
    value = data.get(field_name, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{path}.{field_name} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


@dataclass
class EvidenceSource:
    source_id: str
    source_type: SourceType = SourceType.OTHER
    title: Optional[str] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    publisher_or_author: Optional[str] = None
    publication_date: Optional[str] = None
    publication_year: Optional[int] = None
    topic: Optional[str] = None
    population: Optional[str] = None
    sample_size: Optional[int] = None
    duration: Optional[str] = None
    human_or_animal: Optional[str] = None
    intervention: Optional[str] = None
    comparison: Optional[str] = None
    outcome_studied: Optional[str] = None
    main_claim: Optional[str] = None
    main_finding: Optional[str] = None
    effect_direction: Optional[str] = None
    data_or_method: Optional[str] = None
    limitations: list[str] = field(default_factory=list)
    funding_or_conflicts: Optional[str] = None
    evidence_excerpt: Optional[str] = None
    references_original_source: Optional[str] = None
    metadata_status: Optional[str] = None
    contributed_by: list[str] = field(default_factory=list)
    duplicate_source_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "EvidenceSource":
        if not isinstance(data, Mapping):
            raise ValidationError(f"{path} must be an object")
        raw_type = data.get("source_type", data.get("study_type", "other"))
        aliases = {
            "randomized_controlled_trial": "randomized_trial",
            "prospective_cohort": "cohort_study",
            "cohort": "cohort_study",
            "case_control": "case_control_study",
            "cross_sectional": "cross_sectional_study",
            "observational": "observational_study",
            "animal_study": "other",
            "in_vitro": "other",
            "case_report": "other",
        }
        if not isinstance(raw_type, str):
            raise ValidationError(f"{path}.source_type must be a string")
        normalized_type = aliases.get(raw_type.strip().lower(), raw_type.strip().lower())
        try:
            source_type = SourceType(normalized_type)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in SourceType)
            raise ValidationError(
                f"{path}.source_type is unsupported; expected one of: {allowed}"
            ) from exc
        publication_date = _optional_date(data, "publication_date", path)
        publication_year = _optional_int(data, "publication_year", path)
        if publication_date and publication_year and int(publication_date[:4]) != publication_year:
            raise ValidationError(
                f"{path}.publication_date and publication_year disagree"
            )
        if publication_date and publication_year is None:
            publication_year = int(publication_date[:4])
        return cls(
            source_id=_required_string(data, "source_id", path),
            source_type=source_type,
            title=_optional_string(data, "title", path),
            url=_optional_string(data, "url", path),
            doi=_optional_string(data, "doi", path),
            publisher_or_author=_optional_string(data, "publisher_or_author", path),
            publication_date=publication_date,
            publication_year=publication_year,
            topic=_optional_string(data, "topic", path),
            population=_optional_string(data, "population", path),
            sample_size=_optional_int(data, "sample_size", path),
            duration=_optional_string(data, "duration", path),
            human_or_animal=_optional_string(data, "human_or_animal", path),
            intervention=_optional_string(data, "intervention", path),
            comparison=_optional_string(data, "comparison", path),
            outcome_studied=_optional_string(data, "outcome_studied", path),
            main_claim=_optional_string(data, "main_claim", path),
            main_finding=_optional_string(data, "main_finding", path),
            effect_direction=_optional_string(data, "effect_direction", path),
            data_or_method=_optional_string(data, "data_or_method", path),
            limitations=_string_list(data, "limitations", path),
            funding_or_conflicts=_optional_string(data, "funding_or_conflicts", path),
            evidence_excerpt=_optional_string(data, "evidence_excerpt", path),
            references_original_source=_optional_string(
                data, "references_original_source", path
            ),
            metadata_status=_optional_string(data, "metadata_status", path),
        )

    def to_dict(self, *, unknown_for_missing: bool = False) -> dict[str, Any]:
        result = asdict(self)
        result["source_type"] = self.source_type.value
        if unknown_for_missing:
            return {key: ("unknown" if value is None else value) for key, value in result.items()}
        return result


# Backward-compatible name for teammates still importing Study.
Study = EvidenceSource


@dataclass
class Claim:
    claim_id: str
    claim: str
    claim_type: Optional[str] = None
    confidence: Optional[str] = None
    source_ids: list[str] = field(default_factory=list)
    agent_id: Optional[str] = None
    perspective: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str) -> "Claim":
        if not isinstance(data, Mapping):
            raise ValidationError(f"{path} must be an object")
        return cls(
            claim_id=_required_string(data, "claim_id", path),
            claim=_required_string(data, "claim", path),
            claim_type=_optional_string(data, "claim_type", path),
            confidence=_optional_string(data, "confidence", path),
            source_ids=_string_list(data, "source_ids", path),
        )


@dataclass
class ResearchAgentResult:
    agent_id: str
    perspective: str
    overall_conclusion: Optional[str] = None
    overall_confidence: Optional[str] = None
    claims: list[Claim] = field(default_factory=list)
    sources: list[EvidenceSource] = field(default_factory=list)

    @property
    def studies(self) -> list[EvidenceSource]:
        """Compatibility view for the previous research-agent contract."""

        return self.sources

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "agent") -> "ResearchAgentResult":
        if not isinstance(data, Mapping):
            raise ValidationError(f"{path} must be an object")
        raw_claims = data.get("claims", [])
        raw_sources = data.get("sources")
        raw_studies = data.get("studies")
        if raw_sources is not None and raw_studies is not None:
            raise ValidationError(f"{path} must provide sources or studies, not both")
        raw_evidence = raw_sources if raw_sources is not None else (raw_studies or [])
        if not isinstance(raw_claims, list):
            raise ValidationError(f"{path}.claims must be a list")
        if not isinstance(raw_evidence, list):
            field_name = "sources" if raw_sources is not None else "studies"
            raise ValidationError(f"{path}.{field_name} must be a list")

        result = cls(
            agent_id=_required_string(data, "agent_id", path),
            perspective=_required_string(data, "perspective", path),
            overall_conclusion=_optional_string(data, "overall_conclusion", path),
            overall_confidence=_optional_string(data, "overall_confidence", path),
            claims=[
                Claim.from_dict(item, f"{path}.claims[{index}]")
                for index, item in enumerate(raw_claims)
            ],
            sources=[
                EvidenceSource.from_dict(item, f"{path}.sources[{index}]")
                for index, item in enumerate(raw_evidence)
            ],
        )
        for claim in result.claims:
            claim.agent_id = result.agent_id
            claim.perspective = result.perspective
        for source in result.sources:
            source.contributed_by = [result.agent_id]
        return result


@dataclass
class SourceAssessment:
    source_id: str
    credibility_score: float
    methodological_score: float
    source_tier: str
    flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


StudyAssessment = SourceAssessment


@dataclass
class ClaimSupportAssessment:
    claim_id: str
    support: ClaimSupport
    relevance: str
    overstatement: bool
    population_mismatch: bool
    explanation: str

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], path: str = "claim_assessment"
    ) -> "ClaimSupportAssessment":
        if not isinstance(data, Mapping):
            raise ValidationError(f"{path} must be a JSON object")
        try:
            support = ClaimSupport(data.get("support"))
        except (TypeError, ValueError) as exc:
            allowed = ", ".join(item.value for item in ClaimSupport)
            raise ValidationError(f"{path}.support must be one of: {allowed}") from exc
        for name in ("overstatement", "population_mismatch"):
            if not isinstance(data.get(name), bool):
                raise ValidationError(f"{path}.{name} must be a boolean")
        return cls(
            claim_id=_required_string(data, "claim_id", path),
            support=support,
            relevance=_required_string(data, "relevance", path),
            overstatement=data["overstatement"],
            population_mismatch=data["population_mismatch"],
            explanation=_required_string(data, "explanation", path),
        )


@dataclass
class FinalAnswer:
    direct_answer: str
    potential_benefits: list[str]
    potential_risks: list[str]
    who_may_benefit: list[str]
    who_should_be_cautious: list[str]
    conditions_that_change_the_answer: list[str]
    evidence_strength: EvidenceStrength
    remaining_uncertainties: list[str]
    why_this_conclusion: list[str]
    practical_conclusion: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], path: str = "output") -> "FinalAnswer":
        if not isinstance(data, Mapping):
            raise ValidationError(f"{path} must be a JSON object")
        expected = {
            "direct_answer",
            "potential_benefits",
            "potential_risks",
            "who_may_benefit",
            "who_should_be_cautious",
            "conditions_that_change_the_answer",
            "evidence_strength",
            "remaining_uncertainties",
            "why_this_conclusion",
            "practical_conclusion",
        }
        missing = sorted(expected - set(data))
        if missing:
            raise ValidationError(f"{path} is missing required fields: {', '.join(missing)}")
        try:
            strength = EvidenceStrength(data["evidence_strength"])
        except (TypeError, ValueError) as exc:
            allowed = ", ".join(item.value for item in EvidenceStrength)
            raise ValidationError(f"{path}.evidence_strength must be one of: {allowed}") from exc
        return cls(
            direct_answer=_required_string(data, "direct_answer", path),
            potential_benefits=_string_list(data, "potential_benefits", path),
            potential_risks=_string_list(data, "potential_risks", path),
            who_may_benefit=_string_list(data, "who_may_benefit", path),
            who_should_be_cautious=_string_list(data, "who_should_be_cautious", path),
            conditions_that_change_the_answer=_string_list(
                data, "conditions_that_change_the_answer", path
            ),
            evidence_strength=strength,
            remaining_uncertainties=_string_list(data, "remaining_uncertainties", path),
            why_this_conclusion=_string_list(data, "why_this_conclusion", path),
            practical_conclusion=_required_string(data, "practical_conclusion", path),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence_strength"] = self.evidence_strength.value
        return result


AgentOutput = ResearchAgentResult
JudgeOutput = FinalAnswer
