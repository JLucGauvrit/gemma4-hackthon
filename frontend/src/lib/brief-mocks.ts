import type { Brief, Source } from "./brief-types";

const s = (o: Partial<Source> & { title: string }): Source => ({
  doi: null,
  authors: [],
  year: null,
  venue: null,
  license: null,
  retrieved_via: "openaire",
  ...o,
});

const creatineBrief: Brief = {
  claim: "Creatine supplementation improves cognitive performance in healthy adults.",
  position_for: {
    summary:
      "Meta-analyses of randomized trials report small but reliable improvements in short-term memory and reasoning, particularly under cognitive stress or sleep deprivation.",
    claims: [
      {
        text: "A 2023 meta-analysis of 16 RCTs found a small positive effect on short-term memory (SMD ≈ 0.31).",
        cites: ["for-1"],
      },
      {
        text: "Effects appear strongest in vegetarians and older adults, where baseline brain creatine is lower.",
        cites: ["for-2"],
      },
      {
        text: "Under acute stressors (sleep deprivation, hypoxia), reasoning speed improves versus placebo.",
        cites: ["for-3"],
      },
    ],
    sources: [
      s({
        title: "Effects of creatine supplementation on cognitive function: a meta-analysis",
        year: 2023,
        venue: "Nutrition Reviews",
        doi: "10.1093/nutrit/nuad021",
        authors: ["Prokopidis K", "Giannos P"],
        retrieved_via: "openaire",
      }),
      s({
        title: "Creatine and cognition in vegetarians: a randomized trial",
        year: 2011,
        venue: "Proc. Royal Society B",
        doi: "10.1098/rspb.2003.2492",
        authors: ["Rae C", "Digney AL"],
      }),
      s({
        title: "Creatine supplementation during sleep deprivation",
        year: 2024,
        venue: "Scientific Reports",
        doi: "10.1038/s41598-024-54249-9",
        authors: ["Gordji-Nejad A", "Matusch A"],
        retrieved_via: "biorxiv",
      }),
    ],
  },
  position_against: {
    summary:
      "Most well-controlled trials in healthy, non-stressed adults show null or trivial effects; observed benefits often reflect small samples, selective outcomes, or specific deficient subgroups.",
    claims: [
      {
        text: "Large RCTs in healthy young adults find no reliable effect on standard cognitive batteries.",
        cites: ["ag-1"],
      },
      {
        text: "Reported effects shrink toward zero once studies are corrected for small-study bias.",
        cites: ["ag-2"],
      },
      {
        text: "Brain creatine uptake from oral supplementation is limited; MRS studies show only modest increases.",
        cites: ["ag-3"],
      },
    ],
    sources: [
      s({
        title: "No effect of creatine on cognition in healthy young adults",
        year: 2018,
        venue: "Experimental Brain Research",
        doi: "10.1007/s00221-018-5346-8",
        authors: ["Rawson ES", "Venezia AC"],
      }),
      s({
        title: "Publication bias in nutritional cognitive trials",
        year: 2022,
        venue: "BMJ Evidence-Based Medicine",
        doi: "10.1136/bmjebm-2021-111902",
        authors: ["Ioannidis JPA"],
      }),
      s({
        title: "Brain creatine uptake measured by 1H-MRS",
        year: 2020,
        venue: "NMR in Biomedicine",
        doi: "10.1002/nbm.4341",
        authors: ["Dechent P", "Pouwels PJW"],
        retrieved_via: "medrxiv",
      }),
    ],
  },
  crux: "Whether the effect exists in healthy, non-stressed adults, or only in populations with depleted baseline brain creatine (vegetarians, sleep-deprived, elderly).",
  crux_type: "population",
  resolver:
    "A large (n > 500) preregistered RCT in unselected healthy adults, stratified by baseline diet and brain creatine (MRS), with a preregistered primary cognitive outcome, would resolve most of the disagreement.",
  asymmetry: 0.35,
};

const vitcBrief: Brief = {
  claim: "Taking megadoses of vitamin C prevents the common cold in the general population.",
  position_for: {
    summary:
      "A minority of trials and observational reports suggest reduced cold incidence with very high daily doses.",
    claims: [
      {
        text: "Some early trials in specific populations (marathon runners, soldiers) showed reduced incidence.",
        cites: ["c-1"],
      },
    ],
    sources: [
      s({
        title: "Vitamin C and physical stress: subgroup effects",
        year: 2013,
        venue: "Cochrane Database Syst Rev",
        doi: "10.1002/14651858.CD000980.pub4",
        authors: ["Hemilä H", "Chalker E"],
      }),
    ],
  },
  position_against: {
    summary:
      "Large pooled analyses across decades of RCTs find no meaningful reduction in cold incidence in the general population; only a small reduction in duration.",
    claims: [
      {
        text: "Pooled RCTs (n > 11,000) show no reduction in cold incidence in the general population.",
        cites: ["c-2"],
      },
      {
        text: "Duration reduction is modest (~8% adults, ~14% children) and only for prophylactic, not therapeutic, use.",
        cites: ["c-3"],
      },
      {
        text: "Megadoses (>2g/day) show no additional benefit and increase GI side effects.",
        cites: ["c-4"],
      },
    ],
    sources: [
      s({
        title: "Vitamin C for preventing and treating the common cold",
        year: 2013,
        venue: "Cochrane Database Syst Rev",
        doi: "10.1002/14651858.CD000980.pub4",
        authors: ["Hemilä H", "Chalker E"],
      }),
      s({
        title: "Vitamin C supplementation and cold duration",
        year: 2017,
        venue: "Nutrients",
        doi: "10.3390/nu9040339",
        authors: ["Hemilä H"],
      }),
      s({
        title: "Adverse effects of high-dose ascorbate",
        year: 2019,
        venue: "Am J Clin Nutrition",
        doi: "10.1093/ajcn/nqz076",
        authors: ["Padayatty SJ"],
      }),
    ],
  },
  crux: "Whether observed benefits generalize beyond specific stressed subgroups (athletes, soldiers) to the general population.",
  crux_type: "population",
  resolver:
    "The existing Cochrane evidence base (>29 RCTs, >11,000 participants) already answers this for prevention in the general population; no meaningful split remains.",
  asymmetry: 0.92,
};

export const MOCK_BRIEFS: Record<string, Brief> = {
  creatine: creatineBrief,
  vitaminc: vitcBrief,
};

export const DEMO_OPTIONS = [
  { id: "creatine", label: "Creatine & cognition (contested)" },
  { id: "vitaminc", label: "Vitamin C megadoses & colds (consensus)" },
];
