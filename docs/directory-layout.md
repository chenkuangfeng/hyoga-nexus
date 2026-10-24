# 目录设计与依赖边界

本文件对应实际骨架。P1 已落地的 Workspace/Agent/Run 持久化实现位于 platform 包；其他空包与目录仍只是占位，功能状态见总体架构。

```text
hyoga-nexus/
├── apps/
│   ├── api/src/nexus_api/          # FastAPI 入口、http、schemas、dependencies
│   ├── worker/src/nexus_worker/    # 后台入口、jobs、scheduler
│   └── web/src/                   # Element Plus 工作台
│       ├── api/ components/ composables/ layouts/
│       ├── router/ stores/ types/ # 只预留目录，尚未接入路由/状态库
│       └── views/
│           ├── OverviewView.vue   # 当前可运行的能力目录页
│           ├── agents/ chat/ resources/ knowledge/
│           └── channels/ settings/ guanlan/
├── packages/
│   ├── core/src/nexus_core/       # 公共协议、agents、tasks、events、tools
│   ├── platform/src/nexus_platform/
│   │   ├── identity/ workspaces/ agents/ sessions/ runs/
│   │   └── resources/ models/ memory/ jobs/ persistence/ observability/
│   ├── runtimes/src/nexus_runtimes/
│   │   ├── native/                # engine、context、prompts
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
