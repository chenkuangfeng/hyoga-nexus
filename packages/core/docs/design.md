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

## 上下文内容契约

`runtime/context.py` 提供 `ContextDependency`、`ContextBlock`、`ContextBuildInput`、`AssemblyManifest`、`RunContextSnapshot` 与 `ContextProvider`。依赖标识引用来源与版本，不代表授权；块明确角色、位置、生命周期与信任级别，正文摘要由实际文本计算。`ModelMessage.context_source` 是宿主赋予的贡献名，供可信 hook 的持久化来源记录使用，不成为供应商指令。

`runtime/context_assembly.py` 的 `RequestContextAssembler` 是无 I/O 的确定性装配器，由平台准备与 Native 共用；放在 core 是为了避免 platform 导入 runtimes。它只使用本包 DTO 和标准库，拒绝重复贡献名，不在未完成的工具交换后插入尾部资料。v1 复现现有消息布局；v2 资料尾置已有纯装配支持，但未通过真实模型评测前不作为默认布局。工具 schema 仍是请求的独立字段。
