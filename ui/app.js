const EVENT_TYPES = [
  "status",
  "claim_text",
  "snippet",
  "stance",
  "partition",
  "verdict",
  "enriched",
  "turn_claim",
  "violation",
  "crux",
  "clarify",
  "insufficient_evidence",
  "out_of_scope",
  "brief",
  "done",
  "error",
];

const PHASE_LABELS = {
  idle: "Ready for a question",
  connecting: "Connecting to the debate",
  intake: "Framing a testable claim",
  retrieving: "Retrieving scientific papers",
  classifying: "Classifying the evidence",
  preparing: "Preparing the advocates",
  opening: "Opening arguments",
  rebuttal: "Live rebuttals",
  judging: "Judge is finding the crux",
  consensus: "Scientific consensus",
  insufficient: "Insufficient evidence",
  out_of_scope: "Outside the debate scope",
  complete: "Debate complete",
  error: "Connection error",
  cancelled: "Run cancelled",
};

const state = {
  source: null,
  runId: 0,
  terminal: false,
  phase: "idle",
  snippets: new Map(),
  stances: new Map(),
  partition: { FOR: new Set(), AGAINST: new Set() },
  claims: { FOR: [], AGAINST: [] },
  violations: [],
  verdict: null,
  startedAt: null,
};

const $ = (id) => document.getElementById(id);

const els = {
  form: $("query-form"),
  question: $("question"),
  shared: $("shared"),
  button: $("run-button"),
  runState: $("run-state"),
  claimText: $("claim-text"),
  queryText: $("query-text"),
  forClaims: $("for-claims"),
  againstClaims: $("against-claims"),
  forCount: $("for-count"),
  againstCount: $("against-count"),
  verdict: $("verdict"),
  crux: $("crux"),
  resolver: $("resolver"),
  asymmetry: $("asymmetry"),
  asymmetryBar: $("asymmetry-bar"),
  snippetCount: $("snippet-count"),
  supportCount: $("support-count"),
  refuteCount: $("refute-count"),
  unresolvedCount: $("unresolved-count"),
  neutralCount: $("neutral-count"),
  evidenceList: $("evidence-list"),
  eventLog: $("event-log"),
  clearButton: $("clear-button"),
  claimTemplate: $("claim-template"),
  paperTemplate: $("paper-template"),
  forColumn: document.querySelector(".column.for"),
  againstColumn: document.querySelector(".column.against"),
};

els.form?.addEventListener("submit", (event) => {
  event.preventDefault();
  startRun();
});

els.clearButton?.addEventListener("click", () => resetUi({ cancel: true }));

function startRun() {
  const question = els.question?.value.trim();
  if (!question) {
    els.question?.focus();
    return;
  }

  closeSource();
  const runId = ++state.runId;
  resetUi({ cancel: false });
  state.startedAt = performance.now();
  state.terminal = false;

  setPhase("connecting");
  setBusy(true);

  const params = new URLSearchParams({
    question,
    shared_evidence: String(Boolean(els.shared?.checked)),
  });
  const source = new EventSource(`/api/run?${params.toString()}`);
  state.source = source;

  source.addEventListener("open", () => {
    if (!isCurrentRun(runId, source)) return;
    setPhase("intake");
  });

  source.addEventListener("error", () => {
    if (!isCurrentRun(runId, source)) return;
    if (state.terminal) {
      closeSource(source);
      return;
    }
    // EventSource retries automatically. A retry would execute this expensive GET
    // from the beginning and duplicate debate turns, so terminally close instead.
    closeSource(source);
    setBusy(false);
    setPhase(
      "error",
      state.snippets.size
        ? "Live connection was interrupted. Your partial debate is still visible."
        : "Could not connect to the live debate. Check the API and try again.",
    );
  });

  EVENT_TYPES.forEach((type) => {
    source.addEventListener(type, (message) => {
      if (!isCurrentRun(runId, source)) return;
      try {
        applyEvent(JSON.parse(message.data));
      } catch (error) {
        handleMalformedEvent(type, error, source);
      }
    });
  });
}

function isCurrentRun(runId, source) {
  return runId === state.runId && source === state.source;
}

function closeSource(source = state.source) {
  if (source) source.close();
  if (source === state.source) state.source = null;
}

function resetUi({ cancel = false } = {}) {
  if (cancel) {
    state.runId += 1;
    closeSource();
  }

  state.terminal = false;
  state.phase = "idle";
  state.snippets = new Map();
  state.stances = new Map();
  state.partition = { FOR: new Set(), AGAINST: new Set() };
  state.claims = { FOR: [], AGAINST: [] };
  state.violations = [];
  state.verdict = null;
  state.startedAt = null;

  setText(els.claimText, "No run yet.");
  setText(els.queryText, "—");
  els.forClaims?.replaceChildren();
  els.againstClaims?.replaceChildren();
  els.evidenceList?.replaceChildren();
  els.eventLog?.replaceChildren();
  setText(els.forCount, "0");
  setText(els.againstCount, "0");
  setText(els.verdict, "—");
  setText(els.crux, "Waiting for the judge.");
  setText(els.resolver, "—");
  setText(els.asymmetry, "—");
  if (els.asymmetryBar) els.asymmetryBar.style.width = "0%";

  setActiveAgent(null);
  setBusy(false);
  setPhase(cancel ? "cancelled" : "idle");
  updateEvidenceCounts();
}

function applyEvent(event) {
  if (!event || typeof event !== "object") {
    throw new TypeError("SSE payload is not an object");
  }

  logEvent(event);

  switch (event.type) {
    case "status":
      if (state.phase === "connecting") setPhase("intake", event.message);
      break;

    case "claim_text":
      setText(els.claimText, event.claim || "—");
      setText(els.queryText, event.query || "—");
      setPhase("retrieving");
      break;

    case "enriched":
      setPhase(
        "retrieving",
        `Read ${Number(event.count) || 0} full abstract${
          Number(event.count) === 1 ? "" : "s"
        }`,
      );
      break;

    case "snippet":
      if (event.snippet?.id) {
        state.snippets.set(String(event.snippet.id), event.snippet);
        renderEvidence();
        // A citation can arrive before its source in a future backend, so refresh
        // chips whenever the source index changes.
        renderClaims("FOR");
        renderClaims("AGAINST");
      }
      setPhase(
        "retrieving",
        `${state.snippets.size} paper${state.snippets.size === 1 ? "" : "s"} retrieved`,
      );
      break;

    case "stance":
      if (event.id) {
        state.stances.set(String(event.id), {
          stance: event.stance,
          confidence: event.confidence,
          reason: event.reason,
        });
      }
      setPhase("classifying");
      renderEvidence();
      break;

    case "partition":
      state.partition.FOR = new Set(normalizeIds(event.for));
      state.partition.AGAINST = new Set(normalizeIds(event.against));
      setPhase(
        "preparing",
        `${state.partition.FOR.size} FOR · ${state.partition.AGAINST.size} AGAINST`,
      );
      renderEvidence();
      break;

    case "verdict":
      applyVerdict(event.verdict);
      break;

    case "turn_claim":
      applyTurn(event);
      break;

    case "violation":
      state.violations.push(event);
      renderViolation(event);
      break;

    case "crux":
      setActiveAgent(null);
      setPhase("judging");
      setText(els.crux, event.crux || "—");
      setText(els.resolver, event.resolver || "—");
      break;

    case "clarify":
      setPhase("intake", event.question || "Clarification required");
      setText(els.crux, event.question || "Please make the claim more specific.");
      break;

    case "insufficient_evidence":
      applyVerdict("INSUFFICIENT_EVIDENCE");
      setText(
        els.crux,
        event.reason ||
          `${Number(event.on_topic) || 0} on-topic evidence items were found.`,
      );
      break;

    case "out_of_scope":
      applyVerdict("OUT_OF_SCOPE");
      setText(els.crux, event.reason || "This is not a testable scientific claim.");
      break;

    case "brief":
      finishRun(event.brief || {});
      break;

    case "done":
      finishStream();
      break;

    case "error":
      failRun(event.message || "The backend reported an error.");
      break;
  }
}

function applyVerdict(verdict) {
  const normalized = String(verdict || "").toUpperCase();
  state.verdict = normalized || null;
  setText(els.verdict, normalized ? normalized.replaceAll("_", " ") : "—");
  if (els.verdict) els.verdict.dataset.verdict = normalized.toLowerCase();

  switch (normalized) {
    case "CONTESTED":
      setPhase("opening");
      break;
    case "CONSENSUS":
      setActiveAgent(null);
      setPhase("consensus", "Evidence converges; no artificial debate");
      break;
    case "INSUFFICIENT_EVIDENCE":
      setActiveAgent(null);
      setPhase("insufficient");
      break;
    case "OUT_OF_SCOPE":
      setActiveAgent(null);
      setPhase("out_of_scope");
      break;
    default:
      setPhase("preparing");
  }
}

function applyTurn(event) {
  const side = event.side === "AGAINST" ? "AGAINST" : event.side === "FOR" ? "FOR" : null;
  if (!side || !event.claim?.text) return;

  const round = Number(event.round) === 1 ? 1 : 0;
  const claim = {
    text: String(event.claim.text),
    cites: normalizeIds(event.claim.cites),
    round,
  };
  state.claims[side].push(claim);
  renderClaims(side);
  setActiveAgent(side);
  setPhase(
    round === 1 ? "rebuttal" : "opening",
    `${side === "FOR" ? "FOR advocate" : "AGAINST advocate"} ${
      round === 1 ? "rebuts" : "presents an opening"
    }`,
  );
}

function finishRun(brief) {
  state.terminal = true;
  setBusy(false);
  setActiveAgent(null);

  const verdict = String(brief.verdict || state.verdict || "").toUpperCase();
  applyVerdict(verdict);
  setText(els.claimText, brief.claim || els.claimText?.textContent || "—");
  setText(els.crux, brief.crux || els.crux?.textContent || "—");
  setText(els.resolver, brief.resolver || els.resolver?.textContent || "—");
  renderAsymmetry(brief.asymmetry);

  if (verdict === "CONSENSUS") renderConsensusSummary(brief);

  const measuredSeconds = state.startedAt
    ? (performance.now() - state.startedAt) / 1000
    : null;
  const seconds = Number(brief.meta?.latency_s);
  const latency = Number.isFinite(seconds) ? seconds : measuredSeconds;

  switch (verdict) {
    case "CONSENSUS":
      setPhase(
        "consensus",
        `Consensus mapped${formatDuration(latency)}`,
      );
      break;
    case "INSUFFICIENT_EVIDENCE":
      setPhase(
        "insufficient",
        `Insufficient direct evidence${formatDuration(latency)}`,
      );
      break;
    case "OUT_OF_SCOPE":
      setPhase("out_of_scope", `No scientific debate created${formatDuration(latency)}`);
      break;
    default:
      setPhase("complete", `Debate complete${formatDuration(latency)}`);
  }
}

function finishStream() {
  closeSource();
  setBusy(false);
  setActiveAgent(null);
  if (state.terminal) return;

  // A successful stream should contain a brief. Keep this defensive branch for
  // forward-compatible API endpoints that may intentionally stream events only.
  state.terminal = true;
  setPhase("complete");
}

function renderConsensusSummary(brief) {
  const dominant = brief.meta?.dominant;
  const forSummary = brief.position_for?.summary;
  const againstSummary = brief.position_against?.summary;

  if (forSummary && !state.claims.FOR.length) {
    state.claims.FOR.push({
      text: String(forSummary),
      cites: [],
      round: "consensus",
      dominant: dominant === "SUPPORTS",
    });
  }
  if (againstSummary && !state.claims.AGAINST.length) {
    state.claims.AGAINST.push({
      text: String(againstSummary),
      cites: [],
      round: "consensus",
      dominant: dominant === "REFUTES",
    });
  }
  renderClaims("FOR");
  renderClaims("AGAINST");
}

function failRun(message) {
  state.terminal = true;
  closeSource();
  setBusy(false);
  setActiveAgent(null);
  setPhase("error", message);
  setText(els.crux, message);
}

function handleMalformedEvent(type, error, source) {
  console.error(`Invalid ${type} event`, error);
  closeSource(source);
  state.terminal = true;
  setBusy(false);
  setPhase("error", `Received an invalid ${type} event from the server.`);
}

function renderClaims(side) {
  const target = side === "FOR" ? els.forClaims : els.againstClaims;
  const counter = side === "FOR" ? els.forCount : els.againstCount;
  if (!target || !counter || !els.claimTemplate) return;

  target.replaceChildren();
  state.claims[side].forEach((claim) => {
    const node = els.claimTemplate.content.cloneNode(true);
    const argument = node.querySelector(".argument");
    const roundLabel =
      claim.round === 1
        ? "Rebuttal"
        : claim.round === "consensus"
          ? claim.dominant
            ? "Consensus evidence"
            : "Minority evidence"
          : "Opening argument";

    if (argument) {
      argument.dataset.round = String(claim.round);
      argument.dataset.side = side.toLowerCase();
      if (claim.dominant) argument.dataset.dominant = "true";
    }
    setText(node.querySelector(".argument-round"), roundLabel);
    setText(node.querySelector("p"), claim.text);

    const cites = node.querySelector(".cites");
    normalizeIds(claim.cites).forEach((id) => cites?.appendChild(citationChip(id)));
    target.appendChild(node);
  });
  counter.textContent = String(state.claims[side].length);
}

function renderViolation(event) {
  const target = event.side === "FOR" ? els.forClaims : els.againstClaims;
  if (!target) return;
  const node = document.createElement("div");
  node.className = "violation";
  node.setAttribute("role", "note");
  node.textContent = `${event.reason || "Citation guardrail"}: ${
    event.claim || "claim removed"
  }`;
  target.appendChild(node);
}

function citationChip(id) {
  const snippet = state.snippets.get(id);
  const button = document.createElement("button");
  button.className = "cite";
  button.type = "button";
  button.textContent = id;
  button.setAttribute(
    "aria-label",
    snippet?.source?.title ? `${id}: ${snippet.source.title}` : `Source ${id}`,
  );

  if (snippet) {
    const source = snippet.source || {};
    button.title = [
      source.title,
      source.year,
      source.doi ? `DOI: ${source.doi}` : null,
      source.venue,
    ]
      .filter(Boolean)
      .join("\n");
    button.addEventListener("click", () => {
      const paper = [...document.querySelectorAll("[data-snippet-id]")].find(
        (candidate) => candidate.dataset.snippetId === id,
      );
      paper?.scrollIntoView({ behavior: "smooth", block: "center" });
      paper?.focus({ preventScroll: true });
    });
  } else {
    button.disabled = true;
    button.title = "Source metadata has not arrived.";
  }
  return button;
}

function renderEvidence() {
  if (!els.evidenceList || !els.paperTemplate) {
    updateEvidenceCounts();
    return;
  }

  els.evidenceList.replaceChildren();
  [...state.snippets.values()].forEach((snippet) => {
    const node = els.paperTemplate.content.cloneNode(true);
    const article = node.querySelector(".paper");
    const title = node.querySelector("b");
    const meta = node.querySelector(".paper-meta");
    const reason = node.querySelector(".paper-reason");
    const excerpt = node.querySelector(".paper-excerpt");
    const badge = node.querySelector(".paper > span") || node.querySelector("span");
    const classification = state.stances.get(snippet.id);
    const stance =
      (typeof classification === "string"
        ? classification
        : classification?.stance) ||
      snippet.stance ||
      "PENDING";
    const side = state.partition.FOR.has(snippet.id)
      ? "FOR"
      : state.partition.AGAINST.has(snippet.id)
        ? "AGAINST"
        : "";

    if (article) {
      article.dataset.snippetId = snippet.id;
      article.dataset.stance = String(stance).toLowerCase();
      article.dataset.partition = side.toLowerCase();
      article.tabIndex = -1;
    }

    renderPaperTitle(title, snippet);
    setText(
      meta,
      [
        snippet.source?.year,
        snippet.source?.venue,
        snippet.source?.authors?.slice(0, 3).join(", "),
        side ? `Evidence for ${side}` : null,
      ]
        .filter(Boolean)
        .join(" · "),
    );

    const explanation =
      typeof classification === "object" ? classification?.reason : snippet.stance_reason;
    setText(reason, explanation ? `Why ${stance}: ${explanation}` : "");
    if (reason) reason.hidden = !explanation;
    setText(excerpt, snippet.text || "");
    setText(badge, stance);
    els.evidenceList.appendChild(node);
  });
  updateEvidenceCounts();
}

function renderPaperTitle(container, snippet) {
  if (!container) return;
  const label = `[${snippet.id}] ${snippet.source?.title || "Untitled source"}`;
  const doiUrl = safeDoiUrl(snippet.source?.doi);
  if (!doiUrl) {
    container.textContent = label;
    return;
  }

  const link = document.createElement("a");
  link.href = doiUrl;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  link.title = `Open DOI ${snippet.source.doi}`;
  container.replaceChildren(link);
}

function safeDoiUrl(value) {
  if (typeof value !== "string") return null;
  let doi = value.trim();
  if (!doi) return null;

  try {
    if (/^https?:\/\//i.test(doi)) {
      const parsed = new URL(doi);
      if (!["doi.org", "dx.doi.org"].includes(parsed.hostname.toLowerCase())) return null;
      doi = decodeURIComponent(parsed.pathname.replace(/^\/+/, ""));
    } else {
      doi = doi.replace(/^doi:\s*/i, "");
    }
  } catch {
    return null;
  }

  // DOI syntax is intentionally conservative before placing untrusted retrieval
  // metadata into an href.
  if (!/^10\.\d{4,9}\/[-._;()/:A-Z0-9]+$/i.test(doi)) return null;
  return `https://doi.org/${encodeURI(doi)}`;
}

function renderAsymmetry(value) {
  const asymmetry = Number(value);
  if (!Number.isFinite(asymmetry)) return;
  const bounded = Math.min(1, Math.max(0, asymmetry));
  setText(els.asymmetry, bounded.toFixed(2));
  if (els.asymmetryBar) els.asymmetryBar.style.width = `${Math.round(bounded * 100)}%`;
}

function updateEvidenceCounts() {
  const stances = [...state.stances.values()].map((classification) =>
    typeof classification === "string" ? classification : classification.stance,
  );
  setText(els.snippetCount, String(state.snippets.size));
  setText(els.supportCount, String(stances.filter((s) => s === "SUPPORTS").length));
  setText(els.refuteCount, String(stances.filter((s) => s === "REFUTES").length));
  setText(
    els.unresolvedCount,
    String(stances.filter((s) => s === "UNRESOLVED").length),
  );
  setText(els.neutralCount, String(stances.filter((s) => s === "NEUTRAL").length));
}

function logEvent(event) {
  if (!els.eventLog) return;
  const item = document.createElement("li");
  const label = String(event.type || "message").replaceAll("_", " ");
  const detail =
    event.type === "turn_claim"
      ? ` · ${event.side} ${Number(event.round) === 1 ? "rebuttal" : "opening"}`
      : event.type === "stance"
        ? ` · ${event.id} ${event.stance}`
        : "";
  const time = document.createElement("time");
  time.dateTime = new Date().toISOString();
  time.textContent = new Date().toLocaleTimeString();
  item.append(time, ` ${label}${detail}`);
  els.eventLog.prepend(item);
}

function setPhase(phase, detail = "") {
  state.phase = phase;
  const label = PHASE_LABELS[phase] || phase;
  setText(els.runState, detail || label);
  if (els.runState) {
    els.runState.dataset.phase = phase;
    els.runState.title = label;
  }
  document.body.dataset.phase = phase;
}

function setActiveAgent(side) {
  [
    ["FOR", els.forColumn],
    ["AGAINST", els.againstColumn],
  ].forEach(([name, column]) => {
    if (!column) return;
    const active = name === side;
    column.dataset.active = String(active);
    column.setAttribute("aria-current", active ? "step" : "false");
  });
  document.body.dataset.activeAgent = side ? side.toLowerCase() : "";
}

function setBusy(busy) {
  if (els.form) els.form.setAttribute("aria-busy", String(busy));
  if (els.button) {
    // Keep submit available: submitting a new question safely cancels the old
    // stream and starts a fresh run.
    els.button.disabled = false;
    els.button.textContent = busy ? "Restart live" : "Run live";
  }
  if (els.question) els.question.disabled = false;
  if (els.shared) els.shared.disabled = busy;
}

function normalizeIds(ids) {
  if (!Array.isArray(ids)) return [];
  return ids
    .filter((id) => typeof id === "string" || typeof id === "number")
    .map(String);
}

function formatDuration(seconds) {
  return Number.isFinite(seconds) ? ` in ${seconds.toFixed(1)}s` : "";
}

function setText(element, text) {
  if (element) element.textContent = String(text ?? "");
}

resetUi();
