# Definition of done

Testable checklist derived from `DEVILS_ADVOCATES_PRD.md`. Every line should be checkable by looking at something concrete (a file, a number, a screen) — not a judgment call. Section references point back to the PRD.

## 0. Framing (PRD §3)

- [ ] Track 03 — Context Engineering for SLMs is declared at the top of the writeup header.
- [ ] The only variable between the two advocates is which slice of evidence enters their context — nothing else differs. This is stated explicitly in the writeup.

## 1. Shared contract (PRD §7.0) — blocks everyone, must land first

- [ ] `core/schema.py` is committed with `Source`, `Snippet`, `Claim`, `Turn`, `Position`, `Brief` exactly as specified (including `crux_type` as an enum, not free text).
- [ ] A mock `Brief` JSON is committed alongside it, so frontend can build without a working pipeline.

## 2. Retrieval and stance (PRD §7.4, P0 — the whole product depends on this)

- [ ] Retrieval returns real papers with populated provenance: DOI, title, authors, year, venue, license, `retrieved_via`.
- [ ] Retrieval order is keyword search first (on-topic entries), then vector search only within those entries — not a raw semantic search over the whole corpus.
- [ ] Stance classifier labels snippets SUPPORTS / REFUTES / NEUTRAL, batched, no thinking.
- [ ] Manually spot-check a sample of classified snippets — titles alone are not enough to judge stance; read the actual passage.

## 3. Budgeter (PRD §7.4, P1)

- [ ] Top-k snippets per side, hard token ceiling, and the two partitions are disjoint (no snippet appears on both sides).

## 4. Advocates (PRD §7.1 + §4.2)

- [ ] Each advocate can only cite snippet ids present in its own partition; a citation outside its partition causes the claim to be dropped and the violation logged.
- [ ] Any claim with an empty citation list is dropped before the judge ever sees it.
- [ ] Advocates see each other's claims during rebuttal, never each other's evidence.
- [ ] Advocate turns respect the token ceiling (≤150 tokens/turn) and stay stance-locked (a `CONCEDE` action is allowed and logged, nothing else crosses sides).

## 5. Judge (PRD §7.2 + §4.4 + §4.5)

- [ ] Judge runs twice with FOR/AGAINST positions swapped, and the two runs are merged.
- [ ] Judge output is valid `Brief` JSON 10/10 times on a fixed mock transcript.
- [ ] Swapping positions produces the same crux both times.
- [ ] The judge identifies the crux and its `crux_type`, and computes `asymmetry` — it never declares a winner.
- [ ] On JSON parse failure: retries once at higher thinking, then falls back to both-positions-with-no-crux rather than crashing.

## 6. Failure paths (PRD §9)

- [ ] `asymmetry > 0.85` → system returns "not meaningfully split," shows the consensus and the lone dissent, and this case is part of the live demo (not hidden).
- [ ] Fewer than 6 snippets retrieved → query is widened once, then the system says so honestly instead of forcing a debate.

## 7. Eval harness (PRD §8) — clears the Track 03 cap, not optional

- [ ] `eval/questions.jsonl` exists with ~30 claims, each labeled `expect: split` or `expect: consensus`, frozen after being written.
- [ ] Four metrics computed per run: unique sources cited, both-sides-shown (bool), consensus correctly detected, latency/tokens.
- [ ] Four configs compared on a matched token budget: single-pass E4B (no retrieval), naive RAG (all evidence, one context), split-context debate (ours), self-consistency @ n.
- [ ] Ablation 1 (partition on/off) run and result recorded honestly, even if it shows the mechanism doesn't help.
- [ ] Ablation 2 (judge thinking budget high vs. low) run and result recorded.

## 8. Frontend (PRD §7.3)

- [ ] Two columns stream in parallel — FOR on the left, AGAINST on the right.
- [ ] Source chips (title + year, DOI on hover) land under each claim as it arrives, visible without clicking anything.
- [ ] The crux is revealed at the bottom only after both sides have finished.
- [ ] A free-text input lets a judge submit their own question live.

## 9. Deploy (PRD §7.1)

- [ ] The app is deployed to Brev and reachable by someone who is not on the team — not a local-only demo.

## 10. Writeup (PRD §7.3)

- [ ] Contains: what we built and who for; architecture and how Gemma 4 specifically is used; the real eval numbers; an honest "what broke" section (including the debate-vs-self-consistency accuracy finding).
- [ ] Started well before the deadline, not assembled in the last hour.

## 11. Demo claims (PRD §7.4)

- [ ] All three demo claims are verified by actually reading what retrieval returns for them — not hand-picked because they sound contested.
- [ ] Creatine → cognition is confirmed viable (per `BUILD_NOTES.md`). The other two are locked only after passing through the stance classifier.

## 12. Pitch (PRD §11)

- [ ] 5-minute structure rehearsed at least 3 times: hook, live demo (including a consensus question that the system refuses to fake a debate on), architecture, numbers, close.
- [ ] Answers to the two expected Q&A questions (debate vs. self-consistency; how this differs from Ground News/AllSides) are rehearsed, not improvised.

## 13. Timeline checkpoints (PRD §10)

- [ ] +30 min: schema + mock JSON committed, everyone unblocked.
- [ ] +2 h: stance classifier producing sane partitions (if noisy, stop and fix before continuing).
- [ ] +4 h: pipeline runs end to end; eval harness started.
- [ ] +6 h: deployed to Brev — hard deadline.
- [ ] +7 h: writeup first draft exists.
- [ ] +8 h: feature freeze, numbers turned into charts, pitch rehearsed 3×.
