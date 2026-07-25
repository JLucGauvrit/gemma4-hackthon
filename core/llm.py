"""The one seam between the pipeline and Gemma served by vLLM.

Every model-driven stage goes through `generate(role, prompt, tier)`. vLLM
exposes an OpenAI-compatible API, so the pipeline has no dependency on a
particular inference server implementation.

`GEMMA_MODEL` forces every role onto one served model. Otherwise
`VLLM_MODEL_E2B` and `VLLM_MODEL_E4B` select the model for each tier; both
default to `VLLM_MODEL`, making a single-checkpoint deployment the default.
"""

from __future__ import annotations

import contextvars
import json
import os
import re

_usage_sink: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "_usage_sink", default=None)


class capture_usage:
    """Context manager for eval harnesses: collect per-call token usage from
    every generate() call made inside the block, including ones spawned as
    concurrent asyncio tasks (e.g. classify_stance's gather'd batches) — a
    plain module-level list would race across those; each Task instead gets
    its own copy of this ContextVar binding pointing at the SAME list object,
    so appends land safely without a lock (asyncio has no preemption mid-call)."""

    def __enter__(self) -> list[dict]:
        self.records: list[dict] = []
        self._token = _usage_sink.set(self.records)
        return self.records

    def __exit__(self, *exc) -> None:
        _usage_sink.reset(self._token)


def _model_for(tier: str) -> str:
    """Return the vLLM served-model name for a configured tier."""
    if tier not in {"E2B", "E4B"}:
        raise ValueError(f"unknown model tier: {tier}")
    model = (
        os.environ.get("GEMMA_MODEL")
        or os.environ.get(f"VLLM_MODEL_{tier}")
        or os.environ.get("VLLM_MODEL")
    )
    if model is None:
        raise RuntimeError(
            "set VLLM_MODEL (or VLLM_MODEL_E2B/VLLM_MODEL_E4B) to the "
            "served Gemma model name"
        )
    return model


async def generate(role: str, prompt: str, *, tier: str = "E2B") -> str:
    """Return Gemma's text for `role` at `tier`. All our roles emit JSON."""
    import httpx

    model = _model_for(tier)
    base_url = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0,                 # deterministic extraction/classification
        "response_format": {"type": "json_object"},
    }
    headers = {}
    if api_key := os.environ.get("VLLM_API_KEY"):
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        sink = _usage_sink.get()
        if sink is not None:
            usage = data.get("usage") or {}
            sink.append({
                "role": role, "tier": tier,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            })
        return data["choices"][0]["message"]["content"]


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
