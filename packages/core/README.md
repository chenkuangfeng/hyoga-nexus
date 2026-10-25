# nexus-core

跨包共享的厂商无关契约，使用 Python 3.11+，不依赖其他本地包、SQLAlchemy 或模型 SDK。平台、Runtime、工具与应用入口通过这些类型交互。

- `src/nexus_core/platform.py`：主体、空间角色、Run 状态、凭据引用及共享标识。
- `src/nexus_core/runtime/`：模型、工具、执行预算/进度、生命周期与持久化能力协议。
- `src/nexus_core/native/`：Native 行为配置与 hook 数据。

既有 `from nexus_core.runtime import ModelMessage`、`from nexus_core.native import NativePolicy` 可继续使用；具体模块与包入口导出同一类型。类型的具体类定义不再集中在入口文件中。

文档：[需求](docs/requirements.md)、[设计](docs/design.md)。
