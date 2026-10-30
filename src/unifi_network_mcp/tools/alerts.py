"""Derived device-health view over the existing device-list endpoint.

Neither of Ubiquiti's two official, publicly documented REST APIs (UniFi
Site Manager API v1.0.0, UniFi Network Integration API v11.0.97) exposes an
alert/alarm resource at all (confirmed: zero occurrences of "alert"/"alarm"
in either spec's openapi.json, fetched 2026-10-30). This tool derives a
"what's currently wrong" signal from fields the device-list endpoint
already returns and documents -- `state` and `firmwareUpdatable` on each
`Adopted device overview` (see devices.py, which calls the same endpoint)
-- instead of inventing a nonexistent endpoint. Full investigation and
rejected alternatives: docs/tickets/PRD-21266.md.
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
_MAX_DEVICES_DESC = (
    "Internal cap on how many devices to scan before stopping (default "
    "500, i.e. up to 3 upstream pages at 200/page). This is not forwarded "
    "upstream verbatim -- this tool pages through the device list itself "
    "and reports truncated=true if the cap was hit before the whole site "
    "was scanned."
)

# Upstream page size max per the official spec (devices.py docstring).
_UPSTREAM_PAGE_SIZE = 200
_DEFAULT_MAX_DEVICES = 500

# `state` values per the official "Adopted device overview" schema.
_OFFLINE_STATES = {"OFFLINE", "CONNECTION_INTERRUPTED", "ISOLATED"}
_TRANSITIONING_STATES = {"PENDING_ADOPTION", "UPDATING", "GETTING_READY", "ADOPTING", "DELETING"}
_TOPOLOGY_WARNING_STATES = {"U5G_INCORRECT_TOPOLOGY"}


def _issue_types(device: dict) -> list[str]:
    state = device.get("state")
    types: list[str] = []
    if state in _OFFLINE_STATES:
        types.append("offline")
    if state in _TRANSITIONING_STATES:
        types.append("transitioning")
    if state in _TOPOLOGY_WARNING_STATES:
        types.append("topology_warning")
    if device.get("firmwareUpdatable"):
        types.append("firmware_update_available")
    return types


def register(mcp: FastMCP, client_factory: Callable[[], UniFiClient | None]) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def unifi_list_device_issues(
        site_id: Annotated[str, Field(description=_SITE_ID_DESC)],
        max_devices: Annotated[int | None, Field(description=_MAX_DEVICES_DESC)] = None,
    ) -> str:
        """List devices on a site that are not simply online and up to date.

        There is no alert/alarm endpoint in Ubiquiti's official API (see
        README Known Gaps) -- this derives "issues" from the same
        state/firmware fields unifi_list_devices already returns. Use
        unifi_list_devices for the full inventory; use this when you just
        want "what's currently wrong" on a site.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN

        cap = max_devices if max_devices is not None else _DEFAULT_MAX_DEVICES
        issues: list[dict] = []
        scanned = 0
        total_count = 0
        offset = 0

        try:
            while scanned < cap:
                page_limit = min(_UPSTREAM_PAGE_SIZE, cap - scanned)
                result = await client.get(
                    f"/v1/sites/{site_id}/devices",
                    params={"offset": offset, "limit": page_limit},
                )
                data = result.get("data", [])
                total_count = result.get("totalCount", len(data))

                for device in data:
                    issue_types = _issue_types(device)
                    if issue_types:
                        issues.append(
                            {
                                "device_id": device.get("id"),
                                "name": device.get("name"),
                                "model": device.get("model"),
                                "mac": device.get("macAddress"),
                                "state": device.get("state"),
                                "firmware_updatable": device.get("firmwareUpdatable", False),
                                "issue_types": issue_types,
                            }
                        )

                scanned += len(data)
                offset += len(data)

                if not data or scanned >= total_count:
                    break

            return dump_json_capped(
                {
                    "site_id": site_id,
                    "issues": issues,
                    "scanned": scanned,
                    "total_count": total_count,
                    "truncated": scanned < total_count,
                }
            )
        except UniFiError as e:
            return e.to_envelope()
