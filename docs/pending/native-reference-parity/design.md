# 设计：来源明确、逻辑完整、职责分开

## 来源与单一执行循环
GA 的 Python 纯逻辑按经审查的函数/文件迁移，并记录源提交、路径、许可证与适配差异；WeKnora 按相同状态/输入/输出/失败语义翻译为 Python。迁移的是实际实现和测试，不是只借名词重写。异步、授权和持久化替换必须逐条证明兼容。

不启动 GenericAgent.run 再在外层套 NativeEngine；只保留一个模型/工具循环。NativeEngine 作为薄编排器，调用完成策略、回合执行、上下文和恢复服务。现有对外 core 接口、AgentVersion/Session/Run、工具授权与 SSE 保持兼容，通过新增契约或版本扩展能力。

## 目标模块（计划，按真实实现逐步创建）

```text
packages/runtimes/src/nexus_runtimes/native/
  engine/
    __init__.py        # 兼容导出
    runner.py          # 唯一 Run 编排/预算/取消
    turn.py            # 单回合模型与工具交互
    completion.py      # no_tool/自然结束/截断/重复/空响应判定
    recovery.py        # 回合恢复与收尾策略，不重放已完成工具
    state.py           # 回合/收尾队列等内部状态
  context/
    assembly.py        # prompt、历史、已授权记忆的组合
    working.py         # history_info/key_info/anchor/reminder
    compaction.py      # 摘要、保护尾部、溢出恢复
    checkpoints.py     # 摘要检查点与恢复边界
  models/
    openai_compatible.py  # 保留现有适配入口
    protocols/        # Chat Completions / Responses / Messages 适配
    tool_protocol.py  # 文本工具协议和 native tool call 去重
    routing.py        # Mixin 选择/回归策略
    retry.py          # 有界退避、Retry-After、可取消传输重试
    usage.py          # input/output/cache 等使用量
    network.py        # 保留现有目的地址安全边界
  hooks/
    registry.py       # 注册/注销、隔离、可信插件装配
    transforms.py     # typed 上下文变换和 turn-end 扩展
  prompts/
    assembly.py       # 原提示片段按实际能力组合，非宿主全权声明
packages/tools/src/nexus_tools/
  registry/           # 工具契约/版本、受控普通/生成器适配
  gateway/            # 执行授权、结果投影、顺序/只读并发屏障
  builtins/
    ask_user.py       # question/candidates + 持久等待
    checkpoint.py     # key_info/content 兼容
    memory.py         # 长期整理工具、来源与治理
    registration.py   # 按实际 capability 和配置装配
packages/platform/src/nexus_platform/
  memory/             # 领域/服务/仓储、版本/索引/审核，不依赖知识库实现
  runs/               # 运行中指令、通用输入/审批快照与幂等恢复
  resources/          # 动作审批与资源共享分别组织
apps/worker/          # 显式依赖装配
apps/web/             # 用户配置、候选回答、运行中输入和审批的独立页面/组件
```

一个功能按契约、业务逻辑、适配、测试与文档形成闭环；不把所有行为塞进一类，也不为上图批量创建空文件。跨包稳定协议放 core，并保留旧导入出口。

## 两项目冲突解决方案（待确认）

- 完成判断以完整决策表组合 GA no_tool 与 WeKnora 的空/截断/重复/过滤分支；代码块只有展示时可完成，需要动作时继续；不能把所有“无工具”都强制继续或都判成功。
- GA 旧参数和事件语义用兼容适配保留。checkpoint 支持原 key_info，旧 content 仍有效；ask_user candidates 进入类型、持久化、事件和 UI。
- GA 回合总结/工作锚点与 WeKnora 摘要检查点分工：前者保存当前意图/进度，后者保存历史压缩。原始记录保留，索引/摘要带来源、作用域与权限。
- GA 长期记忆直接 patch 替换为平台草稿→评审/验证→版本发布→索引同步→授权读取；完整功能都实现并测试，此为需确认的治理适配，不能伪称原实现字节等同。
- hooks 保留修改上下文的能力，用 typed 转换结果代替 locals 全局对象；插件只能在已有资源权限内工作，不能取得额外 Key/宿主权限。可信插件由部署装配；用户仅管理已安装能力的启用与配置。
- 原地模型热切换通过显式可追溯会话分支和模型版本选择实现，不改原 Session 的固定版本；完整历史/授权材料迁移与分支 UI 都需实现，不能只让用户手动重建空会话。
- 全顺序工具执行保持默认。只读/幂等能力显式声明后才可启用并发，写/执行/未知能力形成顺序屏障。审批消费、工具执行与结果未知分别持久记录。
- 受控预输出重试/故障转移允许可取消退避；部分流失败保留实际结果，不从头拼接重复流，不重放已经完成或副作用未知的工具。所有耗用进入预算。
- 预算/回合提醒提供原行为预设，但不静默修改已有已发布版本。预算耗尽时可以在预留预算中整理已验证结果，不能把未完成任务标 completed 或在停止后额外调用模型。
- 前端用户配置优先；个人和共享范围、管理员权限、默认优先级与版本快照明确。部署主密钥/数据库/启动/隔离后端为例外，不把重试、行为预设、记忆策略留成环境变量。

## 证据与对齐门禁

每项迁移记录来源/原测试、输入输出/异常/状态、目标模块、是否直接复制或翻译、兼容差异、差分/集成证据。代表性对照测试不能代替全部分支审查。上游测试无法运行时明确原因，补足可运行的等价测试并保留未验证标记。

六项执行工具及隔离/产物保持明确未完成；外围知识/技能/MCP、协作、调度、桌面/渠道按独立能力登记，不自动假设实现存在。该提案不能在只有核心补齐时以“全部迁移完成”归档。
