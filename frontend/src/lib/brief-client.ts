import type { Brief } from "./brief-types";
import { MOCK_BRIEFS } from "./brief-mocks";

/**
 * Fetch a disagreement Brief for a given claim.
 *
 * Currently returns mock data. When the backend is ready, swap this
 * implementation to call the Ollama/OpenAI-compatible chat completions
 * endpoint. The return shape (Brief) is the locked contract from the PRD
 * and MUST NOT change — UI components depend on it.
 */
export async function fetchBrief(input: {
  claim: string;
  demoId?: string;
}): Promise<Brief> {
  await new Promise((r) => setTimeout(r, 250));

  if (input.demoId && MOCK_BRIEFS[input.demoId]) {
    return MOCK_BRIEFS[input.demoId];
  }

  // Heuristic mock routing so free-text input feels responsive.
  const q = input.claim.toLowerCase();
  if (q.includes("vitamin c") || q.includes("cold")) return MOCK_BRIEFS.vitaminc;
  return { ...MOCK_BRIEFS.creatine, claim: input.claim || MOCK_BRIEFS.creatine.claim };
}
