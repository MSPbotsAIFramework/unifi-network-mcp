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
    host: str | None
    console_id: str | None
    verify_ssl: bool


# Per-request credential isolation via contextvars.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent SSE connections are isolated.
# UniFi's Network Integration API has no shared/brokerable auth layer to
# delegate to a gateway — the customer's own API key *is* the credential,
# sent straight through as the X-API-Key header on every request (see
# api_client.UniFiClient). This server never caches it beyond one request.
_gateway_creds_var: contextvars.ContextVar[_GatewayCreds | None] = contextvars.ContextVar(
    "unifi_gateway_creds", default=None
)


def get_client_from_context(settings: Settings) -> UniFiClient | None:
    """Resolve the active UniFiClient for the current request context."""
    creds = _gateway_creds_var.get()
    if not creds:
        return None
    return UniFiClient(
        creds.api_key, host=creds.host, console_id=creds.console_id, verify_ssl=creds.verify_ssl
    )


_REQUIRED_HEADERS_MESSAGE = (
    "This server requires the X-Unifi-Api-Key header, plus exactly one of: "
    "X-Unifi-Host (direct mode — a self-hosted console the gateway can "
    "reach directly; the API key must be a LOCAL key generated on that "
    "console) or X-Unifi-Console-Id (connector mode — for a console with no "
    "customer-reachable address, including Official UniFi Hosting/SaaS; the "
    "API key must be a SITE MANAGER key from unifi.ui.com, and the console "
    "ID comes from unifi_list_hosts)."
)


class GatewayTokenMiddleware:
    """ASGI middleware.

    Reads X-Unifi-Api-Key (always required) plus exactly one of
    X-Unifi-Host (direct mode) or X-Unifi-Console-Id (connector mode/SaaS),
    plus the optional X-Unifi-Verify-Ssl (direct mode only), and stores
    them in the contextvar. Returns 401 if the api key is missing, or if
    neither/both of host and console-id are given — there is no sensible
    default to fall back to, since each customer's console (or Site
    Manager account) is a distinct credential.
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
        host = request.headers.get("x-unifi-host") or None
        console_id = request.headers.get("x-unifi-console-id") or None

        if not api_key or bool(host) == bool(console_id):
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": _REQUIRED_HEADERS_MESSAGE,
                    "required_headers": ["X-Unifi-Api-Key"],
                    "required_headers_pick_one": ["X-Unifi-Host", "X-Unifi-Console-Id"],
                    "optional_headers": ["X-Unifi-Verify-Ssl"],
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        verify_ssl_header = (request.headers.get("x-unifi-verify-ssl") or "").strip().lower()
        verify_ssl = verify_ssl_header != "false"

        ctx_token = _gateway_creds_var.set(
            _GatewayCreds(api_key, host, console_id, verify_ssl)
        )
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
            "(routers, switches, Wi-Fi APs) — each customer has their own "
            "console, there is no shared cloud instance of the data itself. "
            "This server reaches a console one of two ways depending on how "
            "the gateway credential was configured: DIRECT mode calls a "
            "self-hosted console's own local API — only works if the "
            "customer has deliberately exposed it to the internet, since it "
            "normally sits behind NAT. CONNECTOR mode calls Ubiquiti's own "
            "cloud (api.ui.com), which proxies to the console without any "
            "customer exposure — the only option for Official UniFi Hosting "
            "(Ubiquiti's own SaaS offering), which has no customer-reachable "
            "address at all. unifi_list_hosts (connector mode only) finds a "
            "console_id. Typical flow: unifi_list_sites to find a site_id; "
            "unifi_list_devices or unifi_list_clients to find a "
            "device_id/client_id; unifi_get_device / "
            "unifi_get_device_statistics for detail; unifi_restart_device to "
            "reboot a device right now (destructive, irreversible — requires "
            "confirm=true). This covers Network only, not Protect (cameras) "
            "or Access (door control) — those are separate controllers with "
            "their own APIs, not wrapped by this server."
        ),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    client_factory: Callable[[], UniFiClient | None] = lambda: get_client_from_context(settings)

    from .tools import clients, devices, hosts, sites

    hosts.register(mcp, client_factory)
    sites.register(mcp, client_factory)
    devices.register(mcp, client_factory)
    clients.register(mcp, client_factory)

    return mcp
