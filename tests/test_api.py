from __future__ import annotations

import http.client
import json
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from api import server as api_server


@contextmanager
def running_api(fake_run):
    with patch.object(api_server, "run", fake_run):
        httpd = api_server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            api_server.DemoHandler,
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield httpd.server_address
        finally:
            httpd.shutdown()
            thread.join(timeout=2)
            httpd.server_close()


def get(address, path: str) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(*address, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def parse_sse(body: bytes) -> list[tuple[str, dict]]:
    events = []
    for frame in body.decode("utf-8").strip().split("\n\n"):
        lines = frame.splitlines()
        event_type = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        events.append((event_type, json.loads(data)))
    return events


class ApiIntegrationTests(unittest.TestCase):
    def test_health_is_available_without_starting_the_pipeline(self):
        def should_not_run(*args, **kwargs):
            raise AssertionError("health must not start a debate")

        with running_api(should_not_run) as address:
            status, headers, body = get(address, "/api/health")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body), {"ok": True})

    def test_run_rejects_an_empty_question_before_starting_the_pipeline(self):
        def should_not_run(*args, **kwargs):
            raise AssertionError("an invalid request must not start a debate")

        with running_api(should_not_run) as address:
            status, headers, body = get(address, "/api/run?question=+++")

        self.assertEqual(status, 400)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body), {"error": "question is required"})

    def test_successful_stream_has_terminal_done_event(self):
        async def fake_run(question, config):
            yield {"type": "brief", "claim": question}

        with running_api(fake_run) as address:
            status, headers, body = get(address, "/api/run?question=Does+it+work%3F")

        self.assertEqual(status, 200)
        self.assertEqual(
            headers["Content-Type"],
            "text/event-stream; charset=utf-8",
        )
        self.assertEqual(
            parse_sse(body),
            [
                ("status", {"type": "status", "message": "starting"}),
                ("brief", {"type": "brief", "claim": "Does it work?"}),
                ("done", {"type": "done"}),
            ],
        )

    def test_stream_preserves_pipeline_order_and_shared_evidence_option(self):
        received = []

        async def fake_run(question, config):
            received.append((question, config.shared_evidence))
            yield {
                "type": "turn_claim",
                "side": "FOR",
                "claim": {"text": "Café evidence", "cites": ["s1"]},
            }
            yield {"type": "crux", "text": "Different populations"}

        with running_api(fake_run) as address:
            status, headers, body = get(
                address,
                "/api/run?question=Cr%C3%A9atine&shared_evidence=true",
            )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-cache")
        self.assertEqual(headers["X-Accel-Buffering"], "no")
        self.assertEqual(received, [("Créatine", True)])
        self.assertEqual(
            [event_type for event_type, _ in parse_sse(body)],
            ["status", "turn_claim", "crux", "done"],
        )
        self.assertEqual(
            parse_sse(body)[1][1]["claim"]["text"],
            "Café evidence",
        )

    def test_pipeline_failure_is_framed_as_terminal_error(self):
        async def failing_run(question, config):
            if False:
                yield {}
            raise RuntimeError("model unavailable")

        with running_api(failing_run) as address:
            status, _, body = get(address, "/api/run?question=Will+it+fail%3F")

        self.assertEqual(status, 200)
        self.assertEqual(
            parse_sse(body),
            [
                ("status", {"type": "status", "message": "starting"}),
                (
                    "error",
                    {"type": "error", "message": "model unavailable"},
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
