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
    host: str
    api_key: str
    verify_ssl: bool


# Per-request credential isolation via contextvars.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent SSE connections are isolated.
# UniFi's Network Integration API has no shared/brokerable auth layer to
# delegate to a gateway — the customer's own local API key *is* the
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
    return UniFiClient(creds.host, creds.api_key, creds.verify_ssl)


class GatewayTokenMiddleware:
    """ASGI middleware.

    Reads X-Unifi-Host and X-Unifi-Api-Key (both required) plus the
    optional X-Unifi-Verify-Ssl from request headers and stores them in the
    contextvar. X-Unifi-Host is the customer's own self-hosted controller
    address — there is no shared/cloud default, unlike a multi-tenant SaaS
    vendor, because each customer runs their own controller. Returns 401 if
    either required header is missing on /mcp requests.
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
        host = request.headers.get("x-unifi-host")
        api_key = request.headers.get("x-unifi-api-key")
        if not host or not api_key:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": (
                        "This server requires the X-Unifi-Host header (the "
                        "customer's own controller address) and the "
                        "X-Unifi-Api-Key header (a local API key generated on "
                        "that controller)."
                    ),
                    "required_headers": ["X-Unifi-Host", "X-Unifi-Api-Key"],
                    "optional_headers": ["X-Unifi-Verify-Ssl"],
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        verify_ssl_header = (request.headers.get("x-unifi-verify-ssl") or "").strip().lower()
        verify_ssl = verify_ssl_header != "false"

        ctx_token = _gateway_creds_var.set(_GatewayCreds(host, api_key, verify_ssl))
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
            "UniFi Network is Ubiquiti's self-hosted network management "
            "platform (routers, switches, Wi-Fi APs) — each customer runs "
            "their own controller, there is no shared cloud instance. This "
            "server talks directly to that controller's own local API, so "
            "it only works if the controller is reachable from wherever "
            "this server runs — for most MSP customers that controller "
            "sits behind NAT and is NOT reachable unless the customer has "
            "deliberately exposed it to the internet. Typical flow: "
            "unifi_list_sites to find a site_id; unifi_list_devices or "
            "unifi_list_clients to find a device_id/client_id; "
            "unifi_get_device / unifi_get_device_statistics for detail; "
            "unifi_restart_device to reboot a device right now (destructive, "
            "irreversible — requires confirm=true). This covers Network "
            "only, not Protect (cameras) or Access (door control) — those "
            "are separate controllers with their own local APIs, not "
            "wrapped by this server."
        ),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    client_factory: Callable[[], UniFiClient | None] = lambda: get_client_from_context(settings)

    from .tools import clients, devices, sites

    sites.register(mcp, client_factory)
    devices.register(mcp, client_factory)
    clients.register(mcp, client_factory)

    return mcp
