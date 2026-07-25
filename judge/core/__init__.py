"""Core contracts and orchestration for the evidence review pipeline."""

from .gemma import CallableGemmaAdapter, GemmaAdapter
from .judge import EvidenceReviewEngine, judge_evidence
from .schema import (
    AgentOutput,
    ClaimSupportAssessment,
    EvidenceSource,
    EvidenceStrength,
    FinalAnswer,
    JudgeOutput,
    ResearchAgentResult,
    SourceAssessment,
    SourceType,
    ValidationError,
)

__all__ = [
    "CallableGemmaAdapter",
    "AgentOutput",
    "ClaimSupportAssessment",
    "EvidenceSource",
    "EvidenceReviewEngine",
    "EvidenceStrength",
    "FinalAnswer",
    "GemmaAdapter",
    "JudgeOutput",
    "ResearchAgentResult",
    "SourceAssessment",
    "SourceType",
    "ValidationError",
    "judge_evidence",
]
