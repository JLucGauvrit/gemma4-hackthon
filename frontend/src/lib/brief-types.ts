export type Stance = "SUPPORTS" | "REFUTES" | "NEUTRAL";

export interface Source {
  doi: string | null;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  license: string | null;
  retrieved_via: "openaire" | "biorxiv" | "medrxiv";
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
  crux: string;
  crux_type: CruxType;
  resolver: string;
  asymmetry: number;
}
