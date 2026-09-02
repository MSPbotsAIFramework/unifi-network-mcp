# unifi-network-mcp

MCP server for **UniFi Network** (Ubiquiti's self-hosted routing/switching/
Wi-Fi platform) — site, device, and client inventory, device statistics, and
device restart, over the [Model Context Protocol](https://modelcontextprotocol.io/)
(Streamable HTTP/SSE transport), built directly against Ubiquiti's official
local **Network Integration API**.

Built for [PRD-17725](https://app.clickup.com/t/2280862/PRD-17725) after an
investigation of the community `sirkirby/unifi-mcp` project found it
couldn't be adopted as-is under our gateway's per-tenant, stateless-header
model (global-singleton credentials, refuses to start without one fixed
controller at boot) — see Known Gaps for the full picture, including the one
constraint no amount of engineering here removes.

## ⚠️ Before you deploy this for a customer, read this

UniFi Network has **no shared cloud instance** — every customer runs their
own controller, and it normally lives on their own LAN behind NAT, which our
cloud-hosted gateway cannot reach. **This server only works if the customer
has deliberately exposed their controller's API to the internet.** That is
a real security decision with a real cost (it puts a network-admin surface
on the public internet), and it is the customer's call to make, not ours —
see "Deployment precondition" below before offering this to anyone.

## When would you use this

- "What sites/devices/clients do we have on this customer's UniFi network?" → `unifi_list_sites`, `unifi_list_devices`, `unifi_list_clients`
- "Look up this specific AP/switch/client" → `unifi_get_device`, `unifi_get_client`
- "How's this device doing right now?" → `unifi_get_device_statistics`
- "Restart this device" → `unifi_restart_device` (⚠️ destructive, drops every client behind it)

**Not covered**: UniFi Protect (cameras) and UniFi Access (door control) are
separate controllers with their own local APIs — out of scope for this
server. Also out of scope in this first pass: firewall/ACL rules, networks
(VLANs/WLANs), hotspot vouchers, VPN, RADIUS — all real endpoints on the
official API (see Known Gaps) but not wrapped here yet.

## Deployment precondition: the controller must be reachable from wherever this runs

This server calls the customer's own controller directly — there is no
proxy/relay layer. Three ways that can be true:

1. **The customer exposes the controller's API to the public internet**
   (reverse proxy, port-forward, tunnel — their choice how). This is the
   only path if the MCP gateway runs in our cloud. Recommend a reverse
   proxy with its own access control in front, not a bare port-forward —
   the local API key alone is not enough attack-surface reduction for an
   internet-facing admin interface.
2. **This server runs inside the customer's own network** (e.g. as a
   container next to their controller) — avoids exposing anything, but
   means a per-customer deployment instead of one shared gateway instance.
3. **A site-to-site VPN / private link** between our infrastructure and the
   customer's network — no public exposure, but real network engineering
   per customer.

Path 1 is what PRD-17725's "customer is willing to expose the interface"
scenario assumes. Whichever path is used, `X-Unifi-Host` must resolve to
wherever the controller is actually reachable from — that's on whoever
deploys this, not something this server can arrange.

## Tools

授权需要 `X-Unifi-Host` / `X-Unifi-Api-Key` 两个请求头（见下方授权说明）。

| Tool | 功能 | 参数 |
|---|---|---|
| `unifi_list_sites` | 列出该 controller 管理的全部站点 | 无 |
| `unifi_list_devices` | 列出某站点下的设备（AP/交换机/网关） | `site_id`(必填)、`offset`/`limit`/`filter_expr`(可选) |
| `unifi_get_device` | 获取某设备详情 | `site_id`、`device_id`(均必填) |
| `unifi_get_device_statistics` | 获取某设备最新性能指标 | `site_id`、`device_id`(均必填) |
| `unifi_restart_device` | 立即重启指定设备——**破坏性、不可撤销** | `site_id`、`device_id`(均必填)、`confirm`(必填，必须为true) |
| `unifi_list_clients` | 列出某站点下连接的客户端设备 | `site_id`(必填)、`offset`/`limit`/`filter_expr`(可选) |
| `unifi_get_client` | 获取某客户端详情 | `site_id`、`client_id`(均必填) |

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

Every request to `/mcp` must include the following HTTP headers (provided by the
MCP caller/gateway):

| Header | 类型 | 是否必填 | 字段描述 |
|---|---|---|---|
| `X-Unifi-Host` | string | 必填 | 客户自己 UniFi controller 的地址（裸 host/IP 或带端口，或完整 URL）——必须是从本服务运行的地方能访问到的地址，见上方"Deployment precondition"。 |
| `X-Unifi-Api-Key` | string | 必填 | 在客户 controller 里生成的本地 API Key（Settings → Control Plane → Integrations → Create New API Key）。不要用客户的 admin 账号密码——本地 API Key 是独立、可单独吊销的凭据，也是本服务唯一接受的认证方式。 |
| `X-Unifi-Verify-Ssl` | string | 可选，默认 `true` | 仅当 controller 用自签名证书时设为 `false`——不建议，因为请求现在是走公网而不是局域网，跳过证书校验有真实的中间人风险；更好的做法是让暴露出来的那一层带上有效证书。 |

Missing either required header returns `401 Unauthorized`.

**认证机制**：这个 API（Ubiquiti 官方的 "Network Integration API"）本身就是无状态的单头认证——收到 `X-Unifi-Api-Key` 后原样透传给 controller 的 `X-API-Key` header，没有 token 交换或 session/cookie 登录这一步。凭据只在一次请求的生命周期内持有，从不缓存。

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
- Headers: `X-Unifi-Host`, `X-Unifi-Api-Key` (both required), `X-Unifi-Verify-Ssl` (optional)

## 测试示例 (Test Example)

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Unifi-Host: <customer-exposed-controller-address>" \
  -H "X-Unifi-Api-Key: <local-api-key>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": { "name": "unifi_list_sites", "arguments": {} }
  }'
```

> ⚠️ 本仓库为公开仓库，请勿在任何提交的文件中写入真实的客户 controller 地址/API Key，
> 上面的占位符仅为示意。

## Known Gaps

- **Nothing here has been exercised against a real live controller.**
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
- **Cloud-connector proxy path not implemented.** Ubiquiti also documents
  reaching this same Integration API via `api.ui.com`'s connector proxy
  (`https://api.ui.com/v1/connector/consoles/{consoleId}/proxy/network/integration/v1/...`),
  which would avoid the "customer must expose their controller" precondition
  entirely for any console already adopted to a UI.com account. This wasn't
  explored deeply enough in this investigation to build against — worth
  evaluating before asking any customer to expose their controller, since it
  may remove the need for that entirely. See also the narrower, already-cloud
  **Site Manager API** (`unifi.ui.com`) discussed on PRD-17725 for read-only
  cross-site visibility without this precondition at all, at the cost of a
  much smaller endpoint surface (sites/devices/ISP metrics only, no clients,
  no restart).
