# Devil's Advocates

**Track 03 — Context Engineering for SLMs**
Gemma 4 Hackathon · 42 Paris

> A disagreement engine for contested scientific questions. Given a claim, it produces a sourced disagreement brief: the strongest case for, the strongest case against, where they actually diverge, and what evidence would settle it. The judge never picks a winner.

---

## What we built, and who for

*(PRD §1 — pull directly from there, do not redefine the product here)*

- One sentence: what the tool does.
- Who it's for: [researcher / PhD student / science journalist] who needs to know, today, whether the literature actually agrees on something.
- The gap it fills: Google Scholar returns papers with no synthesis; an LLM returns a confident paragraph that hides the disagreement.
- [ ] Insert the live example brief (creatine → cognition, or whichever claim demoed) as a worked illustration.

## Architecture, and how Gemma 4 is used

*(Pull from PRD §5 diagram and §6 model tiers)*

- [ ] Paste/redraw the pipeline: Claim Extractor → Retriever → Stance Classifier → Budgeter → Advocate FOR / Advocate AGAINST → Rebuttal → Judge → Brief.
- [ ] Explain the two-tier model story in plain terms: one nested checkpoint (E2B inside E4B via MatFormer), not three separate models — this is the Gemma-specific claim, not swappable to another model family without losing it.
- [ ] State per-role thinking budgets: claim extractor (low), stance classifier (none, batched), advocates (low, ≤150 tokens/turn, stance-locked), judge (high, structured JSON, run twice with sides swapped).
- [ ] Note the Alien MCP sources used for retrieval: OpenAIRE (breadth, abstracts, provenance), medRxiv (clinical full-text depth), and why bioRxiv was excluded or minimized (basic biology, not health claims).

## The numbers

*(From the eval harness — PRD §8. Do not write this section until real numbers exist.)*

- [ ] Sources cited (unique DOIs) — per config.
- [ ] Both sides shown (bool) — per config.
- [ ] Consensus correctly detected on `expect: consensus` questions.
- [ ] Latency / token count.
- [ ] Comparison table: single-pass E4B (baseline) vs. naive RAG (baseline) vs. split-context debate (ours) vs. self-consistency @ n (the honest critic).
- [ ] Ablation 1 — partition on/off: does "both sides shown" actually improve? This is the Track 03 claim; report the real result even if negative.
- [ ] Ablation 2 — judge thinking budget high vs. low: does crux quality degrade?

## What broke

*(Required by PRD §7.3 — this is not optional, and it is meant to be genuinely honest, not a disguised brag.)*

- [ ] State plainly: debate does not reliably beat self-consistency on accuracy, and we measured it rather than assumed it.
- [ ] What the system produces instead that voting cannot: a legible, sourced account of *why* the literature disagrees, not just a majority answer.
- [ ] Any other real failure encountered during the build (retrieval noise, stance classifier misfires, judge JSON parse failures, claims dropped for missing citations, etc.) — list honestly, it reads as rigor, not weakness.

---

## Appendix — pitch talking points (from PRD §11, for rehearsal, not for the writeup itself)

1. Hook (30s): the Scholar/LLM gap.
2. Live demo (2 min): two columns streaming, source chips landing, crux revealed at the bottom — then a consensus question, where the system refuses to fake a debate.
3. Architecture (1 min): nested checkpoint, two tiers, one model in memory, split evidence, per-role thinking budgets.
4. Numbers (1 min): memory vs. three checkpoints, MTP speedup, source coverage, the partition ablation result.
5. Close (30s): "The world does not lack information. It lacks a legible view of what is actually in dispute — and what it rests on."

Rehearsed answers to expected questions are in PRD §11 — reuse verbatim, don't improvise them live.
