# unifi-network-mcp

MCP server for **UniFi Network** (Ubiquiti's routing/switching/Wi-Fi
platform) — site, device, and client inventory, device statistics, and
device restart, over the [Model Context Protocol](https://modelcontextprotocol.io/)
(Streamable HTTP/SSE transport), built against Ubiquiti's official
**Network Integration API**, reached through Ubiquiti's own cloud
**connector** proxy (`api.ui.com`) rather than a customer's own network.

Built for [PRD-17725](https://app.clickup.com/t/2280862/PRD-17725). An
investigation of the community `sirkirby/unifi-mcp` project found it
couldn't be adopted as-is under our gateway's per-tenant, stateless-header
model (global-singleton credentials, refuses to start without one fixed
controller at boot). This server was originally built with an additional
direct-to-console mode for self-hosted customers willing to expose their
network, but **that mode was dropped (2026-09-03) to focus on SaaS
customers first** — see Known Gaps.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Why the connector path, not a direct connection

UniFi has no single shared cloud instance of the data — every customer has
their own console — but a growing share of customers run **Official UniFi
Hosting (OUH)**, Ubiquiti's own SaaS offering, where the console itself
runs inside Ubiquiti's cloud. An OUH console has **no customer-reachable
address at all** — there's nothing to give this server as a direct host.

Ubiquiti's own **connector** proxy solves this for any console (OUH or
self-hosted) adopted to a UI.com account: this server calls
`https://api.ui.com/v1/connector/consoles/{console_id}/...`, and Ubiquiti's
own infrastructure proxies the request to the console. No customer network
exposure needed at all — this server never talks to a customer's network
directly.

## When would you use this

- "Which consoles can we see?" → `unifi_list_hosts` (start here to find a console_id)
- "What sites/devices/clients do we have on this customer's UniFi network?" → `unifi_list_sites`, `unifi_list_devices`, `unifi_list_clients`
- "Look up this specific AP/switch/client" → `unifi_get_device`, `unifi_get_client`
- "How's this device doing right now?" → `unifi_get_device_statistics`
- "Restart this device" → `unifi_restart_device` (⚠️ destructive, drops every client behind it)

**Not covered**: UniFi Protect (cameras) and UniFi Access (door control) are
separate controllers with their own local APIs — out of scope for this
server. Also out of scope in this first pass: firewall/ACL rules, networks
(VLANs/WLANs), hotspot vouchers, VPN, RADIUS — all real endpoints on the
official API (see Known Gaps) but not wrapped here yet. Direct-to-console
connections for self-hosted customers unwilling to use the connector path
are out of scope for now too (see Known Gaps).

## Tools

Authorization requires the two request headers `X-Unifi-Api-Key` / `X-Unifi-Console-Id` (see the authentication notes below).

| Tool | Description | Parameters |
|---|---|---|
| `unifi_list_hosts` | List all consoles visible to this Site Manager account | None |
| `unifi_list_sites` | List all sites managed by this console | None |
| `unifi_list_devices` | List the devices (AP/switch/gateway) under a site | `site_id` (required), `offset`/`limit`/`filter_expr` (optional) |
| `unifi_get_device` | Get details of a device | `site_id`, `device_id` (both required) |
| `unifi_get_device_statistics` | Get the latest performance metrics of a device | `site_id`, `device_id` (both required) |
| `unifi_restart_device` | Restart the specified device immediately - **destructive and irreversible** | `site_id`, `device_id` (both required), `confirm` (required, must be true) |
| `unifi_list_clients` | List the client devices connected under a site | `site_id` (required), `offset`/`limit`/`filter_expr` (optional) |
| `unifi_get_client` | Get details of a client | `site_id`, `client_id` (both required) |

## Quick Start

### Docker (recommended)

```bash
docker compose up --build
```

The server starts on `http://localhost:8080`.

### Local (uv)

```bash
uv sync
python -m unifi_network_mcp
```

## Health Check

```bash
curl http://localhost:8080/health
# {"status": "ok"}
```

No credentials are required for the health endpoint.

## Authentication Parameters (Authentication)

Every request to `/mcp` must include the following HTTP headers (provided by
the MCP caller/gateway):

| Header | Type | Required | Description |
|---|---|---|---|
| `X-Unifi-Api-Key` | string | Yes | **Site Manager** API Key, generated at unifi.ui.com → Settings → API Keys - not an API Key generated locally on the customer's console; the two are not interchangeable, and using the wrong one returns 401. |
| `X-Unifi-Console-Id` | string | Yes | The host ID of the target console in Site Manager; look it up with `unifi_list_hosts`. |

Do not use the customer's admin account password in place of the API Key - the Site Manager API Key is an independent credential that can be revoked separately, and it is the only authentication method this service accepts. Missing either header returns `401 Unauthorized`.

**Authentication mechanism**: this API (Ubiquiti's official "Network Integration API") is itself stateless single-header authentication - the received `X-Unifi-Api-Key` is passed through as-is as the upstream `X-API-Key` header, with no token exchange or session/cookie login step. Credentials are held only for the lifetime of a single request and never cached. Requests actually go to `https://api.ui.com/v1/connector/consoles/{console_id}/network/integration/...`, and Ubiquiti's own cloud forwards them to the console - this path has been run end-to-end with a fake key (see Known Gaps), confirming that it is a real request and a real response, not a guess.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_HTTP_PORT` | `8080` | Listening port |
| `MCP_HTTP_HOST` | `0.0.0.0` | Listening host |

## MCP Endpoint

```
POST http://localhost:8080/mcp
```

Connect your MCP client with:
- Transport: `http` (Streamable HTTP / SSE)
- Headers: `X-Unifi-Api-Key`, `X-Unifi-Console-Id` (both required)

## Test Example (Test Example)

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Unifi-Api-Key: <site-manager-api-key>" \
  -H "X-Unifi-Console-Id: <console-host-id-from-unifi_list_hosts>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": { "name": "unifi_list_sites", "arguments": {} }
  }'
```

> ⚠️ This repository is public; do not write real customer API Keys/console IDs into any committed file,
> the placeholders above are for illustration only.

## Known Gaps

- **Direct-to-console mode was built, verified live, then deliberately
  dropped (2026-09-03) to focus on SaaS/connector customers first.** The
  removed code let this server call a self-hosted console's own address
  directly (`X-Unifi-Host` + a local console API key) for customers
  willing to expose their network — see git history (commits `e3f5bbe`
  through `3d207e7`) if that capability needs to come back; it was a
  working, tested code path, not abandoned mid-build.
- **Connector mode's URL shape IS confirmed against real Ubiquiti
  infrastructure.** Both `GET https://api.ui.com/v1/hosts`
  (`unifi_list_hosts`) and
  `GET https://api.ui.com/v1/connector/consoles/{id}/network/integration/v1/sites`
  were called for real with a dummy key while running this server locally,
  and both came back with a genuine `401 Unauthorized` from Ubiquiti's own
  API (confirmed in this server's own httpx request log) — not a 404 or a
  connection failure, which is what a wrong path/host would produce. The
  base URL, path structure (no `/proxy/` segment — that's implicit
  server-side per Ubiquiti's own spec), and `X-API-Key` header all come
  from Ubiquiti's own Site Manager OpenAPI spec
  (`developer.ui.com/site-manager/v1.0.0/openapi.json`), not guessed.
  **Still unconfirmed**: the success path (a real Site Manager key actually
  returning host/site data), and whether an Official UniFi Hosting console
  specifically behaves identically to a self-hosted one through this same
  proxy — no OUH account was available to test with.
- **The underlying resource API (sites/devices/clients shapes) is the same
  Network Integration API either way** — Ubiquiti's own spec describes the
  connector as a transparent proxy to the console's own local endpoint
  (`http://127.0.0.1/proxy/[path]`). So the endpoint/field shapes below,
  taken from the official OpenAPI spec (`UniFi Network API v10.0.162`,
  mirrored at [opastorello/unifi-api-docs](https://github.com/opastorello/unifi-api-docs))
  and cross-checked against a real third-party MCP's working implementation
  ([sirkirby/unifi-mcp](https://github.com/sirkirby/unifi-mcp)), should
  still apply — but none of it has been exercised against a real live
  console through the connector path specifically.
- **Connector mode's stated limits are taken as documented, not tested**:
  per-console rate limit of 100 requests/minute, 25-second upstream request
  timeout, 10MB response body cap. A large fleet or a slow console response
  could plausibly hit these in ways this server doesn't specially handle
  beyond its normal retry logic.
- **Non-organization vs. organization Site Manager API keys behave
  differently per Ubiquiti's own docs** ("non-organization API keys:
  limited to API key owner's consoles only; organization API keys: can
  access any console within the organization") — this server has no
  awareness of that distinction; it's purely a property of which kind of
  key the customer generates and hands over.
- **Version requirement, not yet verified against a real console**: per
  Ubiquiti's own documentation, the Network Integration API requires
  UniFi Network 9.x+ on a UniFi OS console or UniFi OS Server, and the
  connector proxy requires console firmware >= 5.0.3 — it does not exist
  on older controllers or the legacy self-hosted Network Application.
  There is no code here to detect or gracefully degrade on an older
  console; a customer on an old version will simply get connection/404
  errors from every tool.
- **The official API's `filter` query parameter is passed through
  unvalidated.** The spec documents filterable properties and allowed
  functions per resource (e.g. devices: `id`, `macAddress`, `name`, `model`,
  `state`, `firmwareVersion`, ... with functions like `eq`/`ne`/`in`/`like`)
  but no concrete example of the actual expression syntax was found during
  this investigation — so `filter_expr` is offered as a passthrough for an
  operator who already knows a working filter string, not something this
  server can construct correctly on its own. Tool docstrings say so
  explicitly rather than inventing a syntax.
- **`unifi_restart_device`'s request shape is desk-verified, not
  field-verified.** `POST .../devices/{deviceId}/actions` with
  `{"action": "RESTART"}` is exactly what the OpenAPI spec's discriminated
  union documents (`RESTART` is the only mapped action for devices at this
  spec version) — never actually executed against a real device.
- **Client actions exist in the official API but aren't wrapped here.**
  `POST .../clients/{clientId}/actions` supports
  `AUTHORIZE_GUEST_ACCESS`/`UNAUTHORIZE_GUEST_ACCESS` — a guest-hotspot
  workflow, not a generic "block this client" control (that capability, if
  it exists, is not in this endpoint). Left out of this MVP since it's a
  narrower use case than device inventory/restart; add it if a real need
  shows up.
- **No write/config endpoints beyond device restart are wrapped**: the
  official API also has full CRUD for ACL rules, firewall zones, networks
  (VLANs), traffic-matching lists, WiFi broadcasts (SSIDs), and hotspot
  vouchers, plus read endpoints for RADIUS profiles, VPN servers/tunnels,
  WANs, pending-devices, device-tags, DPI apps/categories, and countries —
  all real, all in the spec, none wrapped here. This MVP intentionally
  covers inventory + one control action (PRD-17725's stated ask) rather
  than the full surface; expand from `network/v10.0.162/openapi.json` in
  [opastorello/unifi-api-docs](https://github.com/opastorello/unifi-api-docs)
  if broader coverage is needed later.
- **Pagination (`offset`/`limit`) is passed through, not independently
  verified.** The spec documents `offset` default 0, `limit` default 25 /
  max 200 for the list endpoints — taken as given, not smoke-tested against
  a real large fleet.
- **A separate, narrower, already-cloud "Site Manager API"** (plain
  `unifi.ui.com`/`api.ui.com` endpoints like `/v1/sites`, `/v1/devices`,
  `/v1/isp-metrics` — not the connector-proxy path this server uses) also
  exists and was discussed on PRD-17725, for read-only cross-site
  visibility at the cost of a much smaller endpoint surface (no clients, no
  restart, no per-console Integration API access). Not used here — this
  server's connector reaches the full Integration API via the proxy
  instead, which is strictly more capable when it's available.
