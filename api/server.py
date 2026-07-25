from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from core.pipeline import run
from core.schema import Config


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST_ROOT = ROOT / "frontend" / "dist"
UI_ROOT = ROOT / "ui"
SSE_HEARTBEAT_SECONDS = 12.0


def _jsonable(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


def _sse(event_type: str, payload: dict) -> bytes:
    body = json.dumps(_jsonable(payload), ensure_ascii=False)
    return f"event: {event_type}\ndata: {body}\n\n".encode("utf-8")


def _static_root() -> Path:
    """Prefer the compiled React app, while retaining the zero-build demo UI."""
    if (FRONTEND_DIST_ROOT / "index.html").is_file():
        return FRONTEND_DIST_ROOT
    return UI_ROOT


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "DevilsAdvocatesHTTP/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            self._stream_run(parsed.query)
            return
        if parsed.path == "/api/health":
            self._json({"ok": True})
            return
        self._serve_static(parsed.path)

    def _stream_run(self, query_string: str) -> None:
        params = parse_qs(query_string)
        question = (params.get("question") or [""])[0].strip()
        if not question:
            self._json({"error": "question is required"}, HTTPStatus.BAD_REQUEST)
            return

        cfg = Config(shared_evidence=(params.get("shared_evidence") or ["false"])[0] == "true")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        async def emit() -> None:
            queue: asyncio.Queue[dict | object] = asyncio.Queue()
            finished = object()

            async def produce() -> None:
                try:
                    async for event in run(question, cfg):
                        await queue.put(event)
                finally:
                    await queue.put(finished)

            producer = asyncio.create_task(produce())
            try:
                self.wfile.write(_sse("status", {"type": "status", "message": "starting"}))
                self.wfile.flush()
                while True:
                    try:
                        event = await asyncio.wait_for(
                            queue.get(),
                            timeout=SSE_HEARTBEAT_SECONDS,
                        )
                    except TimeoutError:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    if event is finished:
                        break
                    assert isinstance(event, dict)
                    self.wfile.write(_sse(str(event.get("type", "message")), event))
                    self.wfile.flush()
                await producer
                self.wfile.write(_sse("done", {"type": "done"}))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                try:
                    self.wfile.write(_sse("error", {"type": "error", "message": str(exc)}))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
            finally:
                if not producer.done():
                    producer.cancel()
                try:
                    await producer
                except (asyncio.CancelledError, Exception):
                    pass

        asyncio.run(emit())
        self.close_connection = True

    def _serve_static(self, raw_path: str) -> None:
        static_root = _static_root().resolve()
        rel = "index.html" if raw_path in {"", "/"} else unquote(raw_path).lstrip("/")
        target = (static_root / rel).resolve()
        if static_root not in target.parents and target != static_root:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            # React Router/TanStack client routes need the SPA shell. Asset
            # requests must remain real 404s so failed deploys are visible.
            if not Path(rel).suffix and (static_root / "index.html").is_file():
                target = static_root / "index.html"
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if target.name == "index.html":
            self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the live Devil's Advocates UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    print(f"live UI: http://{args.host}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
