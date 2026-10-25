# 用户模型设置验收

## 范围与参考映射

用户已确认提案。实现基于本地固定版本 WeKnora `e1f9a6166` 和 GenericAgent `a9a36b4` 阅读，不复制其源码。

| 参考行为 | 本项目实现 | 验证 |
| --- | --- | --- |
| WeKnora `frontend/src/api/model/index.ts` 多模型与 credentials configured 元数据 | 设置页多个供应商/模型，固定掩码与配置状态，无 Key 读取接口 | 设置查询/秘密保护及浏览器用例 |
| WeKnora `internal/application/service/model.go` UpdateModelCredentials，内置凭据管理员校验 | 个人归属与共享管理员校验；Key 替换下一次解析生效 | 个人隔离、管理员拒绝、凭据轮换测试 |
| WeKnora `model_copy_test.go`、`model_catalog_test.go` 配置归属/秘密边界 | 禁止旧接口复制加密凭据使用权限，密文绑定引用 ID | 旧接口旁路拒绝与密文完整性测试 |
| GenericAgent `llmcore.py` 模型配置与协议选择 | OpenAI-compatible 协议保留；模型版本固定，默认只用于创建 | 默认优先级与 Session/AgentVersion 保持测试 |
| 原有 Native 工具/等待/取消/SSE | 保持执行循环，新增模型权限复核与安全网络客户端 | 原有 Python 与对话浏览器回归 |

Typed 服务、独立数据库秘密表和受控网络是多用户平台新增边界；不将共享资源权限等同于个人凭据授权。`cryptography==47.0.0`、`httpx==0.28.1` 由锁文件确定。

## 验证

- `openspec validate user-model-provider-settings --strict --no-interactive` 通过。
- 本地文档链接检查与 `git diff --check` 通过。
- `uv sync --locked --extra dev` 通过。
- `uv run --locked pytest -q -rs`：38 passed、1 skipped，跳过 PostgreSQL 专项。
- 迁移用例覆盖空库 upgrade/downgrade/re-upgrade、保留已有 P1 数据、重复 upgrade；增量创建四张模型设置表。
- 新增设置测试覆盖个人/共享权限、密文与错误秘密保护、轮换与地址变更、停用/默认清除、默认优先级、旧版本/会话不变、旧 API 旁路拒绝、测试限流及 DNS/IP/Host/SNI 固定。
- 设置浏览器用例覆盖新增供应商/模型、默认选择、Key 不回显与取消清理、测试反馈、发布、停用、1440px/375px 布局和键盘操作。
- Node 22.23.4 下 `npm ci`、`npm run build` 通过；`npm run test:browser` 的既有对话与新增设置两套用例通过。

## 实际边界

未发送真实供应商请求；Provider 测试使用模拟 HTTP/模型。浏览器使用确定性 API/SSE 夹具，数据库测试使用真实 SQLite，不等同部署端到端验收。

API/worker 首次部署需要同一加密主密钥和 Alembic 升级。主密钥备份与受控重加密由部署管理，未实现自动主密钥轮换。供应商 Key 替换已实现。

PostgreSQL 迁移/锁/并发与故障恢复留到最后环境执行。沙箱仅保留接口，代码执行和文件产物不可用。FastAPI/Starlette 的 httpx 弃用与 Element Plus 全量引入的大 chunk 提醒为现有非失败警告。
