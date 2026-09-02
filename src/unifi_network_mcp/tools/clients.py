"""Client (connected-device) inventory — read only.

Endpoints (from the official OpenAPI spec, UniFi Network API v10.0.162):
  GET /v1/sites/{siteId}/clients
  GET /v1/sites/{siteId}/clients/{clientId}

Not yet exercised against a real live controller — see README Known Gaps.
"""

from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import UniFiClient, UniFiError
from ._common import NO_TOKEN

_SITE_ID_DESC = "Site UUID, from unifi_list_sites."
_FILTER_DESC = (
    "Optional server-side filter expression on this resource's filterable "
    "properties (e.g. macAddress, ipAddress, model, state). The exact "
    "expression grammar is documented by the API but hasn't been exercised "
    "here — if you don't already have a working filter string, omit this "
    "and filter the returned list yourself instead of guessing one."
)


def register(mcp: FastMCP, client_factory: Callable[[], UniFiClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def unifi_list_clients(
        site_id: Annotated[str, Field(description=_SITE_ID_DESC)],
        offset: Annotated[
            int | None, Field(description="0-based offset for paging. Omit for 0.")
        ] = None,
        limit: Annotated[
            int | None, Field(description="Page size, 1-200. Omit for the API default (25).")
        ] = None,
        filter_expr: Annotated[str | None, Field(description=_FILTER_DESC)] = None,
    ) -> str:
        """List clients connected (or recently connected) to one site's network.

        A "client" is an end-user device — phone, laptop, IoT gadget — not
        a device we manage; see unifi_list_devices for the APs/switches/
        gateways themselves.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(
                f"/v1/sites/{site_id}/clients",
                params={"offset": offset, "limit": limit, "filter": filter_expr},
            )
            return dump_json_capped(result)
        except UniFiError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def unifi_get_client(
        site_id: Annotated[str, Field(description=_SITE_ID_DESC)],
        client_id: Annotated[str, Field(description="Client UUID, from unifi_list_clients.")],
    ) -> str:
        """Get full details for one connected client by its UUID."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/v1/sites/{site_id}/clients/{client_id}")
            return dump_json_capped(result)
        except UniFiError as e:
            return e.to_envelope()
