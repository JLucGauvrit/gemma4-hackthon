"""OAuth'd MCP client for the Alien research servers.

The plugin tools inside Claude Code are Claude's, not the app's. A standalone
process needs its own OAuth client — that's this. One browser login on first
run; tokens cached under ~/.devils_advocates/, headless (refresh-token) after.

    async with session("openaire") as s:
        res = await s.call_tool("openaire_search_research_products", {...})
"""

from __future__ import annotations

import asyncio
import os
import webbrowser
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

SERVERS = {
    "openaire": "https://openaire.mcp.alien.club/mcp",
    "medrxiv": "https://medrxiv.mcp.alien.club/mcp",
    "biorxiv": "https://biorxiv.mcp.alien.club/mcp",
}

CALLBACK_PORT = int(os.environ.get("DA_CALLBACK_PORT", "8765"))
CALLBACK_BIND_HOST = os.environ.get("DA_CALLBACK_BIND_HOST", "localhost")
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
TOKEN_DIR = Path(os.environ.get("DA_TOKEN_DIR", Path.home() / ".devils_advocates"))


class _FileStorage(TokenStorage):
    """Per-server token + client-registration cache as plain JSON files."""

    def __init__(self, key: str):
        self._tok = TOKEN_DIR / f"{key}.tokens.json"
        self._cli = TOKEN_DIR / f"{key}.client.json"

    async def get_tokens(self) -> OAuthToken | None:
        return OAuthToken.model_validate_json(self._tok.read_text()) if self._tok.exists() else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        self._tok.write_text(tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return OAuthClientInformationFull.model_validate_json(self._cli.read_text()) if self._cli.exists() else None

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        self._cli.write_text(info.model_dump_json())


async def _redirect(url: str) -> None:
    print(f"\n[auth] Opening browser to authorize. If it doesn't open, visit:\n{url}\n")
    webbrowser.open(url)


async def _await_callback() -> tuple[str, str | None]:
    """Serve exactly one localhost request to capture ?code=&state=."""
    captured: dict[str, str | None] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            captured["code"] = q.get("code", [""])[0]
            captured["state"] = q.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h3>Authorized.</h3> You can close this tab.")

        def log_message(self, *a):  # silence
            pass

    def serve_one():
        srv = HTTPServer((CALLBACK_BIND_HOST, CALLBACK_PORT), Handler)
        srv.handle_request()
        srv.server_close()

    await asyncio.to_thread(serve_one)
    return captured.get("code", ""), captured.get("state")


def _provider(server: str) -> OAuthClientProvider:
    url = SERVERS[server]
    return OAuthClientProvider(
        server_url=url.removesuffix("/mcp"),
        client_metadata=OAuthClientMetadata(
            client_name="Devils Advocates",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="openid profile email offline_access",
            token_endpoint_auth_method="client_secret_post",
        ),
        storage=_FileStorage(server),
        redirect_handler=_redirect,
        callback_handler=_await_callback,
    )


@asynccontextmanager
async def session(server: str):
    """Open an initialized MCP session. Reuse it for multiple call_tool()s."""
    url = SERVERS[server]
    async with streamablehttp_client(url, auth=_provider(server)) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            yield s


def tool_text(result) -> str:
    """Flatten a call_tool result to its text payload."""
    return "".join(getattr(c, "text", "") for c in result.content)


if __name__ == "__main__":  # smoke: trigger login + list tools
    import sys

    srv = sys.argv[1] if len(sys.argv) > 1 else "openaire"

    async def _smoke():
        async with session(srv) as s:
            tools = await s.list_tools()
            print(f"[{srv}] authorized · {len(tools.tools)} tools")
            for t in tools.tools[:5]:
                print("  •", t.name)

    asyncio.run(_smoke())
