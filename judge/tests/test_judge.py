from __future__ import annotations

import json
import unittest

from core.judge import (
    EvidenceReviewEngine,
    assess_study,
    build_evidence_package,
    detect_source_relationships,
    deduplicate_studies,
    parse_claim_support,
    parse_final_answer,
)
from core.schema import (
    EvidenceSource,
    EvidenceStrength,
    SourceType,
    Study,
    ValidationError,
)


def valid_output(**overrides):
    result = {
        "direct_answer": "The evidence supports a cautious, context-dependent answer.",
        "potential_benefits": ["A supported benefit."],
        "potential_risks": ["A supported risk."],
        "who_may_benefit": ["Some adults."],
        "who_should_be_cautious": ["People with relevant medical conditions."],
        "conditions_that_change_the_answer": ["Population and duration."],
        "evidence_strength": "moderate",
        "remaining_uncertainties": ["Long-term outcomes."],
        "why_this_conclusion": ["Controlled evidence is relevant but limited in duration."],
        "practical_conclusion": "Consider sustainability and seek clinical guidance when needed.",
    }
    result.update(overrides)
    return result


def agent_payload():
    return {
        "agent_id": "benefits_agent",
        "perspective": "potential_benefits",
        "overall_conclusion": "Raw agent conclusion.",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim": "The intervention may support modest weight loss.",
                "claim_type": "causal",
                "confidence": "moderate",
                "source_ids": ["study_1"],
            }
        ],
        "sources": [
            {
                "source_id": "study_1",
                "source_type": "randomized_trial",
                "title": "A randomized trial",
                "doi": "https://doi.org/10.1000/TEST.1",
                "publication_date": "2023-05-10",
                "population": "Adults with overweight",
                "sample_size": 250,
                "duration": "12 weeks",
                "human_or_animal": "human",
                "main_finding": "Both groups lost weight.",
                "limitations": ["Short duration"],
                "funding_or_conflicts": "unknown",
                "evidence_excerpt": "Both interventions produced modest changes.",
            }
        ],
    }


class SequenceAdapter:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        return next(self.responses)


class RaisingAdapter:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("model unavailable")


class ValidationTests(unittest.TestCase):
    def test_missing_agent_id_has_useful_path(self):
        payload = agent_payload()
        del payload["agent_id"]
        with self.assertRaisesRegex(ValidationError, r"agents\[0\]\.agent_id"):
            build_evidence_package("Is this beneficial?", [payload])

    def test_optional_study_fields_remain_unknown(self):
        payload = agent_payload()
        payload["sources"][0] = {"source_id": "study_1", "title": "Sparse metadata"}
        package = build_evidence_package("Is this beneficial?", [payload])
        source = package["sources"][0]
        self.assertEqual(source["sample_size"], "unknown")
        self.assertEqual(source["funding_or_conflicts"], "unknown")

    def test_empty_agents_rejected(self):
        with self.assertRaisesRegex(ValidationError, "at least one"):
            build_evidence_package("Question?", [])

    def test_duplicate_agent_ids_rejected(self):
        payload = agent_payload()
        with self.assertRaisesRegex(ValidationError, "must be unique"):
            build_evidence_package("Question?", [payload, payload])

    def test_unsourced_claim_is_rejected_before_model(self):
        payload = agent_payload()
        payload["claims"][0]["source_ids"] = []
        package = build_evidence_package("Question?", [payload])
        self.assertEqual(package["claims"], [])
        self.assertEqual(
            package["provenance"]["rejected_claims"][0]["reason"],
            "no_valid_source_ids",
        )

    def test_malformed_publication_date_rejected(self):
        payload = agent_payload()
        payload["sources"][0]["publication_date"] = "May 10, 2023"
        with self.assertRaisesRegex(ValidationError, "YYYY-MM-DD"):
            build_evidence_package("Question?", [payload])

    def test_legacy_studies_field_is_supported(self):
        payload = agent_payload()
        payload["studies"] = payload.pop("sources")
        package = build_evidence_package("Question?", [payload])
        self.assertEqual(package["provenance"]["unique_source_count"], 1)


class SourceTypeTests(unittest.TestCase):
    def test_all_supported_source_types_parse(self):
        for source_type in SourceType:
            payload = agent_payload()
            payload["sources"][0]["source_type"] = source_type.value
            parsed = build_evidence_package("Question?", [payload])
            self.assertEqual(parsed["sources"][0]["source_type"], source_type.value)

    def test_unknown_source_type_has_clear_error(self):
        payload = agent_payload()
        payload["sources"][0]["source_type"] = "influencer_video"
        with self.assertRaisesRegex(ValidationError, "source_type is unsupported"):
            build_evidence_package("Question?", [payload])


class DeduplicationTests(unittest.TestCase):
    def test_doi_is_normalized_and_deduplicated(self):
        one = Study(source_id="a", doi="https://doi.org/10.1000/ABC", title="First")
        two = Study(source_id="b", doi="doi:10.1000/abc", population="Adults")
        unique, aliases = deduplicate_studies([one, two])
        self.assertEqual(len(unique), 1)
        self.assertEqual(aliases["b"], "a")
        self.assertEqual(unique[0].population, "Adults")
        self.assertIn("b", unique[0].duplicate_source_ids)

    def test_normalized_url_used_when_doi_missing(self):
        one = Study(source_id="a", url="HTTPS://EXAMPLE.COM/paper/?utm=x")
        two = Study(source_id="b", url="https://example.com/paper")
        unique, aliases = deduplicate_studies([one, two])
        self.assertEqual(len(unique), 1)
        self.assertEqual(aliases["b"], "a")

    def test_normalized_title_used_when_doi_and_url_missing(self):
        one = Study(source_id="a", title="Diet, Timing & Health")
        two = Study(source_id="b", title=" diet timing and health ")
        unique, _ = deduplicate_studies([one, two])
        self.assertEqual(len(unique), 1)

    def test_author_year_title_deduplicates_different_urls(self):
        one = EvidenceSource(
            source_id="a",
            title="Same original paper",
            url="https://publisher.example/paper",
            publisher_or_author="Example Authors",
            publication_year=2024,
        )
        two = EvidenceSource(
            source_id="b",
            title="Same original paper",
            url="https://repository.example/paper",
            publisher_or_author="Example Authors",
            publication_year=2024,
        )
        unique, aliases = deduplicate_studies([one, two])
        self.assertEqual(len(unique), 1)
        self.assertEqual(aliases["b"], "a")

    def test_claim_sources_are_remapped_after_deduplication(self):
        first = agent_payload()
        second = agent_payload()
        second["agent_id"] = "risks_agent"
        second["perspective"] = "potential_risks"
        second["sources"][0]["source_id"] = "same_study"
        second["claims"][0]["claim_id"] = "claim_2"
        second["claims"][0]["source_ids"] = ["same_study"]
        package = build_evidence_package("Question?", [first, second])
        self.assertEqual(package["provenance"]["unique_source_count"], 1)
        self.assertEqual(package["claims"][1]["source_ids"], ["study_1"])


class SourceChainTests(unittest.TestCase):
    def test_same_title_different_pages_is_marked_as_mirror(self):
        one = EvidenceSource(
            source_id="one",
            source_type=SourceType.ACADEMIC_SOURCE,
            title="Shared page title",
            url="https://one.example/page",
        )
        two = EvidenceSource(
            source_id="two",
            source_type=SourceType.ACADEMIC_SOURCE,
            title="Shared page title",
            url="https://two.example/page",
        )
        relationships = detect_source_relationships(
            [one, two], {"one": "one", "two": "two"}
        )
        self.assertIn(
            {
                "source_id": "two",
                "related_source_id": "one",
                "relationship": "mirrored_page",
            },
            relationships,
        )

    def test_secondary_page_points_to_original(self):
        original = EvidenceSource(
            source_id="paper",
            source_type=SourceType.RANDOMIZED_TRIAL,
            doi="10.1000/original",
        )
        article = EvidenceSource(
            source_id="news",
            source_type=SourceType.NEWS_ARTICLE,
            url="https://news.example/story",
            references_original_source="10.1000/original",
        )
        relationships = detect_source_relationships(
            [original, article], {"paper": "paper", "news": "news"}
        )
        self.assertIn(
            {
                "source_id": "news",
                "related_source_id": "paper",
                "relationship": "secondary_article_discussing_original_source",
            },
            relationships,
        )

    def test_circular_chain_is_flagged(self):
        one = EvidenceSource(
            source_id="one",
            source_type=SourceType.NEWS_ARTICLE,
            references_original_source="two",
        )
        two = EvidenceSource(
            source_id="two",
            source_type=SourceType.BLOG,
            references_original_source="one",
        )
        relationships = detect_source_relationships(
            [one, two], {"one": "one", "two": "two"}
        )
        self.assertTrue(
            any(item["relationship"] == "circular_citation_chain" for item in relationships)
        )


class ScoringTests(unittest.TestCase):
    def test_stronger_design_scores_higher_than_observational(self):
        common = {
            "publication_year": 2024,
            "population": "Adults",
            "sample_size": 300,
            "duration": "16 weeks",
            "human_or_animal": "human",
            "limitations": ["Single center"],
            "funding_or_conflicts": "none reported",
            "evidence_excerpt": "Relevant result",
        }
        rct = assess_study(
            Study(source_id="rct", source_type=SourceType.RANDOMIZED_TRIAL, **common),
            current_year=2026,
        )
        observational = assess_study(
            Study(source_id="obs", source_type=SourceType.OBSERVATIONAL_STUDY, **common),
            current_year=2026,
        )
        self.assertGreater(rct.methodological_score, observational.methodological_score)

    def test_quality_flags_missing_metadata(self):
        result = assess_study(
            Study(source_id="s", source_type=SourceType.COHORT_STUDY),
            current_year=2026,
        )
        self.assertIn("sample_size_unknown", result.flags)
        self.assertIn("limitations_not_reported", result.flags)
        self.assertIn("population_unknown", result.flags)

    def test_causal_claim_with_only_observational_source_is_flagged(self):
        payload = agent_payload()
        payload["sources"][0]["source_type"] = "observational_study"
        package = build_evidence_package("Question?", [payload])
        self.assertIn(
            "possible_correlation_as_causation",
            package["claims"][0]["deterministic_warning_flags"],
        )

    def test_social_media_cannot_receive_high_source_prior(self):
        result = assess_study(
            EvidenceSource(source_id="post", source_type=SourceType.SOCIAL_MEDIA),
            current_year=2026,
        )
        self.assertLess(result.credibility_score, 0.2)
        self.assertIn("anecdotal_only", result.flags)

    def test_company_source_is_flagged(self):
        result = assess_study(
            EvidenceSource(source_id="company", source_type=SourceType.COMPANY_SOURCE),
            current_year=2026,
        )
        self.assertIn("commercial_interest", result.flags)
        self.assertIn("company_only_evidence", result.flags)


class OutputAndRetryTests(unittest.TestCase):
    def test_valid_output_parses(self):
        result = parse_final_answer(json.dumps(valid_output()))
        self.assertEqual(result.evidence_strength, EvidenceStrength.MODERATE)

    def test_claim_support_parses(self):
        raw = json.dumps(
            {
                "assessments": [
                    {
                        "claim_id": "claim_1",
                        "support": "partially_supported",
                        "relevance": "direct",
                        "overstatement": True,
                        "population_mismatch": False,
                        "explanation": "The source supports a narrower claim.",
                    }
                ]
            }
        )
        assessments = parse_claim_support(raw)
        self.assertEqual(assessments[0].support.value, "partially_supported")

    def test_invalid_claim_support_rejected(self):
        with self.assertRaisesRegex(ValidationError, "assessments list"):
            parse_claim_support('{"wrong": []}')

    def test_invalid_strength_rejected(self):
        with self.assertRaisesRegex(ValidationError, "must be one of"):
            parse_final_answer(json.dumps(valid_output(evidence_strength="excellent")))

    def test_malformed_json_retried_once(self):
        adapter = SequenceAdapter(["not json", json.dumps(valid_output())])
        result = EvidenceReviewEngine(adapter).review("Question?", [agent_payload()])
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(result.evidence_strength, EvidenceStrength.MODERATE)

    def test_generation_failure_returns_deterministic_fallback(self):
        adapter = SequenceAdapter(["not json", '{"still": "invalid"}'])
        result = EvidenceReviewEngine(adapter).review("Question?", [agent_payload()])
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(result.evidence_strength, EvidenceStrength.INSUFFICIENT)
        self.assertEqual(result.potential_benefits, [])
        self.assertIn("could not be synthesized", result.direct_answer)

    def test_runtime_exception_retried_then_falls_back(self):
        adapter = RaisingAdapter()
        result = EvidenceReviewEngine(adapter).review("Question?", [agent_payload()])
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(result.evidence_strength, EvidenceStrength.INSUFFICIENT)


if __name__ == "__main__":
    unittest.main()
