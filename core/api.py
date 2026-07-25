"""OpenAI-compatible HTTP facade for the Devil's Advocates pipeline.

OpenWebUI can register this service as an OpenAI connection. The pipeline is
still the only place that performs retrieval and model calls; this module only
turns a chat request into a question and serializes the resulting Brief.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from core.pipeline import run_to_brief
from core.schema import Brief, Source

MODEL_ID = "devils-advocates"


def _message_text(content: Any) -> str:
    """Extract text from OpenAI's string or multipart message content."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type", "text") == "text"
        ).strip()
    return ""


def _question(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("'messages' must be a list")
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            question = _message_text(message.get("content"))
            if question:
                return question
    raise ValueError("a non-empty user message is required")


def _source_line(source: Source) -> str:
    year = str(source.year) if source.year else "n.d."
    authors = ", ".join(source.authors[:3]) or "Unknown authors"
    doi = f"https://doi.org/{source.doi}" if source.doi else None
    title = f"[{source.title}]({doi})" if doi else source.title
    return f"- {title} — {authors} ({year})"


def brief_to_markdown(brief: Brief) -> str:
    """Render the structured research result as a concise chat answer."""
    lines = [f"## Claim\n{brief.claim}"]
    if brief.meta.get("out_of_scope"):
        lines.extend(["## Result", brief.crux, f"**Next step:** {brief.resolver}"])
        return "\n\n".join(lines)

    def position(title: str, claims: list) -> None:
        lines.append(f"## {title}")
        if not claims:
            lines.append("No citation-grounded argument was produced.")
            return
        lines.extend(f"- {claim.text} _(evidence: {', '.join(claim.cites)})_" for claim in claims)

    position("Evidence for", brief.position_for.claims)
    position("Evidence against", brief.position_against.claims)
    lines.extend([
        "## Crux",
        f"{brief.crux}\n\n**Type:** {brief.crux_type}\n\n**How to resolve it:** {brief.resolver}",
        "## Sources",
    ])
    sources = brief.position_for.sources + brief.position_against.sources
    seen: set[tuple[str | None, str]] = set()
    for source in sources:
        key = (source.doi, source.title)
        if key not in seen:
            lines.append(_source_line(source))
            seen.add(key)
    lines.append(f"\n_Evidence asymmetry: {brief.asymmetry:.2f} (0 = balanced, 1 = one-sided)._" )
    return "\n\n".join(lines)


def _chunk(completion_id: str, created: int, delta: dict[str, str], finish_reason: str | None = None) -> str:
    return "data: " + json.dumps({
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": MODEL_ID,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }) + "\n\n"


async def _stream_answer(question: str) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    yield _chunk(completion_id, created, {"role": "assistant"})
    try:
        brief = await run_to_brief(question)
        yield _chunk(completion_id, created, {"content": brief_to_markdown(brief)})
        yield _chunk(completion_id, created, {}, "stop")
    except Exception as exc:
        yield _chunk(completion_id, created, {"content": f"\n\nAPI error: {exc}"})
        yield _chunk(completion_id, created, {}, "stop")
    yield "data: [DONE]\n\n"


async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


async def list_models(_: Request) -> JSONResponse:
    return JSONResponse({"object": "list", "data": [{
        "id": MODEL_ID, "object": "model", "created": 0, "owned_by": "devils-advocates",
    }]})


async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        question = _question(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        return JSONResponse({"error": {"message": str(exc), "type": "invalid_request_error"}}, status_code=400)

    if payload.get("stream") is True:
        return StreamingResponse(_stream_answer(question), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    try:
        brief = await run_to_brief(question)
    except Exception as exc:
        return JSONResponse({"error": {"message": str(exc), "type": "server_error"}}, status_code=500)
    content = brief_to_markdown(brief)
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion",
        "created": int(time.time()), "model": MODEL_ID,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    })


app = Starlette(routes=[
    Route("/health", health),
    Route("/v1/models", list_models),
    Route("/v1/chat/completions", chat_completions, methods=["POST"]),
])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"],
)


def main() -> None:
    """Run the API locally or in the application container."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()
