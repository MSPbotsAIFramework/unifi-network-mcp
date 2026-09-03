# unifi-network-mcp

MCP server for **UniFi Network** (Ubiquiti's routing/switching/Wi-Fi
platform) — site, device, and client inventory, device statistics, and
device restart, over the [Model Context Protocol](https://modelcontextprotocol.io/)
(Streamable HTTP/SSE transport), built directly against Ubiquiti's official
**Network Integration API**.

Built for [PRD-17725](https://app.clickup.com/t/2280862/PRD-17725) after an
investigation of the community `sirkirby/unifi-mcp` project found it
couldn't be adopted as-is under our gateway's per-tenant, stateless-header
model (global-singleton credentials, refuses to start without one fixed
controller at boot) — see Known Gaps for the full picture.

## Two ways to reach a console — pick per customer

UniFi has **no single shared cloud instance of the data** — every customer
has their own console — but there are two distinct ways this server can
reach one, selected by which headers the request carries:

| | **Direct mode** | **Connector mode** |
|---|---|---|
| Use for | Self-hosted/hardware console the customer is willing to expose | Official UniFi Hosting (Ubiquiti's own SaaS) — or any console the customer won't expose |
| Headers | `X-Unifi-Host` + `X-Unifi-Api-Key` | `X-Unifi-Console-Id` + `X-Unifi-Api-Key` |
| `X-Unifi-Api-Key` is | A **local** key from the console itself | A **Site Manager** key from unifi.ui.com |
| Request goes to | The console's own address, directly | `api.ui.com`, which proxies to the console |
| Customer network exposure needed? | **Yes** — see the precondition below | **No** — this is the whole point |

**Official UniFi Hosting (OUH) customers must use connector mode** — an OUH
console runs inside Ubiquiti's own cloud and has no customer-reachable
address to give as `X-Unifi-Host` in the first place. Connector mode also
works for a self-hosted console that's adopted to a UI.com account, as an
alternative to exposing it directly.

## ⚠️ Direct mode's precondition: the console must be reachable from wherever this runs

Direct mode calls the customer's own console directly — there is no
proxy/relay layer. Three ways that can be true:

1. **The customer exposes the console's API to the public internet**
   (reverse proxy, port-forward, tunnel — their choice how). This is the
   only path if the MCP gateway runs in our cloud and connector mode isn't
   used instead. Recommend a reverse proxy with its own access control in
   front, not a bare port-forward — the local API key alone is not enough
   attack-surface reduction for an internet-facing admin interface.
2. **This server runs inside the customer's own network** (e.g. as a
   container next to their console) — avoids exposing anything, but means
   a per-customer deployment instead of one shared gateway instance.
3. **A site-to-site VPN / private link** between our infrastructure and the
   customer's network — no public exposure, but real network engineering
   per customer.

This precondition is exactly why connector mode exists: for any customer
unwilling or unable to do one of the above (which includes every OUH/SaaS
customer by definition), connector mode reaches the same API with no
exposure at all.

## When would you use this

- "Which consoles can we see?" (connector mode only) → `unifi_list_hosts`
- "What sites/devices/clients do we have on this customer's UniFi network?" → `unifi_list_sites`, `unifi_list_devices`, `unifi_list_clients`
- "Look up this specific AP/switch/client" → `unifi_get_device`, `unifi_get_client`
- "How's this device doing right now?" → `unifi_get_device_statistics`
- "Restart this device" → `unifi_restart_device` (⚠️ destructive, drops every client behind it)

**Not covered**: UniFi Protect (cameras) and UniFi Access (door control) are
separate controllers with their own local APIs — out of scope for this
server. Also out of scope in this first pass: firewall/ACL rules, networks
(VLANs/WLANs), hotspot vouchers, VPN, RADIUS — all real endpoints on the
official API (see Known Gaps) but not wrapped here yet.

## Tools

授权需要 `X-Unifi-Api-Key`，外加 `X-Unifi-Host` 或 `X-Unifi-Console-Id` 二选一（见下方授权说明）。

| Tool | 功能 | 参数 | 模式 |
|---|---|---|---|
| `unifi_list_hosts` | 列出该 Site Manager 账号能看到的全部 console | 无 | 仅 connector 模式 |
| `unifi_list_sites` | 列出该 controller 管理的全部站点 | 无 | 均可 |
| `unifi_list_devices` | 列出某站点下的设备（AP/交换机/网关） | `site_id`(必填)、`offset`/`limit`/`filter_expr`(可选) | 均可 |
| `unifi_get_device` | 获取某设备详情 | `site_id`、`device_id`(均必填) | 均可 |
| `unifi_get_device_statistics` | 获取某设备最新性能指标 | `site_id`、`device_id`(均必填) | 均可 |
| `unifi_restart_device` | 立即重启指定设备——**破坏性、不可撤销** | `site_id`、`device_id`(均必填)、`confirm`(必填，必须为true) | 均可 |
| `unifi_list_clients` | 列出某站点下连接的客户端设备 | `site_id`(必填)、`offset`/`limit`/`filter_expr`(可选) | 均可 |
| `unifi_get_client` | 获取某客户端详情 | `site_id`、`client_id`(均必填) | 均可 |

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

## 授权参数说明 (Authentication)

Every request to `/mcp` must include `X-Unifi-Api-Key`, plus **exactly one**
of `X-Unifi-Host` or `X-Unifi-Console-Id` (provided by the MCP caller/gateway):

| Header | 类型 | 是否必填 | 字段描述 |
|---|---|---|---|
| `X-Unifi-Api-Key` | string | 必填 | 见下方——具体是哪种 API Key，取决于用的是 direct 还是 connector 模式，两者不能混用。 |
| `X-Unifi-Host` | string | 二选一（direct 模式） | 客户自己 UniFi console 的地址（裸 host/IP 或带端口，或完整 URL）——必须是从本服务运行的地方能访问到的地址，见上方"Direct mode's precondition"。此时 `X-Unifi-Api-Key` 必须是在这台 console 里生成的**本地** API Key（Settings → Control Plane → Integrations → Create New API Key）。 |
| `X-Unifi-Console-Id` | string | 二选一（connector 模式） | 客户 console 在 Site Manager 里的 host ID——用 `unifi_list_hosts` 查。此时 `X-Unifi-Api-Key` 必须是 unifi.ui.com → Settings → API Keys 生成的 **Site Manager** API Key，不能用本地 console 的 API Key。**OUH（官方 SaaS 托管）客户必须用这个模式**，因为它们的 console 根本没有客户能拿到的地址。 |
| `X-Unifi-Verify-Ssl` | string | 可选，默认 `true`，仅 direct 模式生效 | 仅当 console 用自签名证书时设为 `false`——不建议，因为请求现在是走公网而不是局域网，跳过证书校验有真实的中间人风险；更好的做法是让暴露出来的那一层带上有效证书。connector 模式下始终忽略此项（`api.ui.com` 一直是正规签发的证书）。 |

不要用客户的 admin 账号密码代替任一种 API Key——两种 API Key 都是独立、可单独吊销的凭据，也是本服务唯一接受的认证方式。缺少 `X-Unifi-Api-Key`，或 `X-Unifi-Host`/`X-Unifi-Console-Id` 一个都没给 / 两个都给了，均返回 `401 Unauthorized`。

**认证机制**：这个 API（Ubiquiti 官方的 "Network Integration API"）本身就是无状态的单头认证——不管走哪种模式，收到的 API Key 都原样透传为上游的 `X-API-Key` header，没有 token 交换或 session/cookie 登录这一步。凭据只在一次请求的生命周期内持有，从不缓存。两种模式唯一的区别是请求打到哪：direct 模式直接打客户 console 自己的地址；connector 模式打 `https://api.ui.com/v1/connector/consoles/{console_id}/network/integration/...`，由 Ubiquiti 自己的云转发到 console——这条路径已经用假 Key 实际跑通过（见 Known Gaps），确认走的是真请求、真响应，不是猜的。

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
- Headers: `X-Unifi-Api-Key` (required) + exactly one of `X-Unifi-Host` / `X-Unifi-Console-Id`, `X-Unifi-Verify-Ssl` (optional, direct mode only)

## 测试示例 (Test Example)

Direct mode:

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Unifi-Host: <customer-exposed-console-address>" \
  -H "X-Unifi-Api-Key: <local-api-key>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": { "name": "unifi_list_sites", "arguments": {} }
  }'
```

Connector mode (SaaS / OUH, or any console the customer won't expose):

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Unifi-Console-Id: <console-host-id-from-unifi_list_hosts>" \
  -H "X-Unifi-Api-Key: <site-manager-api-key>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": { "name": "unifi_list_sites", "arguments": {} }
  }'
```

> ⚠️ 本仓库为公开仓库，请勿在任何提交的文件中写入真实的客户 console 地址/API Key，
> 上面的占位符仅为示意。

## Known Gaps

- **Direct mode has never been exercised against a real live controller.**
  Unlike this fleet's other recent vendor-mcps (datto-rmm-mcp, easydmarc-mcp),
  we had no test/trial UniFi account or exposed controller to call against —
  every endpoint's request/response shape below comes from Ubiquiti's own
  official OpenAPI spec (`UniFi Network API v10.0.162`, mirrored at
  [opastorello/unifi-api-docs](https://github.com/opastorello/unifi-api-docs)),
  cross-checked against a real third-party MCP's working implementation
  ([sirkirby/unifi-mcp](https://github.com/sirkirby/unifi-mcp) —
  `packages/unifi-core/src/unifi_core/auth.py` uses the same `X-API-Key`
  header and the same `/proxy/network/integration` path prefix this server
  uses, confirmed by reading that repo's source directly, not assumed).
  **Test this for real (a customer's exposed controller, or a lab UniFi
  device) before treating this as production-ready.**
- **Connector mode's URL shape IS confirmed against real Ubiquiti
  infrastructure — added 2026-09-03, more verified than direct mode.**
  Both `GET https://api.ui.com/v1/hosts` (`unifi_list_hosts`) and
  `GET https://api.ui.com/v1/connector/consoles/{id}/network/integration/v1/sites`
  were called for real with a dummy key while running this server locally,
  and both came back with a genuine `401 Unauthorized` from Ubiquiti's own
  API (confirmed in this server's own httpx request log) — not a 404 or a
  connection failure, which is what a wrong path/host would produce. The
  base URL, path structure (no `/proxy/` segment — that's implicit server-
  side per Ubiquiti's own spec, unlike direct mode's explicit
  `/proxy/network/integration` prefix), and `X-API-Key` header all come
  from Ubiquiti's own Site Manager OpenAPI spec
  (`developer.ui.com/site-manager/v1.0.0/openapi.json`), not guessed.
  **Still unconfirmed**: the success path (a real Site Manager key actually
  returning host/site data), and whether an Official UniFi Hosting console
  specifically behaves identically to a self-hosted one through this same
  proxy — no OUH account was available to test with.
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
  UniFi Network 9.x+ on a UniFi OS console or UniFi OS Server — it does not
  exist on older controllers or the legacy self-hosted Network Application.
  There is no code here to detect or gracefully degrade on an older
  controller; a customer on an old version will simply get connection/404
  errors from every tool.
- **TLS verification defaults to ON (`verify_ssl=True`)**, unlike the
  community repo (which defaults to skipping verification, appropriate for
  a same-LAN connection). This is a deliberate difference: once a customer
  exposes their controller to the *public* internet, skipping TLS
  verification is a materially worse idea than it is on a LAN, so the
  opt-out (`X-Unifi-Verify-Ssl: false`) exists for a self-signed cert but
  is not the default.
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
  server's connector mode reaches the full Integration API via the proxy
  instead, which is strictly more capable when it's available.
