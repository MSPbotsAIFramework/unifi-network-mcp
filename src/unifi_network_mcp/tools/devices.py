"""Device inventory + restart, per the official Network Integration API.

Endpoints (all from the official OpenAPI spec, UniFi Network API
v10.0.162):
  GET  /v1/sites/{siteId}/devices
  GET  /v1/sites/{siteId}/devices/{deviceId}
  GET  /v1/sites/{siteId}/devices/{deviceId}/statistics/latest
  POST /v1/sites/{siteId}/devices/{deviceId}/actions  {"action": "RESTART"}

None of these have been exercised against a real live controller — see
README Known Gaps. The RESTART action body shape is exactly what the spec
documents (a discriminated union on "action", with "RESTART" the only
mapped variant at this spec version).
"""

from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import UniFiClient, UniFiError
from ._common import NO_TOKEN

_SITE_ID_DESC = "Site UUID, from unifi_list_sites."
_DEVICE_ID_DESC = "Device UUID, from unifi_list_devices."
_FILTER_DESC = (
    "Optional server-side filter expression on this resource's filterable "
    "properties (e.g. macAddress, name, model, state, firmwareVersion). "
    "The exact expression grammar is documented by the API but hasn't been "
    "exercised here — if you don't already have a working filter string, "
    "omit this and filter the returned list yourself instead of guessing "
    "one."
)


def register(mcp: FastMCP, client_factory: Callable[[], UniFiClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def unifi_list_devices(
        site_id: Annotated[str, Field(description=_SITE_ID_DESC)],
        offset: Annotated[
            int | None, Field(description="0-based offset for paging. Omit for 0.")
        ] = None,
        limit: Annotated[
            int | None, Field(description="Page size, 1-200. Omit for the API default (25).")
        ] = None,
        filter_expr: Annotated[str | None, Field(description=_FILTER_DESC)] = None,
    ) -> str:
        """List the devices (APs, switches, gateways) on one site.

        Use to find a device_id by name/model/MAC before calling
        unifi_get_device, unifi_get_device_statistics, or
        unifi_restart_device.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(
                f"/v1/sites/{site_id}/devices",
                params={"offset": offset, "limit": limit, "filter": filter_expr},
            )
            return dump_json_capped(result)
        except UniFiError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def unifi_get_device(
        site_id: Annotated[str, Field(description=_SITE_ID_DESC)],
        device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    ) -> str:
        """Get full details for one device by its UUID."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/v1/sites/{site_id}/devices/{device_id}")
            return dump_json_capped(result)
        except UniFiError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def unifi_get_device_statistics(
        site_id: Annotated[str, Field(description=_SITE_ID_DESC)],
        device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    ) -> str:
        """Get the latest performance statistics for one device.

        E.g. CPU/memory load, uptime, client count — exact fields are
        whatever the controller currently reports.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/v1/sites/{site_id}/devices/{device_id}/statistics/latest")
            return dump_json_capped(result)
        except UniFiError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def unifi_restart_device(
        site_id: Annotated[str, Field(description=_SITE_ID_DESC)],
        device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
        confirm: Annotated[
            bool,
            Field(
                description=(
                    "Required — must be explicitly true to proceed. This tool "
                    "refuses to call the API otherwise."
                )
            ),
        ] = False,
    ) -> str:
        """Reboot a device (AP, switch, or gateway) right now.

        ⚠️ DESTRUCTIVE, IRREVERSIBLE. Drops every client connected through
        this device and takes it offline for the duration of its reboot
        (typically well under a minute for APs, longer for gateways/
        routers, during which everything behind it also loses connectivity).
        Only set confirm=true on an explicit, unambiguous instruction naming
        the specific device — never on vague intent ("fix the wifi").
        """
        if not confirm:
            return error_envelope(
                "invalid_argument", "Destructive operation requires confirm=true", False
            )
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.post(
                f"/v1/sites/{site_id}/devices/{device_id}/actions",
                json_body={"action": "RESTART"},
            )
            return dump_json_capped(result)
        except UniFiError as e:
            return e.to_envelope()
