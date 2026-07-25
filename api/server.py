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
UI_ROOT = ROOT / "ui"


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
            try:
                self.wfile.write(_sse("status", {"type": "status", "message": "starting"}))
                self.wfile.flush()
                async for event in run(question, cfg):
                    self.wfile.write(_sse(str(event.get("type", "message")), event))
                    self.wfile.flush()
                self.wfile.write(_sse("done", {"type": "done"}))
                self.wfile.flush()
            except BrokenPipeError:
                return
            except Exception as exc:
                self.wfile.write(_sse("error", {"type": "error", "message": str(exc)}))
                self.wfile.flush()

        asyncio.run(emit())
        self.close_connection = True

    def _serve_static(self, raw_path: str) -> None:
        rel = "index.html" if raw_path in {"", "/"} else unquote(raw_path).lstrip("/")
        target = (UI_ROOT / rel).resolve()
        if UI_ROOT not in target.parents and target != UI_ROOT:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
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
