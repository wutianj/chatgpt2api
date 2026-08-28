# 统一用户门户

## 入口

同一个应用提供用户端和管理员端：

| 入口 | 身份 | 能力 |
| --- | --- | --- |
| `/` | 用户 | 工作台、最近任务和余额概览 |
| `/chat` | 用户 | 对话与联网搜索 |
| `/image` | 用户 | 文生图、图生图 |
| `/canvas` | 用户、管理员 | 无限画布集成 |
| `/tasks` | 用户 | 当前用户任务和取消 |
| `/account` | 用户 | 资料、API Key、最近用量 |
| `/wallet` | 用户 | 余额、套餐、订单、兑换码和流水 |
| `/admin` | 管理员 | 管理概览 |
| `/admin/accounts` | 管理员 | 原有账号池 |
| `/admin/users` | 管理员 | 用户状态和余额 |
| `/admin/orders` | 管理员 | 订单、人工到账、退款和兑换码 |
| `/admin/audit` | 管理员 | 用户、订单和额度操作审计 |

普通用户的 API 请求只能通过注册会话或用户 API Key 进入，账号池、代理、系统设置、更新状态和审计接口统一由管理员权限保护。旧 `/pool/` 入口返回 `301` 到 `/#/admin`。

无限画布从 `/api/integrations/infinite-canvas/session` 获取短期 `canvas:ai` 令牌。该令牌只接受 `/v1/*` AI 调用，过期时间默认 24 小时且可通过 `CHATGPT2API_CANVAS_TOKEN_TTL_SECONDS` 调整；普通用户令牌绑定用户钱包和任务隔离，管理员令牌使用管理员身份且不绑定用户钱包。用户主会话令牌不会拼进画布外链，钱包、账户和管理接口也不会接受画布令牌。旧画布构建通过 `apiKey`、`baseUrl` 和 `#access_token` 接收这枚令牌，并由兼容接口 `/api/canvas/session` 返回旧版所需的账户摘要。

直接调用 `/v1/*` 时可以携带 `Idempotency-Key`（最多 160 个字符）。相同用户、相同接口和相同 Key 的重复请求不会再次扣费或创建任务；原请求仍在处理时返回 `409`，可到 `/tasks` 查询状态。图片任务和 PPT/PSD 任务继续使用请求体中的 `client_task_id` 做幂等。

## 订单流程

首期支持人工确认订单和 provider-neutral webhook：

1. 用户在 `/wallet` 创建套餐订单，订单状态为 `pending`。
2. 人工收款后，管理员在 `/admin/orders` 点击“确认到账”，或支付服务调用 webhook。
3. 服务在单个履约事务中写入订单 `paid`、用户额度和 `order_credit` 流水。
4. 重复确认只返回已完成订单，不重复增加余额。
5. 退款会校验用户余额，写入 `order_refund` 反向流水并将订单置为 `refunded`。

用户取消仍处于 `queued` 或 `running` 的任务时，服务会把对应的 `reserved` 用量退回；底层已经提交的上游任务会继续由服务回收，但晚到结果不会把门户中的已取消任务恢复成成功。

支付回调地址：

```text
POST /api/payments/webhook/{provider}
X-Payment-Signature: sha256=<HMAC-SHA256(raw-request-body)>
```

回调 JSON：

```json
{
  "event_id": "provider-event-id",
  "order_id": "order_xxx",
  "status": "paid",
  "amount_units": 990,
  "provider_order_id": "provider-order-id"
}
```

必须设置 `CHATGPT2API_PAYMENT_WEBHOOK_SECRET`。事件 ID、订单状态、订单金额、支付渠道和 HMAC 都会校验；未设置密钥时回调返回 `503`，前端回跳不会改变订单状态。

## 备份与恢复

服务器上执行本地归档：

```bash
APP_DIR=/opt/chatgpt2api BACKUP_DIR=/opt/chatgpt2api/backups deploy/backup.sh
```

脚本会保存 Application Database 一致性快照、完整 `data/` 资产、`config.json`、`.env`、Caddy 配置和版本文件，并生成 `.sha256` 校验文件。PostgreSQL 部署需要额外设置 `DATABASE_URL`，脚本使用 `pg_dump --format=custom`。

恢复默认只校验归档，不修改运行目录：

```bash
deploy/restore.sh /opt/chatgpt2api/backups/chatgpt2api-<timestamp>.tar.gz
```

确认校验结果后再执行：

```bash
APP_DIR=/opt/chatgpt2api deploy/restore.sh /opt/chatgpt2api/backups/chatgpt2api-<timestamp>.tar.gz --apply
```

恢复会先停止 Compose 应用，并将原 `data/` 保存为 `data.before-restore`，完成后重新启动应用并检查 `/`、`/admin`、`/v1/models`。

## 部署配置

生产域名模板位于 `deploy/Caddyfile.prod`：`gptapi.n9k2m.shop` 反代到应用端口，`canvas.n9k2m.shop` 继续提供之前部署的无限画布静态构建；旧 `/image` 入口跳转到统一站点的 `/image`，画布生成请求通过短期令牌回到 `gptapi.n9k2m.shop`。Compose 已暴露支付回调密钥、计费单位和 `/version` 健康检查配置。
