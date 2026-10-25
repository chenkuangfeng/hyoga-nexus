# 通用智能体 9 大核心模块与 Hyoga-Nexus 博采众长选型方案

> 生成日期：2026-10-25
> 对比范围：`/project/deer-flow`、`/project/WeKnora`、`/project/ragflow`、`/project/hermes-agent`、`/project/GenericAgent`、`/project/hyoga-nexus`

本文档汇总了对五个外部参考项目（**Deer-Flow**、**WeKnora**、**RAGFlow**、**Hermes-Agent**、**GenericAgent**）与 **Hyoga-Nexus** 的源码级横向对比，提炼出通用智能体（General Agent）的 **9 大核心模块标准架构**，深入剖析了 **知识库（Knowledge Base）与记忆（Memory）的边界、触发机制与协同闭环**，并给出每个模块向 **Hyoga-Nexus** 移植时的具体借鉴选型、源码锚点、落地方案与避坑清单。

---

## 一、 六大项目核心底座横向对比基线

### 1.1 9 大核心维度横向对比总表

| 维度 | **Deer-Flow** (全栈多智能体平台) | **WeKnora** (企业级 RAG 问答底座) | **RAGFlow** (深度知识编译与 Agentic RAG) | **Hermes-Agent** (极客全能个人助手) | **GenericAgent** (极简自进化种子) | **Hyoga-Nexus** (强治理垂直生产力平台) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **核心定位** | 基于 LangGraph 的异步工作流与沙箱多智能体编排 | 基于 Go 的无状态多租户知识库问答与 Agent 服务 | 深度文档解析 (DeepDoc) + 知识编译 + Agentic RAG 引擎 | 多端 IM 网关接入的全天候本地/容器生产力 Agent | 300 行主循环 + SOP 自进化的极简宿主机 Agent | 显式受控状态机 + 强版本/权限/审计治理的垂直平台 |
| **1. 会话与生命周期** | `RunManager` + `ThreadState` 双层解耦；支持 `reject`/`rollback`/`interrupt`/`enqueue` 并发策略 | **无状态 Session 容器**：Go 实例不驻留会话，状态存 Redis + PG；Redis Pub/Sub 跨实例 Cancel | `harness/core/AgentLoop` 支持推模式缓冲、抢占 (`preemptCtrl`) 与中断检查点保存 | SQLite (`state.db`) 持久化 + 多渠道网关动态会话路由；支持 `parent_session_id` 会话分叉链 | 进程内全局变量 + 磁盘文件，无多用户/多会话并发隔离；支持 `fork` 自重启 | PG 双平面分离：交互会话 (`chat_sessions`) 与后台分析执行 (`analysis_runs`) 解耦 |
| **2. 认知与执行引擎** | LangGraph 状态图 + 14 层洋葱圈 Middleware + `SubagentExecutor` 并发子智能体池 | Go 同步 ReAct 循环 (`AgentEngine`) + Hook 拦截器 | Eino ReAct Agent + **独立 `SynthModel` 兜底汇总隔离** + **流式已吐字禁重试** + **检索裁判断路器** | 单文件巨型同步 Loop (`AIAgent.run_conversation`) + 进程池 Subagent (`delegate_tool`) | 300 行 `agent_runner_loop` + `BaseHandler.dispatch` 动态分发 `do_<tool>` | 显式有限状态机 `RunRunner`，拒绝黑盒多智能体自治 |
| **3. 上下文与消息记录** | 链式 `RunJournal`（通过 `parent_id` 支持树状分支）+ `SummarizationMiddleware` + `DurableContextMiddleware` | 滑动窗口加载近期历史 + Redis 瞬态流与 PG 最终消息双写 | **`EvidenceRegistry` 自动省略本轮重复召回段落正文（省 30%~50% Token）** + `LargeToolResult` 截断 | **双轨存储** + **严守 System Prompt 静态化保 KV Cache** + 两阶段 `ContextCompressor` | **三层递进工作记忆**：`raw_history` + `history_summary` + `working_checkpoint` (`key_info`) | 平台数据库强 Schema 组装 + 模板化 Prompt 注入 + `WorkingCheckpoint` |
| **4. 原子工具与沙箱** | `SandboxProvider`（Local / Docker / K8s）+ `/mnt/user-data` 虚拟路径映射 + MCP | Go 内置 RAG 检索工具集 + 受控沙箱执行 + MCP | 正交检索/导航工具集 + 受控 JS 执行 (`tool_run_javascript`) + MCP | 6 大执行后端（Local / Docker / SSH / Modal / Daytona / Singularity）+ 超大输出自动转存文件 | 9 个宿主机原生工具（`code_run` / `file_patch` / `web_scan` 等），无沙箱隔离 | 强权限网关封装的确定性领域工具与受控命令执行 |
| **5. 技能系统 (Skill)** | **L1 延迟发现 (`describe_skill`) + 沙箱只读签名投射 (`projection.py`) + 静态 AST 安全扫描** | **Claude 规范三级渐进披露 + 独创 Installer Agent 安装期预烘焙租户技能镜像** | 模板化 Agent Mode (`conf/agentic_rag.yaml`) + Canvas 工作流编排 | **5 层目录扫描 + 平台/环境/App 准入过滤 + 防压缩保护 + `skill_manage` 自主热更新** | **SOP 即 Skill**：`global_mem_insight.txt` 指针表 + `memory/*_sop.md` + Python 脚本 | **版本化资源绑定 (`AgentVersion`) + 发布期依赖强校验 + “Skill 绝不授予额外权限”** |
| **6. 记忆与自我演进** | 异步去抖队列 (`MemoryUpdater`) 后台提炼全局 User Profile 与 Fact | 无跨会话自演进机制，聚焦企业静态知识库检索 | 聚焦知识库侧增量脏编译 (`WikiDirtyCompiler`)，弱化个人会话自进化 | SQLite FTS5 全文检索历史会话 + Agent 自主调用工具写回记忆与技能 | 读取 SOP 时触发 `log_memory_access` 统计与 `[SYSTEM TIPS]`；满 10 轮直接 `file_patch` 改写 SOP | 模型仅可调用 `propose` 提交 `memory_drafts` 草稿，必须经人工 `review` 审批后发布版本 |
| **7. 事件总线与观测** | `StreamBridge`（内存 / Redis Streams）+ `Last-Event-ID` 游标断点重连 | Go 泛型内存 `EventBus` + `SessionEventRelay` 桥接 SSE | `harness/events`（内存 / 本地文件 / NATS JetStream）+ 工具耗时与错误样本统计 | 回调函数驱动 CLI 渲染与 IM 网关消息定时编辑刷新 | 仅 `ui.py` 进程内 `Queue` 供终端/Streamlit 展示 | 异步队列流式推送 + 完整数据库审计表 (`run_events` / `tool_executions`) |
| **8. 控制面与安全治理** | **3 门禁 `required-secrets` 带外注入与 stdout 自动脱敏** + Sidecar 凭证代理 + Clarify 挂起 | 多租户隔离 (`TenantID`) + RBAC + 租户级环境变量声明 + AgentGrant | `internal/permission` 租户与数据集 (`DatasetIDs`/`DocIDs`) 强作用域绑定 | 危险命令正则拦截审批 + 项目级 `.agents/skills` 检疫门禁 (Quarantine) | 零权限与多租户治理（完全信任本地单用户环境） | 完整控制面（Workspace / RBAC / ResourceGrant / AgentVersion 发布校验 / 记忆审核） |
| **9. 知识库与证据溯源** | 轻量外部 `deerflow/rag/` 检索适配器接口 | **多租户混合 RAG + Neo4j 图谱 + 按图谱能力动态暴露工具** | **行业天花板**：DeepDoc 解析 + **知识编译 (`Claim` 原子命题/目录树/图谱同流索引)** + **`EvidenceRegistry` `[ID:n]` 确定性引用** + **两级动态工具门禁** | 无独立文档级知识库与 Citation 体系 | 无独立知识库模块（外部资料混放于 `memory/` 目录） | **独立的 `packages/knowledge`**：不可变 `DocumentVersion`、Pre-Filter 混合 RAG + 选配图谱、强制 `Citation` 证据回溯 |

---

### 1.2 参考项目核心优缺点速览

1. **Deer-Flow**
   * **优势**：工程化最完备的 Python 异步智能体底座；`RunManager` + `StreamBridge` 解决了长任务断线重连；`skills/projection.py`（沙箱只读投射）与 `secret_context.py`（请求级密钥注入 + stdout 脱敏）是极佳的安全标杆；14 层 Middleware 切面清晰。
   * **劣势**：重度耦合 LangChain / LangGraph 的消息与状态序列化体系，框架黑盒魔法较多；原生知识库仅有一层薄适配器。
2. **WeKnora**
   * **优势**：“无状态 Session 容器”天然适合云原生水平扩缩容；多租户知识库权限预过滤与图谱工具动态挂载设计清晰；针对禁网沙箱首创 **Installer Agent 安装期依赖预装与租户技能镜像固化**；多租户资源授权（`ResourceGrant` / `AgentGrant`）模型严谨。
   * **劣势**：Go 同步请求级 ReAct 循环对超长程自主研究任务的上下文压缩、树状分支与跨会话经验演进支持较弱。
3. **RAGFlow（2026 新架构 `internal/agentic_rag` & `internal/ingestion`）**
   * **优势**：**知识库与 Agentic RAG 领域的工程细节天花板**——首创 `EvidenceRegistry`（给模型所见段落分配 `[ID:n]` 短句柄并自动省略本轮重复召回段落正文，省 30%~50% Token 且彻底杜绝伪造 Citation）；知识编译将带原文逐字引语的 `Claim`（原子事实命题）与目录树/图谱并入统一索引流，导航时优先召回 `Claim`；细粒度正交工具集（`grep_chunks`、`list_chunks` 锚点展开、`navigate_structure`）配合两级动态工具门禁（启动前 1ms 探针 + 会话级 30min 负缓存）与检索裁判断路器（`decisionBreaker`），极具实战价值。
   * **劣势**：仓库正处于从 Python 向 Go（CGO 静态链接 C++/Rust 原生库 `pdfium`/`office_oxide`/`onnxruntime`）全面迁移的过渡期，构建链较重；缺少通用的 Skill 沙箱投射与受控自演进记忆审批体系。
4. **Hermes-Agent**
   * **优势**：**上下文工程（Context Engineering）极致精细**——严格保护 System Prompt 静态前缀以命中 LLM KV Cache，配合两阶段压缩器与活跃 Skill 防裁剪保护；支持平台/环境/App 级别的 Skill 准入过滤与 FTS5 跨会话全文检索。
   * **劣势**：核心循环 `run_agent.py` 超过万行，单文件巨石架构耦合重；无独立文档知识库与 Citation 证据体系；基于单机 SQLite，不支持多租户高并发服务化。
5. **GenericAgent**
   * **优势**：**极简主义与高信噪比的工作记忆设计**——300 行主循环清晰可控；`raw_history` + `history_summary` + `working_checkpoint` 三层递进记忆结构极大提升了长任务目标保持能力；读取 SOP 时自动记录访问频次并注入 `[SYSTEM TIPS]` 强制提取步骤到 Checkpoint 的机制以极小代价解决了“长任务遗忘 SOP”的痛点。
   * **劣势**：零多用户隔离、零沙箱防护、把外部事实与内部经验混同于 `memory/` 目录且允许模型直接覆写生产 SOP，不能直接用于多租户严肃场景。

---

## 二、 通用智能体的 9 大核心模块全景架构

```mermaid
flowchart TB
    subgraph Control["模块 8：控制面、安全治理与人机协同 (Control Plane, Security & HITL)"]
        RBAC["多租户隔离 / RBAC / ResourceGrant / 预算配额"]
        HITL["高危工具拦截审批 (Interrupt) & 记忆发布审核 (Review)"]
        SecretGate["请求级密钥网关 (Request-Scoped Secrets)"]
    end

    subgraph Entry["模块 1：会话与执行生命周期管理 (Session & Run Lifecycle)"]
        Gateway["多渠道接入网关 (Web / CLI / IM) & 会话路由"]
        RunMgr["后台化执行 (Background Run) / 并发门禁 / 分布式取消 (Cancel)"]
    end

    subgraph Core["核心认知与上下文层 (Brain & Working Memory)"]
        Loop["模块 2：核心认知与执行引擎\n(Agent Loop / ReAct / 中间件切面 / 受控只读 Subagent)"]
        Context["模块 3：上下文工程与消息记录\n(Prompt KV Cache 保护 / 两阶段压缩 / WorkingCheckpoint / EvidenceRegistry 去重)"]
    end

    subgraph FourPillars["能力与知识四柱矩阵 (Hands, Playbooks, Experience & Ground Truth)"]
        Tool["模块 4：原子工具与沙箱环境\n(领域工具 / Bash / MCP / 容器隔离)"]
        Skill["模块 5：技能与领域工作流系统\n(SKILL.md 三级披露 / 沙箱只读投射 / 依赖预烘焙)"]
        Memory["模块 6：长效记忆与自我演进系统\n(用户画像 / 记忆索引 / propose->review 经验沉淀)"]
        KB["★ 模块 9：知识库与证据溯源系统\n(不可变文档版本 / 知识编译 Claim & 图谱 / Pre-Filter 混合检索 / [ID:n] Citation)"]
    end

    subgraph Infra["模块 7：事件总线与实时可观测性 (Event Bus & Observability)"]
        EventBus["流式事件分发 (StreamBridge) / 游标断点重连 / 全链路审计轨迹 (run_events)"]
    end

    Entry --> Loop
    Loop <--> Context
    Loop --> Tool
    Loop <--> Skill
    Loop <--> Memory
    Loop <--> KB
    Skill -.->|"1. 编排检索与分析步骤"| KB
    Memory -.->|"2. 提供术语口径与偏好指导检索"| KB
    KB -.->|"3. 返回带 [ID:n] 句柄的去重原文证据"| Context
    Context -.->|"4. 提炼方法论提交 MemoryDraft"| Memory
    Control --> Entry
    Control --> Skill
    Control --> Tool
    Control --> Memory
    Control --> KB
    Loop --> EventBus
```

### 能力与知识层【四柱矩阵】职责边界（模块 4 vs. 模块 5 vs. 模块 6 vs. 模块 9）

| 核心模块 | 形象比喻 | 核心回答的问题 | 事实属性与治理特征 | 在 Hyoga-Nexus 中的对应包 |
| :--- | :--- | :--- | :--- | :--- |
| **模块 4：原子工具与沙箱**<br>*(Tool & Sandbox)* | **“手与安全车间”** | 智能体能执行什么**原子动作**？（跑代码、调行情接口、抓网页） | 动作执行权 + 容器隔离 + 超大输出自动落盘截断 | `packages/tools` + 沙箱后端 |
| **模块 5：技能与领域工作流**<br>*(Skill System)* | **“岗位操作手册 (SOP)”** | 面对复杂领域任务，应该**按什么标准步骤组合工具**？ | 程序性规范（`SKILL.md` 三级渐进披露），**绝不授予额外权限** | `packages/skills` |
| **模块 6：长效记忆与自演进**<br>*(Memory System)* | **“个人工作笔记与经验本”** | 当前分析到了哪一步（`Checkpoint`）？用户有什么偏好？过往踩过什么坑？ | 内部交互衍生状态，**非权威事实**，走 `propose -> review` 审批演进 | `packages/platform/memory` |
| **模块 9：知识库与证据溯源**<br>*(Knowledge Base & Citation)* | **“权威图书馆与证据链”** | 支撑研究结论的**外部客观原文证据**在哪里？出处是哪篇文档第几页？ | **权威事实源 (Ground Truth)**，版本不可变，强制 Pre-Filter 权限与 `Citation` | `packages/knowledge` |

> **补充边界（结构化领域数据源 `DataSource`）**：如 [`docs/pending/knowledge-base-implementation.md`](file:///project/hyoga-nexus/docs/pending/knowledge-base-implementation.md#L14) 所确立的铁律——**“结构化股票行情、财务数据和平台记忆不进入文档知识库或其图谱”**。结构化行情与财务报表由确定性领域工具（模块 4）精确查询，非结构化文档（财报原文 PDF、公告、研报）归入知识库（模块 9），经验与偏好归入记忆（模块 6）。

---

## 三、 专项深潜：知识库（Knowledge Base）与记忆（Memory）的边界、触发与协同

### 3.1 知识库 vs. 记忆：8 大工程维度对比

| 维度 | **知识库 (模块 9: Knowledge Base)** | **记忆 (模块 6: Memory)** |
| :--- | :--- | :--- |
| **1. 数据来源与产生方式** | **外部导入**：人工上传文档（PDF/MD/Docx）、外部公告/研报同步 | **内部衍生**：由会话历史、工具调用过程、模型反思（`propose`）或用户偏好沉淀生成 |
| **2. 事实权威性 (Truthfulness)** | **高权威（证据源 / Ground Truth）**：原文不可篡改，必须附带 `Citation`（文档版本 + 页码/Chunk 定位） | **非权威（经验/启发式状态）**：可能包含过时偏好或模型归纳偏差，**不可作为研究报告的客观事实依据** |
| **3. 颗粒度与存储形态** | **大颗粒度多模态文档**：原文件（对象存储） $\rightarrow$ 父子分块（Chunk） $\rightarrow$ 关键词/向量双索引 + 选配知识编译（Claim/目录树/图谱） | **细颗粒度结构化/半结构化条目**：短期 `WorkingCheckpoint`（JSON）、长期偏好/经验条目、SOP 草稿（`MemoryDraft`） |
| **4. 写入与变更管线** | **重资产异步编译管线**：上传 $\rightarrow$ 去重 $\rightarrow$ 不可变 `DocumentVersion` $\rightarrow$ 后台解析/分块/Embedding/知识编译 $\rightarrow$ 索引版本原子切换 | **轻量化状态流转**：短期检查点随 Step 实时更新；长期记忆走 `propose`（草稿） $\rightarrow$ 人工 `review`（审核）版本化生效 |
| **5. 权限与隔离边界** | **资源级多对多授权**：属于 Workspace 资产，通过 `AgentResourceBinding` 与 `ResourceGrant` 控制，**必须在检索前（Pre-Filter）计算授权范围** | **分层作用域（Scope）**：分为 `Run/Session` 级（工作检查点）、`User` 级（个人偏好）、`Agent/Workspace` 级（公共经验与 SOP） |
| **6. 淘汰与生命周期** | **按文档版本与业务有效性管理**：撤权、删除或上传新版本时，同步清理旧版本的向量与图谱索引 | **按时间衰减与热度淘汰**：短期记忆随会话归档；长期记忆按访问频次（`access_count`）与人工订正持续迭代或淘汰 |
| **7. Prompt 注入协议标签** | `<knowledge_evidence ref="n" doc_version="...">`（配合 `EvidenceRegistry` 短句柄，明确标识外部客观证据） | `<agent_memory scope="...">` / `<working_checkpoint>`（明确标识内部状态与经验参考） |
| **8. 观澜（投研）典型示例** | 《贵州茅台 2025 年年度报告.pdf》、证监会处罚公告库、卖方深度研报库 | “该分析师习惯用 DCF + PE 历史分位双视角”、“某接口查港股代码需补 0”、“当前 Run 已确认的 3 个财务疑点” |

---

### 3.2 运行时触发机制：Push（框架注入） + Pull（工具拉取） + Hook（生命周期钩子）

知识库和记忆**并非全部通过工具触发**，而是根据层级与运行阶段采用混合触发策略：

| 运行阶段 | **记忆 (Memory) 如何触发？** | **知识库 (Knowledge Base) 如何触发？** | **触发主体** |
| :--- | :--- | :--- | :--- |
| **1. 会话/Run 启动期**<br>*(拼装首轮上下文)* | **【框架自动 Push】**<br>直接往上下文注入：<br>① 当前会话 `WorkingCheckpoint`<br>② 用户核心偏好画像<br>③ **L1 记忆目录索引 (`memory_index`)** | **【框架自动 Push 仅目录元数据 + 工具面探针】**<br>① 注入当前 `AgentVersion` 已授权绑定的**知识库名称与简介列表**<br>② 执行 1ms 存在性探针（`datasetsHaveCompiledKnowledge`），按实际能力动态挂载图谱/结构导航工具 | **Runtime 框架代码**<br>*(无需模型调工具)* |
| **2. ReAct 推理循环中**<br>*(查细节 / 多跳找证据)* | **【模型调 Tool Pull】**<br>模型看 L1 索引发现某条历史经验有用，主动调用：<br>• `read_memory(id)` 读取 L2 全文<br>• `search_memory(query)` 搜历史记录 | **【模型调 Tool Pull（95% 主路径！）】**<br>模型根据问题自主拆解并改写查询词，组合调用正交检索工具族：<br>• `grep_chunks`（字面/正则精确匹配）<br>• `search_knowledge`（关键词+向量混合检索）<br>• `list_chunks`（按锚点 Chunk 上下展开阅读）<br>• `navigate_structure` / `query_knowledge_graph` | **LLM 自主决策**<br>*(通过 `tool_calls`)* |
| **3. 步骤推进 / 窗口满时**<br>*(维护短期工作状态)* | **【Tool + 框架阈值 Hook 双触发】**<br>• 模型主动调 `update_working_checkpoint`<br>• 或当上下文超阈值时，压缩器 Hook 强制拦截要求模型先更新 Checkpoint | **【`EvidenceRegistry` 自动去重拦截】**<br>同一 Run 内再次召回相同 Chunk 文本片段时，自动省略重复正文，仅返回首次分配的 `[ID:n]` 引用号 | **LLM 工具调用**<br>或 **Runtime 拦截器** |
| **4. 任务收尾 / 归档期**<br>*(经验沉淀与文档入库)* | **【Tool 提议 + 后台 Hook + 人工审批】**<br>• 模型调 `propose_memory` 提交草稿 $\rightarrow$ 人工调 `review` 审批生效<br>• `after_run` 异步钩子更新记忆访问热度统计 | **【确定性引用解析 + 异步文档编译】**<br>• `CitedIDsFromMarkers` 将报告中的 `[ID:n]` 还原为真实 `chunk_id` 与文档版本定位<br>• 新增文档走后台异步解析/分块/知识编译管线 | **后处理器 / 异步 Worker / 人工审批** |

---

### 3.3 知识库与记忆在单次 `AnalysisRun` 中的协同触发时序图

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant Runner as RunRunner & EvidenceRegistry
    participant LLM as 大模型 (Brain)
    participant Mem as 模块 6: 记忆系统 (Memory)
    participant KB as 模块 9: 知识库 (Knowledge Base)

    User->>Runner: 发起分析请求 ("分析茅台2025年报渠道改革成效")
    
    rect rgb(235, 245, 255)
        Note over Runner,KB: 阶段 1：启动期框架自动 Push & 动态工具面探测（不调工具）
        Runner->>Mem: 获取 WorkingCheckpoint + 用户偏好 + L1 记忆索引(memory_index)
        Runner->>KB: 获取已绑定知识库目录 + 探测是否存在知识编译/图谱产物 (compile_kwd)
        Runner->>LLM: 组装首轮上下文 (System静态前缀 + 记忆索引 + 知识库列表 + 动态挂载可用检索工具)
    end

    rect rgb(255, 248, 235)
        Note over Runner,KB: 阶段 2：ReAct 循环中模型通过 Tool 按需 Pull（记忆指导检索 + EvidenceRegistry 去重）
        LLM->>Runner: tool_call: read_memory(id="白酒行业分析口径")
        Runner->>Mem: 读取 L2 记忆正文 (+1 访问计数 & 自动附带 [SYSTEM TIP])
        Mem-->>LLM: 返回记忆正文 ("重点关注合同负债与i茅台直销占比...")
        
        LLM->>Runner: tool_call: search_knowledge(kb="年报库", query="茅台 2025 直销 i茅台 合同负债")
        Runner->>KB: Pre-Filter 权限过滤 + 混合检索 (或优先召回编译态 Claim 命题)
        KB-->>Runner: 返回候选 Chunk 列表
        Runner->>Runner: EvidenceRegistry.ServeText() 分配短句柄 ref="0", ref="1" (若文本已见过则省略正文)
        Runner-->>LLM: 返回带 ref="0", ref="1" 的原文证据块
        
        LLM->>Runner: tool_call: list_chunks(anchor_chunk_ids=["chunk_x"]) (展开被截断的跨页表格)
        Runner->>KB: 拉取相邻前后 Chunk
        KB-->>LLM: 返回完整上下文并登记 ref="2"
        
        LLM->>Runner: tool_call: update_working_checkpoint(已核实数据 & 引用 [ID:0][ID:2])
        Runner->>Mem: 更新当前会话 WorkingCheckpoint
    end

    rect rgb(235, 255, 240)
        Note over Runner,KB: 阶段 3：收尾期机械式 Citation 解析 & 经验沉淀触发
        LLM->>Runner: (可选) tool_call: propose_memory(diff="新增i茅台数字渠道核查要点")
        Runner->>Mem: 写入 memory_drafts 表 (status=pending_review)
        LLM->>Runner: 输出包含 [ID:0] [ID:2] 的最终报告文本
        Runner->>Runner: ExpandCommaCitations + CitedIDsFromMarkers 校验并映射为权威 Citation 对象
        Runner->>User: 输出带可点击精确 Citation 的研究报告
    end
```

---

## 四、 Hyoga-Nexus 9 大模块“博采众长”移植与落地方案

### 4.1 9 大模块选型总览矩阵

| 模块 | **首选抄作业对象** | **次选/补充对象** | **移植到 Hyoga-Nexus 的核心机制** | **坚决不抄（避坑）** |
| :--- | :--- | :--- | :--- | :--- |
| **模块 1：会话与生命周期** | **Deer-Flow** (`RunManager`) | **WeKnora** (分布式 Cancel) | 后台 Task 托管 + 并发冲突策略（`reject`/`enqueue`/`interrupt`）+ 跨实例取消广播 | 不抄 Hermes 的 SQLite 单机锁；不抄 GenericAgent 的进程全局变量 |
| **模块 2：认知与执行引擎** | **Deer-Flow** (Middleware 切面) | **RAGFlow** (`SynthModel` 隔离 & 断路器) + **Hermes** (Subagent) | `RunRunner` 洋葱圈 Middleware + **流式已吐字禁重试** + **独立 `SynthModel` 汇总实例** + **受控只读 Subagent** | 不引入 LangGraph 黑盒动态图；不抄 Hermes 万行单文件巨石类 |
| **模块 3：上下文与消息记录** | **Hermes-Agent** (KV Cache + 双阶段压缩) | **GenericAgent** (`working_checkpoint`) + **RAGFlow** (`EvidenceRegistry` 去重) | **Prompt 静态前缀隔离（保 KV Cache）** + **重复召回段落正文自动省略** + 两阶段压缩 + 结构化检查点 | 不抄 Deer-Flow 繁琐的 LangChain 消息序列化补丁 |
| **模块 4：原子工具与沙箱** | **Deer-Flow** (`SandboxProvider`) | **Hermes** (超大输出自动转存文件) | 统一 `SandboxProvider`（Local/Docker/K8s）+ 虚拟路径映射 + 超长工具输出落盘截断 | 不抄 GenericAgent 的宿主机裸跑 `subprocess` / `inline_eval` |
| **模块 5：技能系统 (Skill)** | **Deer-Flow** (延迟发现 + CoW 投射) | **WeKnora** (安装期镜像预装) | **L1 延迟发现** + **激活态防压缩追踪** + **沙箱只读签名投射** + **离线依赖预烘焙** | 不抄 Hermes 允许模型在生产运行时直接 `skill_manage` 改写技能文件 |
| **模块 6：记忆与自我演进** | **GenericAgent** (读取钩子 + 热度统计) | **Deer-Flow** (异步去抖提取) | 在 Hyoga 现有 `propose -> review` 闭环上，增加**读取 SOP 时自动注入 Checkpoint 提示**与**记忆访问频次统计** | 不抄 GenericAgent/Hermes 的无审核直接覆写 SOP（破坏治理原则） |
| **模块 7：事件总线与观测** | **Deer-Flow** (`StreamBridge`) | **RAGFlow** (工具耗时/错误样本统计) | **内存 / Redis Streams 双模 `StreamBridge`**（支持 `after_seq` 游标重连）+ 工具级平均延迟与错误样本采集 | 不在主推理协程里对每个 `token_delta` 同步阻塞写 PostgreSQL |
| **模块 8：控制面与安全治理** | **Deer-Flow** (`required-secrets` 网关) | **保留 Hyoga 现有设计** | 在 Hyoga 现有 RBAC + 版本发布校验基础上，补齐**请求级密钥带外注入与 stdout/日志自动脱敏** | — |
| **模块 9：知识库与证据溯源** | **RAGFlow** (`EvidenceRegistry` + 知识编译 `Claim` + 正交工具族 + 两级门禁) | **WeKnora** (多租户 Pre-Filter 范围检索 + 图谱编排) | **Pre-Filter 权限过滤** + **`[ID:n]` 确定性引用句柄** + **`Claim` 原子命题编译** + **`grep_chunks`/`list_chunks` 正交工具** + **两级动态工具门禁与裁判断路器** | 不把结构化行情/财务指标或未审核的平台记忆混入文档知识库与图谱 |

---

### 4.2 逐模块落地设计细节

#### 模块 1：会话与生命周期管理
* **现状**：[`PlatformRunStore`](file:///project/hyoga-nexus/packages/platform/src/nexus_platform/runs/store.py) 已分离 `chat_sessions` 与 `analysis_runs`，但执行层仍在请求链路内直接驱动 [`RunRunner`](file:///project/hyoga-nexus/packages/runtime/src/nexus_runtime/runs/runner.py)。
* **源码参考**：
  * Deer-Flow：[`deerflow/runtime/runs/manager.py`](file:///project/deer-flow/backend/packages/harness/deerflow/runtime/runs/manager.py#L46-L150)
  * WeKnora：[`internal/application/service/session.go`](file:///project/WeKnora/internal/application/service/session.go#L110-L155)
* **Hyoga-Nexus 改造方案**：
  1. **后台执行池 (`RunWorkerPool`)**：API 收到创建 Run 请求后仅落库 `AnalysisRun(status='pending')` 并立即返回 `run_id`，交由后台 `asyncio.Task` 池（或独立 Worker 进程）异步消费执行。
  2. **同会话并发门禁 (`multitask_strategy`)**：当同一 `session_id` 存在未结束的 Run 时，支持按配置执行 `reject`（返回 409 Busy）、`enqueue`（入队等待前序完成）或 `interrupt`（中止前序 Run 并启动新 Run）。
  3. **分布式优雅中止 (`Cancel`)**：通过 Redis Pub/Sub 广播 `cancel:{run_id}` 信号，触发目标 Worker 调用 `task.cancel()`，在 `finally` 块中完成沙箱回收并写入 `run_cancelled` 事件。

#### 模块 2：核心认知与执行引擎
* **现状**：[`RunRunner`](file:///project/hyoga-nexus/packages/runtime/src/nexus_runtime/runs/runner.py) 是干净的显式 Python 状态机。
* **源码参考**：
  * Deer-Flow：[`deerflow/agents/middlewares/loop_detection_middleware.py`](file:///project/deer-flow/backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py)、[`deerflow/subagents/executor.py`](file:///project/deer-flow/backend/packages/harness/deerflow/subagents/executor.py)
  * RAGFlow：[`internal/agentic_rag/agent.go`](file:///project/ragflow/internal/agentic_rag/agent.go#L50-L200)、[`internal/agentic_rag/decision_breaker.go`](file:///project/ragflow/internal/agentic_rag/decision_breaker.go)
  * Hermes-Agent：[`tools/delegate_tool.py`](file:///project/hermes-agent/tools/delegate_tool.py)
* **Hyoga-Nexus 改造方案**：
  1. **保持纯 Python 显式主循环，引入轻量 Middleware 协议**：定义 `RunMiddleware` 接口（`before_model_call`、`after_model_call`、`wrap_tool_call`、`on_run_finish`），避免引入 LangGraph。
  2. **死循环检测中间件 (`LoopDetectionMiddleware`)**：对每次工具调用的 `(tool_name, canonical_json(args))` 计算签名；同一签名连续出现 3 次时在工具返回中追加系统警告，达到 5 次时临时剥夺该工具调用权，强制模型基于已有信息汇总结论。
  3. **流式已吐字禁重试 + 独立 `SynthModel` 实例隔离（抄 RAGFlow `agent.go`）**：
     * 遇到 429/529/网络闪断时按指数退避重试，但**一旦模型已向客户端流式发出任何正文 Token，严禁自动重试**（防止前端拼接两段半截话）；严格区分连接阶段超时（可重试）与单轮总生成超时（Fail Fast）。
     * 当 ReAct 循环达到最大步数上限触发强制总结（`finalize_answer`）时，使用独立的 `SynthModel` 客户端实例，防止主循环模型实例的 Failover 冷却状态污染最终总结。
  4. **受控只读子任务 (`spawn_readonly_subrun`)**：针对“同时对比多家公司财报”等高噪音并行场景，允许主 Run 在平台配额内派生只读子 Run（拥有独立上下文窗口、继承当前 Workspace 只读权限、禁止再派生子任务），执行完毕后仅将结构化结论汇入主 Run。

#### 模块 3：上下文工程与消息记录
* **现状**：[`packages/prompts`](file:///project/hyoga-nexus/packages/prompts/) 与 `RunRunner` 尚未实现针对长程多步工具调用的 KV Cache 保护与多阶段压缩。
* **源码参考**：
  * Hermes-Agent：[`agent/context_compressor.py`](file:///project/hermes-agent/agent/context_compressor.py#L1050-L1200)
  * Deer-Flow：[`deerflow/agents/middlewares/durable_context_middleware.py`](file:///project/deer-flow/backend/packages/harness/deerflow/agents/middlewares/durable_context_middleware.py)
  * GenericAgent：[`ga.py`](file:///project/GenericAgent/ga.py#L525-L580)（`raw_history` / `history_summary` / `working_checkpoint`）
  * RAGFlow：[`internal/agentic_rag/evidence_registry.go`](file:///project/ragflow/internal/agentic_rag/evidence_registry.go#L55-L86)
* **Hyoga-Nexus 改造方案**：
  1. **System Prompt 静态前缀铁律（保 KV Cache）**：将 `AgentVersion` 的固定角色指令、Tool Schema、Skill L1 索引固定在 System Prompt 最前端且**跨轮次字节级不变**；动态变化的当前时间、已激活 Skill 状态、`working_checkpoint` 统一注入到独立的 `<durable_runtime_context>` 消息块中，使长程分析任务的 LLM Prompt Cache 命中率保持在 85% 以上。
  2. **检索证据去重与两阶段上下文压缩 (`ContextCompactor`)**：
     * **Phase 0（实时去重，抄 RAGFlow `EvidenceRegistry.ServeText`）**：同一 Run 内多次检索若命中同一 `(chunk_id, sha256(snippet_text)[:16])`，后续工具返回直接省略重复正文，仅提示参看已发布的 `[ID:n]`，省去 30%~50% 的冗余检索 Token。
     * **Phase 1（工具输出脱水）**：距离当前轮次超过 N 步的超长工具返回（如几百行原始财报表格），自动替换为 `[已归档至 tool_execution:{id}，摘要：...]`，但豁免近期加载的 `SKILL.md` 正文（借鉴 Hermes `_collect_protected_skill_names`）。
     * **Phase 2（历史区间折叠）**：当总 Token 超过模型窗口阈值（如 75%）时，保留首尾消息，将中间轮次压缩为结构化 `<history_summary>`。
  3. **结构化工作检查点 (`working_checkpoint`)**：借鉴 GenericAgent，在 Run 状态中维护显式的检查点槽位（包含 `objective`、`verified_facts`、`citations`、`active_sop_steps`、`pending_questions`），确保即使经历多次上下文压缩，核心研究脉络与证据引用也绝不丢失。

#### 模块 4：原子工具与沙箱执行环境
* **现状**：[`packages/tools`](file:///project/hyoga-nexus/packages/tools/) 需补齐安全隔离的代码/脚本执行后端与大输出保护。
* **源码参考**：
  * Deer-Flow：[`deerflow/sandbox/`](file:///project/deer-flow/backend/packages/harness/deerflow/sandbox/)
  * Hermes-Agent：[`tools/`](file:///project/hermes-agent/tools/)
* **Hyoga-Nexus 改造方案**：
  1. **统一 `SandboxProvider` 抽象**：定义 `SandboxSession` 协议，支持 `LocalRestrictedSandbox`（开发调试）与 `DockerPoolSandbox`（生产环境无外网容器池，预装 Pandas/Numpy/Matplotlib 等投研计算库）。
  2. **虚拟路径映射与 Artifact 自动采集**：模型在沙箱内仅能访问 `/workspace/inputs`（只读）、`/workspace/skills`（只读投射）和 `/workspace/outputs`（读写）；`/workspace/outputs` 下生成的图表或报告文件自动由平台采集并登记为 `RunArtifact`。
  3. **超大输出自动落盘截断**：单次工具输出超过阈值（如 16KB）时，自动将完整内容写入沙箱临时文件，仅向模型返回头部预览、行数统计与文件路径，防止单次工具调用撑爆上下文。

#### 模块 5：技能与领域工作流系统 (Skill System)
* **现状**：已有 [`skills/guanlan/stock-analysis/SKILL.md`](file:///project/hyoga-nexus/skills/guanlan/stock-analysis/SKILL.md) 及“Skill 不越权”原则，需补齐渐进式披露、沙箱脚本投射与离线依赖治理。
* **源码参考**：
  * Deer-Flow：[`deerflow/skills/describe.py`](file:///project/deer-flow/backend/packages/harness/deerflow/skills/describe.py)、[`deerflow/skills/projection.py`](file:///project/deer-flow/backend/packages/harness/deerflow/skills/projection.py)、[`deerflow/skills/security_scanner.py`](file:///project/deer-flow/backend/packages/harness/deerflow/skills/security_scanner.py)
  * WeKnora：[`internal/agent/skills/skill.go`](file:///project/WeKnora/internal/agent/skills/skill.go#L36-L79)、[`internal/application/service/tenant_skill_install.go`](file:///project/WeKnora/internal/application/service/tenant_skill_install.go)
  * Hermes-Agent：[`agent/skill_utils.py`](file:///project/hermes-agent/agent/skill_utils.py#L90-L193)、[`tools/skills_tool.py`](file:///project/hermes-agent/tools/skills_tool.py#L121-L136)
* **Hyoga-Nexus 改造方案**：
  1. **三级渐进式披露 + 防重复加载**：
     * **L1**：仅将当前 `AgentVersion` 已绑定且有权限的 Skill `name` + `description`（Skill 数量多时可开启延迟发现，仅放名称列表）注入 Prompt。
     * **L2**：模型调用 `load_skill` 时返回 `SKILL.md` 正文，同时启用会话内去重（借鉴 Hermes `dedup_skill_view`）并将技能名记入 `RunState.active_skills`（受防压缩保护，且写入 `run_events` 审计）。
     * **L3**：Skill 目录下的 `scripts/`、`references/`、`templates/` 仅在沙箱内按需读取或执行。
  2. **沙箱只读签名投射 (`SkillProjection`)**：借鉴 Deer-Flow `projection.py`，仅将当前 `AgentVersion` 显式绑定的 Skill 目录生成带 SHA256 清单的只读视图挂载进沙箱 `/workspace/skills/{skill_slug}`，拦截一切越界软链接。
  3. **发布期安全扫描与依赖预烘焙**：借鉴 Deer-Flow 的 `security_scanner.py`（静态 AST / Shell / 硬编码密钥扫描）与 WeKnora 的预装理念，严禁 Skill 在对话运行期联网执行 `pip install`，所有依赖必须在技能入库/版本发布阶段完成扫描与镜像预烘焙。

#### 模块 6：长效记忆与自我演进系统
* **现状**：Hyoga-Nexus 已具备领先的 [`propose`](file:///project/hyoga-nexus/packages/platform/src/nexus_platform/runs/store.py#L222-L235) $\rightarrow$ 人工 [`review`](file:///project/hyoga-nexus/apps/api/src/nexus_api/http/native.py#L74-L86) 受控演进工作流。
* **源码参考**：
  * GenericAgent：[`ga.py`](file:///project/GenericAgent/ga.py#L444-L446)（`do_file_read` 中的 `log_memory_access` 与 `[SYSTEM TIPS]`）
* **Hyoga-Nexus 改造方案**：
  1. **读取 SOP / Memory 时的自动提醒钩子（Read-Time Hook）**：当模型调用 `read_memory` 或 `load_skill` 时，在返回文本末尾自动追加：
     `"[SYSTEM TIP] 请将该 SOP/记忆中的关键执行步骤与约束条件立即提取并更新至 working_checkpoint 中。"`
     这一极简机制能显著降低长任务后半段模型偏离 SOP 的概率。
  2. **记忆与技能热度遥测 (`Access Telemetry`)**：在 `memory_entries` 与 `skill_usages` 上记录 `access_count` 与 `last_accessed_at`，帮助平台管理员识别高频核心 SOP 与长期未被调用的僵尸记忆。

#### 模块 7：事件总线与实时可观测性
* **现状**：[`store.py`](file:///project/hyoga-nexus/packages/platform/src/nexus_platform/runs/store.py) 使用进程内 `asyncio.Queue` 配合 `run_events` 表。
* **源码参考**：
  * Deer-Flow：[`deerflow/runtime/stream_bridge.py`](file:///project/deer-flow/backend/packages/harness/deerflow/runtime/stream_bridge.py)
  * RAGFlow：[`internal/agentic_rag/agent.go`](file:///project/ragflow/internal/agentic_rag/agent.go#L103-L120)（`ToolCallCounts` / `ToolCallErrors` / `ToolErrorSamples` / `ToolCallDurations`）
* **Hyoga-Nexus 改造方案**：
  1. **抽象 `StreamBridge`（支持游标断点续传）**：提供 `MemoryStreamBridge`（单机）与 `RedisStreamBridge`（多实例生产环境），每个流式事件分配单调递增序号 `seq`，前端 SSE 断线重连时携带 `Last-Event-ID` / `after_seq` 即可无损补齐漏掉的增量输出。
  2. **高频流式帧与落库审计事件分离 + 工具级诊断汇总**：高频 `token_delta` 仅经 `StreamBridge` 推送前端；在 `run_finished` 时借鉴 RAGFlow 自动汇总每个工具的调用次数、失败次数、首个错误样本（`ToolErrorSamples`）与累计耗时，让单次慢 Run 或异常 Run 无需翻查底层日志即可一眼定位瓶颈。

#### 模块 8：控制面、安全治理与人机协同
* **现状**：Workspace、RBAC、ResourceGrant、AgentVersion 发布校验与记忆 Review 已就绪。
* **源码参考**：
  * Deer-Flow：[`deerflow/runtime/secret_context.py`](file:///project/deer-flow/backend/packages/harness/deerflow/runtime/secret_context.py)、[`deerflow/sandbox/env_policy.py`](file:///project/deer-flow/backend/packages/harness/deerflow/sandbox/)
* **Hyoga-Nexus 改造方案**：
  1. **请求级密钥网关 (`Request-Scoped Secret Broker`)**：
     * Skill 或 Tool 在元数据中声明 `required_secrets: ["TUSHARE_TOKEN", "WIND_API_KEY"]`。
     * 执行沙箱脚本时，必须同时满足三重门禁：**① Workspace 已配置该凭证 $\times$ ② 当前 `AgentVersion` 已授权绑定该 Skill/Tool $\times$ ③ 该 Skill 在当前 Run 中已激活**，平台才将凭证通过内存通道注入子进程环境变量。
  2. **输出与日志强制脱敏 (`Secret Scrubbing`)**：在沙箱 stdout/stderr 返回给模型或写入 `tool_executions` / `run_events` 表之前，自动将所有已注入密钥的明文替换为 `[REDACTED]`，确保**沙箱进程可用、大模型与日志不可见**。

#### 模块 9：知识库与证据溯源系统 (Knowledge Base & Citation System)
* **现状**：已在 [`docs/pending/knowledge-base-implementation.md`](file:///project/hyoga-nexus/docs/pending/knowledge-base-implementation.md) 完成 P3.1 ~ P3.5 详细设计。
* **源码参考**：
  * RAGFlow：[`internal/agentic_rag/evidence_registry.go`](file:///project/ragflow/internal/agentic_rag/evidence_registry.go)、[`internal/agentic_rag/citations.go`](file:///project/ragflow/internal/agentic_rag/citations.go)、[`internal/agentic_rag/tool_navigate_structure.go`](file:///project/ragflow/internal/agentic_rag/tool_navigate_structure.go)、[`internal/agentic_rag/compiled_knowledge.go`](file:///project/ragflow/internal/agentic_rag/compiled_knowledge.go)、[`internal/agentic_rag/nav_tool_enablement.go`](file:///project/ragflow/internal/agentic_rag/nav_tool_enablement.go)、[`internal/agentic_rag/decision_breaker.go`](file:///project/ragflow/internal/agentic_rag/decision_breaker.go)、[`internal/parser/tableutil/table_html.go`](file:///project/ragflow/internal/parser/tableutil/table_html.go)
  * WeKnora：[`internal/application/service/graph.go`](file:///project/WeKnora/internal/application/service/graph.go)、[`internal/agent/tools/query_knowledge_graph.go`](file:///project/WeKnora/internal/agent/tools/query_knowledge_graph.go)、[`internal/application/service/agent_tool_surface_test.go`](file:///project/WeKnora/internal/application/service/agent_tool_surface_test.go)
* **Hyoga-Nexus 改造方案（融合 WeKnora 权限骨架 + RAGFlow 深度机制）**：
  1. **检索前权限强过滤（Pre-Retrieval Scope Filtering，抄 WeKnora）**：在调用向量服务或图谱服务前，先根据当前 Principal、Workspace、`AgentResourceBinding` 与 `ResourceGrant` 计算出可见的 `(kb_id, doc_version_id)` 范围，杜绝“先全局召回再过滤”。
  2. **`EvidenceRegistry` 确定性短句柄与防幻觉后处理（抄 RAGFlow `evidence_registry.go` & `citations.go`）**：
     * 检索工具向模型返回的每个段落均按本轮首次出现顺序打上 `ref="n"`（`[ID:n]`），模型在答案中只写 `[ID:n]`，不再让模型手抄复杂 UUID `chunk_id`。
     * 答案生成后，自动执行 `ExpandCommaCitations`（将模型合并写的 `[ID:1, ID:3]` 拆为标准单标记）、剥离超出本轮 `EvidenceRegistry` 范围的伪造编号、并将标记置于行内反引号（`` ` ``）外部。
  3. **知识编译：同流索引与 `Claim`（带原文引语的原子命题）优先召回（抄 RAGFlow `tool_navigate_structure.go`）**：
     * 在可选的知识编译/图谱阶段，除抽取实体关系外，支持从财报/研报中编译抽取带逐字原文证据的原子事实命题（`entity_type_kwd="claim"`，格式：`<命题> | Evidence: "<原文引语>" [chunks: c1]`），并作为带 `compile_kwd` 标签的记录存入同一套索引引擎。
     * 结构化导航检索时，通过关键词覆盖率下限（`>=0.3`）+ 向量余弦相似度下限（`>=0.4`）+ RRF 融合优先召回 `Claim`；无 `Claim` 命中时再回退至目录树下钻。
  4. **正交细粒度检索工具族 + 父子分块锚点展开（抄 RAGFlow `internal/agentic_rag/tool_*.go`）**：
     * 除 `search_knowledge`（关键词+向量混合检索）外，提供 `grep_chunks`（针对证券代码、科目名、表号的精确字面/正则匹配）、`doc_outline`（文档章节大纲浏览）以及 `list_chunks(anchor_chunk_ids)`（围绕命中 Chunk 上下展开相邻块，配合父子分块彻底解决跨页财务表格被切断的问题）。
  5. **两级动态工具门禁与重排/裁判断路器（抄 RAGFlow `compiled_knowledge.go`、`nav_tool_enablement.go`、`decision_breaker.go`）**：
     * **第 1 级（Run 启动前 1ms 探针）**：探测当前绑定知识库是否存在已编译的图谱/结构产物，不存在则直接不注入 `query_knowledge_graph` / `navigate_structure` 工具。
     * **第 2 级（会话级 30min 负缓存）**：运行中若某高阶工具确认数据集级缺失，自动在当前会话中屏蔽该工具 30 分钟，防止模型空转重试。
     * **断路器降级（Circuit Breaker）**：当重排（Rerank）、小模型裁判（Decision Judge）或图谱服务连续失败 3 次时，断路器打开 60s 直接旁路降级回基础混合检索，避免每次检索因外部组件超时而卡死数分钟。

---

## 五、 推荐分阶段落地路线图（Roadmap）

1. **Phase A（低成本高收益：上下文工程、SOP 遵循率与执行防呆质变）**
   * 落地 **模块 3**：System Prompt 静态前缀隔离（保 KV Cache）+ 两阶段工具输出压缩 + `working_checkpoint`。
   * 落地 **模块 6**：读取 Memory / Skill 时自动注入 `[SYSTEM TIP]` 钩子与访问频次统计。
   * 落地 **模块 2**：`LoopDetectionMiddleware` 死循环检测切面 + 流式已吐字禁重试 + 独立 `SynthModel` 汇总实例。
2. **Phase B（打通深度领域工作流与权威证据链：Skill + 知识库 + 沙箱）**
   * 落地 **模块 5**：Skill 三级渐进披露、`RunState.active_skills` 防压缩保护、沙箱只读签名投射 (`SkillProjection`)。
   * 落地 **模块 9**：`packages/knowledge` 文档生命周期、Pre-Filter 混合 RAG、**`EvidenceRegistry` `[ID:n]` 去重与确定性引用**、`grep_chunks`/`list_chunks` 正交工具族、两级动态工具门禁、裁判断路器与选配知识编译（`Claim` + 图谱）。
   * 落地 **模块 4**：统一 `SandboxProvider` 抽象、虚拟路径映射与超大工具输出自动落盘截断。
3. **Phase C（生产级高可用与企业安全闭环）**
   * 落地 **模块 1 & 7**：`RunManager` 后台 Worker 化、同会话并发冲突策略、分布式 Cancel、`StreamBridge` 游标断点续传、工具级耗时与错误样本统计。
   * 落地 **模块 8**：三重门禁 `required_secrets` 带外注入与输出自动脱敏网关、受控只读子任务 (`spawn_readonly_subrun`)。
