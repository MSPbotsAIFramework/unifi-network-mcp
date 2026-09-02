"""Site discovery — read only.

GET /v1/sites, per the official OpenAPI spec (UniFi Network API
v10.0.162). Not yet exercised against a real live controller — see README
Known Gaps.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .._json import dump_json_capped
from ..api_client import UniFiClient, UniFiError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], UniFiClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def unifi_list_sites() -> str:
        """List the sites this controller manages.

        A "site" is a logical grouping of devices/clients (usually one
        physical location). Almost every other tool here needs a site_id —
        call this first if you don't already have one.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get("/v1/sites")
            return dump_json_capped(result)
        except UniFiError as e:
            return e.to_envelope()
