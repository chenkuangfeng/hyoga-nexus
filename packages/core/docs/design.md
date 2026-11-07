# 共享契约设计

`runtime/__init__.py` 与 `native/__init__.py` 仅导出；模块间只依赖本包类型及 Python 标准库。同一类型仅定义一次，因此旧入口与细分模块的类型身份相同。

| 模块 | 类型/职责 |
| --- | --- |
| `runtime/models.py` | ModelMessage/Request/Chunk、ChatModelPort；工具定义引用 tools 模块 |
| `runtime/tools.py` | 工具定义、调用、结果和执行端口；取消依赖 cancellation 模块 |
| `runtime/budgets.py` | 执行预算、可持久化进度 |
| `runtime/events.py` | 生命周期事件和异步 hook 端口 |
| `runtime/store.py` | 消息/事件/进度持久化端口，具体事务留在平台 |
| `runtime/errors.py`、`cancellation.py` | 稳定 RuntimeFault 与取消能力 |
| `runtime/memory.py`、`sandbox.py` | 记忆草稿与隔离执行能力契约，接口不表示已有真实后端 |
| `runtime/outcomes.py` | 执行结束结果 |
| `native/policy.py` | 内置工具集合与 NativePolicy 配置验证 |
| `native/hooks.py` | HookContext/HookTransform，共享消息与变换数据 |
| `egress.py` | 受保护的出站下载：只允许公网地址、逐跳校验重定向、连接已校验的字面地址、字节与时间上限；`web_fetch` 与技能远程安装共用 |

这次拆分保留原 DTO/Protocol 字段与方法，不增加供应商私有状态、ORM 或第二个执行循环。真正的协议请求构建、历史重放和上下文压缩由 runtimes 实现。
