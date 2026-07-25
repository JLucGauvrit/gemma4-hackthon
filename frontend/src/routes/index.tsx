import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchBrief } from "@/lib/brief-client";
import { DEMO_OPTIONS } from "@/lib/brief-mocks";
import type { Brief, Claim, Position, Source } from "@/lib/brief-types";

export const Route = createFileRoute("/")({
  component: DevilsAdvocates,
});

function SourceChip({ source }: { source: Source }) {
  const label = source.year ? `${shortTitle(source.title)} • ${source.year}` : shortTitle(source.title);
  const tooltip =
    (source.doi ? `DOI: ${source.doi}\n` : "") +
    (source.venue ? `${source.venue}\n` : "") +
    (source.authors.length ? source.authors.join(", ") : "");
  const href = source.doi
    ? `https://doi.org/${encodeURIComponent(source.doi)}`
    : `https://explore.openaire.eu/search/find?keyword=${encodeURIComponent(source.title)}`;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={tooltip}
      className="source-chip"
    >
      {label}
    </a>
  );
}

function shortTitle(t: string) {
  return t.length > 30 ? t.slice(0, 27) + "..." : t;
}

// Animated agent component
function DebateAgent({
  side,
  message,
  sources,
  visible,
  index
}: {
  side: "for" | "against";
  message: string;
  sources?: Source[];
  visible: boolean;
  index: number;
}) {
  const isFor = side === "for";
  const agentName = isFor ? "FOR" : "AGAINST";
  
  return (
    <div 
      className={`agent ${side} ${visible ? "visible" : "hidden"}`}
      style={{
        animationDelay: `${index * 0.1}s`,
        opacity: visible ? 1 : 0
      }}
    >
      <div className="agent-avatar" data-tooltip={agentName}>
        <img
          src="/debate-agent.png"
          alt=""
          className="agent-avatar-image"
          aria-hidden="true"
        />
      </div>
      <div className="agent-speech">
        <p className="agent-message">{message}</p>
        {sources && sources.length > 0 && (
          <div>
            {sources.map((src, i) => (
              <SourceChip key={i} source={src} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// Consensus meter component
function ConsensusMeter({ asymmetry }: { asymmetry: number }) {
  const forPercentage = (1 - asymmetry) * 100;
  const againstPercentage = asymmetry * 100;
  const consensusStrength = Math.abs(asymmetry - 0.5) * 2;
  
  // Determine consensus level
  let consensusLevel = "BALANCED";
  let consensusColor = "#64748b";
  
  if (consensusStrength > 0.7) {
    consensusLevel = "STRONG CONSENSUS";
    consensusColor = "#10b981";
  } else if (consensusStrength > 0.4) {
    consensusLevel = "MODERATE CONSENSUS";
    consensusColor = "#3b82f6";
  } else if (consensusStrength < 0.1) {
    consensusLevel = "STRONG DISAGREEMENT";
    consensusColor = "#ef4444";
  } else if (consensusStrength < 0.25) {
    consensusLevel = "MODERATE DISAGREEMENT";
    consensusColor = "#f59e0b";
  }

  return (
    <div className="consensus-meter">
      <div className="consensus-bar-container">
        <span className="consensus-label">AGAINST</span>
        <div className="consensus-bar-wrapper">
          <div 
            className="consensus-bar against" 
            style={{ width: `${againstPercentage}%` }}
          >
            {againstPercentage > 15 && (
              <span className="consensus-value">{Math.round(againstPercentage)}%</span>
            )}
          </div>
          <div 
            className="consensus-bar for" 
            style={{ width: `${forPercentage}%` }}
          >
            {forPercentage > 15 && (
              <span className="consensus-value">{Math.round(forPercentage)}%</span>
            )}
          </div>
          <div className="consensus-marker"></div>
        </div>
        <span className="consensus-label">FOR</span>
      </div>
      <div className="consensus-scale">
        <span>Disagreement</span>
        <span style={{ color: consensusColor, fontWeight: 700 }}>{consensusLevel}</span>
        <span>Consensus</span>
      </div>
    </div>
  );
}

// Conclusion component
function ConclusionSection({ brief }: { brief: Brief }) {
  let verdict: "for" | "against" | "consensus" = "consensus";
  let verdictText = "Contested evidence";
  let verdictDescription = "The evidence supports competing interpretations.";
  
  if (brief.verdict === "CONSENSUS" && brief.meta?.dominant === "REFUTES") {
    verdict = "against";
    verdictText = "Consensus: AGAINST";
    verdictDescription = brief.position_against.summary;
  } else if (brief.verdict === "CONSENSUS" && brief.meta?.dominant === "SUPPORTS") {
    verdict = "for";
    verdictText = "Consensus: FOR";
    verdictDescription = brief.position_for.summary;
  } else if (brief.verdict === "OUT_OF_SCOPE") {
    verdictText = "Outside scientific scope";
    verdictDescription = brief.crux;
  } else if (brief.verdict === "INSUFFICIENT_EVIDENCE") {
    verdictText = "Insufficient evidence";
    verdictDescription = brief.crux;
  }

  return (
    <div className="conclusion-section">
      <h3 className="conclusion-title">🎯 FINAL VERDICT</h3>
      <div className="conclusion-content">
        <p style={{ marginBottom: "1rem" }}>
          <strong>Crux:</strong> {brief.crux}
        </p>
        <p style={{ marginBottom: "1rem" }}>
          <strong>What would resolve it:</strong> {brief.resolver}
        </p>
      </div>
      <div className="conclusion-verdict">
        <span className={`verdict-badge ${verdict}`}>{verdictText}</span>
        <p style={{ marginTop: "1rem", fontSize: "0.95rem", opacity: 0.9 }}>
          {verdictDescription}
        </p>
      </div>
    </div>
  );
}

// Debate section
function DebateSection({
  brief,
  forVisible,
  againstVisible,
  complete,
}: {
  brief: Brief;
  forVisible: number;
  againstVisible: number;
  complete: boolean;
}) {
  const forClaims = brief.position_for.claims;
  const againstClaims = brief.position_against.claims;
  
  return (
    <div className="debate-section">
      <div className="debate-header">
        <h2 className="debate-title">🔥 AGENTS DEBATE</h2>
        <ConsensusMeter asymmetry={brief.asymmetry} />
      </div>
      
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {/* FOR Agents */}
        {forClaims.slice(0, forVisible).map((claim, i) => {
          const sources = claim.cites
            .map((id) => brief.citation_sources?.[id])
            .filter((source): source is Source => Boolean(source));
          return (
            <DebateAgent
              key={`for-${i}`}
              side="for"
              message={claim.text}
              sources={sources}
              visible={i < forVisible}
              index={i}
            />
          );
        })}
        
        {/* AGAINST Agents */}
        {againstClaims.slice(0, againstVisible).map((claim, i) => {
          const sources = claim.cites
            .map((id) => brief.citation_sources?.[id])
            .filter((source): source is Source => Boolean(source));
          return (
            <DebateAgent
              key={`against-${i}`}
              side="against"
              message={claim.text}
              sources={sources}
              visible={i < againstVisible}
              index={i}
            />
          );
        })}
        
        {/* Loading indicator */}
        {(!complete || forVisible < forClaims.length || againstVisible < againstClaims.length) && (
          <div style={{ 
            textAlign: "center", 
            padding: "1.5rem",
            color: "#64748b"
          }}>
            <span className="loading-dots">
              <span></span>
              <span></span>
              <span></span>
            </span>
            <span style={{ marginLeft: "0.5rem" }}>Agents are thinking...</span>
          </div>
        )}
      </div>
    </div>
  );
}

export function DevilsAdvocates() {
  const [input, setInput] = useState("");
  const [demoId, setDemoId] = useState<string | undefined>();
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(false);
  const [runId, setRunId] = useState(0);
  const [chatMessages, setChatMessages] = useState<{text: string; isUser: boolean}[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [clarifyQuestion, setClarifyQuestion] = useState<string | null>(null);
  const [clarifyAnswer, setClarifyAnswer] = useState("");
  const clarifyResolveRef = useRef<((answer: string) => void) | null>(null);
  const [debateComplete, setDebateComplete] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    if (input.trim()) {
      setLoading(true);
      setBrief(null);
      setDebateComplete(false);
      setError("");
      setClarifyQuestion(null);
      fetchBrief({
        claim: input,
        demoId,
        signal: controller.signal,
        onUpdate: (nextBrief) => setBrief(nextBrief),
        onClarify: (question) =>
          new Promise<string>((resolve) => {
            clarifyResolveRef.current = resolve;
            setClarifyQuestion(question);
          }),
      }).then((b) => {
        if (!controller.signal.aborted) {
          setBrief(b);
          setLoading(false);
          setDebateComplete(true);
        }
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setLoading(false);
          setError(cause instanceof Error ? cause.message : "The live debate failed.");
        }
      });
    }
    return () => {
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, input]);

  const isConsensus = brief?.verdict === "CONSENSUS";

  const forClaims = brief?.position_for.claims ?? [];
  const againstClaims = brief?.position_against.claims ?? [];

  const forVisible = forClaims.length;
  const againstVisible = againstClaims.length;

  const bothDone =
    !!brief &&
    !isConsensus &&
    debateComplete &&
    forVisible >= forClaims.length &&
    againstVisible >= againstClaims.length;

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (input.trim()) {
      setDemoId(undefined);
      setRunId((n) => n + 1);
      // Add user message to chat
      setChatMessages(prev => [...prev, { text: input, isUser: true }]);
      setChatInput("");
    }
  };

  const runDemo = (id: string) => {
    const demo = DEMO_OPTIONS.find((d) => d.id === id);
    setDemoId(id);
    if (demo) {
      setInput(demo.claim);
      setChatMessages(prev => [...prev, { text: demo.claim, isUser: true }]);
      setRunId((n) => n + 1);
    }
  };

  const handleClarifySubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const answer = clarifyAnswer.trim();
    if (!answer || !clarifyResolveRef.current) return;
    setChatMessages(prev => [
      ...prev,
      { text: clarifyQuestion ?? "", isUser: false },
      { text: answer, isUser: true },
    ]);
    clarifyResolveRef.current(answer);
    clarifyResolveRef.current = null;
    setClarifyQuestion(null);
    setClarifyAnswer("");
  };

  const handleChatSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (chatInput.trim() && !brief) {
      setInput(chatInput);
      setChatMessages(prev => [...prev, { text: chatInput, isUser: true }]);
      setChatInput("");
    }
  };

  const resetDebate = () => {
    setInput("");
    setDemoId(undefined);
    setBrief(null);
    setLoading(false);
    setDebateComplete(false);
    setError("");
    setChatMessages([]);
    setChatInput("");
    setClarifyQuestion(null);
    setClarifyAnswer("");
    clarifyResolveRef.current = null;
  };

  const displayedClaim = useMemo(() => brief?.claim ?? input, [brief, input]);

  return (
    <div className="app-container">
      {/* Header */}
      <header className="header">
        <h1>👹 vs 😇 Devil's Advocates</h1>
        <p>Ask a question, refine with chat, watch agents debate</p>
      </header>

      {/* Pre-debate chat */}
      {!brief && (
        <div className="chat-input-container">
          <label className="chat-input-label">
            {chatMessages.length === 0 ? "Ask your question" : "Refine your question"}
          </label>
          
          {/* Chat messages */}
          {chatMessages.length > 0 && (
            <div style={{ 
              marginBottom: "1rem", 
              maxHeight: "200px", 
              overflowY: "auto"
            }}>
              {chatMessages.map((msg, i) => (
                <div 
                  key={i}
                  style={{
                    padding: "0.75rem",
                    marginBottom: "0.5rem",
                    background: msg.isUser ? "#eff6ff" : "#f8fafc",
                    borderRadius: "0.5rem",
                    borderLeft: msg.isUser ? "3px solid #3b82f6" : "3px solid #cbd5e1"
                  }}
                >
                  <p style={{ margin: 0, fontSize: "0.9rem" }}>
                    {msg.text}
                  </p>
                </div>
              ))}
            </div>
          )}
          
          <form onSubmit={handleChatSubmit} style={{ display: "flex", gap: "0.75rem" }}>
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder={chatMessages.length === 0 ? "e.g. Does creatine improve memory?" : "Add more details..."}
              className="chat-input"
              disabled={loading}
            />
            <button
              type="submit"
              className="primary-button"
              disabled={!chatInput.trim() || loading}
            >
              {loading ? (
                <span className="loading-dots">
                  <span></span>
                  <span></span>
                  <span></span>
                </span>
              ) : (
                chatMessages.length === 0 ? "Start Debate" : "Update"
              )}
            </button>
          </form>
          
          {/* Demo buttons */}
          <div className="demo-buttons">
            <span className="demo-label">Examples:</span>
            {DEMO_OPTIONS.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => runDemo(d.id)}
                className={`demo-button ${demoId === d.id ? "active" : ""}`}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="question-display">
          <p className="question-text">⚠️ {error}</p>
          <button type="button" className="secondary-button" onClick={resetDebate}>
            Try another question
          </button>
        </div>
      )}

      {/* Question display */}
      {brief && !error && (
        <div className="question-display">
          <p className="question-text">❓ "{displayedClaim}"</p>
          <button type="button" className="secondary-button" onClick={resetDebate}>
            {loading ? "Stop debate" : "New debate"}
          </button>
        </div>
      )}

      {/* Clarify: the pipeline needs the claim pinned down before it retrieves */}
      {clarifyQuestion && (
        <div className="clarification-section">
          <p className="clarification-title">🤖 {clarifyQuestion}</p>
          <form className="clarification-questions" onSubmit={handleClarifySubmit}>
            <input
              className="clarification-input"
              value={clarifyAnswer}
              onChange={(e) => setClarifyAnswer(e.target.value)}
              placeholder="Your answer…"
              autoFocus
            />
            <button type="submit" className="clarification-question" disabled={!clarifyAnswer.trim()}>
              Send
            </button>
          </form>
        </div>
      )}

      {/* Debate section */}
      {brief && !isConsensus && (
        <DebateSection
          brief={brief}
          forVisible={forVisible}
          againstVisible={againstVisible}
          complete={debateComplete}
        />
      )}

      {/* Consensus view */}
      {brief && isConsensus && (
        <div className="consensus-section">
          <div className="consensus-header">
            <h3 className="consensus-title">✅ SCIENTIFIC CONSENSUS</h3>
            <p className="consensus-subtitle">No significant disagreement on this topic</p>
          </div>
          <ConsensusMeter asymmetry={brief.asymmetry} />
          <ConclusionSection brief={brief} />
        </div>
      )}

      {/* Conclusion for non-consensus */}
      {brief && !isConsensus && bothDone && (
        <ConclusionSection brief={brief} />
      )}

      {/* Footer */}
      <footer className="footer">
        <p>Sources: OpenAIRE, bioRxiv, medRxiv</p>
        <p style={{ marginTop: "0.5rem" }}>
          Agents debate based on scientific evidence. You decide.
        </p>
      </footer>
    </div>
  );
}
