"""Client for Ubiquiti's official, local Network Integration API.

Endpoint shapes and the ``X-API-Key`` header are taken from the official
OpenAPI spec (UniFi Network API v10.0.162, mirrored at
github.com/opastorello/unifi-api-docs) and cross-checked against a real
third-party MCP's working implementation (github.com/sirkirby/unifi-mcp,
packages/unifi-core/src/unifi_core/auth.py — same ``X-API-Key`` header,
same ``/proxy/network/integration`` path prefix). This has NOT been
exercised against a real live controller — see README Known Gaps.
"""

import asyncio
from typing import Any

import httpx

from ._json import error_envelope

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 20.0

_INTEGRATION_PATH_PREFIX = "/proxy/network/integration"

# Two shared connection pools for the process lifetime, keyed by the only
# per-tenant setting that must be baked into an httpx.Client at construction
# time (verify=). No credentials are ever stored on either — the API key and
# host are passed per-request (see server.py's contextvar-based credential
# isolation), so sharing each pool across tenants/requests is safe: it holds
# only TCP connections, never a request's auth material.
_http_clients: dict[bool, httpx.AsyncClient] = {}


def _get_http_client(verify_ssl: bool) -> httpx.AsyncClient:
    client = _http_clients.get(verify_ssl)
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, verify=verify_ssl)
        _http_clients[verify_ssl] = client
    return client


# status_code -> (error code, retryable). status_code 0 means a network/
# connection-level failure (no response at all) — the common case here,
# since this server dials a customer-controlled, internet-exposed endpoint
# that may simply be unreachable or mid-reboot.
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def _classify(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    return "invalid_argument", False


class UniFiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"UniFi Network API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = _classify(self.status_code)
        return error_envelope(code, self.message, retryable)


def _normalize_base_url(host: str) -> str:
    """A customer-provided controller address. Accept a bare host/IP
    (optionally with a port) or a full URL, with or without a trailing
    slash — mirrors the same real-world inconsistency handled for other
    vendors in this fleet (e.g. datto-rmm-mcp's tenant_integration rows).
    """
    value = host.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value.rstrip("/")
    return f"https://{value.rstrip('/')}"


class UniFiClient:
    """Async httpx client wrapping Ubiquiti's local Network Integration API.

    Takes the customer's controller host and local API key directly — this
    API's auth is a single stateless header (``X-API-Key``), no token
    exchange or session/cookie login involved. Requires UniFi Network 9.x+
    on a UniFi OS console (the Integration API doesn't exist on older
    controllers or the legacy self-hosted Network Application).
    """

    def __init__(self, host: str, api_key: str, verify_ssl: bool = True):
        self._api_key = api_key
        self._base_url = _normalize_base_url(host) + _INTEGRATION_PATH_PREFIX
        self._verify_ssl = verify_ssl

    def _clean_params(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def get(self, path: str, params: dict | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json_body: Any = None) -> Any:
        return await self._request("POST", path, json_body=json_body)

    async def _request(
        self, method: str, path: str, params: dict | None = None, json_body: Any = None
    ) -> Any:
        client = _get_http_client(self._verify_ssl)
        url = f"{self._base_url}{path}"
        params = self._clean_params(params)

        headers = {"X-API-Key": self._api_key, "Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.request(
                    method, url, headers=headers, params=params, json=json_body
                )
            except httpx.RequestError as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, _MAX_BACKOFF_SECONDS))
                    continue
                raise UniFiError(0, f"{e or type(e).__name__} (url={url})") from e

            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                delay = self._retry_delay(resp, attempt)
                await asyncio.sleep(delay)
                continue

            self._raise_for_status(resp)
            return self._parse_body(resp)

        # Unreachable in practice (loop always returns or raises above), but
        # keeps type checkers happy and guards against future edits.
        if last_exc:
            raise UniFiError(0, f"{last_exc}") from last_exc
        raise UniFiError(0, "request failed with no response")

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        return min(2**attempt, _MAX_BACKOFF_SECONDS)

    def _extract_error(self, resp: httpx.Response) -> str:
        try:
            detail = resp.json()
            if isinstance(detail, dict):
                return (
                    detail.get("message")
                    or detail.get("detail")
                    or detail.get("error")
                    or str(detail)
                )
            return str(detail)
        except ValueError:
            return resp.text

    def _parse_body(self, resp: httpx.Response) -> Any:
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return {"raw_response": resp.text}

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise UniFiError(resp.status_code, self._extract_error(resp))
