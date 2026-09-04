import contextvars
from collections.abc import Callable
from typing import NamedTuple

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import UniFiClient
from .config import Settings


class _GatewayCreds(NamedTuple):
    api_key: str
    console_id: str


# Per-request credential isolation via contextvars.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent SSE connections are isolated.
# UniFi's Network Integration API has no shared/brokerable auth layer to
# delegate to a gateway — the customer's own Site Manager API key *is* the
# credential, sent straight through as the X-API-Key header on every
# request (see api_client.UniFiClient). This server never caches it beyond
# one request.
_gateway_creds_var: contextvars.ContextVar[_GatewayCreds | None] = contextvars.ContextVar(
    "unifi_gateway_creds", default=None
)


def get_client_from_context(settings: Settings) -> UniFiClient | None:
    """Resolve the active UniFiClient for the current request context."""
    creds = _gateway_creds_var.get()
    if not creds:
        return None
    return UniFiClient(creds.api_key, creds.console_id)


_REQUIRED_HEADERS = ["X-Unifi-Api-Key", "X-Unifi-Console-Id"]
_REQUIRED_HEADERS_MESSAGE = (
    "This server requires the X-Unifi-Api-Key header (a SITE MANAGER API "
    "key from unifi.ui.com, not a local console key) and the "
    "X-Unifi-Console-Id header (the target console's host ID — find it via "
    "unifi_list_hosts)."
)


class GatewayTokenMiddleware:
    """ASGI middleware.

    Reads X-Unifi-Api-Key and X-Unifi-Console-Id (both required) from
    request headers and stores them in the contextvar. Returns 401 if
    either is missing on /mcp requests.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        api_key = request.headers.get("x-unifi-api-key")
        console_id = request.headers.get("x-unifi-console-id")

        if not api_key or not console_id:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": _REQUIRED_HEADERS_MESSAGE,
                    "required_headers": _REQUIRED_HEADERS,
                    "optional_headers": [],
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        ctx_token = _gateway_creds_var.set(_GatewayCreds(api_key, console_id))
        try:
            await self.app(scope, receive, send)
        finally:
            _gateway_creds_var.reset(ctx_token)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all UniFi Network tools."""
    # DNS-rebinding protection is a browser-oriented safeguard that rejects
    # non-localhost Host headers with 421. Disable it so the server works
    # correctly behind a reverse proxy or docker network.
    mcp = FastMCP(
        name="unifi-network-mcp",
        instructions=(
            "UniFi Network is Ubiquiti's network management platform "
            "(routers, switches, Wi-Fi APs). This server reaches a "
            "customer's console through Ubiquiti's own cloud (api.ui.com), "
            "which proxies to the console without needing any customer "
            "network exposure — this is the only supported path, and the "
            "only way to reach Official UniFi Hosting (Ubiquiti's own SaaS "
            "offering), which has no customer-reachable address at all. "
            "unifi_list_hosts finds a console_id. Typical flow: "
            "unifi_list_hosts to find a console_id; unifi_list_sites to "
            "find a site_id; unifi_list_devices or unifi_list_clients to "
            "find a device_id/client_id; unifi_get_device / "
            "unifi_get_device_statistics for detail; unifi_restart_device to "
            "reboot a device right now (destructive, irreversible — requires "
            "confirm=true). This covers Network only, not Protect (cameras) "
            "or Access (door control) — those are separate controllers with "
            "their own APIs, not wrapped by this server."
        ),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
        json_response=True,
    )

    client_factory: Callable[[], UniFiClient | None] = lambda: get_client_from_context(settings)

    from .tools import clients, devices, hosts, sites

    hosts.register(mcp, client_factory)
    sites.register(mcp, client_factory)
    devices.register(mcp, client_factory)
    clients.register(mcp, client_factory)

    return mcp
