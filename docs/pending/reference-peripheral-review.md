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

## 执行头与中英文记忆模板

本批阅读全文并核对索引 SHA-256：`assets/code_run_header.py`、`assets/global_mem_insight_template.txt`、`assets/global_mem_insight_template_en.txt`。同时定点核对 `ga.py:code_run/get_global_memory` 与 `agentmain.py` 的初始化入口；未执行上游脚本。根许可证为 MIT，版权为 2025 lsdefine；本次只记录分析，没有复制实现。

### 代码执行头

- `ga.py:code_run` 仅在 Python/py 文件执行分支将执行头文本写入临时脚本；缺失时跳过。shell 分支不插入执行头。
- 头部依据临时脚本的 `__file__` 计算 `../memory` 并加入 `sys.path`，不保证指向项目的真实 memory 目录；目标实现必须明确脚本位置与模块路径的关系。
- 包装 `subprocess.run`：移除 text/universal_newlines/encoding/errors 参数，按 text 标志决定是否将字符串 input 编码为默认 UTF-8，捕获的 stdout/stderr 优先按默认 UTF-8 解码，失败后按 GBK replacement 解码。指定 encoding 只启用文本模式，并不使用指定编码；errors 参数被丢弃。未设置文本模式时保留字节输出。
- 包装 `Popen.__init__`：Windows 将 CREATE_NO_WINDOW 位与已有 creationflags 合并；其他平台不加此标志。这是脚本进程中的模块级修改，会影响其后续子进程调用。
- 替换 `sys.excepthook`，仅对 ImportError/AttributeError 在原 traceback 后附加探测/安装依赖提示；其他异常沿用原处理。提示本身不安装包，也不提供执行授权。

目标归属：隔离执行适配器的脚本准备、编码与进程生命周期。六项执行工具继续暂缓，此头部未迁移。不能在平台/API/worker 进程直接加载以获得相同效果；编码参数行为与临时路径须列入后续提案的兼容决策。

待验证：UTF-8/GBK/无效字节、空输出、文本与字节 input、显式 encoding/errors、check/timeout 异常携带输出、Windows flags 合并、缺失头文件和临时脚本目录变化。

### 记忆模板初始化和注入

- 两个模板包含 L0 元 SOP、空 L2、L3 技能/脚本索引、L4 原始会话位置及八条操作规则；其中涉及浏览器、桌面、手机、定时、自主运行等内容。模板中的索引不能证明这些能力已在 Nexus 实现或可调用。
- `agentmain.py` 在 GA_LANG 未设置时按系统 locale 选择 zh/en；只有值严格等于 en 时使用英文后缀。创建 memory 目录，并仅在 L2 文件缺失时写入初始标题。
- insight 文件缺失时才复制所选模板；模板也缺失时写空文件。已有 insight 不覆盖，后续语言切换也不重新初始化。初始化发生在模块加载阶段，而非每次 Run。
- `get_system_prompt` 追加日期与 `get_global_memory`。后者通过 `load_L1` 取得 insight，再拼接所选语言的固定结构和路径；捕获 FileNotFoundError。不能将“模板已初始化”视为长期记忆整理、审核发布或检索已完成。

目标归属：记忆初始化、已授权索引读取和提示编排；前端管理语言与个人/空间默认，服务端保存作用域和版本。共享源码目录写入、原始宿主路径及未实现能力索引需要显式适配；模板指令不得授予工具权限。此批不实现新的记忆行为。

待验证：首次/重复初始化、缺失模板、已有用户内容保留、语言切换、固定结构缺失、并发初始化、个人/空间隔离与撤权后索引过滤。对 `frontends/tests` 的文件名引用检索未发现直接覆盖，不代表不存在间接测试；尚未运行上游测试。

## 当前进度口径

[综合架构分析](open-source-agents-analysis-and-solution.md)覆盖九组项目的架构研究；[阶段方案](omni-agent-phased-implementation-plan.md)是待确认规划。两者不等于逐文件完整审查或实现验收。

Native 已有提交 `3022368` 的迁移实现及[本地验证记录](native-reference-parity/verification.md)。[原差距审计](native-reference-audit.md)中的缺失表为该实现之前的发现，必须结合验证记录和现有代码阅读，不能据此断言现在仍全部缺失。本次没有重跑其中的程序测试，也没有认证其完整上游兼容性。
