export type Stance = "SUPPORTS" | "REFUTES" | "UNRESOLVED" | "NEUTRAL";

export interface Source {
  doi: string | null;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  license: string | null;
  retrieved_via: "openaire" | "biorxiv" | "medrxiv" | string;
}

export interface Snippet {
  id: string;
  text: string;
  stance: Stance;
  confidence: number;
  source: Source;
}

export interface Claim {
  text: string;
  cites: string[];
}

export type CruxType =
  | "population"
  | "methodology"
  | "timeframe"
  | "measured-construct"
  | "effect-size"
  | "none";

export interface Position {
  summary: string;
  claims: Claim[];
  sources: Source[];
}

export interface Brief {
  claim: string;
  position_for: Position;
  position_against: Position;
  citation_sources?: Record<string, Source>;
  crux: string;
  crux_type: CruxType;
  resolver: string;
  asymmetry: number;
  transcript?: Array<{
    agent: "FOR" | "AGAINST";
    round: number;
    claims: Claim[];
  }>;
  meta?: Record<string, unknown>;
  verdict?: "CONTESTED" | "CONSENSUS" | "INSUFFICIENT_EVIDENCE" | "OUT_OF_SCOPE";
}
