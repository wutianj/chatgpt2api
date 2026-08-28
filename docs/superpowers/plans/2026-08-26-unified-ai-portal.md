# 统一 AI 门户实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框跟踪进度。

**目标：** 将聊天、生图、无限画布、用户账户、余额充值和账号池管理统一到 `gptapi.n9k2m.shop`，以当前 yukkcat `/pool` 的 Vue 视觉系统作为唯一前端基础，并通过角色权限区分用户端和管理端。

**架构：** 保留 yukkcat `3.2.2` 的 AI 调度、图片任务和账号池能力，在同一个 FastAPI 应用中增加真实用户、任务、计费和 API Key 领域。Vue 应用使用一个 AppShell 和一套主题，用户路由与管理员路由共享组件但使用独立权限守卫。Caddy 只保留一个主域名，旧的画布和 `/pool` 地址使用兼容跳转。

**技术栈：** FastAPI、Pydantic、SQLAlchemy、SQLite（首期）/ PostgreSQL（扩展）、Vue 3、Vue Router、Pinia、Vite、Playwright、Docker、Caddy。

---

## 一、当前基线

- `web-vue/src/router/routes.ts` 当前主要是管理员路由，`admin_console` 和 `studio` 能力已经存在。
- `web-vue/src/layouts/AppShell.vue` 已有侧边栏、主题、响应式布局和管理员菜单，是统一 UI 的基础。
- `web-vue/src/views/Studio.vue` 已包含聊天、搜索、图片和文件任务能力，可以扩展为用户工作台。
- `api/ai.py`、`api/image_tasks.py` 已按认证身份处理 AI 请求和图片任务。
- `services/auth_service.py` 当前管理管理员 Key 和用户 Key，但用户 Key 不是注册用户体系，不能直接承担余额、订单和任务归属。
- `services/storage/database_storage.py` 当前主要保存账号池和认证 Key，需要增加用户、任务和计费领域表。
- 当前线上账号池数量为 `0`，这是服务器数据库没有账号记录的真实状态，导入账号池属于独立运维步骤。

## 二、统一入口

| 地址 | 角色 | 功能 |
|---|---|---|
| `/` | 用户 | 首页、最近任务、余额、套餐入口 |
| `/chat` | 用户 | 聊天和联网搜索 |
| `/image` | 用户 | 文生图、图生图、历史结果 |
| `/canvas` | 用户 | 无限画布，复用现有画布能力 |
| `/tasks` | 用户 | 只显示当前用户自己的任务 |
| `/account` | 用户 | 个人资料、登录设备、API Key |
| `/wallet` | 用户 | 余额、消费明细、套餐和兑换码 |
| `/admin` | 管理员 | 管理概览 |
| `/admin/accounts` | 管理员 | 账号池、分组、同步和测试 |
| `/admin/users` | 管理员 | 用户、状态、额度和 Key |
| `/admin/orders` | 管理员 | 订单、充值、退款和兑换码 |
| `/admin/settings` | 管理员 | 系统配置、备份和更新 |

兼容入口：

- `canvas.n9k2m.shop/image` 跳转到 `gptapi.n9k2m.shop/image`。
- `gptapi.n9k2m.shop/pool/` 保留并跳转到 `/admin/`，旧 Hash 路由继续可访问。
- `/v1/*` 保持 API 兼容，不改现有客户端的认证方式和响应格式。

## 三、权限边界

### 用户端

- 用户只能读写自己的资料、API Key、任务、余额和订单。
- 用户请求进入 AI 引擎前必须得到 `user_id`、`api_key_id` 和计费策略。
- 用户不能读取账号池记录、ChatGPT Access Token、代理配置、系统设置或更新状态。
- 用户不能调用任何 `require_admin` 保护的接口。

### 管理端

- 管理员可以管理账号池、用户、套餐、兑换码、订单、公告、备份和系统更新。
- 更新入口只在管理员菜单中显示，后端更新接口继续强制 `require_admin`。
- 所有余额调整、退款、Key 禁用、账号池修改和系统更新写入审计日志。

### API Key

- 管理员 Key 只用于管理端，不下发给普通用户。
- 用户 API Key 只允许调用 AI 和任务接口，并绑定 `user_id`。
- Key 创建后只显示一次，支持禁用、删除、轮换和最近使用时间。

## 四、数据模型

### 用户与会话

创建：`services/storage/user_repository.py`、`services/user_auth_service.py`、`contracts/user_auth.py`。

- `users`: `id`, `email`, `display_name`, `password_hash`, `role`, `enabled`, `created_at`, `last_login_at`。
- `sessions`: `id`, `user_id`, `token_hash`, `expires_at`, `revoked_at`, `created_at`, `last_seen_at`。
- `user_api_keys`: `id`, `user_id`, `name`, `key_hash`, `enabled`, `last_used_at`, `created_at`。
- 密码只保存 Argon2id 或 bcrypt 哈希；会话和 Key 只保存哈希值。

### 计费

创建：`services/storage/billing_repository.py`、`services/billing_service.py`、`contracts/billing.py`。

- `plans`: 套餐名称、价格、赠送额度、有效期、可用模型和启用状态。
- `wallet_ledger`: `id`, `user_id`, `entry_type`, `amount`, `balance_after`, `reference_type`, `reference_id`, `idempotency_key`, `created_at`。
- `orders`: `id`, `user_id`, `plan_id`, `amount`, `status`, `provider`, `provider_order_id`, `paid_at`, `created_at`。
- `redeem_codes`: `code_hash`, `plan_id`, `status`, `claimed_by`, `claimed_at`, `expires_at`。
- 余额使用整数最小单位，消费采用“预扣、结算、退款”三阶段，禁止直接覆盖余额字段。

### 任务与用量

创建：`services/storage/task_repository.py`、`services/task_service.py`、`contracts/tasks.py`。

- `user_tasks`: `id`, `user_id`, `api_key_id`, `task_type`, `model`, `status`, `request_json`, `result_json`, `error_code`, `created_at`, `completed_at`。
- `usage_records`: `id`, `user_id`, `task_id`, `model`, `units`, `amount`, `status`, `created_at`。
- `task_id`、`user_id`、`api_key_id` 全部建立索引。
- 查询任务时始终使用当前身份过滤，不能先查全表再由前端过滤。

## 五、文件清单

### 后端新增

- `contracts/user_auth.py`: 注册、登录、会话、资料和用户 Key 请求响应模型。
- `contracts/billing.py`: 套餐、余额流水、兑换码和订单模型。
- `contracts/tasks.py`: 用户任务列表、详情、状态和用量模型。
- `services/storage/user_repository.py`: 用户、会话和用户 Key 持久化。
- `services/storage/billing_repository.py`: 套餐、账本、订单和兑换码持久化。
- `services/storage/task_repository.py`: 任务和用量持久化。
- `services/user_auth_service.py`: 密码校验、会话生命周期和身份解析。
- `services/billing_service.py`: 预扣、结算、退款、兑换和幂等处理。
- `services/task_service.py`: 任务创建、状态推进、归属校验和用量记录。
- `api/user_auth.py`: `/api/auth/register`、`/api/auth/login`、`/api/auth/session`、`/api/auth/logout`。
- `api/user.py`: `/api/user/profile`、`/api/user/keys`、`/api/user/usage`。
- `api/billing.py`: `/api/wallet`、`/api/plans`、`/api/redeem`、`/api/orders`。
- `api/tasks.py`: `/api/tasks`、`/api/tasks/{task_id}`、`/api/tasks/{task_id}/cancel`。

### 后端修改

- `services/application_database.py`: 注册新 SQLAlchemy 模型和数据库迁移版本。
- `api/app.py`: 挂载用户认证、用户、计费和任务路由。
- `api/support.py`: 增加 `require_user`、`require_session` 和统一身份上下文。
- `api/ai.py`: 创建 AI 任务前调用计费预扣，完成或失败时结算或退款。
- `api/image_tasks.py`: 将图片任务绑定到用户任务表，保留现有图片轮询协议。
- `api/system.py`: 保持更新接口管理员权限，并增加更新审计事件。
- `services/auth_service.py`: 保留现有管理员 Key 兼容逻辑，禁止把管理员 Key 当作注册用户会话。

### 前端新增

- `web-vue/src/api/user.ts`: 用户资料、用户 Key 和用量接口。
- `web-vue/src/api/billing.ts`: 余额、套餐、兑换码和订单接口。
- `web-vue/src/api/tasks.ts`: 用户任务列表、详情和取消接口。
- `web-vue/src/stores/user.ts`: 用户资料、余额和当前用户状态。
- `web-vue/src/stores/wallet.ts`: 余额、流水和套餐状态。
- `web-vue/src/views/Home.vue`: 用户首页和最近任务。
- `web-vue/src/views/UserChat.vue`: 用户聊天页，复用 Studio 的流式消息组件。
- `web-vue/src/views/UserImage.vue`: 用户生图页，复用 Studio 图片任务组件。
- `web-vue/src/views/UserTasks.vue`: 用户任务中心。
- `web-vue/src/views/UserAccount.vue`: 用户资料和 API Key。
- `web-vue/src/views/UserWallet.vue`: 余额、套餐和兑换码。
- `web-vue/src/views/AdminUsers.vue`: 管理员用户管理。
- `web-vue/src/views/AdminOrders.vue`: 管理员订单和兑换码管理。

### 前端修改

- `web-vue/src/router/routes.ts`: 按用户和管理员重新组织路由。
- `web-vue/src/router/index.ts`: 增加 `requiresUser`、`requiresAdmin` 和登录跳转守卫。
- `web-vue/src/layouts/AppShell.vue`: 统一用户菜单和管理员菜单，隐藏无权限入口。
- `web-vue/src/stores/auth.ts`: 同时保存登录身份、角色和能力，不再只面向管理员控制台。
- `web-vue/src/api/auth.ts`: 增加注册用户登录会话接口，保留管理员 Key 兼容登录。
- `web-vue/src/views/Login.vue`: 支持用户登录、注册和找回密码入口。
- `web-vue/src/views/Studio.vue`: 拆出用户工作台复用组件，保留管理员调试能力的权限限制。
- `web-vue/src/style.css`、`web-vue/src/styles/features.css`: 统一用户端、管理端和画布的颜色、间距、字体和空状态。

### 部署修改

- `deploy/Caddyfile.prod`: 将 `/`、`/chat`、`/image`、`/canvas`、`/admin` 统一到一个前端入口，保留 `/v1/*` 代理。
- `deploy/docker-compose.yml`: 固定 yukkcat 镜像版本，挂载 Application Database、图片和备份目录。
- `deploy/backup.sh`: 备份 SQLite 数据库、图片文件、配置和 Caddy 配置。
- `deploy/restore.sh`: 在临时目录校验备份后恢复，恢复完成才替换线上文件。

## 六、实现任务

### 任务 1：冻结接口和数据库迁移

文件：`contracts/*.py`、`services/application_database.py`、`services/storage/*`。

- [ ] 定义用户、会话、用户 Key、套餐、账本、订单、兑换码、任务和用量模型。
- [ ] 为每个表增加唯一索引、外键关系和创建时间索引。
- [ ] 实现启动迁移，旧数据库没有新表时自动创建，已有账号池数据保持不变。
- [ ] 添加数据库备份前后记录和迁移版本号。
- [ ] 运行 `python -m pytest test/test_application_database.py -q`，验证新表创建、重复迁移和旧账号池读取。

### 任务 2：用户认证和权限

文件：`api/user_auth.py`、`api/support.py`、`services/user_auth_service.py`、`web-vue/src/api/auth.ts`、`web-vue/src/stores/auth.ts`、`web-vue/src/views/Login.vue`。

- [ ] 实现注册、登录、退出、会话过期和禁用用户处理。
- [ ] 登录成功只返回会话 Cookie 或短期会话令牌，不返回密码哈希。
- [ ] 实现 `require_user`、`require_admin` 和用户身份上下文。
- [ ] 保留管理员 Key 登录兼容能力，但管理员 Key 不创建普通用户余额账户。
- [ ] 测试未登录、普通用户、管理员、禁用用户和过期会话的状态码。
- [ ] 运行 `python -m pytest test/test_user_auth_api.py -q`。

### 任务 3：统一前端壳层和路由

文件：`web-vue/src/router/routes.ts`、`web-vue/src/router/index.ts`、`web-vue/src/layouts/AppShell.vue`、`web-vue/src/style.css`。

- [ ] 将用户入口设为 `/`，将管理入口设为 `/admin`。
- [ ] 将现有 `Dashboard.vue`、`Accounts.vue`、`Settings.vue`、`Proxy.vue`、`Logs.vue`、`Monitor.vue` 迁移到管理员命名空间。
- [ ] 将聊天、生图、画布、任务、账户和钱包加入用户菜单。
- [ ] 统一顶部导航、侧边栏、按钮、颜色、空状态、加载态和错误态。
- [ ] 用户登录后默认进入 `/`，管理员登录后默认进入 `/admin`。
- [ ] 没有 `admin_console` 能力的身份访问 `/admin/*` 时返回用户首页，不显示管理菜单。
- [ ] 运行 `npm run build` 和 Playwright 路由 smoke test。

### 任务 4：用户任务和 AI 调用归属

文件：`api/ai.py`、`api/image_tasks.py`、`api/tasks.py`、`services/task_service.py`、`web-vue/src/api/tasks.ts`、`web-vue/src/views/UserTasks.vue`。

- [ ] 聊天、生图、文件任务创建时写入 `user_tasks`。
- [ ] 任务列表和详情只按当前 `user_id` 查询。
- [ ] 为请求增加幂等键，重复提交不重复创建任务或扣费。
- [ ] 记录排队、执行中、成功、失败、取消和退款状态。
- [ ] 保留现有 SSE、图片轮询和文件下载行为。
- [ ] 测试用户 A 不能读取或取消用户 B 的任务。
- [ ] 运行 `python -m pytest test/test_task_ownership.py -q`。

### 任务 5：余额、套餐、兑换码和用量

文件：`api/billing.py`、`services/billing_service.py`、`services/storage/billing_repository.py`、`web-vue/src/views/UserWallet.vue`。

- [ ] 实现套餐列表、余额查询、账单明细和兑换码兑换。
- [ ] 兑换码使用哈希保存，单个兑换码只能成功兑换一次。
- [ ] AI 调用执行预扣，成功按实际用量结算，失败释放预扣金额。
- [ ] 使用 `idempotency_key` 防止重复回调和重复扣费。
- [ ] 管理员可以手工充值、退款、禁用兑换码，并写入审计日志。
- [ ] 运行 `python -m pytest test/test_billing_ledger.py -q`，覆盖并发扣费、重复兑换、失败退款和余额不足。

### 任务 6：管理员用户、账号池和更新入口

文件：`api/accounts.py`、`api/system.py`、`web-vue/src/views/AdminUsers.vue`、`web-vue/src/views/AdminOrders.vue`、`web-vue/src/views/Accounts.vue`。

- [ ] 将账号池页面挂到 `/admin/accounts`，用户端不出现账号池入口。
- [ ] 将现有用户 Key 管理扩展为用户状态、额度、最近调用和禁用操作。
- [ ] 管理员可以查看账号池健康状态，但任何用户 API 不返回账号凭证。
- [ ] 更新内容、系统设置、备份恢复和配置修改只允许管理员。
- [ ] 增加用户、订单、余额、兑换码、账号池和更新操作的审计列表。
- [ ] 测试普通用户访问所有管理员接口都返回 `403` 或 `401`。

### 任务 7：画布合并和旧站兼容

文件：`deploy/Caddyfile.prod`、`web-vue/src/views/UserImage.vue`、画布集成组件和资源代理配置。

- [ ] 将画布作为 `/canvas` 用户路由集成，统一登录状态和用户任务回写。
- [ ] 画布生成任务使用统一的 `user_tasks` 和余额流水。
- [ ] 旧 `canvas.n9k2m.shop/image` 保留 301 跳转，不再独立维护登录状态。
- [ ] 旧 `/pool/` 跳转到 `/admin/`，保留一段时间的 Hash 路由兼容。
- [ ] 通过浏览器验证桌面端和移动端跳转、登录、返回和任务展示。

### 任务 8：充值支付和上线准备

文件：`api/billing.py`、`services/billing_service.py`、`web-vue/src/views/UserWallet.vue`、`deploy/Caddyfile.prod`、`deploy/docker-compose.yml`。

- [ ] 订单状态使用 `created`、`pending`、`paid`、`failed`、`refunded`、`expired`。
- [ ] 支付回调校验签名、金额、订单号和幂等键，前端回跳不直接改订单状态。
- [ ] 用户端只显示自己的订单，管理端支持按订单号、用户和状态筛选。
- [ ] 配置定时数据库备份、图片资产备份、磁盘空间告警和容器健康检查。
- [ ] 在临时环境完成注册、充值、消费、失败退款、管理员更新和回滚测试。
- [ ] 线上部署前保存 Caddy、compose、镜像版本和数据库备份，部署后验证 `/`、`/chat`、`/image`、`/canvas`、`/admin`、`/v1/models`。

## 七、验收标准

- 未登录用户打开主域名进入统一登录/注册入口。
- 普通用户登录后只看到用户菜单，能够聊天、生图、使用画布、查看自己的任务和余额。
- 管理员登录后进入 `/admin`，能管理账号池、用户、套餐、订单、兑换码和系统更新。
- 普通用户无法读取账号池、代理、系统设置、更新状态和其他用户任务。
- 失败任务不会产生最终扣费，重复请求不会重复扣费。
- 用户 API Key 可以单独禁用和轮换，管理员 Key 不下发给用户。
- 三个旧入口都能跳转到统一域名，页面视觉和登录状态一致。
- 数据库、图片和配置均有可验证的备份与恢复流程。
- 15GB 小服务器上保持单应用、SQLite、现有 Redis，不新增 PostgreSQL 容器；用户量增长后再迁移 PostgreSQL。

## 八、首期不做

- 不重写 yukkcat 的账号池调度核心。
- 不把 basketikun 和 yukkcat 两套前端继续并行维护。
- 不首期加入邀请返利、复杂代理分销和多租户组织空间。
- 不在没有账本、订单幂等和回调验签之前接入真实支付。
