import unittest
from unittest.mock import AsyncMock, patch

from core.pipeline import (
    _advocate_prompt,
    _stance_prompt,
    budget,
    classify_stance,
    route,
    run,
)
from core.schema import Claim, Config, Snippet, Source


def snippet(sid: str, text: str) -> Snippet:
    return Snippet(
        id=sid,
        text=text,
        stance="NEUTRAL",
        confidence=0.0,
        source=Source(
            doi=f"10/{sid}",
            title=f"Source {sid}",
            authors=[],
            year=2026,
            venue="Test",
            license=None,
            retrieved_via="openaire",
        ),
    )


class StancePromptTests(unittest.TestCase):
    def test_uncertainty_is_not_treated_as_refutation(self):
        prompt = _stance_prompt(
            "Creatine supplementation improves cognition in healthy adults.",
            [snippet("s1", "There is insufficient evidence to reach a conclusion.")],
        )

        self.assertIn("INSUFFICIENT evidence", prompt)
        self.assertIn("UNRESOLVED", prompt)
        self.assertNotIn("weak, mixed, or null on-topic finding — that is REFUTES", prompt)

    def test_rebuttal_prompt_directly_addresses_opponent(self):
        prompt = _advocate_prompt(
            "FOR",
            "Creatine improves cognition.",
            [snippet("s1", "A trial reported improved memory.")],
            [Claim("The evidence is too uncertain.", ["s2"])],
        )

        self.assertIn("Respond directly", prompt)
        self.assertIn("The evidence is too uncertain.", prompt)


class StanceClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_preserves_its_reason(self):
        response = (
            '[{"id":"s1","stance":"UNRESOLVED","confidence":0.8,'
            '"reason":"The review says the evidence is insufficient, not that there is no effect."}]'
        )

        with patch("core.pipeline.llm.generate", new=AsyncMock(return_value=response)):
            classified = await classify_stance(
                "Creatine improves cognition.",
                [snippet("s1", "Evidence is insufficient to reach a conclusion.")],
                Config(),
            )

        self.assertEqual("UNRESOLVED", classified[0].stance)
        self.assertIn("insufficient", classified[0].stance_reason)

    async def test_directional_batch_label_is_verified_individually(self):
        batch_response = (
            '[{"id":"s1","stance":"SUPPORTS","confidence":0.7,'
            '"reason":"mentions possible improvements"},'
            '{"id":"s2","stance":"NEUTRAL","confidence":0.8,'
            '"reason":"does not report a result"}]'
        )
        verification_response = (
            '[{"id":"s1","stance":"UNRESOLVED","confidence":0.9,'
            '"reason":"possible improvements require replication"}]'
        )

        with patch(
            "core.pipeline.llm.generate",
            new=AsyncMock(side_effect=[batch_response, verification_response]),
        ) as generate:
            classified = await classify_stance(
                "Creatine improves cognition.",
                [
                    snippet("s1", "Possible improvements require replication."),
                    snippet("s2", "A protocol for a future study."),
                ],
                Config(),
            )

        self.assertEqual(2, generate.await_count)
        self.assertEqual("UNRESOLVED", classified[0].stance)
        self.assertIn("replication", classified[0].stance_reason)

    def test_unresolved_evidence_challenges_but_does_not_refute_the_claim(self):
        unresolved = snippet("s1", "The evidence is insufficient.")
        unresolved.stance = "UNRESOLVED"
        unresolved.confidence = 0.8

        for_pile, against_pile = budget([unresolved], Config())

        self.assertEqual([], for_pile)
        self.assertEqual(["s1"], [item.id for item in against_pile])
        self.assertEqual("UNRESOLVED", against_pile[0].stance)


class DebateConfigTests(unittest.TestCase):
    def test_rebuttal_is_enabled_by_default(self):
        self.assertTrue(Config().rebuttal)

    def test_two_one_sided_sources_do_not_establish_consensus(self):
        self.assertEqual("INSUFFICIENT_EVIDENCE", route(2, 0, 1.0, Config()))


class DebateStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_contested_run_streams_openings_then_rebuttals(self):
        evidence = [
            snippet("s1", "Positive result."),
            snippet("s2", "Positive replication."),
            snippet("s3", "Null result."),
            snippet("s4", "Null replication."),
        ]
        evidence[0].stance = evidence[1].stance = "SUPPORTS"
        evidence[2].stance = evidence[3].stance = "REFUTES"
        for item in evidence:
            item.confidence = 0.8

        calls = []

        async def fake_advocate(side, claim, partition, rnd, cfg, opponent=None):
            calls.append((side, rnd, [c.text for c in opponent or []]))
            yield {
                "type": "turn_claim",
                "side": side,
                "round": rnd,
                "claim": Claim(f"{side} round {rnd}", [partition[0].id]),
            }

        async def fake_enrich(items):
            for item in items:
                item.text += " Full result."

        async def fake_classify(claim, items, cfg):
            self.assertTrue(all(item.text.endswith("Full result.") for item in items))
            return items

        judge_result = {
            "crux": "Different results.",
            "crux_type": "effect-size",
            "resolver": "A larger replication.",
            "asymmetry": 0.0,
        }
        intake_result = {
            "verdict": "CLAIM",
            "claim": "Creatine improves cognition.",
            "query": "creatine cognition",
        }

        with (
            patch("core.pipeline.intake_decide", new=AsyncMock(return_value=intake_result)),
            patch("core.pipeline.retrieve", new=AsyncMock(return_value=evidence)),
            patch("core.pipeline.classify_stance", side_effect=fake_classify),
            patch("core.retrieve.enrich_full_abstracts", side_effect=fake_enrich),
            patch("core.pipeline.advocate", side_effect=fake_advocate),
            patch("core.pipeline.judge", new=AsyncMock(return_value=judge_result)),
        ):
            events = [event async for event in run("Does creatine help?")]

        turns = [event for event in events if event["type"] == "turn_claim"]
        self.assertEqual([0, 0, 1, 1], sorted(event["round"] for event in turns))
        phases = [event["phase"] for event in events if event["type"] == "phase"]
        self.assertEqual(["opening", "rebuttal", "judging"], phases)
        rebuttals = [call for call in calls if call[1] == 1]
        self.assertEqual(2, len(rebuttals))
        self.assertTrue(all(opponent_claims for _, _, opponent_claims in rebuttals))


if __name__ == "__main__":
    unittest.main()
