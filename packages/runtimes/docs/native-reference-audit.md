# Native 与 GenericAgent / WeKnora 源码差距审计

日期：2026-10-25。本文核对源码、工具 schema 和代表性测试；不是完整迁移验收，也不表示两个上游项目的所有文件均已逐行审查。

## 结论和证据范围

当前 Native 是已经本地验证的基础闭环，**没有完整迁移 GenericAgent，也没有完整迁移 WeKnora 的智能体能力**。原有 P2 验收矩阵证明的是已选闭环能力，不能据此断言与上游完整等价。

用户明确要求迁移方式改为：深度分析两个项目的实际逻辑与细节，按原源码复制或等价翻译迁移，保留模块结构，允许改善配置易用性，日常配置优先进入用户前端。当前只完成审计、规则更新和提案，尚未新增下面列出的 Runtime 能力。

| 项目 | 锁定源码 | 许可证 | 本轮范围 |
| --- | --- | --- | --- |
| GenericAgent | `a9a36b4b219593369de01c3e5973e56ac02e568b` | MIT，Copyright (c) 2025 lsdefine | agent_loop、agentmain、ga、llmcore、工具 schema、hooks/project_mode、记忆/SOP、代表性前端和测试 |
| WeKnora | `e1f9a6166a593a4804a2f99f1d942919c9cc8ea7` | 主项目 MIT；依赖按其 LICENSE 清单分别审查 | agent engine/think/act/observe/finalize、压缩、steer、审批/策略、技能管理和代表性测试 |

[源码索引](reference-source-inventory.tsv) 仅记录 git 已跟踪文本文件的相对路径、锁定提交、SHA-256 和阅读状态，不包含源码或配置内容。索引包含 GenericAgent 161 个、WeKnora 4735 个文件；文件数量不等于功能数量。`read_or_targeted_review` 表示已阅读或定点核查，`inventoried_not_reviewed` 表示尚未审查，不能据此勾选迁移完成。跨项目全量审查仍有明确待办。

## GenericAgent：核心执行差距

| 能力与上游位置 | Nexus 实际状态 | 差距与迁移要求 |
| --- | --- | --- |
| `agent_loop.py:agent_runner_loop` 模型→工具→下一轮 | 基础循环、流式文本、顺序多工具已实现 | 还缺 no_tool 完成判断、done hooks、可修改的回合收尾等原逻辑 |
| `StepOutcome(data,next_prompt,should_exit)` | ToolResult 的继续/完成/等待/退出已实现 | 语义映射不代表整套 Handler 逻辑已保留；原 `data` 可为结构化对象，当前主要为字符串 |
| `BaseHandler.dispatch` 普通函数/生成器工具 | 注册器只接受协作式 async 函数 | 没有生成器进度适配；需保留中间输出和最终返回值，不阻塞 worker |
| `ga.py:do_no_tool/_retry_or_exit` | 没有工具调用就直接 completed | 空响应、坏文本工具协议、仅大代码块等未走原判断；属于实质遗漏 |
| `_done_hooks` 收尾提示队列 | 缺失 | 上游保留此扩展点；本轮未查到默认入队生产者，不能误写为默认自动执行的功能 |
| `turn_end_callback` 摘要、提醒、hook | 只有生命周期元数据通知 | 缺少每轮摘要和 history_info、15/17/41/175 回合分支、turn-end 回调 |
| `_get_anchor_prompt/_fold_earlier` | 仅字符截断历史与启动时注入检查点 | 缺少长/短历史分层、按回合注入、当前工作记忆和跨任务过期提醒 |
| `get_system_prompt/get_global_memory` | 主要使用 Agent 配置指令 | 未迁移系统提示模板、日期/记忆索引组装和 L0/L1 导航；不能原样声称已获宿主权限 |
| `agentmain.py:abort` | 模型流取消、工具取消、未知副作用 interrupted 已实现 | 使用异步取消替代线程 socket hack，保留行为并补充对照测试 |
| `put_task/run` 串行 Queue | 同 Session 活跃 Run 互斥，忙时拒绝新 Run | 这是策略差异，不能宣称等同原排队；需要显式用户排队/插入行为设计 |
| `_intervene/_keyinfo` 与 turn-end 注入 | 缺失 | 用户只能等待输入或停止，不能运行中纠偏；需要持久化、有序消费和身份校验 |
| `_current_queue` 重新附着实时任务 | 有持久事件和 SSE 游标 | 属于平台化映射，须保留刷新/重连不重放任务的能力 |
| `next_llm/load_llm_sessions` | 多供应商设置已有；已发布 Session 固定模型 | 未实现原地热切换/历史迁移或显式会话分支，不能把创建另一会话称为等价切换 |
| `/session.*`、`/resume` | 未实现命令兼容 | 不迁移任意 setattr；由受控设置与会话恢复替代，差异须确认 |

核心源码：[agent_loop.py](https://github.com/lsdefine/GenericAgent/blob/a9a36b4/agent_loop.py)、[ga.py](https://github.com/lsdefine/GenericAgent/blob/a9a36b4/ga.py)、[agentmain.py](https://github.com/lsdefine/GenericAgent/blob/a9a36b4/agentmain.py)。

## GenericAgent：九项工具逐项核对

以 `assets/tools_schema.json` 中实际九项工具为准，不能拿三个安全内置工具称为完整工具库。

| 上游工具 | Nexus | 具体缺口 |
| --- | --- | --- |
| code_run | 只有 SandboxPort，调用被 gate 拒绝 | Python/shell、代码块取脚本、cwd、流式日志、超时、停止、输出配额与 inline_eval 都未迁移；用户此前明确沙箱暂不实现 |
| file_read | 缺失 | 行区间/行号、keyword 周边、长行截断、编码回退、记忆访问记录 |
| file_patch | 缺失 | 唯一匹配/重复匹配处理、newline、文件引用展开 |
| file_write | 缺失 | overwrite/append/prepend、正文 file_content 回退、引用展开、大写入提醒 |
| web_scan | 缺失 | 标签页列表/切换、HTML 简化、纯文本模式、上下文输出配额 |
| web_execute_js | 缺失 | script/代码块/文件来源、tab 切换、页面变化监测、结果保存 |
| update_working_checkpoint | 部分实现，接口不兼容 | 上游参数 key_info，本项目参数 content；缺少锚点回注、passed_sessions 与提示分支 |
| ask_user | 持久等待与回答已实现，接口不完整 | candidates 丢失，事件/持久字段/前端选项缺失；恢复机制不能冒充候选项兼容 |
| start_long_term_update | 未迁移，只有 propose_memory_draft | 缺少读 L0、L1/L2/L3 导航、整理触发、patch/同步索引和整理后的原任务报告 |

六项执行/文件/浏览器工具保持“未迁移、暂不开放”。不把占位接口标为完成；也不在缺少隔离后端时复制宿主 eval、subprocess、全局 cwd 或浏览器实例为默认可用能力。

## GenericAgent：模型、记忆与周边能力

| 能力 | 已有部分 | 仍缺细节 |
| --- | --- | --- |
| OpenAI Chat Completions | SDK 流式文本、工具参数片段、total usage、错误映射 | 非流式、reasoning/options 参数、更多 finish reason、完整 usage/cache 语义 |
| OpenAI Responses / Anthropic Messages | 未实现 | `llmcore.py` 对应流和非流解析、内容块转换、thinking 签名/缓存兼容；不是外部 Codex/Claude Code Runtime |
| 文本工具协议 ToolClient | 未实现 | tool_use 解析/容错、bad_json 恢复、工具 schema 缓存刷新和与 native tool call 的去重 |
| MixinSession | 未实现 | 多模型选择、预输出故障转移、部分流失败后下一次切换、spring-back、历史与配置一致性 |
| 请求重试 | 原实现明确关闭 SDK 自动重试 | 缺少可取消退避、Retry-After 上限、无可见输出前的受控重试，不能重放已执行工具 |
| 上下文压缩 | 保留最近完整工具交换、历史摘录 | 缺少 tag 分层压缩、keep-prefix、按模型窗口调整和摘要检查点，不能把截断称为语义总结 |
| 生命周期 hooks | before/after 元数据事件、异常隔离、运行级清理 | `LifecycleEvent` frozen 且无消息，不能替代原 hook 对上下文的修改；缺 register/unregister/discover、typed transformation 与 turn-end 扩展 |
| project_mode | 未实现 | 项目作用域、规则+记忆指针注入、按需读取和收尾沉淀；不复制共享 temp/projects 全局目录 |
| 长期记忆/SOP | 待审核草稿 | L0 治理、L1 指针、L2 事实、L3 SOP/脚本、L4 原始会话和索引同步均未形成闭环 |
| 内容块/图片 | ModelMessage.content 仅 str | 上游 llmcore 支持内容块；agentmain.put_task 的 images 字段本身不能证明图片端到端可用，需逐入口验证 |
| usage/成本/观测 | token 总预算、运行/工具事件 | input/output/cache、TTFT、TPS、成本账本、追踪插件未迁移；不复制明文完整 prompt 日志 |
| 子智能体/Hub/反射/定时 | 未实现 | --func/--task/--reflect、回复/干预/停止、调度与协作结果闭环；不能仅把 SOP 当实现 |
| 命令、导出、备份、桌面/多渠道 | 多数未实现 | 前端命令、历史/日志恢复、导出/备份、原生桌面/IM 适配各自独立待办；不是 Native 基础闭环的现成能力 |
| MCP | Nexus 未实现 | 上游 ACP 声明 MCP http/sse false，不能错误地列为“复制即可获得完整 MCP” |

依据：[llmcore.py](https://github.com/lsdefine/GenericAgent/blob/a9a36b4/llmcore.py)、[hooks](https://github.com/lsdefine/GenericAgent/blob/a9a36b4/plugins/hooks.py)、[项目模式](https://github.com/lsdefine/GenericAgent/blob/a9a36b4/plugins/project_mode.py)、[记忆 SOP](https://github.com/lsdefine/GenericAgent/blob/a9a36b4/memory/memory_management_sop.md)。

## WeKnora：值得直接等价翻译的智能体逻辑

WeKnora 不只是资源平台。`internal/agent/engine.go` 本身就是带状态、工具、流、上下文和恢复能力的执行引擎。其 Go 实现应翻译到本项目 Python 责任模块，不为复用引入整套 Go 服务或在 Native 外再套循环。

| 能力与源码 | 有价值的细节 | Nexus 差距与组合方式 |
| --- | --- | --- |
| engine/observe/length_truncation_test | 空响应有限重试、重复/卡死检测、自然结束与截断区别 | 修复当前空响应直接成功；结合 GA no_tool 保留代码待执行澄清分支 |
| act.go / act_order_test | 截断参数拒绝执行；只读工具可并行，写/执行/未知工具作为顺序屏障；单工具 panic 不拖垮同批 | 当前全顺序保留默认；并发扩展须显式能力声明与权限，不能直接打开全部并行 |
| think.go | context overflow 压缩后只重试一次、协议垃圾恢复、可取消退避、stream stall | 当前错误直接结束；迁移恢复策略，仍坚持不重放已完成工具、不拼接重复部分流 |
| finalize/terminal_event_test | 空重试不发终态；流过的答案不重复发送；取消/挂起不生成假完成 | 事件终态与用户看到的最终答案须分开设计并对照测试 |
| compaction + checkpoint + token/calibration | token 估算校准、保护最近交换、摘要跨回合检查点、摘要失败降级、无可压缩时停止 | 本项目只有字符摘录；按原边界翻译并与 GA 工作记忆锚点组合，保留原始历史 |
| steer.go / steer_test | 先持久化再注入、消费失败不越过队头、回合尾新指令不提前结束、额外回合有界 | 对应 GA intervene/keyinfo 的持久平台实现，解决用户运行中纠偏 |
| suspend.go / resume_test | 记录被阻塞工具位置、已完成调用、恢复快照；挂起不是取消或完成 | 当前 waiting_input 已持久化，但缺通用审批/协作恢复快照 |
| approval/hitl/policy/grants | read/probe/write/destructive，allow/ask/deny，参数修改、执行标记、会话授权/失效/绑定 hash | 现有 ResourceGrant 只管资源共享，不等价于动作审批；必须独立实现 |
| skills manager / loader | 元数据先发现、正文按需读取、安装来源与权限、资源和环境准备 | 与本项目 skills 包结合；指令与实际执行分离，未实现沙箱不能宣称脚本可运行 |
| tool registry / modelcontext | 授权工具面、延迟工具发现、统一输出预算、模型可见投影与 UI 数据隔离 | 当前 registry/公开摘要是基础；动态发现与完整 handle/citation 边界尚缺 |
| knowledge/citations/runtime context | 授权文档检索和引用、选中文档、mention MCP/skills、页面上下文 | 归 P3/P4 的能力也须逐项登记，不能笼统写成“后续知识库”后从对齐清单消失 |
| collaboration/background | 父子任务权限继承、挂起、消息交付、结果复核、取消传播和恢复 | 对 GA 子任务能力的多租户增强，不把子任务输出未经父任务审查即当最终答案 |
| memory prompt/tools | 已发布记忆提示注入和独立管理入口 | 补足当前只有草稿的缺口；知识、用户记忆、项目/SOP 仍分别管理 |

源码入口：[WeKnora agent](https://github.com/Tencent/WeKnora/tree/e1f9a6166/internal/agent)。本轮阅读代表性测试，没有运行 WeKnora Go 测试或依赖服务，不宣称其上游测试在本环境通过。

## 两项目必须先解决的冲突

1. **完成判断**：GA 有 no_tool 代码澄清、空/异常文本重试；WeKnora 细分自然结束、截断、内容过滤、卡死。做一张统一状态/输出决策表和差分测试，不能任选一个并删掉另一个的分支。
2. **运行预算**：GA CLI 常用 180 回合且有较长周期提醒；当前默认 12 回合；WeKnora 又有迭代与有限超额策略。保留可配置能力，在前端提供行为预设/预算，不静默更改已有已发布版本。
3. **模型切换**：GA 允许空闲时原地保留历史切换，Nexus Session 固定版本。需显式可追溯分支/模型选择记录，先确认契约；默认值不能暗改会话。
4. **记忆写入**：GA 直接 patch 文件并同步索引；Nexus 约定先草稿审核。迁移完整读取/整理/版本发布链路，保留审核边界，不能拿草稿替代整个原功能。
5. **工具能力**：宿主 Python/shell/文件/浏览器与多租户授权隔离冲突。用户已明确沙箱暂缓，本提案不能默认为解除限制；六项工具必须继续标为待迁移。
6. **hook 修改能力**：GA 使用 locals 引用变更；现有只读 metadata 丢失扩展能力。提供受控结构化变换，不把 secrets/全局对象暴露给插件。
7. **并发/重试**：GA 多工具顺序；WeKnora 只读并发与写屏障。顺序作为兼容默认，按能力显式启用，模型重试与工具副作用重放严格分离。
8. **上游提示和平台权限**：GA 提示声称宿主物理权限，部分原生模型代码带特定产品身份/头信息。本项目按实际授权能力和正式供应商协议映射，原细节全部记录，不直接拷贝越权声明、个人记忆或凭据日志。

## 结构和配置要求

以 GA 源码逻辑为迁移主干，按 WeKnora 已有 think/act/observe/finalize/compaction/policy/hitl 的职责拆分。Native 只有一个实际执行循环。`__init__.py` 逐步只做兼容导出；主 Engine 只编排，不承担模型解析、工具实现、记忆存取和审批持久化。

日常配置必须在前端用户设置提供：行为预设、模型协议/参数/故障转移、回合/输出预算、重试、上下文压缩、工作记忆提醒、项目/长期记忆范围、工具/技能/审批策略。按个人/空间权限保存版本与默认值。数据库、部署主密钥、服务启动/隔离基础设施才保留部署端例外，并说明原因。

## 本轮验证与限制

- `uv run --locked pytest tests/test_native_runtime.py -q`：20 passed；证明当前闭环回归，不证明上游完整对齐。
- `uv run --locked pytest /project/GenericAgent/frontends/tests/test_bridge_model_switch.py -q`：13 passed。该上游文件使用模拟 Session/Agent，不能作为真实供应商或真实热切换端到端证据。
- 独立内存模型探针：分别返回空文本、只有大代码块、未解析的 tool_use 文本，再发送合法 done(stop)。当前 Engine 三者均返回 `completed` 且无错误，直接证实 no_tool 分支缺口。
- 源码/许可证核对、索引和文档检查不代替真实供应商、WeKnora Go 部署、PostgreSQL 或隔离环境验收。
- 本轮未迁移任何上游源码、未新增执行权限、未安装上游整套依赖。

迁移实施范围、结构和验收任务见 [提案](../../../openspec/changes/native-reference-parity/proposal.md)。源码未读完、功能未迁完、部署未验收三者分别跟踪，不合并成“已完成”。
