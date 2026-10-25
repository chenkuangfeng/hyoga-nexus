# GenericAgent hooks 与插件模块审查

2026-10-25。来源 GenericAgent `a9a36b4b219593369de01c3e5973e56ac02e568b`，根 MIT / Copyright 2025 lsdefine。全文阅读 plugins 的四个 Python 文件并核对来源索引哈希；定点核对 agent_loop、agentmain 的装配与 ga.turn_end_callback。没有导入上游插件、调用 Langfuse 或复制实现。第三方 SDK 兼容性和许可证尚未验收。

## 注册、分发与装配

`plugins/__init__.py` 仅包标记。`hooks.py` 使用进程全局 registry；register 追加且不去重，unregister 按对象身份移除全部匹配，clear 可清单事件或全部，has 查询是否存在回调。trigger 按列表顺序调用，回调返回 dict 时替换传给后续回调的 ctx；普通 Exception 写 stderr 并继续，BaseException 不在捕获范围内。回调可以原地修改引用对象，没有类型、耗时和权限约束。

执行循环传入 locals()，但不接收 trigger 的返回值。因此返回 dict 可改变后续 hook 看到的上下文，不能据此声称会替换循环局部变量；共享 messages/args 等可变对象的原地修改可以影响执行。tool_after 只在工具正常返回后调用，模型/工具抛错没有 finally 保障对应 after；agent_after 也不保证异常退出时触发。终止回合可能在 turn_after 前 break，事件配对不能简单假定完整。

自动发现按文件名排序扫描非下划线 Python 文件，向 sys.path 添加扫描目录父路径，但 load 固定导入 plugins.name；传入任意目录并不保证从该目录实际导入。导入失败返回 false 并写 stderr，discover 不汇总失败；模块缓存意味着 clear 后再次 load 通常不会重新执行装饰器。扫描 hooks.py 本身也会经过 import 缓存。

## Project Mode

项目名从 handler.parent._ga_project_mode_name 取得，实例级激活状态与全局注册表分别存在。hook 从尾部查最后一条 user message，字符串拼接或多模态 list 追加 text block；无项目、无 user 或不支持的 content 类型不注入。没有重复注入标记。

L1 每轮包含项目目录、规则、记忆文件指针及收尾纪律；L2 文件全文不进入提示。_memory_stat 为统计行数和 UTF-8 字节数读取整个文件，权限/解码错误向 trigger 传播并被记录。代码开头目录注释含“全文注入”，与实际实现不符，应以函数逻辑为准。

项目名直接参与路径拼接，本模块没有规范化或授权；不能据此断言其他项目名入口也无校验。本次没有完整审查其激活命令。收尾纪律要求模型自行写文件，插件不自动完成记忆持久化、审核或发布。

## Langfuse tracing

导入时读取 langfuse_config 并尝试创建客户端；配置缺失、SDK 缺失或其他初始化异常均静默禁用。启用时注册 agent、LLM、tool 前后回调，并包装 llmcore 的 Claude/OpenAI SSE parser。

状态用 threading.local：任务 trace、单个 generation、工具 span 栈和 usage。agent_after 更新退出原因并 flush；LLM 输入/输出通过 str 截到 20,000 字符；工具参数仅过滤下划线开头字段，结果投影 data/next_prompt/should_exit。此过滤不是秘密脱敏，没有用户/空间授权或外发审批。失败大多吞掉，不应把“未报错”算作观测完整。

usage 提取兼容 Anthropic message_start/message_delta、Responses response.completed 及 Chat Completions usage；缓存创建/读取字段按对应分支保存。多数 token 字段按 truthy 判断，零值不覆盖旧值；坏 JSON 跳过。parser 包装将所有流行存入列表，原生成器正常结束后才提取 usage；异常/提前关闭没有 finally 提取，非流式请求没有在这里覆盖。没有显式恢复原 parser 的卸载流程。

## Nexus 当前映射与差异

定点阅读 native/hooks/registry.py、engine/runner.py 和现有两个 hooks 用例。当前 HookRegistry 是 Run 级、显式可信模块装配，注册去重、回调快照遍历、1 秒 timeout、typed HookTransform 和有界 user 消息/done prompts；失败发送不含原始错误的 hook.failed。runner 最终清理注册表。此为已存在实现，本批未改代码。

上下文变换仅允许 agent.before/after 与 turn.before/after；模型/工具生命周期还有独立接口，不能将两者合称完全等价于上游 locals 修改。返回变换受角色/长度限制，与上游任意可变对象不等价；同步可信模块导入失败的处理也需单独验证。项目模式完整管理和 Langfuse 插件尚无本批兼容证据。

后续批次需保留上下文注入、按需记忆读取、生命周期与 usage 观测的实际能力；全局注册、宿主路径与外发内容按平台隔离/授权适配，并在提案中明确。工具/文件能力暂缓时不能假设原项目收尾写文件可用。日常项目配置与观测启用须提供对应前端设置、服务端持久化和权限边界。

## 验证清单与边界

现有 Nexus 两个针对性用例用于检查上下文注入/收尾提示和多工具生命周期；本批执行 `uv run --locked pytest -q tests/test_native_parity.py::test_empty_and_code_recovery_and_completion_hooks tests/test_native_runtime.py::test_multitool_bad_arguments_hooks_and_session_history`，结果 2 passed、无跳过，耗时 2.98 秒；有一条 Starlette/httpx 弃用警告。它们不能证明上游全部插件兼容。

待补分支：重复注册/注销、触发时增删回调、返回 dict 与原地修改、普通异常/BaseException、模型/工具异常后的 after、重复加载/clear 后加载、超时与取消、项目多模态/重复注入/路径授权、缺失/坏编码记忆、并发 Run 与 asyncio 任务隔离、三种 usage/零值/坏 JSON、流中断和 span 清理、日志脱敏与跨空间观测边界。

检索上游 frontends/tests 未发现对这些插件文件的直接命名引用；cost_tracker 的 hook 测试属于另一观测实现，不能替代 Langfuse 验收。尚未执行上游插件或真实观测服务测试，完整测试映射仍未完成。
