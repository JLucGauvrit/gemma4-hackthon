const state = {
  source: null,
  snippets: new Map(),
  stances: new Map(),
  partition: { FOR: new Set(), AGAINST: new Set() },
  claims: { FOR: [], AGAINST: [] },
  violations: [],
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
  neutralCount: $("neutral-count"),
  evidenceList: $("evidence-list"),
  eventLog: $("event-log"),
  clearButton: $("clear-button"),
  claimTemplate: $("claim-template"),
  paperTemplate: $("paper-template"),
};

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  startRun();
});

els.clearButton.addEventListener("click", resetUi);

function startRun() {
  const question = els.question.value.trim();
  if (!question) return;
  if (state.source) state.source.close();

  resetUi();
  state.startedAt = performance.now();
  els.button.disabled = true;
  setRunState("connecting");

  const params = new URLSearchParams({
    question,
    shared_evidence: String(els.shared.checked),
  });
  state.source = new EventSource(`/api/run?${params}`);

  state.source.addEventListener("error", () => {
    if (els.button.disabled) {
      setRunState("connection lost");
      els.button.disabled = false;
    }
  });

  [
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
    "out_of_scope",
    "brief",
    "error",
  ].forEach((type) => {
    state.source.addEventListener(type, (event) => {
      applyEvent(JSON.parse(event.data));
    });
  });
}

function resetUi() {
  state.snippets = new Map();
  state.stances = new Map();
  state.partition = { FOR: new Set(), AGAINST: new Set() };
  state.claims = { FOR: [], AGAINST: [] };
  state.violations = [];
  els.claimText.textContent = "No run yet.";
  els.queryText.textContent = "-";
  els.forClaims.replaceChildren();
  els.againstClaims.replaceChildren();
  els.evidenceList.replaceChildren();
  els.eventLog.replaceChildren();
  els.forCount.textContent = "0";
  els.againstCount.textContent = "0";
  els.verdict.textContent = "-";
  els.crux.textContent = "Waiting for the judge.";
  els.resolver.textContent = "-";
  els.asymmetry.textContent = "-";
  els.asymmetryBar.style.width = "0%";
  updateEvidenceCounts();
}

function applyEvent(event) {
  logEvent(event);
  switch (event.type) {
    case "status":
      setRunState(event.message || "starting");
      break;
    case "claim_text":
      setRunState("retrieving papers");
      els.claimText.textContent = event.claim || "-";
      els.queryText.textContent = event.query || "-";
      break;
    case "snippet":
      state.snippets.set(event.snippet.id, event.snippet);
      renderEvidence();
      break;
    case "stance":
      state.stances.set(event.id, event.stance);
      setRunState("classifying stance");
      renderEvidence();
      break;
    case "partition":
      state.partition.FOR = new Set(event.for || []);
      state.partition.AGAINST = new Set(event.against || []);
      setRunState("building arguments");
      renderEvidence();
      break;
    case "verdict":
      els.verdict.textContent = event.verdict || "-";
      setRunState((event.verdict || "verdict").toLowerCase());
      break;
    case "enriched":
      setRunState(`enriched ${event.count || 0} abstracts`);
      break;
    case "turn_claim":
      state.claims[event.side].push(event.claim);
      renderClaims(event.side);
      setRunState(`${event.side.toLowerCase()} argued`);
      break;
    case "violation":
      state.violations.push(event);
      renderViolation(event);
      break;
    case "crux":
      els.crux.textContent = event.crux || "-";
      els.resolver.textContent = event.resolver || "-";
      setRunState("judged");
      break;
    case "out_of_scope":
      setRunState(`out of scope: ${event.on_topic || 0} on-topic`);
      break;
    case "brief":
      finishRun(event.brief);
      break;
    case "error":
      setRunState("error");
      els.crux.textContent = event.message || "Backend error";
      els.button.disabled = false;
      if (state.source) state.source.close();
      break;
  }
}

function finishRun(brief) {
  els.button.disabled = false;
  if (state.source) state.source.close();
  els.verdict.textContent = brief.verdict || els.verdict.textContent;
  els.crux.textContent = brief.crux || els.crux.textContent;
  els.resolver.textContent = brief.resolver || els.resolver.textContent;
  const asymmetry = Number(brief.asymmetry);
  if (Number.isFinite(asymmetry)) {
    els.asymmetry.textContent = asymmetry.toFixed(2);
    els.asymmetryBar.style.width = `${Math.round(asymmetry * 100)}%`;
  }
  const seconds = brief.meta?.latency_s ?? ((performance.now() - state.startedAt) / 1000).toFixed(1);
  setRunState(`done in ${seconds}s`);
}

function renderClaims(side) {
  const target = side === "FOR" ? els.forClaims : els.againstClaims;
  const counter = side === "FOR" ? els.forCount : els.againstCount;
  target.replaceChildren();
  state.claims[side].forEach((claim) => {
    const node = els.claimTemplate.content.cloneNode(true);
    node.querySelector("p").textContent = claim.text;
    const cites = node.querySelector(".cites");
    claim.cites.forEach((id) => cites.appendChild(citationChip(id)));
    target.appendChild(node);
  });
  counter.textContent = String(state.claims[side].length);
}

function renderViolation(event) {
  const target = event.side === "FOR" ? els.forClaims : els.againstClaims;
  const node = document.createElement("div");
  node.className = "violation";
  node.textContent = `${event.reason}: ${event.claim}`;
  target.appendChild(node);
}

function citationChip(id) {
  const snippet = state.snippets.get(id);
  const button = document.createElement("button");
  button.className = "cite";
  button.type = "button";
  button.textContent = id;
  if (snippet) {
    const source = snippet.source || {};
    button.title = [
      source.title,
      source.year,
      source.doi ? `doi: ${source.doi}` : null,
      source.venue,
    ].filter(Boolean).join("\n");
    button.addEventListener("click", () => {
      document.querySelector(`[data-snippet-id="${id}"]`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    });
  }
  return button;
}

function renderEvidence() {
  els.evidenceList.replaceChildren();
  [...state.snippets.values()].forEach((snippet) => {
    const node = els.paperTemplate.content.cloneNode(true);
    const article = node.querySelector(".paper");
    const title = node.querySelector("b");
    const meta = node.querySelector("p");
    const badge = node.querySelector("span");
    const stance = state.stances.get(snippet.id) || snippet.stance || "PENDING";
    const side = state.partition.FOR.has(snippet.id)
      ? "FOR"
      : state.partition.AGAINST.has(snippet.id)
        ? "AGAINST"
        : "";
    article.dataset.snippetId = snippet.id;
    article.dataset.stance = stance.toLowerCase();
    title.textContent = `[${snippet.id}] ${snippet.source?.title || "Untitled source"}`;
    meta.textContent = [
      snippet.source?.year,
      snippet.source?.venue,
      snippet.source?.doi ? `doi:${snippet.source.doi}` : null,
      side ? `partition:${side}` : null,
    ].filter(Boolean).join(" | ");
    badge.textContent = stance;
    els.evidenceList.appendChild(node);
  });
  updateEvidenceCounts();
}

function updateEvidenceCounts() {
  const stances = [...state.stances.values()];
  els.snippetCount.textContent = String(state.snippets.size);
  els.supportCount.textContent = String(stances.filter((s) => s === "SUPPORTS").length);
  els.refuteCount.textContent = String(stances.filter((s) => s === "REFUTES").length);
  els.neutralCount.textContent = String(stances.filter((s) => s === "NEUTRAL").length);
}

function logEvent(event) {
  const item = document.createElement("li");
  const label = event.type || "message";
  item.textContent = `${new Date().toLocaleTimeString()} ${label}`;
  els.eventLog.prepend(item);
}

function setRunState(text) {
  els.runState.textContent = text;
}
