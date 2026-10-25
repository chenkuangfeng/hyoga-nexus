# 目录设计与依赖边界

本文件对应实际骨架。P1 已落地的 Workspace/Agent/Run 持久化实现位于 platform 包；P2 的 Native、工具与对话模块已落地；其他空包与目录仍只是占位，功能状态见总体架构。

```text
hyoga-nexus/
├── apps/
│   ├── api/src/nexus_api/          # FastAPI 入口、http、schemas、dependencies
│   ├── worker/src/nexus_worker/    # 后台入口、jobs、scheduler
│   └── web/src/                   # Element Plus 工作台
│       ├── api/ components/ composables/ layouts/
│       ├── router/ stores/ types/ # 只预留目录，尚未接入路由/状态库
│       └── views/
│           ├── OverviewView.vue   # 平台能力状态页
│           ├── agents/ chat/ resources/ knowledge/
│           └── channels/ settings/ guanlan/
├── packages/
│   ├── core/src/nexus_core/       # 公共协议、agents、tasks、events、tools
│   ├── platform/src/nexus_platform/
│   │   ├── identity/ workspaces/ agents/ sessions/ runs/
│   │   └── resources/ models/ memory/ jobs/ persistence/ observability/
│   ├── runtimes/src/nexus_runtimes/
│   │   ├── native/                # engine、context、models（OpenAI-compatible）
│   │   ├── adapters/              # codex、claude_code、deepseek
│   │   └── capabilities/
│   ├── skills/src/nexus_skills/   # registry、loader、bindings、versions
│   ├── tools/src/nexus_tools/     # registry、gateway、builtins
│   ├── mcp/src/nexus_mcp/         # client、gateway、server
│   ├── knowledge/src/nexus_knowledge/
│   │   └── domain/ ingestion/ parsing/ indexing/ retrieval/
│   │       citations/ providers/ persistence/
│   ├── sandbox/src/nexus_sandbox/# contracts、local、docker、artifacts
│   ├── connectors/src/nexus_connectors/
│   │   └── common/ web/ wecom/ wechat/ qq/
│   └── guanlan/src/guanlan/
│       ├── domain/ data/          # providers、repositories、ingestion、quality、schedules
│       └── analysis/ announcements/ hotspots/ dragon_tiger/
│           backtesting/ reports/ tools/ evaluations/
├── skills/
│   ├── general/                  # 通用技能内容预留
│   └── guanlan/                  # 股票分析、公告、热点、龙虎榜、回测技能草稿
├── configs/                      # agents、models、channels 的非敏感示例
├── migrations/                   # platform Alembic、knowledge、guanlan
├── docs/adr/                     # 技术决策记录
├── tests/                        # 软件测试，后续按模块增设目录
├── evals/                        # agent、knowledge、skills、guanlan 基准样例
├── scripts/                      # 开发辅助入口
├── examples/                     # 集成与配置示例预留
├── infra/docker/                 # 部署预留
├── docs/                         # 架构、模型、契约、计划和参考分析
├── pyproject.toml                # Python workspace / 应用组合依赖
└── uv.lock
```

## 为什么这样拆

- core 是稳定协议，platform 是平台应用服务，runtimes 是执行器，三者不混在一个 Agent 类里。
- 技能、工具、MCP、知识库分别管理，再由智能体绑定；不会每增加一个 Runtime 就复制一套资源。
- packages/skills 管理技能机制，顶层 skills 保存指令与资源内容，两者职责不同。
- knowledge 处理文档证据，platform/memory 处理记忆，guanlan/data 处理结构化股票数据。
- sandbox 是跨 Runtime 执行边界，connectors 是消息边界，股票逻辑只放 guanlan。
- packages 是可安装 Python 包；内部目录是模块，不等于独立部署服务。

## 本轮迁移

保留原有包名与导入；Codex/Claude Code/DeepSeek 占位目录移至 runtimes/adapters，新增 native。core/memory 空占位移至 platform/memory。现有前端能力页移至 views/OverviewView.vue，App.vue 保留应用入口。新增包纳入 workspace、锁文件与安装脚本，CI 使用锁文件安装。

没有复制 GenericAgent/WeKnora 源码，没有实现计划中的业务接口，也没有一次性安装尚未使用的数据库、模型或解析 SDK。

## P2 实际模块

- `core/runtime/`：按模型、工具、预算、事件、取消、记忆与 Sandbox 分布的厂商无关契约；`core/native/` 保存 Native 策略和 hook DTO，原导入路径继续导出。
- `platform/runs/`：提交、查询/事件、领取、取消、执行准备、持久适配和输入恢复分别组织；`service.py`、`execution.py` 保留原导入入口；`platform/persistence/models/` 按领域组织实体，共用唯一 Base。
- `runtimes/native/engine`、`context`、`models`：模型/工具循环、有界摘录、SDK 适配；`tools/registry`、`gateway`、`builtins`：工具注册、授权执行和安全内置工具。
- `apps/worker/native.py`：模型凭据、工具与持久化的组合入口；`apps/web/src/api/chat.ts`、`types/chat.ts`、`composables/useConversation.ts`：类型化通信与对话状态。
- `migrations/platform/versions/b5a16ed22801_native_runtime.py`：P2 增量迁移；`tests/test_native_*.py`、`tests/web/conversation.mjs`：隔离验证。

使用方式见 [worker](../apps/worker/README.md) 和 [Web](../apps/web/README.md) 说明。没有新增 SQLite 应用后端产品模式，也未实现隔离 Sandbox 或文件产物。

## 用户模型设置

`platform/models/provider_settings.py` 管理供应商、密文和默认偏好；API `http/model_settings.py` 提供设置与有界连接测试；Web `views/settings/ModelSettingsView.vue`、`composables/useModelSettings.ts` 和 `api/modelSettings.ts` 提供用户设置。Runtime `native/models/network.py` 实现目的地址检查和 DNS/IP 固定，worker 显式装配。迁移为 `c8d240ab1701`，模型继续使用不可变版本。

## 部署配置文件

`configs/nexus.example.toml` 是数据库连接示例；工作目录下的 `configs/nexus.toml` 为被忽略的实际配置，由 platform 配置模块统一读取，API、worker 和 Alembic 共用。规则见 [configs](../configs/README.md)。
