"""Site Manager host discovery — read only.

GET https://api.ui.com/v1/hosts, per Ubiquiti's own Site Manager OpenAPI
spec (developer.ui.com/site-manager/v1.0.0/openapi.json). Not yet exercised
against a real live account — see README Known Gaps.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .._json import dump_json_capped
from ..api_client import UniFiClient, UniFiError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], UniFiClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def unifi_list_hosts() -> str:
        """List the consoles (hosts) this Site Manager account can see.

        Use this to find the console_id for X-Unifi-Console-Id, e.g. for
        an Official UniFi Hosting (SaaS) console.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.list_hosts()
            return dump_json_capped(result)
        except UniFiError as e:
            return e.to_envelope()
