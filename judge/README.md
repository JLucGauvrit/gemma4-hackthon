# Gemma 4 Evidence Review Engine

The Evidence Review Engine—also called the Judge Agent—synthesizes scientific
evidence returned by multiple nutrition research agents. It does **not** select
a winning agent and does **not** use majority voting. Agent conclusions remain
untrusted context; cited claims and their linked evidence sources drive the synthesis.

## Architecture

```text
nutrition question
      +
research-agent results
      |
      v
validation -> citation gate -> source deduplication + chains -> deterministic assessment
      |
      v
Gemma semantic review and synthesis
      |
      v
validated FinalAnswer JSON
```

Python owns deterministic operations:

- Typed input and output validation
- Citation/source-link validation
- Deduplication by DOI, canonical URL, normalized title, and author/year/title
- Original-source, mirror, secondary-coverage, and circular-chain detection
- Source-type-aware credibility/methodological priors and warning flags
- JSON parsing, one retry, and a fail-closed fallback

Gemma owns semantic operations:

- Exact-question and population relevance
- Whether evidence supports each claim
- Overstatement, cherry-picking, and ignored conflicts
- Benefits, risks, contextual differences, and remaining uncertainty
- The final balanced user-facing synthesis

## Package layout

```text
core/
  schema.py   Typed agent, evidence-source, claim, assessment, and output models
  gemma.py    Replaceable model protocol and JSON-only prompts
  judge.py    Validation, deduplication, assessment, orchestration, retry/fallback
examples/
  intermittent_fasting_demo.py
tests/
  test_judge.py
```

## Research-agent contract

Call `EvidenceReviewEngine.review(question, agents)` with a list of dictionaries
or typed `ResearchAgentResult` objects. Each agent should provide:

- `agent_id`
- `perspective`
- optional `overall_conclusion`
- `claims`, each with a stable `claim_id`, claim text, and `source_ids`
- `sources`, each with a stable `source_id` and supported `source_type`

All source metadata beyond `source_id` is optional. Missing values remain
unknown and are never invented. A claim with no valid cited source is rejected
before Gemma sees it.

For compatibility, the parser also accepts the previous `studies` field and
maps legacy study types such as `randomized_controlled_trial` to the generic
source taxonomy.

The input schema in `core/schema.py` extends the PRD's existing
`Source`/`Claim` contract with generic and nutrition-specific metadata. Raw
`overall_conclusion` values remain separate from evidence-supported findings.

Supported types include systematic reviews, meta-analyses, trials,
observational designs, guidelines, government and medical organizations,
academic sources, datasets/statistics, expert and news articles, company
sources, blogs, forums, social media, and `other`. Weak or anecdotal sources
may contribute experiences and practical concerns but cannot independently
justify strong causal, medical, prevalence, or safety conclusions.

## Connect a Gemma client

The Judge depends on the small `GemmaAdapter` protocol:

```python
from core import CallableGemmaAdapter, judge_evidence


def call_your_gemma_runtime(prompt: str) -> str:
    # Send prompt to the local or hosted Gemma runtime.
    # Return its raw text response.
    ...


answer = judge_evidence(
    question,
    research_agent_results,
    CallableGemmaAdapter(call_your_gemma_runtime),
)
print(answer.to_dict())
```

The prompt requires JSON only. The response is parsed into `FinalAnswer`; if it
is malformed, the Judge retries once with the validation error. A second
failure returns a deterministic `insufficient` response instead of crashing or
inventing a conclusion.

## Run the tests

The tests use only the Python standard library:

```bash
python -m unittest discover -s tests -v
```

## Run the offline demo

```bash
python examples/intermittent_fasting_demo.py
```

The demo uses a deterministic adapter so it runs without model infrastructure.
Replace `demo_generate` with the project's Gemma client for a live synthesis.
Its duplicate study appears in two agent results and is counted once.

## Passing results from another agent

```python
agent_result = {
    "agent_id": "benefits_agent",
    "perspective": "potential_benefits",
    "overall_conclusion": "Raw agent opinion kept separate from evidence.",
    "overall_confidence": "moderate",
    "claims": [
        {
            "claim_id": "claim_1",
            "claim": "The intervention may support modest weight loss.",
            "claim_type": "causal",
            "confidence": "moderate",
            "source_ids": ["source_1"],
        }
    ],
    "sources": [
        {
            "source_id": "source_1",
            "source_type": "randomized_trial",
            "title": "Example trial",
            "doi": "10.0000/example",
            "publication_date": "2023-05-10",
            # Every other field is optional and stays unknown if omitted.
        }
    ],
}

answer = judge_evidence(question, [agent_result], gemma_adapter)
```

`references_original_source` may contain a source ID, DOI, or canonical URL.
The Judge uses it to prevent several secondary pages about one study from
being interpreted as independent evidence.

## Safety and interpretation

The output is an evidence summary, not personalized medical advice.
`evidence_strength` is one of `strong`, `moderate`, `limited`, `conflicting`,
or `insufficient`. Strength is not derived from source counts; the Judge weighs
design, methods, relevance, independence, sample size, duration, limitations,
claim support, and consistency.
