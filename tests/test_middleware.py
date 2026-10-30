"""Gateway credential middleware tests: missing-header 401, and header
values correctly reaching the per-request contextvar (no global-state
leakage across requests).
"""

import asyncio
import json

import pytest
from starlette.testclient import TestClient

from unifi_network_mcp.__main__ import _build_http_app
from unifi_network_mcp.config import Settings
from unifi_network_mcp.server import create_mcp_server, get_client_from_context


def _make_app():
    settings = Settings()
    mcp = create_mcp_server(settings)
    return _build_http_app(mcp, settings), settings


def test_health_is_local_and_does_not_require_credentials():
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_missing_headers_returns_401_with_required_headers_listed():
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["required_headers"] == ["X-Unifi-Api-Key", "X-Unifi-Console-Id"]


def test_missing_single_header_still_returns_401():
    app, _ = _make_app()
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "X-Unifi-Api-Key": "test-key",
                # X-Unifi-Console-Id intentionally omitted
            },
        )
        assert resp.status_code == 401


def test_header_present_reaches_request_context():
    # Directly exercises the middleware's contextvar plumbing without a full
    # MCP protocol round-trip: confirms the header values that arrive on the
    # request are exactly what get_client_from_context sees, and that they
    # are reset afterward (no leakage to the next request).
    import asyncio

    from unifi_network_mcp.server import GatewayTokenMiddleware, _gateway_creds_var

    settings = Settings()
    seen = {}

    async def fake_app(scope, receive, send):
        seen["creds"] = _gateway_creds_var.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = GatewayTokenMiddleware(fake_app, settings)

    async def run():
        scope = {
            "type": "http",
            "path": "/mcp",
            "headers": [
                (b"x-unifi-api-key", b"test-key-123"),
                (b"x-unifi-console-id", b"console-abc"),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            pass

        await middleware(scope, receive, send)

    asyncio.run(run())
    assert seen["creds"] == ("test-key-123", "console-abc")
    # After the request completes, the contextvar must be reset — a fresh
    # get() outside any request context sees no leftover credential.
    assert _gateway_creds_var.get() is None


def test_client_factory_returns_none_without_context():
    settings = Settings()
    assert get_client_from_context(settings) is None


@pytest.mark.asyncio
async def test_concurrent_requests_cannot_see_each_others_console_devices():
    """TC-UNF-108 / AC6 (PRD-21266): two concurrent requests presenting two
    different X-Unifi-Api-Key / X-Unifi-Console-Id header pairs must never
    mix devices, exercised through the real middleware -> contextvar ->
    UniFiClient-per-request path every tool goes through (api_client.py's
    console_id is baked into the client's base_url at construction,
    api_client.py:105-107) -- not asserted from documentation. Mirrors
    test_header_present_reaches_request_context's directness, but runs two
    requests through asyncio.gather so the contextvar copy-per-Task
    behaviour this module's docstring claims is actually exercised, not
    just stated.
    """
    import unifi_network_mcp.api_client as api_client_mod
    from unifi_network_mcp.server import GatewayTokenMiddleware
    from unifi_network_mcp.tools import alerts
    from mcp.server.fastmcp import FastMCP

    settings = Settings()
    mcp = FastMCP(name="test")
    alerts.register(mcp, lambda: get_client_from_context(settings))

    async def fake_get(self, path, params=None):
        # Yield control so the two concurrent calls below actually
        # interleave instead of running start-to-finish back to back.
        await asyncio.sleep(0)
        console_id = self._base_url.rsplit("/consoles/", 1)[1].split("/", 1)[0]
        device_id = f"device-of-{console_id}"
        return {
            "data": [
                {
                    "id": device_id,
                    "name": device_id,
                    "model": "M",
                    "macAddress": device_id,
                    "state": "OFFLINE",
                    "firmwareUpdatable": False,
                }
            ],
            "count": 1,
            "limit": 200,
            "offset": 0,
            "totalCount": 1,
        }

    original_get = api_client_mod.UniFiClient.get
    api_client_mod.UniFiClient.get = fake_get
    results: dict[str, str] = {}
    try:

        async def call_as(console_id: str, api_key: str) -> None:
            async def app(scope, receive, send):
                tool_result = await mcp.call_tool("unifi_list_device_issues", {"site_id": "s1"})
                text = (
                    tool_result[0][0].text
                    if isinstance(tool_result, tuple)
                    else str(tool_result)
                )
                results[console_id] = text

            middleware = GatewayTokenMiddleware(app, settings)
            scope = {
                "type": "http",
                "path": "/mcp",
                "headers": [
                    (b"x-unifi-api-key", api_key.encode()),
                    (b"x-unifi-console-id", console_id.encode()),
                ],
            }

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                pass

            await middleware(scope, receive, send)

        await asyncio.gather(
            call_as("console-a", "key-a"),
            call_as("console-b", "key-b"),
        )

        body_a = json.loads(results["console-a"])
        body_b = json.loads(results["console-b"])
        ids_a = {issue["device_id"] for issue in body_a["issues"]}
        ids_b = {issue["device_id"] for issue in body_b["issues"]}
        assert ids_a == {"device-of-console-a"}
        assert ids_b == {"device-of-console-b"}
        assert ids_a.isdisjoint(ids_b)
    finally:
        api_client_mod.UniFiClient.get = original_get
