# Build Notes — operational findings

Live-verified against the Alien MCPs on 2026-07-25. This is *operational reality*
the PRD didn't have. It does **not** change any settled §4 decision — it refines
§5/§7.4 (retrieval + stance). Source of truth for design stays the PRD.

## Auth
- The three research MCPs (openaire, biorxiv, medrxiv) are behind **OAuth 2.0
  authz-code + PKCE**, scopes `openid profile email offline_access`. **No static
  token** for these — a human logs in via browser once. `offline_access` →
  refresh token, so the shipped backend runs headless after one login.
- Install path: `openscience@alien` plugin handles the login inside Claude Code.
  The shipped app needs its own OAuth client (auth-code once → store refresh
  token → headless refresh). `oat_` tokens are only for the *build-on-Alien*
  backend (Metamorph/ingest/RAG), which we don't use.

## What each source actually is
- **OpenAIRE = breadth + provenance + abstracts.** ~28 tools, Graph API v3.
  `openaire_search_research_products(query=, detail="full")` returns, per hit:
  title, abstract (~500 chars, stance-bearing), DOI, ORCID authors, journal,
  year, citation_count, `influence_class` (C1=top 0.01%), peer_reviewed, OA
  color, MeSH subjects. 65 hits for "creatine cognition". **This is the primary
  evidence corpus, not just chips.** Search is keyword-**AND** (more terms =
  fewer results — opposite of Google); keep to 2–4 terms, use OR to broaden.
- **medRxiv = clinical full-text depth.** Datasets by specialty: Epidemiology
  11.7K, Infectious Diseases 12.5K, Public/Global Health 7.8K, Neurology 5.8K,
  Psychiatry 4.6K, Cardiovascular 4K, Oncology 2.8K, Nutrition 885, Sports Med
  463, Endocrinology 1.3K. Full text, chunked, keyword + vector search. **Right
  corpus for contested *health* claims.** But sparse per-claim: often only 1–3
  actual intervention trials exist as preprints.
- **bioRxiv = basic-science biology, WRONG for health claims.** Neuroscience
  62K, Microbiology 32K, Bioinformatics 30K, Cell/Molecular/Evo biology.
  Clinical_Trials dataset = 99 entries; clinical specialties near-empty. Use
  bioRxiv only if the domain is molecular/basic biology.

## Retrieval recipe (matters — a naive version poisons the partition)
Vector search matches **phrasing, not topic**: a raw semantic query for
"creatine had no effect on cognition" returned "no effect on cognition" chunks
from a **zebrafish brain-development paper** and a brain-stimulation study —
nothing about creatine. Feed that to the stance classifier and the AGAINST
partition fills with off-topic null results.

**Correct order (per the MCP's own routing docs):**
1. `keyword_search(query, dataset_ids=[relevant specialties])` → on-topic entries
2. `vector_search_chunks(query, entry_ids=[those entries])` → stance passages
   *within* on-topic papers only.

For OpenAIRE, the abstract from `detail="full"` is already the stance unit —
classify the abstract directly, no chunking needed.

## Stance evidence sources (revised)
- **Breadth:** OpenAIRE abstracts (dozens of papers/claim, both sides present).
- **Depth:** medRxiv full-text chunks (few papers, richer passages, satisfies the
  Alien "full text not just abstract" story).
- Titles alone are NOT enough to tell SUPPORTS from REFUTES — confirmed.

## Asymmetry
Weight by `influence_class` / `citation_count` from OpenAIRE, not just raw
source counts. A principled asymmetry number, cheaply.

## Domain recommendation
**Clinical / health interventions** (medRxiv + OpenAIRE): nutrition, supplements,
lifestyle — where contested claims are both real *and* legible to a non-expert
juror. Confirmed viable: **creatine → cognition** (65 OpenAIRE papers incl. null-
result reviews + a real medRxiv RCT). Lock the other two demo claims by running
them through the stance classifier once it exists — do not hand-adjudicate.
