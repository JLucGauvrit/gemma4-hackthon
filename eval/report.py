"""Summarize eval/results.jsonl (produced by eval/evaluate.py) into a table and
a chart: does 'compressed' match 'raw' accuracy while beating 'truncated' at
the same token budget?

Writes eval/table.md and eval/curve.png. Matplotlib only, headless (Agg).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent
RESULTS_PATH = ROOT / "results.jsonl"
TABLE_PATH = ROOT / "table.md"
CURVE_PATH = ROOT / "curve.png"

CONFIG_NAMES = ("raw", "truncated", "compressed")
CONFIG_LABEL = {"raw": "Raw", "truncated": "Truncated", "compressed": "Compressed"}
CONFIG_COLOR = {"raw": "#2a78d6", "truncated": "#eb6834", "compressed": "#1baf7a"}

INK = "#0b0b0b"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"


def _load_rows() -> list[dict]:
    lines = RESULTS_PATH.read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def _summarize(rows: list[dict]) -> dict[str, dict]:
    summary = {}
    for name in CONFIG_NAMES:
        cfg_rows = [r for r in rows if r["config"] == name]
        accs = [r["accuracy"] for r in cfg_rows if r.get("accuracy") is not None]
        summary[name] = {
            "accuracy": _mean(accs),
            "tokens": _mean([r["tokens"] for r in cfg_rows]),
            "latency_s": _mean([r["latency_s"] for r in cfg_rows]),
        }
    return summary


def _write_table(summary: dict[str, dict]) -> None:
    raw_acc = summary["raw"]["accuracy"]
    raw_tok = summary["raw"]["tokens"]
    lines = [
        "| config | mean stance accuracy | mean tokens fed | mean latency (s) | "
        "accuracy retained vs raw (%) | token reduction vs raw (%) |",
        "|---|---|---|---|---|---|",
    ]
    for name in CONFIG_NAMES:
        s = summary[name]
        retained = 100 * s["accuracy"] / raw_acc if raw_acc else float("nan")
        reduction = 100 * (1 - s["tokens"] / raw_tok) if raw_tok else float("nan")
        lines.append(
            f"| {CONFIG_LABEL[name]} | {s['accuracy']:.3f} | {s['tokens']:.1f} | "
            f"{s['latency_s']:.3f} | {retained:.1f}% | {reduction:.1f}% |"
        )
    TABLE_PATH.write_text("\n".join(lines) + "\n")


def _plot_curve(summary: dict[str, dict]) -> None:
    fig, ax = plt.subplots(figsize=(6, 4.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for name in CONFIG_NAMES:
        s = summary[name]
        ax.scatter(s["tokens"], s["accuracy"], s=90, color=CONFIG_COLOR[name],
                   zorder=3, edgecolors=SURFACE, linewidths=1.5)
        ax.annotate(CONFIG_LABEL[name], (s["tokens"], s["accuracy"]),
                    textcoords="offset points", xytext=(8, 8),
                    fontsize=10, color=INK)

    ax.set_xlabel("mean tokens fed", color=MUTED, fontsize=10)
    ax.set_ylabel("mean stance accuracy", color=MUTED, fontsize=10)
    ax.set_title("Accuracy vs tokens fed, by config", color=INK, fontsize=12, pad=12)

    ax.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelsize=9)

    fig.tight_layout()
    fig.savefig(CURVE_PATH, facecolor=SURFACE)
    plt.close(fig)


def _conclusion(summary: dict[str, dict]) -> str:
    raw, trunc, comp = summary["raw"], summary["truncated"], summary["compressed"]
    retained = 100 * comp["accuracy"] / raw["accuracy"] if raw["accuracy"] else float("nan")
    reduction = 100 * (1 - comp["tokens"] / raw["tokens"]) if raw["tokens"] else float("nan")
    beats = "beats" if comp["accuracy"] > trunc["accuracy"] else "trails"
    return (
        f"compressed retains {retained:.1f}% of raw accuracy "
        f"({comp['accuracy']:.3f} vs {raw['accuracy']:.3f}) using {reduction:.1f}% fewer tokens "
        f"than raw ({comp['tokens']:.1f} vs {raw['tokens']:.1f} tokens), and {beats} truncated "
        f"({trunc['accuracy']:.3f} accuracy at {trunc['tokens']:.1f} tokens) at a comparable token budget."
    )


def main() -> None:
    rows = _load_rows()
    summary = _summarize(rows)
    _write_table(summary)
    _plot_curve(summary)
    print(_conclusion(summary))


if __name__ == "__main__":
    main()
