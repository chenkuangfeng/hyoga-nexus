# 重实现前的核心调用链分析

日期：2026-10-25。只使用本地固定快照的实际源码与测试；未将旧审查报告当作本轮已阅读证据。本文是初轮核心深读结果，不表示两个项目全部核心、平台或测试均已完整审查。其余项进入 tasks 的 B0/逐模块深读关卡，未满足前不能迁移该模块或宣称完成。

## 来源与许可

GenericAgent：`a9a36b4b219593369de01c3e5973e56ac02e568b`；根 MIT，Copyright 2025 lsdefine。WeKnora：`e1f9a6166a593a4804a2f99f1d942919c9cc8ea7`；根 MIT，Copyright 2026 Tencent，根许可证另列第三方例外。已阅读根许可，具体实现依赖/片段的归属仍须随每批复用核对。

“抄核心代码”的实现方式：Python 可复用算法保留原逻辑复制；Go 逐分支翻译；服务化、异步、多用户和数据治理的改变单独说明。不能把两个完整应用复制进来当依赖，也不能将 shell/宿主共享 memory 直接带入多用户服务。许可声明保留在实际派生模块与包内文档，不恢复用户已删除的 third_party 目录。

## GA 执行与会话：已核对的实际顺序

完整阅读 agent_loop.py。`agent_runner_loop` 创建 system/user→agent_before→逐 turn 的 turn_before/llm_before→消费生成器→llm_after→native tool_calls 或内置 no_tool→Handler.dispatch→StepOutcome→done queue→turn_end_callback→turn_after。下一回合只传新增 user/tool_results，完整 history 在模型 Session，不能把“本轮 messages 只有一条”误当历史丢失。

分支细节：

- dispatch 给 args 注入 `_index`/`_tool_num`；普通返回与 yield from 的最终返回分开。未知工具和 bad_json 返回 next_prompt，真实动作调用与展示输出不同。
- should_exit 优先结束；无 next_prompt 为当前任务结束，不是下一工具继续执行。`_done_hooks` 是 FIFO 收尾提示，非强制退出时可再请求模型。next_prompts 原实现为 set，有去重但顺序不确定；目标需要稳定次序适配。
- 自然结束会在 turn_after 前 break；agent_after 也非 try/finally 保护。hook 返回 dict 可传给后续 hook，但 loop 不使用返回值；共享对象原地修改仍生效。
- 每十回合重置工具说明缓存；verbose/nonverbose 消费同一个生成器，但公开内容清理不同。只复制循环表面而漏掉工具说明、结束分支与回调顺序会改变行为。

定点深读 agentmain.GenericAgent 的模型加载/next_llm/abort/put_task/run：任务与输出 Queue、后台线程、运行锁与模型锁、输入/输出历史、当前 Queue 供刷新重附着；模型切换保留完整 backend.history 且禁止运行中直接切换；abort 同时设置 stop、工具停止信号、关闭活动 response/socket；finally 复位运行态并 task_done。队列串行语义需要由平台同 Session 互斥/Outbox 等价承载，而不是在 worker 内再启动第二个 GA loop。

## GA 工作记忆、工具与长期记忆

定点阅读 ga.GenericAgentHandler 的 init、工具输出倍率、code_run、ask_user、checkpoint、no_tool、长期整理、fold/anchor、turn_end_callback，以及 plugins/hooks 全文。

- ask_user 通过 should_exit 与候选列表交给入口，不是原循环内阻塞等待；平台 waiting_input 的回答与恢复需要保留工具结果关联和剩余调用。
- no_tool 区分 content 与 thinking 全空、异常尾标记、DSML/截断、单个大代码块与说明正文。`_retry_or_exit` 的计数在原 handler 中累计且第三次退出，代码澄清另走提示分支；当前 CompletionPolicy 的重置/阈值语义不能直接声称相同。
- checkpoint 只在显式有 key_info 时更新，清 passed_sessions；原 handler 在跨任务传递 key_info 时提示旧内容，防止把上个任务约束无条件当本次事实。
- 锚点最近 30 条、奇数回合历史、每四回合旧历史折叠、同批工具仅首个注入；回合总结移除代码/thinking，优先 summary，并按 175/17/41/15 的优先顺序注入提醒。提醒发生在回合末与下一回合前锚点并不天然等价。
- start_long_term_update 不是一个“建草稿”接口：它提供整理指令、读取 L0、检测 L1 过长、限制早期回合并要求索引同步和最终用户报告；原文件写回靠工具。完整迁移必须同时实现合法读取/整理/索引/发布，不能只保留草稿端口。
- code_run 有文件模式、shell 推断、timeout≤600、inline_eval、工作目录复位等分支；后者属于宿主执行。暂缓执行能力仍需记录这些算法与依赖，但不会因为核心重做自动启用。

## WK ReAct：已读主循环与关键分支

定点深读 engine.executeLoop/runReActIteration/runRoundTools，observe.manageContextWindow/runCompaction/analyzeResponse，think.callLLMWithRetry，act.executeToolCalls/Parallel/failTruncatedToolCalls/runToolCallAnswered 的参数修复段。

- executeLoop 以 defer 保证一次 completion 通知；该通知用于保存步骤，不等于平台 Run 成功。CurrentRound 的 next/continue/break 是显式三态，empty retry 可不推进 round；独立逻辑回合和请求 attempt 很重要。
- 单次迭代先压缩，再 drain steer，再注入 background，最后记录 lastSentMsgCount。当前 Nexus 在压缩前 drain 指令，不能认为已严格保持此时序。
- 请求前 sanitize 只用于发给 provider 的投影；结构化 engine history 保留分段。overflow error 与响应命中上下文上限共用 once 标记；强制压缩后再发一次，不能把普通传输重试当作这条路径。
- runCompaction 有 exhaustion-at-message-count，新增历史后才允许再尝试；释放太少时不继续付费压缩，但仍保存可用 summary checkpoint。成功压缩清 usage baseline 与 sent-message 计数。当前简短 compact() 并没有这些完整分支。
- analyzeResponse 区分过滤、自然停止、空内容、纯文本截断和工具回合；空内容不得先发 terminal answer；纯文本截断交付一次并标记 truncated，避免从头续写；结束前仍要 drain steer/background，不能提前关闭 UI 流。
- 连续 length 与无工具重复保护分别计数，空文本也算重复；cancel during stream 保存部分步骤而不把其当完整答案。预算耗尽/fallback 的上游“IsComplete”不能直接映射业务成功，需要沿错误/部分结果口径适配。
- 工具参数 repair 区分可修复语法和被截断的值；修复截断字符串即使 JSON 可解析仍拒绝执行。长度截断整批工具用相同失败事件/历史投影记录。
- 并发只读批次与变更屏障严格按序：先 drain 先前读，再执行变更，再开后续读，最大并发 8；失败 best-effort 不取消同级，panic 隔离到对应调用，结果/事件回到模型原序。不能仅用 gather 实现“并发工具”。
- 核心主循环还直接依赖协作、MCP exposure、页面按钮、产物和 background；这些不在 P0–P2 独立产品范围中，但必须登记依赖/未迁移行为，不删掉相应分支后说完整复制了 engine.go。

## WK 快照、审批与平台边界

全文阅读 suspend.go：版本化 RunSnapshot、PendingRound/BlockedIndex、原始 query/用户指令、累计 usage、已完成 steps 与 provider metadata、pending calls 及未解析 handle、collaboration cursor/MCP exposure。捕获快照前验证 blocked 范围和前序调用均完成；未知版本拒绝；关闭未恢复 Run 时为未完成调用补结果。JSON NUL 清理区分真实转义与转义反斜杠，关联 PostgreSQL jsonb 约束。不是将剩余 ToolCall 列表放进 state 就覆盖了通用快照。

全文阅读 approval/grants.go、application/service/agent_share_scope.go；types/agent_grant.go 与 session_management_scope_test.go 定点核对：

- ActionGrant 包含用户/空间、session/automation scope、grant key、binding hash、risk、最后使用/过期/撤销；风险覆盖与配置变化会使授权失效，automation 有 90 天 idle 规则。资源共享 Grant 与一次性 Approval 不能替代它。
- 共享 Agent 不等于能扩大底层资源：只核查新增 KB 范围，all 要管理员，外空间资源按原 scope 处理。Nexus 需要按 Workspace/ResourceBinding/ResourceGrant 逐点映射，而不是机械照搬 Tenant ID。
- Session 管理测试区分 owner/admin、其他角色和 embed/API/MCP principal，跨 tenant 返回不可见；管理员也不意味着所有来源主体都能管理所有会话。完整服务/仓储实现和组合入口仍须继续深读，当前只读测试不能当作完成迁移。

## 当前 Nexus 对照与类集中证据

基线 AST 检查：persistence/models.py 589 行包含 Base 和 34 个记录类，共 35 类；runs/execution.py 415 行同时包含 ExecutionContext、准备过程、DurableRuntimeStore、输入恢复；runs/service.py 424 行聚合提交/领取/取消/事件；registry/__init__.py 定义三个类，gateway/__init__.py 放权限与执行业务；ProtocolState 同时管理 Responses/Anthropic。问题不以行数定性，而在职责和变更原因混合。

NativeEngine 已 218 行并调用多个模块，但仍直接识别 builtin 名、维护模型上下文、工作记忆、工具结果、审批待处理列表与状态清理；当前 compact 用字符阈值和简化摘要切点，WorkingMemory 没有完整用户历史边界与回合末等价证明。重实现应针对实际行为和数据归属分解，不只是继续给旧方法换名。

现有协议错误/终态/用量修复、同空间授权、Run 幂等、SSE 与 worker 不能无理由退回。已有正常路径/夹具回归不是双项目完整等价证据；新实现以旧对外契约与上游原分支双向验证。

## 本轮离线执行证据

执行固定 GA agent_loop.py 的真实 agent_runner_loop，使用最小离线 client/handler 只探测循环控制，无网络/工具/应用入口：

- 无 done prompt：model_calls=1，CURRENT_TASK_DONE；顺序为 agent_before→turn_before→llm_before→llm_after→turn_end_callback→agent_after，终止回合无 turn_after。
- 一个 done prompt：model_calls=2；首轮有 turn_end_callback/turn_after，第二轮终止时再次跳过 turn_after。

此探针执行真实上游循环，但模型和工具为离线输入；只证明所列分支，不代表完整上游测试或生产能力。没有重跑 Nexus 全量测试、供应商在线调用或 Go 测试；当前 PATH 无 Go。此前 240 passed 的交付记录不能冒用为本轮源码等价验收。

## 尚未完成的深读关卡

1. GA llmcore 全部协议/历史/文本工具/冷却与配置分支、prompt/schema、memory SOP/插件/入口相关测试，不能仅沿用以前已删除审查的结论。
2. WK think 的完整流/首包与停滞检测、compactor/settings/serialize/overflow/token 校准、modelcontext、resume/hitl/approval gate/policy 及原测试。
3. WK 平台主体/空间、Agent/模型/资源共享、session/service/repository/handler/container 的完整调用链、事务与生产配置；P1 与当前 Workspace 逐项差异。
4. 本轮读取的测试文件也有定点范围，尚未转换与运行全部原断言；六项工具及其他阶段依赖继续显式登记。

这些是实施前必须逐模块满足的条件，而非用“以后参考”抵消迁移工作。源码指纹如下，只列本轮涉及的核心文件，不重新生成全仓几千项大索引。

| 项目 | 源文件 | SHA-256 |
| --- | --- | --- |
| GenericAgent | `agent_loop.py` | `c4f65ace32d1499e5db10ce69d81545234c29417076d2eab892e2e6879b65bfd` |
| GenericAgent | `agentmain.py` | `327d5b27012356df39e8c12f444ba61d2eba87cad9aa87a1ed72958c0516ab7f` |
| GenericAgent | `ga.py` | `6271e6ad80b9ca7302029f1a70e823544b5d117f57300efffa0a722843a8afbd` |
| GenericAgent | `plugins/hooks.py` | `5dfaaa7abf21a892c9696c9a973af219c6da7bdb72db43e9747145bd371f0e06` |
| WeKnora | `internal/agent/engine.go` | `c12e81655f4c70bd884f5e1cf90cd57b0300c681ce3cb790ed22ca88f3f5992e` |
| WeKnora | `internal/agent/observe.go` | `5124f3d6e9d2e8050f354430517701e310d0b539b9829db2f2e34b485884db0e` |
| WeKnora | `internal/agent/think.go` | `3be55547f0db2147cfadf27383f1b8cd81ac15fe9091f314f0199724a9e26b4a` |
| WeKnora | `internal/agent/act.go` | `eabbada5e3689980d9452cd86b3ed88ad0cf79f6d58fdac3f33c72b67c911142` |
| WeKnora | `internal/agent/suspend.go` | `97f5d9b83987f4a4dbf51073b836f30ba1a31846cab9e393d84b7617c1b968b5` |
| WeKnora | `internal/agent/checkpoint.go` | `c21c9c4323974e3099e4d4c86cb513add4b34a0b2ab4a925560f509c5c5f3322` |
| WeKnora | `internal/agent/compaction/cutpoint.go` | `cd82583949569825f5c42ec0ef569861f2e96803db3862b7dc680a0016c1400d` |
| WeKnora | `internal/agent/approval/grants.go` | `c7140297190748c5c52d112cd10744d4cd9ed13a5d2a9e1714da2f66cf5f0bdf` |
| WeKnora | `internal/agent/steer_order_test.go` | `f06163f8112fb432287eba3c71399fac70220263795fe6688bb0a4ee8bbee6e8` |
| WeKnora | `internal/agent/act_order_test.go` | `39da0d0012cf34bdaf113cfdaef34941026719e99e404fc1174866dced6fe3ef` |
| WeKnora | `internal/agent/length_truncation_test.go` | `183a4fd72ba0ab9badcbc11d4596b8a06417e5eeaa175336243c3fea0db61765` |
| WeKnora | `internal/application/service/agent_share_scope.go` | `424d39718a40ff34be478680f95fe200c7f5e5289e0fdf64a2e69856917cb6b2` |
| WeKnora | `internal/application/service/session_management_scope_test.go` | `4d91f716ede373e5aede60dad4d03761035819352d539717abf04acebcebecce` |
| WeKnora | `internal/types/agent_grant.go` | `5b72e48b63e8f7b6542506aceb0ec84065c5fdb406fb7f8a360955a05d9e2830` |
