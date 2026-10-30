"""tools/list snapshot + error-envelope mapping tests.

No network calls: tool enumeration goes through FastMCP's in-process
list_tools(), and the error-code mapping is tested directly against
UniFiError, independent of any real HTTP request.
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from unifi_network_mcp.api_client import UniFiClient, UniFiError
from unifi_network_mcp.config import Settings
from unifi_network_mcp.server import create_mcp_server

# name -> (required params, expected annotation hint set to True)
EXPECTED_TOOLS = {
    "unifi_list_hosts": (set(), {"readOnlyHint"}),
    "unifi_list_sites": (set(), {"readOnlyHint"}),
    "unifi_list_devices": ({"site_id"}, {"readOnlyHint"}),
    "unifi_get_device": ({"site_id", "device_id"}, {"readOnlyHint"}),
    "unifi_get_device_statistics": ({"site_id", "device_id"}, {"readOnlyHint"}),
    "unifi_restart_device": ({"site_id", "device_id"}, {"destructiveHint"}),
    "unifi_list_clients": ({"site_id"}, {"readOnlyHint"}),
    "unifi_get_client": ({"site_id", "client_id"}, {"readOnlyHint"}),
    "unifi_list_device_issues": ({"site_id"}, {"readOnlyHint"}),
}


@pytest.mark.asyncio
async def test_tools_list_snapshot():
    mcp = create_mcp_server(Settings())
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == set(EXPECTED_TOOLS), f"unexpected tool set: {names}"

    by_name = {t.name: t for t in tools}
    for name, (expected_required, expected_hints) in EXPECTED_TOOLS.items():
        tool = by_name[name]
        required = set(tool.inputSchema.get("required", []))
        assert required == expected_required, f"{name}: required={required}"

        description = tool.description or ""
        assert len(description) <= 500, f"{name}: description too long ({len(description)})"
        first_line = description.strip().splitlines()[0] if description.strip() else ""
        assert len(first_line) <= 100, f"{name}: first line too long: {first_line!r}"
        assert "GET /" not in description and "POST /" not in description, (
            f"{name}: leaked implementation detail"
        )

        annotations = tool.annotations
        actual_hints = set()
        if annotations is not None:
            for hint in ("readOnlyHint", "destructiveHint", "idempotentHint"):
                if getattr(annotations, hint, None) is True:
                    actual_hints.add(hint)
        assert actual_hints == expected_hints, f"{name}: hints={actual_hints}"


@pytest.mark.asyncio
async def test_service_instructions_present_and_bounded():
    mcp = create_mcp_server(Settings())
    assert mcp.instructions
    assert len(mcp.instructions) <= 1500


@pytest.mark.parametrize(
    "status_code,expected_code,expected_retryable",
    [
        (0, "upstream_error", True),
        (400, "invalid_argument", False),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (503, "upstream_error", True),
    ],
)
def test_error_envelope_mapping(status_code, expected_code, expected_retryable):
    err = UniFiError(status_code, "boom")
    envelope = json.loads(err.to_envelope())
    assert envelope["error"]["code"] == expected_code
    assert envelope["error"]["retryable"] is expected_retryable
    assert envelope["error"]["message"] == "boom"


def test_client_connector_base_url():
    client = UniFiClient("test-key", "console-abc")
    assert client._base_url == (
        "https://api.ui.com/v1/connector/consoles/console-abc/network/integration"
    )


@pytest.mark.asyncio
async def test_restart_device_rejects_without_confirm_before_calling_api():
    captured = {}

    class _StubClient:
        async def post(self, path, json_body=None):
            captured["called"] = path
            return {"should": "not happen"}

    from unifi_network_mcp.tools import devices

    mcp = FastMCP(name="test")
    devices.register(mcp, lambda: _StubClient())
    result = await mcp.call_tool(
        "unifi_restart_device",
        {"site_id": "s1", "device_id": "d1", "confirm": False},
    )
    text = result[0][0].text if isinstance(result, tuple) else str(result)
    assert "invalid_argument" in text
    assert "called" not in captured, "must reject before ever calling the API"


@pytest.mark.asyncio
async def test_no_credentials_returns_not_configured_without_calling_api():
    from unifi_network_mcp.tools import sites

    mcp = FastMCP(name="test")
    sites.register(mcp, lambda: None)
    result = await mcp.call_tool("unifi_list_sites", {})
    text = result[0][0].text if isinstance(result, tuple) else str(result)
    assert "not_configured" in text


# --- unifi_list_device_issues (PRD-21266) ----------------------------------
#
# Field names (id, name, model, macAddress, state, firmwareUpdatable) and
# the list envelope (data/count/limit/offset/totalCount) are taken from the
# official "Adopted device overview [page]" schema in
# developer.ui.com/network/v11.0.97/openapi.json (fetched 2026-10-30), the
# same endpoint unifi_list_devices already calls.


def _device(device_id, state="ONLINE", firmware_updatable=False):
    return {
        "id": device_id,
        "name": device_id,
        "model": "M",
        "macAddress": device_id,
        "state": state,
        "firmwareUpdatable": firmware_updatable,
    }


class _PagedDeviceClient:
    """Stub for UniFiClient.get against /v1/sites/{id}/devices: paginates
    a fixed in-memory device list the same way the real upstream endpoint
    paginates (offset/limit in, data/totalCount out)."""

    def __init__(self, devices):
        self._devices = devices
        self.calls: list[dict] = []

    async def get(self, path, params=None):
        params = params or {}
        self.calls.append(dict(params))
        offset = params.get("offset") or 0
        limit = params.get("limit") or 25
        page = self._devices[offset : offset + limit]
        return {
            "data": page,
            "count": len(page),
            "limit": limit,
            "offset": offset,
            "totalCount": len(self._devices),
        }


async def _call_device_issues(client, **kwargs):
    from unifi_network_mcp.tools import alerts

    mcp = FastMCP(name="test")
    alerts.register(mcp, lambda: client)
    result = await mcp.call_tool("unifi_list_device_issues", {"site_id": "s1", **kwargs})
    text = result[0][0].text if isinstance(result, tuple) else str(result)
    return json.loads(text)


@pytest.mark.asyncio
async def test_device_issues_filters_and_tags_non_online_devices():
    """TC-UNF-101 / AC1."""
    devices = [
        _device("d-online", state="ONLINE"),
        _device("d-offline", state="OFFLINE"),
        _device("d-updating", state="UPDATING"),
    ]
    body = await _call_device_issues(_PagedDeviceClient(devices))
    by_id = {i["device_id"]: i for i in body["issues"]}
    assert set(by_id) == {"d-offline", "d-updating"}
    assert by_id["d-offline"]["issue_types"] == ["offline"]
    assert by_id["d-updating"]["issue_types"] == ["transitioning"]


@pytest.mark.asyncio
async def test_device_issues_tags_offline_and_firmware_together():
    """TC-UNF-102 / AC1."""
    devices = [_device("d1", state="OFFLINE", firmware_updatable=True)]
    body = await _call_device_issues(_PagedDeviceClient(devices))
    assert body["issues"][0]["issue_types"] == ["offline", "firmware_update_available"]


@pytest.mark.asyncio
async def test_device_issues_empty_list_when_all_devices_healthy():
    """TC-UNF-103 / AC2."""
    devices = [_device("d1"), _device("d2")]
    body = await _call_device_issues(_PagedDeviceClient(devices))
    assert body["issues"] == []
    assert body["scanned"] == 2
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_device_issues_unknown_site_returns_structured_error():
    """TC-UNF-104 / AC3: same error envelope as unifi_list_devices, not a
    raw exception."""

    class _FailingClient:
        async def get(self, path, params=None):
            raise UniFiError(404, "site not found")

    body = await _call_device_issues(_FailingClient())
    assert body["error"]["code"] == "not_found"
    assert body["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_device_issues_no_credentials_returns_not_configured():
    """TC-UNF-105 / AC4: same NO_TOKEN envelope every other tool returns."""
    from unifi_network_mcp.tools import alerts

    mcp = FastMCP(name="test")
    alerts.register(mcp, lambda: None)
    result = await mcp.call_tool("unifi_list_device_issues", {"site_id": "s1"})
    text = result[0][0].text if isinstance(result, tuple) else str(result)
    assert "not_configured" in text


@pytest.mark.asyncio
async def test_device_issues_scans_past_first_page_without_truncating():
    """TC-UNF-106 / AC5: 260 devices, default max_devices -- both pages
    must be scanned and nothing reported as truncated."""
    devices = [_device(f"d{i}") for i in range(260)]
    client = _PagedDeviceClient(devices)
    body = await _call_device_issues(client)
    assert body["scanned"] == 260
    assert body["total_count"] == 260
    assert body["truncated"] is False
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_device_issues_stops_at_max_devices_and_reports_truncated():
    """TC-UNF-107 / AC5: 900 devices, max_devices=500 -- stop at the cap,
    report truncated=true, never error or hang."""
    devices = [_device(f"d{i}") for i in range(900)]
    client = _PagedDeviceClient(devices)
    body = await _call_device_issues(client, max_devices=500)
    assert body["scanned"] == 500
    assert body["truncated"] is True
    assert len(client.calls) == 3
