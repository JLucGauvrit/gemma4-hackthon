# Devil's Advocates

**A disagreement engine for contested scientific questions.**

Gemma 4 Hackathon · 42 Paris · Track 03 — Context Engineering for SLMs

---

## 0. How to use this document

This is the single source of truth for the build. If you are an AI agent
working on this repo, read sections 1–5 before writing any code, then read
the component spec for your owner in section 7.

**Do not re-litigate design decisions in section 4.** They were reasoned
through before the build started and changing them mid-day costs more than
any improvement is worth.

---

## 1. What we are building

A system that takes a contested scientific claim and produces a
**disagreement brief**: the strongest case for, the strongest case against,
where the two actually diverge, and what evidence would settle it.

Every claim on both sides carries provenance — DOI, title, venue, year.

### What it is not

- Not a search engine. It does not return a list of papers.
- Not a literature review. A review tells you what a field *says*;
  this tells you what a field is still *fighting about*.
- Not an answer engine. **The judge does not pick a winner.**

### The user

A researcher, PhD student, or science journalist who needs to know whether
the literature actually agrees on something, today, before writing the next
paragraph.

Their current options: Google Scholar returns ten papers and no synthesis.
An LLM returns a confident paragraph that hides the disagreement entirely.

### Example output

```
CLAIM  Creatine supplementation improves cognitive performance
       in healthy adults

FOR    5 sources · effects observed in sleep-deprived and
       vegetarian populations
AGAINST 4 sources · null results in rested omnivorous adults

CRUX   [population]  The two literatures test different baselines.
       Effects concentrate where baseline creatine stores are low.

RESOLVER  An RCT stratifying by baseline serum creatine in a
          single rested population.
```

---

## 2. Why this and not something else

**Scientific literature is the only domain where the other side is genuinely
retrievable.** On a political question, "the other side" is rhetoric — an
advocate would be generating, not retrieving, and provenance has nothing to
grip. In a scientific controversy both sides published papers with methods
sections. That is what makes the provenance claim true rather than
decorative.

---

## 3. Track and scoring

**Track 03 — Context Engineering for SLMs.** Declared at start of build, in
the writeup header. (Track 02 caps at 2 for linear chains with no branching
or recovery — which our loop would be.)

Track 03's question: *can engineered context make a small model do a large
model's job?*

Our answer: the model is fixed and identical across all agents. The **only**
thing that differs between the two advocates is which slice of evidence
enters their context. That partition is the intervention.

Track 03's cap: *"caps at 2 if you claim the small model held up without
measuring it."* Cleared by the eval harness (section 8). **The
partition-on/off ablation is what makes the track claim true rather than
asserted. It is not optional.**

### Rubric alignment (100 pts)

| Criterion | Pts | How we score |
|---|---|---|
| Gemma Integration | 30 | Two capability tiers from one nested checkpoint; per-role thinking budgets; MTP. See §6. |
| Innovation & Impact | 30 | Named user with a deadline. Crux output no existing tool produces. |
| Functionality | 20 | Deployed on Brev, reachable by someone who is not us, free-text input. |
| Presentation & Writeup | 20 | Started at lunch, not at 5pm. Owned by frontend. |

---

## 4. Design decisions — settled, do not change

**4.1 Evidence is partitioned by stance, not by source.**
Both advocates draw from the same scientific corpus. The retriever splits by
which side of the claim each snippet supports. Splitting by source type
(papers vs web) would rig the debate and any judge would spot it.

**4.2 Advocates see each other's claims in rebuttal, never each other's
evidence.**
Shared evidence causes convergence. Convergence destroys the debate.
Disjoint evidence is what keeps two identical models from collapsing into
one voice.

**4.3 Unsourced claims are dropped by the pipeline, not scored down by the
judge.**
Provenance is enforced in code. A 4B model's taste is not a reliable filter.

**4.4 The judge runs twice with positions swapped, and results are merged.**
LLM judges show documented position bias. Two calls, order reversed, merged.
Cheap and visible.

**4.5 The judge identifies the crux; it does not declare a winner.**
Characterising a disagreement is a far easier task for a small model than
adjudicating truth — and it is the more useful output.

**4.6 High asymmetry is a feature, not a failure.**
If the evidence is one-sided, say so. Do not manufacture a debate.

---

## 5. Architecture

```
                        QUESTION (free text)
                              │
                    ┌─────────▼─────────┐
                    │  CLAIM EXTRACTOR   │  E2B · low thinking
                    │  question → single │
                    │  testable claim    │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │     RETRIEVER      │  Alien OpenAIRE MCP
                    │   20–30 snippets   │  + bioRxiv / medRxiv
                    └─────────┬─────────┘
                              │
        ╔═════════════════════▼═════════════════════╗
        ║        STANCE CLASSIFIER  ← THE CORE       ║  E2B · batched
        ║   snippet → SUPPORTS / REFUTES / NEUTRAL   ║  no thinking
        ╚═════════════════════╤═════════════════════╝
                              │
                    ┌─────────▼─────────┐
                    │      BUDGETER      │  top-k per side
                    │ disjoint partitions│  hard token ceiling
                    └───┬────────────┬───┘
                        │            │
              ┌─────────▼──┐   ┌─────▼────────┐
              │ADVOCATE FOR│   │ADVOCATE AGNST│   E2B · parallel
              │  SUPPORTS  │   │   REFUTES    │   low thinking
              │    only    │   │     only     │   ≤150 tok/turn
              └──────┬─────┘   └─────┬────────┘   stance-locked
                     │               │
                     └──► REBUTTAL ◄──┘   claims only, never evidence
                              │           (1 round)
                    ┌─────────▼─────────┐
                    │       JUDGE        │  E4B · HIGH thinking
                    │ 2 runs, order      │  structured JSON
                    │ swapped, merged    │
                    └─────────┬─────────┘
                              │
                     DISAGREEMENT BRIEF
```

**The stance classifier is the project.** Everything else is plumbing around
it. If it is noisy, nothing downstream works. Build and validate it first.

---

## 6. Model tiers — and why Gemma is not swappable

| Role | Model | Thinking | Rationale |
|---|---|---|---|
| Claim extractor | E2B | low | Near-extraction |
| Stance classifier | E2B | none | 3-way classification, batched |
| Advocate ×2 | E2B | low | Bounded: read partition, state claims, cite |
| Judge | E4B | **high** | Cross-document reasoning — the only hard job |

**Two tiers, one checkpoint.** E2B is nested inside E4B (MatFormer + per-layer
embeddings). We serve both tiers from a single loaded model. No other open
family does this — anywhere else, three roles at two tiers means three
separate checkpoints and roughly 3× the memory.

**The swap test, for Q&A:**

> Swap in Qwen 4B and three things break. You need three checkpoints instead
> of one, because nothing else nests a 2B inside a 4B. You lose per-role
> thinking budgets, because they are not a family-wide control elsewhere.
> You lose matched MTP drafters, so the sequential bottleneck gets worse.
> The app would still run — at 3× the memory, without the tier structure
> that makes the debate work.

**Verify in hour 1:** that sub-model extraction / Mix-n-Match tooling ships
for Gemma 4 as it did for 3n, and that the serving stack supports it. This
is a specific question for a mentor. **Fallback if not:** E2B and E4B as two
separate checkpoints. Same tiering argument, less dramatic. Do not bet the
build on unverified nesting.

---

## 7. Component specs

### 7.0 Shared contract — LOCK THIS IN THE FIRST 30 MINUTES

Nobody writes real code until `core/schema.py` is committed **and** a mock
`Brief` JSON is committed alongside it. The mock is what lets frontend build
without waiting for a working pipeline.

```python
Stance = Literal["SUPPORTS", "REFUTES", "NEUTRAL"]

@dataclass
class Source:
    doi: str | None
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    license: str | None
    retrieved_via: str          # "openaire" | "biorxiv" | "medrxiv"

@dataclass
class Snippet:
    id: str                     # short, stable — cited by this id
    text: str
    stance: Stance
    confidence: float
    source: Source

@dataclass
class Claim:
    text: str
    cites: list[str]            # snippet ids. EMPTY LIST => DROPPED.

@dataclass
class Turn:
    agent: Literal["FOR", "AGAINST"]
    round: int                  # 0 = opening, 1 = rebuttal
    claims: list[Claim]

CruxType = Literal[
    "population", "methodology", "timeframe",
    "measured-construct", "effect-size", "none",
]

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
    asymmetry: float            # 0.0 even split … 1.0 one-sided
    transcript: list[Turn]
    meta: dict                  # latency, tokens, model tiers, config
```

`crux_type` is an enum, not free text. It constrains a 4B model to a
classification rather than an essay, and makes the UI trivial.

---

### 7.1 SKELETON — *owner: [lead]*

**Owns:** `core/pipeline.py`, `core/claim.py`, `core/advocate.py`,
serving config, **and the Brev deploy.**

Build order:

1. `schema.py` + mock Brief → commit → tell everyone
2. Ollama running locally, E2B and E4B reachable
3. Claim extractor
4. Advocates (parallel, stance-locked, ≤150 tokens/turn)
5. Pipeline wiring with stubs for stance + judge
6. **Deploy to Brev** — hard deadline +6h

**Advocate constraints (non-negotiable):**
- May cite only snippet ids present in its own partition
- Any claim with `cites == []` is dropped before the judge sees it
- A citation outside its partition → drop claim, log violation
- Stance-locked in system prompt; `CONCEDE` is a permitted, logged action

**Acceptance:** `python -m core.pipeline "some claim"` prints a populated
`Brief` to stdout. Ugly is fine.

**The Brev deploy will silently slip. It is boring and it is yours.** A
local-only demo fails the "reachable by someone who is not you" requirement
and scores like it does not work.

---

### 7.2 JUDGE + EVAL — *owner: [B]*

**Owns:** `core/judge.py`, `eval/`

The judge is the only component doing genuinely hard reasoning. It also has
the only failure mode that is invisible without measurement — which is why
eval lives here. Eval is your feedback loop, not a chore.

**Judge spec:**
- E4B, high thinking, structured JSON output matching `Brief`
- Runs **twice** with FOR/AGAINST positions swapped in the prompt; merge
- Identifies the crux and classifies `crux_type`. **Does not pick a winner.**
- Computes `asymmetry` from the source counts and confidences
- On JSON parse failure: retry once at higher thinking, then fall back to
  both-positions-with-no-crux rather than crashing

**Acceptance:** given a mock transcript, returns valid `Brief` JSON 10/10
times, and produces the same crux when positions are swapped.

**Then build the eval harness — see §8.** This is what clears the Track 03
cap. It matters more than judge polish.

---

### 7.3 FRONTEND + WRITEUP — *owner: [C]*

**Owns:** `ui/`, `writeup/README.md`

You own everything the jury sees. That is 40 of 100 points.

**UI — build against the mock JSON from hour one. Never blocked.**

Three constraints, everything else is your call:
1. Two columns streaming in parallel — FOR left, AGAINST right
2. Source chips land under each claim as it arrives (title + year, DOI on
   hover). This is the differentiator; it must be visible without clicking.
3. Crux revealed at the bottom after both sides settle

Streaming matters more than polish. Content appearing immediately and
continuously is what makes this feel fast — it is genuinely slower than
single-pass, and the streaming is what covers that.

Also needed: a free-text input so a judge can try their own question.

**Writeup — start it at lunch, not at 5pm.** Required sections:
- What we built, who for
- Architecture, and how Gemma 4 is used (pull from §6)
- The numbers (from eval, §8)
- **What broke.** Include the honest note: debate does not beat
  self-consistency on accuracy; we are not claiming it does. What it
  produces instead is a legible, sourced account of the disagreement.
  Voting hides the reasoning. Owning this converts our biggest
  vulnerability into evidence of rigour.

---

### 7.4 CONTEXT — *owner: [D]*

**Owns:** `core/retrieve.py`, `core/stance.py`, `core/budget.py`

**Priority is strict. Do not invert it.**

**P0 — Stance classifier.** The whole product depends on this. E2B, batched,
no thinking, 3-way classification against the claim. Must be reliable before
anything else in this lane starts.

**P0 — Retrieval.** Alien OpenAIRE MCP + bioRxiv/medRxiv. Normalise into
`Snippet` with every provenance field populated. Success is checkable at a
glance: does it return papers with DOIs?

**P1 — Budgeter.** Top-k per side, disjoint partitions, hard token ceiling.

**P2 — LLMLingua compression.** Only after P0 and P1 land and the eval
harness exists.

> **Hard constraint on compression:** it must preserve snippet boundaries and
> ids. Per-claim provenance is the entire differentiator. Compressing *across*
> snippets destroys the ability to say which paper a claim came from and
> breaks the product to save tokens. **Compress within snippets, never
> across them.**

Compression without measurement is worthless — you cannot tell if it helped.
So it lands as one row in the eval harness, or not at all. Either result is
publishable in the writeup: *"compressing context on a 2B model helped/hurt
by X%"* is a genuine Track 03 finding.

**Also owns: the three demo questions.** Find and *verify* three claims where
the literature genuinely splits — verified by reading what retrieval actually
returns, not guessed. If a demo question turns out to have consensus, the
demo looks broken on stage. Highest-risk item nobody would otherwise own.

---

## 8. Eval spec

An eval is a fixed question set, run through different configs, scored
identically. Nothing more.

**`eval/questions.jsonl` — ~30 claims, written before lunch, frozen after.**

```jsonl
{"claim": "Creatine improves cognition in healthy adults", "expect": "split"}
{"claim": "Smoking causes lung cancer", "expect": "consensus"}
{"claim": "Intermittent fasting beats calorie restriction for fat loss", "expect": "split"}
```

**Metrics — all countable, none require knowing the right answer:**

| Metric | Computation |
|---|---|
| Sources cited | unique DOIs in output |
| Both sides shown | ≥1 claim on each side (bool) |
| Consensus detected | on `expect: consensus`, does asymmetry correctly exceed threshold |
| Latency / tokens | wall clock, token count |

**Main comparison — matched token budget across all rows:**

| Config | |
|---|---|
| single-pass E4B, no retrieval | baseline |
| naive RAG — all evidence, one context | baseline |
| **split-context debate** | ours |
| self-consistency @ n | the honest critic |

Including self-consistency proactively is the single highest-credibility
move available. Almost no team will. See the Q&A note in §10.

**Ablation 1 — partition on/off.** *Carries the Track 03 claim.*
Both advocates see all evidence, vs. split evidence. Everything else
identical. If "both sides shown" does not improve, the central mechanism is
decoration — and we need to know that at 2pm, not on stage.

**Ablation 2 — thinking budgets flipped.** *Carries the Gemma-effective
claim.* Judge on high vs low thinking. Does crux quality degrade?

Run on a separate machine. Start it early, walk away, come back to a CSV.

---

## 9. Failure paths

| Condition | Behaviour |
|---|---|
| `asymmetry > 0.85` | Return "not meaningfully split — here is the consensus and the lone dissent." **This is a feature.** Demo it. |
| retrieval < 6 snippets | Widen query once, then say so honestly |
| advocate cites outside its partition | Drop claim, log violation, surface in UI |
| judge JSON unparseable | Retry at higher thinking, then both-positions-no-crux |

Running a consensus question live and watching the system refuse to
manufacture a fight is a strong demo beat. It proves this is not theatre.

---

## 10. Timeline

| Time | Milestone |
|---|---|
| +30 min | Schemas + mock JSON committed. Everyone unblocked. |
| +2 h | Stance classifier printing sane partitions. **If noisy, stop and fix — nothing downstream works.** |
| +4 h | Spine runs end to end. Eval harness started. |
| +6 h | **Deployed to Brev.** Hard deadline. |
| +7 h | Writeup first draft exists. |
| +8 h | Feature freeze. Numbers into charts. Rehearse 3×. |

**Cut order:** rebuttal round → free-text input → SerpApi discourse panel.

**Never cut:** provenance chips, partition on/off ablation, the deploy.

---

## 11. Pitch — 5 min + 3 min Q&A

1. **30s** — "I need to know if the literature agrees on X. Scholar gives me
   ten papers. An LLM gives me a confident paragraph that hides the fight."
2. **2 min** — Live run. Two columns streaming, chips landing, crux at the
   bottom. Then a consensus question, refusing to fake a debate.
3. **1 min** — Architecture: nested checkpoint, two tiers, one model in
   memory, split evidence, per-role thinking budgets.
4. **1 min** — Numbers: memory vs three checkpoints, MTP speedup, source
   coverage, the partition ablation.
5. **30s** — Close: *"The world does not lack information. It lacks a legible
   view of what is actually in dispute — and what it rests on."*

**Rehearsed Q&A — the question you will get:**

> *"How is this better than sampling the model five times and voting?"*
>
> "It is not, on accuracy — the literature says debate does not reliably beat
> self-consistency, and we measured it. We are claiming something voting
> cannot give you: a sourced, legible account of the disagreement. Voting
> collapses five hidden generations into one number and throws the reasoning
> away. That reasoning is the product."

> *"How is this different from Ground News or AllSides?"*
>
> "Those tell you which outlets covered a story and where they lean — bias
> aggregation over headlines. We construct the actual argument from primary
> literature with provenance attached per claim."

**Note:** any mentor who helps us recuses themselves from judging us. Get
Alien integration help from non-jury staff.