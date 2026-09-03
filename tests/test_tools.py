"""tools/list snapshot + error-envelope mapping tests.

No network calls: tool enumeration goes through FastMCP's in-process
list_tools(), and the error-code mapping is tested directly against
UniFiError, independent of any real HTTP request.
"""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from unifi_network_mcp.api_client import UniFiClient, UniFiError, _normalize_base_url
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


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("203.0.113.5", "https://203.0.113.5"),
        ("203.0.113.5:8443", "https://203.0.113.5:8443"),
        ("https://unifi.example.com", "https://unifi.example.com"),
        ("https://unifi.example.com/", "https://unifi.example.com"),
        ("http://203.0.113.5:8443", "http://203.0.113.5:8443"),
    ],
)
def test_normalize_base_url_handles_bare_host_and_full_url(raw, expected):
    assert _normalize_base_url(raw) == expected


def test_client_direct_mode_base_url():
    client = UniFiClient("test-key", host="203.0.113.5")
    assert client._base_url == "https://203.0.113.5/proxy/network/integration"
    assert client._verify_ssl is True


def test_client_connector_mode_base_url_ignores_verify_ssl_false():
    client = UniFiClient("test-key", console_id="console-abc", verify_ssl=False)
    assert client._base_url == (
        "https://api.ui.com/v1/connector/consoles/console-abc/network/integration"
    )
    # api.ui.com always has a real cert — connector mode never honors a
    # request to skip verification, regardless of what direct mode allows.
    assert client._verify_ssl is True


@pytest.mark.parametrize("kwargs", [{}, {"host": "a", "console_id": "b"}])
def test_client_requires_exactly_one_of_host_or_console_id(kwargs):
    with pytest.raises(ValueError):
        UniFiClient("test-key", **kwargs)


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
