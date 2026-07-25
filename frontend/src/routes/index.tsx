import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { fetchBrief } from "@/lib/brief-client";
import { DEMO_OPTIONS } from "@/lib/brief-mocks";
import type { Brief, Claim, Position, Source } from "@/lib/brief-types";

export const Route = createFileRoute("/")({
  component: DevilsAdvocates,
});

const STREAM_DELAY_MS = 700;

function useStreamedClaims(claims: Claim[], enabled: boolean, offsetMs = 0) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    setCount(0);
    if (!enabled) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    claims.forEach((_, i) => {
      timers.push(
        setTimeout(() => setCount((c) => Math.max(c, i + 1)), offsetMs + i * STREAM_DELAY_MS),
      );
    });
    return () => timers.forEach(clearTimeout);
  }, [claims, enabled, offsetMs]);
  return count;
}

function SourceChip({ source }: { source: Source }) {
  const label = source.year ? `${shortTitle(source.title)} · ${source.year}` : shortTitle(source.title);
  const tooltip =
    (source.doi ? `DOI: ${source.doi}\n` : "DOI: —\n") +
    (source.venue ? `${source.venue}\n` : "") +
    (source.authors.length ? source.authors.join(", ") : "");
  return (
    <span
      title={tooltip}
      className="inline-flex items-center rounded-sm border border-neutral-300 bg-neutral-50 px-2 py-0.5 text-[11px] font-medium text-neutral-700 hover:bg-white hover:border-neutral-400 transition-colors cursor-help"
    >
      {label}
    </span>
  );
}

function shortTitle(t: string) {
  return t.length > 60 ? t.slice(0, 57) + "…" : t;
}

function Column({
  side,
  position,
  visibleCount,
}: {
  side: "FOR" | "AGAINST";
  position: Position;
  visibleCount: number;
}) {
  const accent = side === "FOR" ? "text-emerald-800" : "text-rose-800";
  const rule = side === "FOR" ? "border-emerald-800" : "border-rose-800";
  return (
    <section className="flex flex-col">
      <header className={`border-b-2 ${rule} pb-2 mb-4`}>
        <div className={`text-[11px] tracking-[0.2em] font-semibold ${accent}`}>{side}</div>
        <p className="mt-2 text-sm text-neutral-700 leading-relaxed">{position.summary}</p>
      </header>
      <ol className="space-y-5">
        {position.claims.map((claim, i) => {
          const visible = i < visibleCount;
          const sources = claim.cites
            .map((_, idx) => position.sources[idx])
            .filter(Boolean) as Source[];
          const chipSources = sources.length ? sources : position.sources.slice(i, i + 1);
          return (
            <li
              key={i}
              className={`transition-all duration-500 ${
                visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"
              }`}
              aria-hidden={!visible}
            >
              <div className="flex gap-3">
                <span className="text-xs font-mono text-neutral-400 pt-0.5">{String(i + 1).padStart(2, "0")}</span>
                <div className="flex-1">
                  <p className="text-[15px] text-neutral-900 leading-relaxed">{claim.text}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {chipSources.map((src, si) => (
                      <SourceChip key={si} source={src} />
                    ))}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
        {visibleCount < position.claims.length && (
          <li className="flex gap-3 items-center text-xs text-neutral-400 font-mono">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-neutral-400 animate-pulse" />
            drafting…
          </li>
        )}
      </ol>
    </section>
  );
}

function ConsensusView({ brief }: { brief: Brief }) {
  const consensus = brief.position_against;
  const dissent = brief.position_for;
  return (
    <div className="mt-10 rounded-sm border border-neutral-200 bg-neutral-50 p-8">
      <div className="text-[11px] tracking-[0.2em] font-semibold text-neutral-500">
        NOT MEANINGFULLY SPLIT
      </div>
      <p className="mt-3 text-neutral-700 leading-relaxed max-w-3xl">
        This claim isn't meaningfully split — here's the consensus and the lone dissent.
        Asymmetry score: <span className="font-mono">{brief.asymmetry.toFixed(2)}</span>.
      </p>

      <div className="mt-8 grid gap-8 md:grid-cols-[2fr_1fr]">
        <div>
          <div className="text-[11px] tracking-[0.2em] font-semibold text-neutral-900">
            CONSENSUS
          </div>
          <p className="mt-2 text-sm text-neutral-700 leading-relaxed">{consensus.summary}</p>
          <ul className="mt-4 space-y-3">
            {consensus.claims.map((c, i) => (
              <li key={i} className="text-[15px] text-neutral-900 leading-relaxed">
                <span className="font-mono text-xs text-neutral-400 mr-2">
                  {String(i + 1).padStart(2, "0")}
                </span>
                {c.text}
                <div className="mt-1.5 flex flex-wrap gap-1.5 ml-6">
                  {consensus.sources.slice(i, i + 1).map((s, si) => (
                    <SourceChip key={si} source={s} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="border-l border-neutral-300 pl-6">
          <div className="text-[11px] tracking-[0.2em] font-semibold text-neutral-500">
            LONE DISSENT
          </div>
          <p className="mt-2 text-sm text-neutral-600 leading-relaxed italic">{dissent.summary}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {dissent.sources.map((s, i) => (
              <SourceChip key={i} source={s} />
            ))}
          </div>
        </div>
      </div>

      <div className="mt-8 pt-6 border-t border-neutral-200">
        <div className="text-[11px] tracking-[0.2em] font-semibold text-neutral-500">
          WHAT WOULD CHANGE THIS
        </div>
        <p className="mt-2 text-sm text-neutral-700 leading-relaxed max-w-3xl">{brief.resolver}</p>
      </div>
    </div>
  );
}

function CruxSection({ brief, visible }: { brief: Brief; visible: boolean }) {
  return (
    <section
      className={`mt-16 transition-all duration-700 ${
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4 pointer-events-none"
      }`}
    >
      <div className="border-t border-neutral-900 pt-6">
        <div className="flex items-baseline gap-3 flex-wrap">
          <div className="text-[11px] tracking-[0.2em] font-semibold text-neutral-900">CRUX</div>
          <span className="inline-block rounded-sm bg-neutral-900 px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider text-neutral-50">
            {brief.crux_type}
          </span>
          <span className="text-xs font-mono text-neutral-500">
            asymmetry {brief.asymmetry.toFixed(2)}
          </span>
        </div>
        <p className="mt-3 text-lg text-neutral-900 leading-relaxed max-w-4xl">{brief.crux}</p>
      </div>

      <div className="mt-8 grid gap-8 md:grid-cols-[auto_1fr] max-w-4xl">
        <div className="text-[11px] tracking-[0.2em] font-semibold text-neutral-500 md:pt-1">
          WHAT WOULD RESOLVE IT
        </div>
        <p className="text-sm text-neutral-700 leading-relaxed">{brief.resolver}</p>
      </div>
    </section>
  );
}

function DevilsAdvocates() {
  const [input, setInput] = useState("Creatine supplementation improves cognitive performance in healthy adults.");
  const [demoId, setDemoId] = useState<string | undefined>("creatine");
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(false);
  const [runId, setRunId] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setBrief(null);
    fetchBrief({ claim: input, demoId }).then((b) => {
      if (!cancelled) {
        setBrief(b);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const isConsensus = brief ? brief.asymmetry > 0.85 : false;

  const forClaims = brief?.position_for.claims ?? [];
  const againstClaims = brief?.position_against.claims ?? [];

  const forVisible = useStreamedClaims(forClaims, !!brief && !isConsensus, 200);
  const againstVisible = useStreamedClaims(againstClaims, !!brief && !isConsensus, 400);

  const bothDone =
    !!brief &&
    !isConsensus &&
    forVisible >= forClaims.length &&
    againstVisible >= againstClaims.length;

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    setDemoId(undefined);
    setRunId((n) => n + 1);
  };

  const runDemo = (id: string) => {
    const demo = DEMO_OPTIONS.find((d) => d.id === id);
    setDemoId(id);
    if (demo) {
      // Pull claim text from mock at run time
      import("@/lib/brief-mocks").then((m) => {
        setInput(m.MOCK_BRIEFS[id].claim);
        setRunId((n) => n + 1);
      });
    }
  };

  const displayedClaim = useMemo(() => brief?.claim ?? input, [brief, input]);

  return (
    <div className="min-h-screen bg-white text-neutral-900" style={{ fontFamily: "'Iowan Old Style', 'Palatino Linotype', Georgia, serif" }}>
      <div className="mx-auto max-w-6xl px-6 py-12">
        {/* Masthead */}
        <header className="border-b border-neutral-900 pb-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] tracking-[0.3em] font-semibold text-neutral-500 font-sans">
                A DISAGREEMENT ENGINE
              </div>
              <h1 className="mt-1 text-4xl font-semibold tracking-tight">Devil's Advocates</h1>
            </div>
            <div className="text-[10px] tracking-[0.2em] text-neutral-500 font-mono uppercase text-right">
              <div>Gemma 4 Hackathon</div>
              <div>Track 03</div>
            </div>
          </div>
          <p className="mt-4 text-sm text-neutral-600 max-w-2xl leading-relaxed font-sans">
            Enter a contested scientific claim. Two agents will argue the strongest case for and against,
            cite their sources, and identify the crux. We map the disagreement — we don't adjudicate it.
          </p>
        </header>

        {/* Input */}
        <form onSubmit={submit} className="mt-8 font-sans">
          <label htmlFor="claim" className="block text-[11px] tracking-[0.2em] font-semibold text-neutral-900">
            CLAIM
          </label>
          <div className="mt-2 flex gap-2">
            <input
              id="claim"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="e.g. Intermittent fasting improves metabolic health."
              className="flex-1 border border-neutral-300 bg-white px-4 py-3 text-[15px] text-neutral-900 placeholder:text-neutral-400 focus:outline-none focus:border-neutral-900 rounded-sm"
            />
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className="px-6 py-3 bg-neutral-900 text-neutral-50 text-sm font-medium tracking-wide hover:bg-neutral-800 disabled:bg-neutral-300 disabled:cursor-not-allowed rounded-sm"
            >
              {loading ? "Convening…" : "Debate"}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2 items-center">
            <span className="text-[11px] uppercase tracking-wider text-neutral-500">Demos:</span>
            {DEMO_OPTIONS.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => runDemo(d.id)}
                className={`text-xs px-2.5 py-1 rounded-sm border transition-colors ${
                  demoId === d.id
                    ? "border-neutral-900 bg-neutral-900 text-neutral-50"
                    : "border-neutral-300 text-neutral-700 hover:border-neutral-900"
                }`}
              >
                {d.label}
              </button>
            ))}
          </div>
        </form>

        {/* Claim display */}
        {brief && (
          <div className="mt-10">
            <div className="text-[11px] tracking-[0.2em] font-semibold text-neutral-500 font-sans">
              THE CLAIM UNDER DEBATE
            </div>
            <blockquote className="mt-2 text-2xl leading-snug text-neutral-900 max-w-4xl">
              "{displayedClaim}"
            </blockquote>
          </div>
        )}

        {/* Body */}
        {brief && !isConsensus && (
          <div className="mt-10 grid gap-10 md:grid-cols-2">
            <Column side="FOR" position={brief.position_for} visibleCount={forVisible} />
            <Column side="AGAINST" position={brief.position_against} visibleCount={againstVisible} />
          </div>
        )}

        {brief && !isConsensus && <CruxSection brief={brief} visible={bothDone} />}

        {brief && isConsensus && <ConsensusView brief={brief} />}

        {/* Footer */}
        <footer className="mt-20 pt-6 border-t border-neutral-200 text-[11px] text-neutral-500 font-sans flex flex-wrap justify-between gap-2">
          <span>Sources retrieved via OpenAIRE, bioRxiv, medRxiv.</span>
          <span>No winner is declared. The disagreement is the output.</span>
        </footer>
      </div>
    </div>
  );
}
