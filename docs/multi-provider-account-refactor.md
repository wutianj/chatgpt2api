# I7 多 Provider 账号中心重构设计

状态：第二阶段已落地，统一账号域仍按阶段推进
日期：2026-08-29
适用项目：`chatgpt2api`

## 1. 目标

I7 最终提供一个统一的用户端和一个统一的管理端。管理员在同一个账号池中管理
OpenAI、Gemini 以及后续接入的其他模型账号；用户端只看到模型、任务、余额和
自己的 API Key，不看到上游账号、代理、账号组、更新入口或管理数据。

本次重构重点解决：

- GPT 与 Gemini 使用两套后台、两套账号模型的问题。
- 账号类型、OAuth、API Key、Service Account 无法在同一个入口管理的问题。
- 账号分组、代理、并发、优先级、额度和模型能力没有统一调度的问题。
- Free、Plus、Pro、Team 的生图能力无法准确区分的问题。
- 2K 降级后仍按 2K 扣费、失败重复扣费和任务状态不一致的问题。
- 导入账号缺少 RT、OAuth 类型识别错误、未知账号无法批量筛选的问题。

## 2. 设计原则

1. **统一资源，专属适配器**：所有账号进入同一个账号域，但每个平台自己负责
   凭证解析、OAuth 刷新、额度探测、能力判断和请求协议。
2. **兼容优先**：保留现有 GPT 账号 ID、Token 映射、旧 API 和线上用户数据，先
   建立兼容投影，再逐步迁移写入路径。
3. **能力驱动调度**：调度器按 `provider + model + capability` 选账号，不按
   账号名称或套餐字符串猜测能力。
4. **后端拥有业务语义**：前端只提交筛选条件和表单数据，状态、额度、错误分类、
   实际分辨率和扣费结果由后端返回。
5. **敏感凭证隔离**：正常列表和日志永不返回原始 Token、Cookie、OAuth Secret
   或 Service Account 私钥。
6. **可回滚交付**：每一阶段都能独立备份、验证和回滚，不在一次发布中删除旧数据。

## 3. 当前基线

当前 I7 的主要边界：

- `AccountService` 以 Token 到账号的映射为核心，并通过现有 Account Repository
  保存账号状态和运行时信息。
- `api/accounts.py` 同时承载账号、账号组、OAuth、Sub2API 导入和批量操作，部分
  字段仍是 GPT/旧账号语义。
- 账号组当前主要是兼容配置中的单个 `group_id`，还不是标准的多对多绑定。
- Gemini 当前已经有 Provider 配置、模型目录和请求分发，但不是 I7 内置的账号池。
- 用户门户、钱包、订单、兑换码和任务日志已经拥有独立 Repository/事务边界，账号
  重构不能把这些业务重新塞回账号模块。

对应代码：

- `services/account_service.py`
- `api/accounts.py`
- `services/model_catalog_service.py`
- `services/gemini_provider.py`
- `services/storage/portal_repository.py`

## 3.1 当前已落地

Gemini Business 账号池已先以独立凭据存储和 Provider 适配器落地，避免直接改写
现有 GPT 账号表：

- `data/gemini_accounts.json` 保存 Gemini Business cookie 凭据和运行时状态。
- `api/gemini_accounts.py` 提供管理员专用的添加、JSON/JSONL 导入、测试、启停、删除接口。
- `services/gemini_account_pool.py` 实现 `getoxsrf -> JWT -> widgetCreateSession ->
  widgetStreamAssist -> downloadFile` 调用链，支持优先级、并发上限、失败冷却和轮换。
- `services/gemini_provider.py` 在账号池有可用账号时优先走内置账号池；没有账号时继续兼容
  原有 OpenAI 兼容 Provider 配置。
- 管理端新增 `Gemini 账号池` 页面，列表只返回脱敏字段，原始 cookie 不进入列表响应和日志。

当前图生图（带参考文件上传）仍保留为明确的未接入能力；这不会影响 Gemini 文生图和文本
对话账号池，后续接入文件上传时沿用同一账号调度和凭据存储。

## 4. 目标架构

```text
用户端 / 管理端
        |
        v
Portal API / Admin API / OpenAI-compatible API
        |
        +--> Model Capability Resolver
        |          |
        |          v
        +--> Account Scheduler ----> Account Lease / Concurrency
        |          |
        |          v
        +--> Provider Adapter ------> OpenAI / Gemini / Future Providers
        |          |
        |          v
        +--> Result Normalizer ------> Task / Asset / Billing Settlement
        |
        v
Account Repository + Provider Credential Store + Group Policy Store
```

### 4.1 模块职责

| 模块 | 职责 | 不负责 |
| --- | --- | --- |
| `AccountDomain` | 统一账号状态、分组、并发、代理、生命周期 | 不解析平台私有协议 |
| `ProviderRegistry` | 注册 Provider 和账号类型 | 不保存用户钱包 |
| `CredentialStore` | 加密保存、轮换、脱敏和导入 | 不参与账号排序 |
| `CapabilityResolver` | 将模型、尺寸、输入类型转换成能力需求 | 不执行上游请求 |
| `AccountScheduler` | 候选筛选、租约、并发、冷却和重试 | 不决定用户价格 |
| `ProviderAdapter` | OAuth、刷新、探测、额度、请求和结果解析 | 不直接扣用户余额 |
| `BillingService` | 预扣、结算、退款、幂等和流水 | 不选择上游账号 |
| `TaskService` | 任务状态、结果资产和用户隔离 | 不保存 OAuth 凭证 |

## 5. 统一账号数据模型

首期仍由 Account Repository 管理，建议在现有 Application Database 中增加统一
字段/表；不要先把全部旧 JSON 或 Token 文件一次性改写。

### 5.1 `provider_accounts`

```text
id                         稳定内部 ID
provider                   openai / gemini / anthropic / grok / ...
account_type               web / oauth / api_key / setup_token / service_account
credential_kind            openai_web_oauth / openai_codex_oauth /
                           gemini_business_oauth / gemini_api_key / ...
name, notes                管理员可见名称和备注
source                     local / sub2api / reg2 / manual / import
external_id                外部系统账号 ID，可为空
legacy_key_hash            旧 Token 映射哈希，不保存原始 Token
proxy_ref                  direct / proxy_node / proxy_group
status                     active / disabled / error / expired / unknown
schedulable                当前是否允许进入调度
concurrency                账号并发上限
load_factor                负载系数
priority                   调度优先级
rate_multiplier            账号倍率
expires_at                 账号或授权到期时间
auto_pause_on_expired      到期是否自动暂停
created_at, updated_at
```

### 5.2 `account_credentials`

凭证从账号普通资料中拆出，使用服务器密钥加密保存：

```text
account_id
version
encrypted_payload
credential_fingerprint
has_access_token
has_refresh_token
has_api_key
has_setup_token
last_refresh_at
last_refresh_error
```

列表只返回 `has_*` 和状态，不返回 `encrypted_payload`。管理员编辑时支持替换凭证，
不回显完整旧值。

### 5.3 `account_capabilities`

```text
account_id
capability                 chat / image / image_1k / image_2k / image_4k / edit / search
model_pattern              具体模型或匹配模式
enabled
source                     provider_probe / manual_override / imported_metadata
last_verified_at
```

能力必须经过 Provider 探测或管理员明确配置。套餐名称只用于展示和筛选，不能代替
能力字段。

### 5.4 `account_health`

```text
account_id
health                     healthy / unauthorized / rate_limited / quota_exhausted /
                           proxy_failed / credential_incomplete / unknown
last_check_at
last_success_at
last_error_code
last_error_summary
cooldown_until
rate_limit_reset_at
quota_snapshot
```

`credential_incomplete` 专门用于 AT 存在但 RT 缺失、OAuth JSON 字段不完整等情况；
此状态不会混成“正常账号”。

### 5.5 `account_group_bindings`

账号与分组采用多对多关系，一个账号可进入多个业务分组；每个绑定可以拥有独立的
组内优先级。

```text
account_id
group_id
binding_priority
enabled
created_at
```

## 6. Provider 适配器契约

```python
class ProviderAdapter(Protocol):
    provider_id: str

    def supported_account_types(self) -> list[str]: ...
    def normalize_import(self, payload: dict) -> NormalizedAccountInput: ...
    def validate_credentials(self, credentials: dict) -> CredentialCheck: ...
    def refresh_credentials(self, account: ProviderAccount) -> RefreshResult: ...
    def probe(self, account: ProviderAccount) -> AccountProbeResult: ...
    def get_capabilities(self, account: ProviderAccount) -> CapabilitySnapshot: ...
    def get_quota(self, account: ProviderAccount) -> QuotaSnapshot: ...
    def invoke(self, request: ProviderRequest) -> ProviderResult: ...
    def redact(self, credentials: dict) -> dict: ...
```

首期适配器：

| Provider | 账号类型 | 说明 |
| --- | --- | --- |
| OpenAI | Web OAuth | 兼容现有 GPT Web/AT/RT 账号 |
| OpenAI | Codex OAuth | 单独识别 Codex OAuth，不再依赖 Token 字符串猜测 |
| OpenAI | API Key | 保留标准接口账号能力 |
| Gemini | Business OAuth | 接入 Gemini Business 项目的账号凭证 |
| Gemini | API Key | 用于 Provider/API 模式 |
| Gemini | Vertex Service Account | 预留企业账号类型 |

OpenAI 和 Gemini 的凭证不能共用解析器；套餐、额度、刷新方式、错误分类和图像能力
由各自适配器负责。

## 7. 账号导入和 OAuth

### 7.1 统一添加账号弹窗

按 Sub2API 的交互分成三步：

1. 选择平台：OpenAI、Gemini、Anthropic、Grok 等。
2. 选择账号类型：OAuth、API Key、Setup Token、Service Account。
3. 填写平台专属凭证，并填写通用字段：名称、备注、分组、代理、并发、优先级、
   负载系数和自动暂停策略。

### 7.2 OAuth 识别规则

导入 JSON 时必须先识别 `credential_kind`，再验证字段：

- OpenAI Codex OAuth 使用 Codex 专属字段映射。
- OpenAI Web OAuth 使用 AT/RT 生命周期。
- Gemini Business OAuth 使用 Gemini 专属字段映射。
- 无法识别时进入 `unknown`，管理员可以查看脱敏错误并重新选择类型。

不能通过“是否有某个 Token 字段”直接把 Codex 账号当成普通 GPT 账号。

### 7.3 RT 缺失处理

- 有 AT、无 RT：导入成功但标记 `credential_incomplete`，只允许在 AT 未过期时
  进行有限探测，不允许作为长期可刷新账号。
- 有 RT：导入后立即做一次刷新/探测，成功才进入正常调度。
- 字段错误、刷新失败、代理失败、额度耗尽分别记录不同错误码。
- 批量导入返回逐条结果：created、reused、incomplete、failed，并保留可下载错误报告。

### 7.4 幂等导入

导入指纹优先使用 `provider + credential_kind + external_id`；没有 external_id 时
使用服务端计算的凭证指纹。重复导入返回 reused，不重复创建账号或分组绑定。

## 8. 分组、代理和调度

### 8.1 账号组策略

账号组不再只是代理组名称，而是模型能力和商业策略的组合：

```text
OpenAI Free
  chat, image_1k

OpenAI Paid
  chat, image_1k, image_2k

Gemini Image
  gemini image capabilities

4K Reserved
  image_4k, enabled=false
```

组策略可配置模型范围、能力开关、并发上限、用户套餐、计费点数、代理组和调度倍率。

### 8.2 候选账号流程

```text
用户请求
  -> 解析 provider / model / resolution / input type
  -> 校验用户套餐和组策略
  -> 筛选 active + schedulable
  -> 筛选 capability
  -> 检查 quota / expiry / cooldown
  -> 检查 proxy 和并发租约
  -> 按 priority、load_factor、最近延迟排序
  -> 创建 account lease
  -> ProviderAdapter 调用
  -> 释放 lease 并更新健康状态
```

账号被限流、代理失败或暂时超载时，只进入冷却，不直接永久删除；连续失败达到阈值
才自动暂停并记录审计。

### 8.3 生图能力规则

- Free GPT 账号只进入 `image_1k` 候选池。
- Plus OAuth、Pro OAuth、Team OAuth 才进入 `image_2k` 候选池。
- 2K 没有可用账号时，默认返回“2K 暂无可用额度”，不静默伪装成 2K。
- 若业务明确启用降级策略，必须在结果中返回 `requested_resolution=2k`、
  `effective_resolution=1k`，前端明确提示用户，计费按实际生图结果结算。
- 4K 字段、价格和能力可以配置，但默认 `enabled=false`，不进入候选池。

## 9. 统一调用与计费

### 9.1 调用上下文

每次调用生成统一上下文：

```text
request_id
user_id / api_key_id
provider
model
requested_capability
requested_resolution
effective_resolution
selected_account_id
selected_group_id
proxy_ref
attempts
result_status
actual_output_metadata
```

### 9.2 计费配置

管理员在套餐设置中可修改：

```text
chat_price
image_1k_price
image_2k_price
image_4k_price
search_price
file_task_price
```

套餐仍支持价格、赠送点数、有效期、上架状态；兑换码继续支持预设套餐和自定义点数。

### 9.3 结算原则

重构目标采用预扣加幂等结算：

1. 请求进入任务时按最大可能费用预留点数。
2. Provider 返回后记录真实 `effective_resolution` 和输出元数据。
3. 成功时按真实结果结算，多预留部分自动退回。
4. 失败、超时、额度不足和未提交上游时全额退回。
5. 每个 `task_id + billing_operation` 只能有一条扣费结果。
6. 重试不能新建重复扣费流水，退款也必须有唯一引用号。

第一阶段可继续使用现有预留/退款接口，但必须先把“请求分辨率”和“实际分辨率”
分开保存；第二阶段再切换到真实结果结算。

## 10. 管理端 API

以下为规范接口。现有 `/api/accounts/*` 保留为兼容别名，逐步转发到规范服务。

```text
GET    /api/admin/accounts
POST   /api/admin/accounts
GET    /api/admin/accounts/{id}
PATCH  /api/admin/accounts/{id}
DELETE /api/admin/accounts/{id}

POST   /api/admin/accounts/{id}/test
POST   /api/admin/accounts/{id}/refresh
POST   /api/admin/accounts/{id}/enable
POST   /api/admin/accounts/{id}/disable
POST   /api/admin/accounts/bulk

POST   /api/admin/accounts/import/{provider}
GET    /api/admin/accounts/export?provider=&group_id=

GET    /api/admin/account-groups
POST   /api/admin/account-groups
PATCH  /api/admin/account-groups/{id}
DELETE /api/admin/account-groups/{id}

GET    /api/admin/accounts/{id}/health
GET    /api/admin/accounts/{id}/audit
```

列表筛选参数：`provider`、`account_type`、`credential_kind`、`status`、`health`、
`group_id`、`capability`、`proxy_ref`、`search`、`page`、`page_size`。

普通响应只返回脱敏 DTO；原始凭证只允许专门的管理员备份导出，并且需要审计记录。

## 11. 管理端 UI

保留 I7 现有 AppShell，重做 `/admin/accounts` 的业务内容，交互借鉴 Sub2API：

- 顶部平台筛选：全部、OpenAI、Gemini、Anthropic、Grok 等。
- 第二层账号类型筛选：OAuth、API Key、Setup Token、Service Account。
- 搜索：名称、邮箱、外部 ID、凭证指纹、错误码。
- 账号表格：平台、类型、套餐、能力、状态、额度、代理、并发、最近检查、成功率。
- 添加账号弹窗：平台和类型卡片 + 平台专属认证表单 + 通用调度字段。
- 批量操作：启用、禁用、删除、分组、设置代理、测试、导出。
- 详情抽屉：健康状态、额度快照、最近错误、能力探测、OAuth 更新时间和审计记录。
- 未知账号筛选：`health=unknown` 或 `credential_kind=unknown`，支持批量删除前预览。
- RT 缺失筛选：`health=credential_incomplete`，不能与正常账号混在一起。

用户端只保留：AI 对话、AI 生图、无限画布、我的任务、余额与套餐、账户设置；不显示
账号池、代理、管理更新、源代码信息和管理员入口。

## 12. 用户端和管理权限

- `/login` 统一处理用户登录和管理员账号密码登录。
- 管理员登录后进入同一 AppShell，但按角色显示管理菜单。
- 用户会话不能访问 `/api/admin/*`、账号池、代理、系统设置、审计和更新接口。
- 用户端不显示更新内容、版本更新入口或上游账号来源。
- 用户 API Key 只能调用授权模型和用户自己的任务/资产接口。
- 画布令牌继续保持短期、用户隔离和最小权限，不直接继承管理员权限。

## 13. 迁移方案

### 阶段 A：只读统一投影

- 新增 `provider`、`account_type`、`credential_kind`、`health`、`capabilities` 的
  统一读取模型。
- 现有 GPT 账号自动映射为 `provider=openai`。
- 旧 `group_id` 投影为一个绑定，不改变当前调度结果。
- 增加诊断字段和数据一致性报告。

### 阶段 B：Provider Registry 和凭证存储

- 引入 OpenAI Web/Codex OAuth 适配器。
- 引入 Gemini Business OAuth/API Key/Service Account 适配器。
- 完成脱敏、刷新、探测和导入幂等。
- 旧 Token 存储保留只读回退，确认迁移后再停止写入。

### 阶段 C：统一调度

- 把现有 GPT 图片账号选择、Gemini Provider 请求和代理选择接入同一 Scheduler。
- 先以影子模式记录候选结果，不改变线上选号。
- 对比影子结果和现有结果，确认成功率、延迟和账号切换无异常后切正式路径。

### 阶段 D：统一计费

- 增加 1K、2K、4K 独立价格配置和实际结果字段。
- 修正降级时的请求尺寸/实际尺寸混淆。
- 加入结算幂等、失败退回和重复任务保护。
- 现有余额、套餐、订单、兑换码流水保持兼容。

### 阶段 E：统一 UI 和清理旧入口

- 上线 Sub2API 风格的多平台账号池。
- Gemini 账号池并入 I7 管理端。
- 保留旧路径兼容跳转一段时间。
- 确认备份、回滚和线上健康检查通过后，再删除废弃的独立 Gemini 管理入口。

## 14. 测试矩阵

### 账号和凭证

- OpenAI Free/Plus/Pro/Team OAuth 导入、刷新、失效和删除。
- Codex OAuth JSON 导入后类型识别正确。
- Gemini OAuth/API Key/Service Account 导入和脱敏。
- AT-only、RT 缺失、RT 失效、字段错误、重复导入。
- 逐条导入结果、失败重试和幂等复用。

### 调度和生图

- Free 只命中 1K。
- Plus/Pro/Team 命中 2K。
- 没有 2K 能力时返回明确降级信息。
- 4K 配置存在但关闭时不会被选中。
- 并发达到上限、代理失败、限流、额度耗尽和冷却恢复。
- 多账号并发下租约不会重复占用或泄漏。

### 计费和门户

- 1K、2K、4K 价格可由管理员修改。
- 自定义兑换码点数保持可配置。
- 成功、失败、超时、降级、重试和重复请求的流水正确。
- 用户只能看到自己的任务、资产、余额和 API Key。
- 管理员才能看到账号池、代理、导入、更新和审计。

### 发布

- Python 编译、后端单元测试、前端构建、运行时路由契约。
- SQLite 和 PostgreSQL 的迁移/回滚测试。
- 线上备份校验、Compose 健康检查、`/`、`/admin`、`/v1/models` 和生图冒烟。
- 旧 `/api/accounts/*` 兼容接口回归。

## 15. 发布和回滚要求

每个阶段发布前必须保存：

- Application Database 一致性备份。
- `data/` 图片和任务资产。
- 配置、代理组、账号分组和版本文件。
- 当前容器镜像、Compose 配置和 Caddy 配置。
- 迁移版本和可执行回滚脚本。

回滚顺序：停止新版本、恢复应用代码/镜像、恢复数据库或反向迁移、恢复配置、启动
服务、验证用户登录、账号列表、模型列表、生图、余额流水和管理员登录。

## 16. 直接复用 Sub2API 的边界

已确认 Sub2API 源码位于 `D:\yewu\_research\sub2api`，其统一账号模型、平台/类型
表单、分组绑定、调度状态、凭证脱敏和幂等导入值得直接借鉴。

I7 不直接替换成 Sub2API 的整套 Go/Ent 后端，原因是 I7 已经有稳定的 Python API、
门户、图片任务、钱包和部署边界。优先移植领域结构、接口契约和流程；如果复制具体
代码，保留 Sub2API 的 LGPL-3.0 许可证和版权/NOTICE 信息，并在发布文档中注明来源。

## 17. Gemini Business 生图适配器来源

Gemini 生图实现来源为：

`https://github.com/yukkcat/gemini-business2api`

该仓库的主线定位是 Gemini Business 到 OpenAI 兼容 API 的网关，包含多账号调度、
图片生成/编辑、文件和多模态能力。当前主线还把刷新能力拆成可选的
`refresh-worker`，主服务不再内嵌旧的刷新执行器。

关键模块及其在 I7 中的移植职责：

| 上游模块 | 上游职责 | I7 移植方式 |
| --- | --- | --- |
| `core/account.py` | Gemini Business 账号配置、会话缓存、配额冷却和多账号管理 | 提炼为 `GeminiAccountAdapter` 和统一 Scheduler 的 Provider 状态实现 |
| `core/auth.py` | OAuth/Cookie 到短期 JWT 的认证链路 | 放入 Gemini 凭证适配器，凭证由 I7 Credential Store 托管 |
| `core/google_api.py` | 创建业务 Session、上传上下文、读取生成文件元数据、下载图片 | 保留为 Gemini Transport 层，接入 I7 的代理、超时、重试和任务日志 |
| `app/api/routers/images.py` | `/v1/images/generations` 和 `/v1/images/edits` 兼容接口 | 不直接复制路由，接入 I7 Image Task Service |
| `app/services/image_service.py` | 解析 Markdown 中的 Base64/URL 图片并保存为公共资产 | 复用解析思路，但统一交给 I7 ImageStorageService 保存和删除 |
| `app/services/account_service.py` | 账号状态、配额桶、冷却和启停 | 映射到 I7 `account_health`，不再维护第二个账号池 |

### 17.1 生图链路的事实

上游 `/v1/images/generations` 的当前流程是：

```text
ImageGenerationRequest
  -> 构造 ChatRequest(model=req.model)
  -> 调用 chat_handler
  -> 读取 choices[0].message.content
  -> 提取 Markdown Base64 或图片 URL
  -> 持久化/返回 OpenAI data[]
```

这意味着：

- `size` 在当前上游图片路由中没有被用于强制生成尺寸。
- `quality` 和 `style` 也不是原生 Gemini Business 请求参数的可靠映射。
- 返回了图片，不等于返回了请求的 1K、2K 或 4K 原始像素。
- I7 必须在 ProviderResult 中读取真实图片字节并检测宽高，写入
  `actual_width`、`actual_height`、`effective_resolution`。
- 2K 计费和用户提示只能依据实际检测结果，不能只看前端选择或请求字段。

### 17.2 I7 的 Gemini 生图调用契约

```python
result = await gemini_image_adapter.generate(
    account=account,
    prompt=prompt,
    requested_resolution="1k | 2k | 4k",
    aspect_ratio=aspect_ratio,
    count=count,
    references=references,
)

assert result.assets
assert result.actual_width > 0 and result.actual_height > 0
```

适配器必须返回：

```text
provider
model
account_id
requested_resolution
effective_resolution
width / height
mime_type
asset_bytes_or_staging_path
provider_request_id
fallback_reason
```

I7 的分辨率策略仍然是：GPT Free 不进入 2K 候选池，GPT Plus/Pro/Team OAuth 才进入
2K 候选池；Gemini 是否支持 2K 必须通过实际探测结果或明确的 Provider 能力配置
决定，4K 先预留但默认关闭。

### 17.3 上游账号状态的映射

上游已有 `active`、手动禁用、访问受限、过期、限流、额度受限和不可用等状态，I7
统一映射为 `account_health`，并额外保留：

- `credential_incomplete`：缺少刷新字段或 OAuth JSON 不完整。
- `proxy_failed`：账号本身未判定失效，仅代理链路失败。
- `capability_unknown`：账号可认证，但尚未确认 2K/编辑/视频能力。

不能把代理失败、短期限流和账号永久失效都直接标记为删除。

### 17.4 许可证记录

该 Gemini Business2API 仓库 README 当前声明为 `Cooperative Non-Commercial License
(CNC-1.0)`；它与 Sub2API 的 LGPL-3.0 不是同一个许可证。I7 如果直接复制该仓库的
实现，需要在源码发布包中保留 Gemini Business2API 的 LICENSE/版权说明，并在第三方
依赖清单中分别记录两个项目的来源和许可证。
