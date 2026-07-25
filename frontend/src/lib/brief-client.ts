import type { Brief, Claim, Snippet, Source } from "./brief-types";

type StreamEvent =
  | { type: "claim_text"; claim: string }
  | { type: "snippet"; snippet: Snippet }
  | { type: "turn_claim"; side: "FOR" | "AGAINST"; round: number; claim: Claim }
  | { type: "clarify"; question: string }
  | { type: "verdict"; verdict: Brief["verdict"] }
  | { type: "crux"; crux: string; resolver: string }
  | { type: "brief"; brief: Brief }
  | { type: "error"; message: string };

interface FetchBriefInput {
  claim: string;
  demoId?: string;
  signal?: AbortSignal;
  onUpdate?: (brief: Brief) => void;
  /** Asked when the backend needs the claim pinned down. Resolve with the
   * user's answer; the pipeline folds it back into intake and keeps going. */
  onClarify?: (question: string) => Promise<string>;
}

const EVENT_TYPES = [
  "claim_text",
  "snippet",
  "turn_claim",
  "clarify",
  "verdict",
  "crux",
  "brief",
  "error",
] as const;

function emptyBrief(claim: string): Brief {
  return {
    claim,
    position_for: { summary: "", claims: [], sources: [] },
    position_against: { summary: "", claims: [], sources: [] },
    citation_sources: {},
    crux: "The agents are examining the evidence.",
    crux_type: "none",
    resolver: "The judge will identify what would resolve the disagreement.",
    asymmetry: 0.5,
    verdict: "CONTESTED",
  };
}

function sourcesForClaims(
  claims: Claim[],
  snippets: Map<string, Snippet>,
  fallback: Source[],
): Source[] {
  const cited = claims.flatMap((claim) =>
    claim.cites
      .map((id) => snippets.get(id)?.source)
      .filter((source): source is Source => Boolean(source)),
  );
  const candidates = cited.length ? cited : fallback;
  return candidates.filter(
    (source, index) =>
      candidates.findIndex(
        (candidate) =>
          candidate.doi === source.doi && candidate.title === source.title,
      ) === index,
  );
}

function normalizeBrief(brief: Brief, snippets: Map<string, Snippet>): Brief {
  const forSources = sourcesForClaims(
    brief.position_for.claims,
    snippets,
    brief.position_for.sources,
  );
  const againstSources = sourcesForClaims(
    brief.position_against.claims,
    snippets,
    brief.position_against.sources,
  );

  const rawAsymmetry = brief.asymmetry;
  const dominant = brief.meta?.dominant;
  const againstIsDominant = dominant === "REFUTES";
  // Python uses 0=balanced and 1=one-sided. The original visual meter uses
  // 0=FOR, .5=balanced, and 1=AGAINST, so adapt only at this UI boundary.
  const directionalAsymmetry =
    brief.verdict === "CONSENSUS"
      ? 0.5 + (againstIsDominant ? rawAsymmetry / 2 : -rawAsymmetry / 2)
      : 0.5;
  const citationSources = Object.fromEntries(
    Array.from(snippets, ([id, snippet]) => [id, snippet.source]),
  );

  return {
    ...brief,
    asymmetry: directionalAsymmetry,
    citation_sources: citationSources,
    meta: { ...brief.meta, backend_asymmetry: rawAsymmetry },
    position_for: {
      ...brief.position_for,
      summary:
        brief.position_for.summary ||
        brief.position_for.claims[0]?.text ||
        "The retrieved evidence does not establish a supporting case.",
      sources: forSources.length ? forSources : brief.position_for.sources,
    },
    position_against: {
      ...brief.position_against,
      summary:
        brief.position_against.summary ||
        brief.position_against.claims[0]?.text ||
        "The retrieved evidence does not establish an opposing case.",
      sources: againstSources.length ? againstSources : brief.position_against.sources,
    },
  };
}

/**
 * Fetch a disagreement Brief for a given claim.
 *
 * The backend emits named Server-Sent Events. A partial Brief is published
 * whenever an advocate speaks, so the original debate UI updates in real time.
 */
export function fetchBrief(input: FetchBriefInput): Promise<Brief> {
  return new Promise((resolve, reject) => {
    const apiBase = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
    // A run_id is only needed to answer a mid-stream clarify question; skip it
    // (and the interactive intake) for callers that don't handle clarify.
    const runId = input.onClarify ? crypto.randomUUID() : undefined;
    const url = `${apiBase}/api/run?question=${encodeURIComponent(input.claim)}`
      + (runId ? `&run_id=${runId}` : "");
    const source = new EventSource(url);
    const snippets = new Map<string, Snippet>();
    let draft = emptyBrief(input.claim);
    let settled = false;

    const publish = () => input.onUpdate?.({
      ...draft,
      position_for: { ...draft.position_for },
      position_against: { ...draft.position_against },
    });

    const finishWithError = (error: Error) => {
      if (settled) return;
      settled = true;
      source.close();
      reject(error);
    };

    const handle = (message: MessageEvent<string>) => {
      let event: StreamEvent;
      try {
        event = JSON.parse(message.data) as StreamEvent;
      } catch {
        finishWithError(new Error("The debate server returned an invalid event."));
        return;
      }

      if (event.type === "claim_text") {
        draft = { ...draft, claim: event.claim };
        publish();
      } else if (event.type === "snippet") {
        snippets.set(event.snippet.id, event.snippet);
        draft = {
          ...draft,
          citation_sources: {
            ...draft.citation_sources,
            [event.snippet.id]: event.snippet.source,
          },
        };
      } else if (event.type === "turn_claim") {
        const key = event.side === "FOR" ? "position_for" : "position_against";
        const position = draft[key];
        const citedSources = event.claim.cites
          .map((id) => snippets.get(id)?.source)
          .filter((candidate): candidate is Source => Boolean(candidate));
        draft = {
          ...draft,
          [key]: {
            ...position,
            claims: [...position.claims, event.claim],
            sources: [...position.sources, ...citedSources],
          },
        };
        publish();
      } else if (event.type === "clarify") {
        if (!input.onClarify || !runId) return;
        input.onClarify(event.question).then((answer) => {
          const answerUrl = `${apiBase}/api/answer?run_id=${runId}&text=${encodeURIComponent(answer)}`;
          return fetch(answerUrl);
        }).catch(() => finishWithError(new Error("Could not send your clarification.")));
      } else if (event.type === "verdict") {
        draft = { ...draft, verdict: event.verdict };
        publish();
      } else if (event.type === "crux") {
        draft = { ...draft, crux: event.crux, resolver: event.resolver };
        publish();
      } else if (event.type === "brief") {
        const finalBrief = normalizeBrief(event.brief, snippets);
        draft = finalBrief;
        publish();
        settled = true;
        source.close();
        resolve(finalBrief);
      } else if (event.type === "error") {
        finishWithError(new Error(event.message || "The live debate failed."));
      }
    };

    EVENT_TYPES.forEach((type) => source.addEventListener(type, handle as EventListener));
    source.onerror = () => {
      if (!settled) {
        finishWithError(new Error("Lost the connection to the live debate server."));
      }
    };

    const abort = () => {
      if (settled) return;
      settled = true;
      source.close();
      reject(new DOMException("The debate was cancelled.", "AbortError"));
    };
    input.signal?.addEventListener("abort", abort, { once: true });
  });
}
