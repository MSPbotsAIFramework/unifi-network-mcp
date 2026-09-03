"""Client for Ubiquiti's official Network Integration API, reached through
the **connector** path — this server calls Ubiquiti's own cloud
(``https://api.ui.com/v1/connector/consoles/{console_id}/...``), which
proxies the request to the console over Ubiquiti's own infrastructure. No
customer network exposure needed at all: works for ANY console adopted to
a UI.com account, including Official UniFi Hosting (OUH, Ubiquiti's own
SaaS offering), which has no customer-reachable address to give us in the
first place.

(Direct mode — calling a self-hosted console's own local API address —
was deliberately dropped: see README/CHANGELOG. Only the connector path is
supported for now.)

Endpoint shapes (base URL, path structure, auth header, the exact example
``GET /v1/connector/consoles/{id}/network/integration/v1/sites``,
per-console rate limit of 100 req/min, 25s request timeout, 10MB response
cap) are taken directly from Ubiquiti's own Site Manager OpenAPI spec
(``developer.ui.com/site-manager/v1.0.0/openapi.json``). The underlying
resource shapes (sites/devices/clients) are the same Network Integration
API described in the UniFi Network API v10.0.162 spec (mirrored at
github.com/opastorello/unifi-api-docs) — the connector is a transparent
proxy to that same API, per Ubiquiti's own description ("proxied through
api.ui.com... to the remote console at http://127.0.0.1/proxy/[path]").
Never exercised against a real live account — see README Known Gaps.
"""

import asyncio
from typing import Any

import httpx

from ._json import error_envelope

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 20.0

_CONNECTOR_BASE = "https://api.ui.com"
_SITE_MANAGER_HOSTS_URL = "https://api.ui.com/v1/hosts"

# One shared connection pool for the process lifetime. No credentials are
# ever stored on it — the API key is passed per-request (see server.py's
# contextvar-based credential isolation), so sharing it across
# tenants/requests is safe: it holds only TCP connections, never a
# request's auth material. api.ui.com is Ubiquiti's own cloud with a real
# CA-signed cert, so there is no per-tenant verify= setting to key on
# (unlike a direct-to-console connection would need).
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    return _http_client


# status_code -> (error code, retryable). status_code 0 means a network/
# connection-level failure (no response at all).
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


class UniFiClient:
    """Async httpx client wrapping Ubiquiti's Network Integration API via
    the connector (cloud proxy) path.

    Auth is a single stateless header (``X-API-Key``) — no token exchange
    or session/cookie login involved — but it must be a **Site Manager**
    API key generated at unifi.ui.com > Settings > API Keys, not a local
    console key (a local key has no meaning to api.ui.com and will 401).

    Requires console firmware >= 5.0.3 per Ubiquiti's own spec, and — for a
    non-organization Site Manager API key — only reaches consoles owned by
    that same UI.com account.
    """

    def __init__(self, api_key: str, console_id: str):
        self._api_key = api_key
        self._base_url = f"{_CONNECTOR_BASE}/v1/connector/consoles/{console_id}/network/integration"

    def _clean_params(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def get(self, path: str, params: dict | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json_body: Any = None) -> Any:
        return await self._request("POST", path, json_body=json_body)

    async def list_hosts(self) -> Any:
        """The Site Manager `GET /v1/hosts` call — always against
        api.ui.com regardless of which console this instance targets,
        since discovering a console's host ID is itself a Site-Manager-key
        operation independent of any one console.
        """
        return await self._request_absolute("GET", _SITE_MANAGER_HOSTS_URL)

    async def _request(
        self, method: str, path: str, params: dict | None = None, json_body: Any = None
    ) -> Any:
        url = f"{self._base_url}{path}"
        return await self._request_absolute(method, url, params=params, json_body=json_body)

    async def _request_absolute(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        json_body: Any = None,
    ) -> Any:
        client = _get_http_client()
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
