# reg2 注册机账号导入

Status: current

## 适用范围

本手册用于把 reg2 注册机里已经注册成功、带 Access Token 和邮箱密码的
账号导入本系统账号池，供普通生图模型调度使用。

reg2 导入账号保存为 `source=reg2`、`source_type=web`。普通生图请求不限制
账号来源，会从这些账号里取号；Codex 图片模型仍只选择 `source_type=codex`
的账号。

## 前置条件

1. reg2 状态页已经包含 `生图 JSONL` 导出按钮。
2. 本系统后台账号池页面已经包含 `导入 reg2 注册机账号` 导入模式。
3. 操作账号需要后台管理员权限。
4. 导入文件必须至少包含 `access_token` 和 `password`。缺少任一字段的行会被跳过。

## 导出

在 reg2 状态页勾选要导出的账号，然后执行其中一种操作：

1. 点击 `生图 JSONL`：只下载导入文件，不改变 reg2 出库状态。
2. 点击 `生图 JSONL 并出库`：下载导入文件，并把成功导出的账号标记出库。

导出文件名默认为 `reg2-image-site.jsonl`，内容是一行一个 JSON 对象。

## 导入

进入后台 `账号池管理`：

1. 打开 `导入/添加`。
2. 选择 `导入 reg2 注册机账号`。
3. 选择 reg2 导出的 JSONL 或 JSON 文件。
4. 如需统一归组，先在账号池选择目标账号组；未指定目标组时，系统会按
   reg2 导出的 `reg2_group` 自动创建或复用账号组。
5. 确认导入结果里的 `新增`、`跳过`、`坏行` 和 `同步` 数量。

## 支持格式

导入器支持以下本地文件内容：

1. JSONL：每行一个账号对象。
2. JSON 数组：数组元素为账号对象。
3. JSON 对象：对象本身为账号，或包含 `records` / `accounts` 数组。

字段别名兼容：

| 目标字段 | 支持来源 |
| --- | --- |
| Access Token | `access_token`、`accessToken`、`token`、`at`，或 `credentials`/`tokens` 容器内同名字段 |
| 邮箱密码 | `password`、`email_password`、`mail_password`、`mailbox_password`，或 `credentials` 容器内同名字段 |
| 2FA | `totp_secret`、`totpSecret`、`twofa_secret`、`otp_secret` |
| 分组 | `reg2_group`、`group`、`group_name` |

## 验证

导入后在账号池验证：

1. 过滤或搜索导入邮箱，账号状态应为 `正常`。
2. 账号来源应显示为 reg2/web。
3. 分组应为 UI 指定目标组，或 reg2 导出的分组。
4. 执行账号同步后，同步数量应覆盖新增账号。
5. 普通生图请求应能进入 `等待账号` 后成功选取这些账号。

代码级验证命令：

```powershell
cd D:\yewu\_repo_reviews\yukkcat-chatgpt2api
python -m pytest tests/test_reg2_import_api.py -q
python -m pytest -q

cd D:\yewu\_repo_reviews\yukkcat-chatgpt2api\web-vue
npm run build --silent
```

API 冒烟验证可以使用脱敏样例：

```powershell
cd D:\yewu\_repo_reviews\yukkcat-chatgpt2api
python scripts\smoke_reg2_import.py --base-url http://127.0.0.1:3000 --admin-key local-test-admin-key --no-sync
```

样例文件位于 `docs/runbooks/examples/reg2-image-site-sample.jsonl`，只包含
`.example.test` 邮箱和假 token。

## 失败处理

导入结果中：

1. `missing_access_token` 表示该行没有可用 Access Token，不能导入。
2. `missing_password` 表示该行没有邮箱密码，不能作为完整 reg2 账号导入。
3. `invalid` 表示文件行不是对象，或字段结构无法识别。
4. `skipped` 表示账号已存在或 token 已被现有账号接管。

处理方式：

1. 回到 reg2 确认账号是否已注册成功并生成 token。
2. 对缺密码账号，先修复 reg2 邮箱记录再重新导出。
3. 对已存在账号，优先在账号池搜索邮箱或账号 ID，不要重复导入。

## 回滚

误导入时，在账号池按导入分组或邮箱筛选后批量删除。删除账号会从本地账号池
移除，不会反向删除 reg2 的账号记录。
