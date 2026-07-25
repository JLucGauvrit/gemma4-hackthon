# Devil's Advocates

**Track 03 — Context Engineering for SLMs**  
**Gemma 4 Hackathon · 42 Paris**

> A disagreement engine for contested scientific questions. Given a claim, it produces a sourced disagreement brief: the strongest case for, the strongest case against, where the evidence actually diverges, and what evidence would settle the question. The Judge never simply picks a winner.

---

## What we built, and who for

Devil's Advocates helps people understand whether the available evidence truly agrees on a scientific claim.

It is designed for researchers, PhD students, science journalists, and curious users who need to know:

- what the strongest evidence **for** a claim is;
- what the strongest evidence **against** it is;
- whether the disagreement is genuine or mostly superficial;
- which assumptions, populations, methods, or outcomes create the split;
- what evidence would most likely resolve the disagreement.

The gap is simple:

- Google Scholar returns papers but does not synthesize the disagreement.
- A general-purpose LLM often returns one confident paragraph that hides uncertainty.
- Naive RAG can place all evidence into one context and allow the strongest narrative to dominate.

Devil's Advocates instead creates two controlled, evidence-grounded contexts and asks Gemma to expose the real crux of the disagreement.

### Core principle

> **The system compares evidence, not opinions.**

The advocates' conclusions are treated as untrusted context. Only claims linked to valid evidence sources are allowed to reach the Judge.

---

## Worked example

For a question such as:

> **Does creatine improve cognition?**

the system retrieves relevant evidence, classifies passages by stance, and builds two sourced cases.

The final result is not simply:

> "Yes" or "No."

Instead, the system may explain that:

- some evidence suggests benefits in specific populations or under specific conditions;
- other studies report small, inconsistent, or null effects;
- differences in population, dosage, baseline nutritional status, cognitive task, and study design may explain the disagreement;
- stronger evidence would require larger, longer, better-controlled trials using consistent outcomes.

The output focuses on **why** the literature differs, not only on which side contains more papers.

---

## Architecture, and how Gemma 4 is used

```text
User claim
    |
    v
Claim Extractor
    |
    v
Retriever
    |
    v
Stance Classifier
SUPPORTS / REFUTES / NEUTRAL
    |
    v
Context Budgeter
disjoint FOR and AGAINST evidence partitions
    |
    +--------------------------+
    |                          |
    v                          v
Advocate FOR              Advocate AGAINST
same model                same model
same instructions         same instructions
different evidence        different evidence
    |                          |
    +------------+-------------+
                 |
                 v
              Rebuttal
                 |
                 v
        Evidence Review Judge
                 |
                 v
      Structured disagreement brief
```

### Why this is Track 03

The main experimental variable is **context construction**.

Both advocates use:

- the same model;
- the same role structure;
- the same response constraints;
- the same token budget.

The only important difference is which evidence slice enters each advocate's context.

This lets us test whether controlled context partitioning helps Gemma reveal both sides of a contested question more reliably than a single mixed context.

### Gemma 4 model strategy

The intended model design uses one nested Gemma checkpoint through MatFormer rather than loading several unrelated models.

This supports different effective model tiers for different jobs while keeping one model family in memory.

Role-specific reasoning budgets:

| Role | Reasoning budget | Main task |
|---|---:|---|
| Claim Extractor | Low | Convert the user's question into a searchable claim |
| Stance Classifier | None, batched | Label passages as SUPPORTS, REFUTES, or NEUTRAL |
| Advocates | Low | Build short, stance-locked, sourced cases |
| Judge | High | Identify the crux, evaluate evidence, and return structured JSON |

Advocate turns are intentionally short, approximately 150 tokens or less. The Judge receives the higher reasoning budget because synthesis and conflict analysis are more demanding.

The Judge is run twice with the FOR and AGAINST positions swapped. The two results are then merged. This reduces position-order bias and checks whether both runs identify the same underlying crux.

---

## Retrieval

The project uses Alien research MCPs.

### OpenAIRE

OpenAIRE provides broad literature coverage and useful provenance metadata, including:

- title;
- abstract;
- DOI;
- authors;
- journal;
- publication year;
- citation count;
- influence class;
- peer-review status;
- open-access information;
- subject metadata.

The abstract returned by the full-detail search is treated as a stance-bearing evidence unit.

OpenAIRE is the main breadth layer.

### medRxiv

medRxiv provides deeper clinical full-text passages.

The correct retrieval order is:

1. keyword search to identify on-topic entries;
2. vector search only inside those entries.

This is important because raw semantic search can retrieve passages that match the wording of a claim while being unrelated to the actual topic.

For example, a semantic query containing "no effect on cognition" may return unrelated null-result passages from papers that do not study creatine.

medRxiv is therefore used as the clinical depth layer.

### bioRxiv

bioRxiv is useful for molecular and basic-science questions, but it is not the default source for clinical nutrition or health-intervention claims.

For those questions, OpenAIRE and medRxiv are more appropriate.

---

## Shared evidence contract

Every claim must cite one or more valid source or snippet IDs.

A source may represent:

- a systematic review or meta-analysis;
- a randomized or controlled trial;
- an observational study;
- a clinical guideline;
- a government, academic, or medical-organization source;
- a dataset or statistics report;
- an expert or news article;
- a company page;
- a blog, forum, or social-media source.

Missing metadata remains unknown. The system never invents it.

Weak or anecdotal sources may help identify:

- personal experiences;
- practical barriers;
- public concerns;
- reported side effects;
- questions that require further investigation.

However, they cannot independently justify strong causal, clinical, prevalence, or safety claims.

The system also checks whether several sources are actually:

- exact duplicates;
- mirrored pages;
- secondary articles discussing the same original study;
- parts of the same citation chain;
- circularly citing one another.

Several articles covering one paper are not counted as several independent pieces of evidence.

---

## The advocates

The FOR and AGAINST advocates are stance-locked.

Each advocate:

- sees only its own evidence partition;
- may cite only source or snippet IDs present in that partition;
- must keep claims short and sourced;
- may rebut the other advocate's claims;
- never sees the other advocate's hidden evidence;
- may explicitly concede a point.

A claim is dropped before reaching the Judge when:

- it has no citations;
- its citation list is empty;
- it cites a source outside the advocate's partition;
- its cited source cannot be validated.

This prevents unsupported model-generated claims from influencing the synthesis.

---

## The Judge

The Judge is an **Evidence Review Engine**, not a voting mechanism.

It does not ask:

> Which advocate is right?

It asks:

> Which conclusions are actually justified by the available evidence?

The Judge identifies:

- the main point of disagreement;
- the type of disagreement;
- the strength and asymmetry of the evidence;
- supported benefits and risks;
- relevant population differences;
- conditions that change the answer;
- remaining uncertainty;
- what evidence would most likely resolve the question.

It can conclude that the evidence is:

- `strong`
- `moderate`
- `limited`
- `conflicting`
- `insufficient`

It is explicitly allowed to say that the current evidence is insufficient instead of forcing a binary conclusion.

### Deterministic work in Python

Python handles:

- typed input and output validation;
- citation validation;
- missing-field handling;
- URL and DOI normalization;
- deduplication by DOI, canonical URL, normalized title, and author/year/title;
- original-source and mirror detection;
- source-chain and circular-reference detection;
- source-type-aware priors and warnings;
- JSON parsing;
- one retry after malformed output;
- a conservative fallback when generation fails.

### Semantic work in Gemma

Gemma handles:

- relevance to the exact question;
- population relevance;
- whether the cited evidence supports the claim;
- whether a conclusion is overstated;
- cherry-picking detection;
- correlation-versus-causation errors;
- ignored contradictory evidence;
- benefits, risks, contextual differences, and uncertainty;
- final user-facing synthesis.

### Judge evaluation criteria

The Judge evaluates:

1. **Evidence quality**  
   How reliable is the source or study design?

2. **Question relevance**  
   Does the evidence answer the user's actual question?

3. **Population match**  
   Was the relevant population studied?

4. **Methodological strength**  
   Were the design, sample size, duration, comparison, and outcomes appropriate?

5. **Claim-to-source support**  
   Does the cited source really support the wording of the claim?

6. **Consistency**  
   Do independent sources reach similar conclusions?

7. **Independence**  
   Are the sources truly separate, or are they repeating the same original evidence?

8. **Recency**  
   Is the evidence current enough for the question?

9. **Limitations**  
   Were important weaknesses acknowledged?

10. **Conflict-of-interest risk**  
    Could commercial or institutional interests affect interpretation?

11. **Benefits versus risks**  
    What positive and negative outcomes are actually supported?

12. **Remaining uncertainty**  
    What cannot yet be concluded reliably?

The number of sources alone does not determine the result. A smaller amount of strong, relevant, independent evidence may outweigh many weak, repetitive, or indirect sources.

### Reasoning safeguards

The Judge flags:

- cherry-picking;
- correlation presented as causation;
- overstated conclusions;
- unsupported claims;
- ignored conflicting evidence;
- population overgeneralization;
- missing limitations;
- source-to-claim mismatch;
- multiple articles repeating one original source;
- company claims supported only by company material;
- anecdotes treated as prevalence data;
- animal evidence generalized directly to humans;
- outdated guidance presented as current.

---

## Judge output

The Judge returns valid structured JSON.

```json
{
  "direct_answer": "",
  "potential_benefits": [],
  "potential_risks": [],
  "who_may_benefit": [],
  "who_should_be_cautious": [],
  "conditions_that_change_the_answer": [],
  "evidence_strength": "",
  "remaining_uncertainties": [],
  "why_this_conclusion": [],
  "practical_conclusion": ""
}
```

### Field meanings

- `direct_answer`  
  One concise and balanced answer.

- `potential_benefits`  
  Benefits supported by the available evidence.

- `potential_risks`  
  Risks or disadvantages supported by the evidence.

- `who_may_benefit`  
  Populations for whom benefits appear more likely.

- `who_should_be_cautious`  
  Populations for whom evidence or safety guidance supports caution.

- `conditions_that_change_the_answer`  
  Factors such as age, health status, intervention type, dose, duration, food quality, medication use, or lifestyle.

- `evidence_strength`  
  `strong`, `moderate`, `limited`, `conflicting`, or `insufficient`.

- `remaining_uncertainties`  
  Questions the evidence cannot answer confidently.

- `why_this_conclusion`  
  Short user-facing explanations of the evidence basis. This is not private chain-of-thought.

- `practical_conclusion`  
  A useful real-world interpretation without unsafe personalized medical advice.

For the complete product brief, the Judge also identifies the central crux, its `crux_type`, and evidence asymmetry. It never declares a winner merely because one side contains more sources.

---

## Example output: intermittent fasting

```json
{
  "direct_answer": "Intermittent fasting may be helpful for some adults, but it is not universally beneficial or clearly superior to other sustainable dietary approaches.",
  "potential_benefits": [
    "May support modest weight loss when it reduces total calorie intake.",
    "May improve some metabolic markers in certain adult populations.",
    "May provide a simple and structured eating schedule."
  ],
  "potential_risks": [
    "May cause hunger, fatigue, or difficulty concentrating.",
    "Can be difficult to maintain over time.",
    "May encourage overeating during the eating window for some people."
  ],
  "who_may_benefit": [
    "Some healthy adults who prefer structured eating schedules.",
    "Some adults with overweight or obesity."
  ],
  "who_should_be_cautious": [
    "People with a history of eating disorders.",
    "Pregnant or breastfeeding people.",
    "People taking glucose-lowering medication.",
    "Children and adolescents unless medically supervised."
  ],
  "conditions_that_change_the_answer": [
    "The fasting protocol.",
    "Overall calorie intake.",
    "Food quality.",
    "Medical history.",
    "Medication use.",
    "Long-term sustainability."
  ],
  "evidence_strength": "moderate",
  "remaining_uncertainties": [
    "Long-term effects remain unclear.",
    "It is uncertain whether intermittent fasting is superior to other calorie-controlled diets.",
    "Evidence differs between populations and fasting protocols."
  ],
  "why_this_conclusion": [
    "Several controlled human studies report modest benefits.",
    "Benefits are not consistently greater than conventional calorie restriction.",
    "Evidence for long-term outcomes and some populations remains limited."
  ],
  "practical_conclusion": "Intermittent fasting can be one reasonable strategy for some adults, but the best approach depends on health status, food quality, personal preference, and sustainability."
}
```

This example shows that the Judge can preserve both supported benefits and supported risks without forcing either advocate to win.

---

## Failure handling

The system is designed to fail honestly.

- If fewer than six useful snippets are retrieved, the query is widened once.
- If evidence is overwhelmingly one-sided, the system returns **not meaningfully split** instead of inventing a debate.
- In a consensus case, it shows the consensus and any credible minority dissent.
- If the Judge returns malformed JSON, the system retries once with a higher reasoning budget.
- If the second attempt also fails, it returns a conservative fallback rather than crashing or fabricating a conclusion.
- Claims with missing or invalid citations are removed.
- Retrieval noise is logged rather than silently treated as valid evidence.

---

## The numbers

> **Do not fill this section with estimated or invented results. Replace the placeholders only after the evaluation harness has been run.**

The evaluation harness compares four configurations using matched token budgets:

1. single-pass Gemma baseline;
2. naive RAG baseline;
3. split-context debate;
4. self-consistency at `n` samples.

### Planned metrics

| Configuration | Unique sources cited | Both sides shown | Consensus correctly detected | Latency | Token count |
|---|---:|---:|---:|---:|---:|
| Single-pass Gemma | TBD | TBD | TBD | TBD | TBD |
| Naive RAG | TBD | TBD | TBD | TBD | TBD |
| Split-context debate | TBD | TBD | TBD | TBD | TBD |
| Self-consistency @ n | TBD | TBD | TBD | TBD | TBD |

### Planned ablations

**Ablation 1 — Context partitioning on versus off**

Question:

> Does splitting evidence into disjoint FOR and AGAINST contexts improve the probability that both credible sides are shown?

Result: **TBD after evaluation**

**Ablation 2 — Judge reasoning budget high versus low**

Question:

> Does reducing the Judge's reasoning budget reduce the quality or stability of the identified crux?

Result: **TBD after evaluation**

The evaluation set should contain approximately 30 frozen claims labeled:

- `expect: split`
- `expect: consensus`

Real results must be reported honestly, including negative results.

---

## What broke

The project does not assume that debate automatically improves factual accuracy.

Important failure modes already identified include:

### Retrieval noise

Raw semantic search can return passages that match the wording of a claim while being unrelated to its subject.

This is why medRxiv retrieval uses keyword search first and vector search only within confirmed on-topic entries.

### Titles are not enough

A title often cannot reliably reveal whether a paper supports or refutes a claim. The stance classifier must inspect the actual abstract or passage.

### Duplicate evidence looks stronger than it is

Several articles, reviews, or pages may refer to the same original study. Without source-chain detection, one result can appear to be many independent confirmations.

### Noisy evidence can create an artificial debate

If irrelevant or weak passages enter the partitions, the system may manufacture disagreement where the literature is mostly aligned.

### JSON generation can fail

The Judge may return malformed structured output. The system retries once, then fails closed.

### Claims can be dropped

Claims without valid citations are removed. This may make an advocate's case shorter, but it is preferable to allowing unsupported conclusions.

### Consensus questions should not be forced into debate

When asymmetry is very high, the correct result is not two equally persuasive columns. The system should report that the question is not meaningfully split.

### Debate may not beat self-consistency on accuracy

This must be measured rather than assumed.

Even if debate does not win on raw answer accuracy, the product may still provide something voting cannot:

> a legible, sourced account of why the literature disagrees and what the disagreement rests on.

Additional measured failures and trade-offs should be added here after the end-to-end evaluation is complete.

---

## Current implementation status

The Judge package currently includes:

```text
judge/
  core/
    schema.py
    gemma.py
    judge.py
  examples/
    intermittent_fasting_demo.py
  tests/
    test_judge.py
  README.md
```

The existing Judge implementation supports:

- dictionaries or typed research-agent results;
- generic evidence sources rather than research papers only;
- legacy `studies` input for compatibility;
- source validation and citation gates;
- DOI, URL, title, and author/year/title deduplication;
- source-chain detection;
- replaceable Gemma adapters;
- JSON-only model prompts;
- one retry after malformed output;
- deterministic fallback output;
- offline tests;
- an intermittent-fasting demo.

Run the Judge tests from the `judge` directory:

```bash
python -m unittest discover -s tests -v
```

Run the offline demo:

```bash
python examples/intermittent_fasting_demo.py
```

Basic integration:

```python
from core import CallableGemmaAdapter, judge_evidence

answer = judge_evidence(
    question,
    research_agent_results,
    CallableGemmaAdapter(call_your_gemma_runtime),
)

print(answer.to_dict())
```

The complete product still requires full integration of:

- retrieval;
- stance classification;
- context budgeting;
- advocates and rebuttals;
- the frontend;
- Brev deployment;
- the evaluation harness;
- final measured numbers.

---

## Demo and pitch

The strongest currently confirmed demo domain is clinical and health interventions because the disagreements are real, understandable to non-experts, and can be grounded in relevant literature.

Confirmed viable claim:

> **Does creatine improve cognition?**

The other demo claims should be locked only after the retrieval and stance pipeline confirms that they contain a genuine and legible evidence split.

Suggested five-minute pitch:

1. **Hook**  
   Google Scholar gives papers without synthesis; an LLM gives synthesis without visible disagreement.

2. **Live demo**  
   Show FOR and AGAINST evidence arriving in parallel, then reveal the crux.

3. **Consensus test**  
   Submit a question where evidence is overwhelmingly one-sided and show that the system refuses to fake a debate.

4. **Architecture**  
   Explain context partitioning, Gemma role budgets, and the nested checkpoint design.

5. **Numbers**  
   Present the real evaluation and ablation results.

6. **Close**  
   > The world does not lack information. It lacks a legible view of what is actually in dispute — and what that dispute rests on.

---

## Closing

Devil's Advocates is not designed to make disagreement louder.

It is designed to make disagreement **legible, sourced, and testable**.

> **The Judge does not decide which agent wins. It explains which conclusions are justified, where the evidence differs, and what remains unknown.**
