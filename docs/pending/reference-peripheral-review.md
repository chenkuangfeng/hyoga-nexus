# GenericAgent 外围入口与协作源码审查

2026-10-25；来源固定为 GenericAgent `a9a36b4b219593369de01c3e5973e56ac02e568b`。本次完整阅读以下三个文件，核对其索引 SHA-256；只做静态审查，没有导入、启动服务、执行脚本或调用模型。根 MIT 许可证已登记，实际迁移前仍须核对所用依赖及片段归属。

## UltraPlan：阶段编排与子任务

来源：`assets/ga_ultraplan.py`。

- `plan` 首次绑定 rundir；非 daemon 模式启动或连接回环 HTTP daemon，将当前脚本文本和 cwd 发送给 `/exec`，接收 stdout/stderr/returncode 后退出。并非纯计划数据上传。
- `/exec` 用 `_exec_lock` 串行运行脚本，临时改变全局 cwd/env，finally 恢复；`SystemExit` 映射返回码，普通异常输出 traceback。rundir 分隔的 `_sessions` 为进程内状态，没有持久恢复。
- `phase` 维护嵌套阶段与耗时，普通 Exception 标 fail；其余退出路径落入 finally，不能把阶段 done 作为任务成功证据。事件最多保留 60 条，任务最多 80 条。
- `_run` 接受 callable、tuple/list、dict；tuple/dict 生成提示文件并启动 `agentmain.py --func` 子进程，非零退出或 timeout 向上传播；普通值直接返回。
- `parallel` 默认最多三个线程，显式 max_workers 可覆盖；`executor.map` 按输入顺序返回结果。没有显式同级取消传播、预算共享或失败结果复核。
- `mapchain` 让不同 item 并行，每个 item 内逐步骤传递 previous/item；不构成任意有环图调度器。

目标归属：Runtime 协作编排、平台子 Run/阶段事件、worker 装配、前端阶段视图。需保留嵌套阶段、输入序结果、链式传值与异常语义；执行脚本、进程与 cwd/env 替换必须经过隔离能力。当前沙箱暂缓，不开放此执行路径。尚未迁移，不把任务列表界面等同于完整协作能力。

待验证：重复 plan、嵌套异常与 SystemExit、空并行、顺序结果与乱序完成、子进程超时后的清理、同级取消、重启恢复与跨空间隔离。上游测试目录定点检索未发现直接命名这三个模块的用例，不代表不存在间接覆盖。

## Agent BBS：板块消息与文件引用

来源：`assets/agent_bbs.py`。

- 每次请求通过 header/query key 选板块；配置按 mtime_ns 热加载，解析/校验异常保留旧配置。每板块有自己的 SQLite db。
- 注册同名用户会返回既有 token；发帖另验证用户 token。此身份语义不能直接替代平台 Principal/Membership。
- poll 以 id 升序、since_id 排他消费；posts 以 id 降序分页，支持作者过滤；count/authors 为独立查询。
- 上传校验 token，使用随机目录及 basename 保存原始字节；下载仅经板块 key 中间件，没有逐用户 token 检查。上传目录为全局目录，文件引用本身没有板块归属校验。
- CLI key 模式有后台空闲退出逻辑；活跃时间仅在发帖时更新，读取/上传不重置计时。不能概括成所有请求都延长存活。

目标归属：平台协作消息与受授权产物服务；游标消费、作者过滤、文件引用需分别登记。板块 key、同名取回 token、共享上传目录不能照搬为多租户授权。替换为现有身份体系及产物授权属于提案需确认的行为适配。文件能力暂缓，消息总线也尚未实现此兼容。

待验证：配置热加载失败、重复注册、跨板块引用、撤权、游标边界、上传大小及流式处理、空闲退出与活动定义。

## HTTP App：单实例任务和监控

来源：`assets/ga_httpapp.py`。

- 模块加载即创建 GA、后台线程和全局 outputs/stopped；数据操作接口支持 header/query key，根监控 HTML 无需 key，实际轮询接口另校验。
- put_task 忙时返回 `ok=false`；input 空闲时投递，忙时写 intervene，锁内复查避免空闲/运行转换竞态。abort 调用 GA abort，并不立即设置 stopped。
- run_task 以 turn 槽位覆盖增量，兼顾上一回合落定值；done 时以完整 outputs 替换；异常也在 finally 设置 stopped。因此 stopped 代表空闲，不能当作 completed。
- output 返回输出尾部与完整 history；llm 接口可切模型，sysprompt 接口可修改额外系统提示。它们没有会话版本、权限范围与审计的独立模型。

目标归属：现有 Session/Run/Event、SSE、追加指令、模型分支与版本化 Agent 设置。当前已有部分本地实现，但尚无这套入口的逐分支兼容证明。保留运行中输入与刷新监控行为；不能复制全局 Agent、原地改已发布配置或将所有 finally 退出显示为成功。

待验证：忙闲竞态、输出覆盖与重连、异常/取消的终态区分、模型分支历史完整性、提示修改的版本与权限边界。

## 当前进度口径

[综合架构分析](open-source-agents-analysis-and-solution.md)覆盖九组项目的架构研究；[阶段方案](omni-agent-phased-implementation-plan.md)是待确认规划。两者不等于逐文件完整审查或实现验收。

Native 已有提交 `3022368` 的迁移实现及[本地验证记录](native-reference-parity/verification.md)。[原差距审计](native-reference-audit.md)中的缺失表为该实现之前的发现，必须结合验证记录和现有代码阅读，不能据此断言现在仍全部缺失。本次没有重跑其中的程序测试，也没有认证其完整上游兼容性。
