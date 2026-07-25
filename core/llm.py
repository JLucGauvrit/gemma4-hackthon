"""The one seam between the pipeline and Gemma.

Every model-driven stage goes through `generate(role, prompt, tier)`. Today that
hits a local Ollama serving Gemma 4; swap `_ollama` for a Brev/OpenAI-compatible
call at deploy time and nothing upstream changes.

`GEMMA_MODEL` forces every role onto one model (run all-E4B before you've pulled
E2B). Unset it once `ollama pull gemma4:e2b` is done — that's the Track-03 run
(E2B for extract/stance/advocate, E4B only for the judge).
"""

from __future__ import annotations

import json
import os
import re

# tier -> Ollama model tag. Overridden wholesale by GEMMA_MODEL.
_OLLAMA_MODEL = {"E2B": "gemma4:e2b", "E4B": "gemma4:e4b"}


async def generate(role: str, prompt: str, *, tier: str = "E2B") -> str:
    """Return Gemma's text for `role` at `tier`. All our roles emit JSON."""
    import httpx

    model = os.environ.get("GEMMA_MODEL") or _OLLAMA_MODEL[tier]
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",               # constrain output to valid JSON
        "options": {"temperature": 0},  # deterministic extraction/classification
    }
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, json=payload)
        r.raise_for_status()
        return r.json()["response"]


def parse_json(text: str):
    """Tolerant JSON load — handles ```fences``` and leading/trailing prose."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"[\[{]", t)
        if m is None:
            raise
        end = max(t.rfind("]"), t.rfind("}"))
        return json.loads(t[m.start():end + 1])
