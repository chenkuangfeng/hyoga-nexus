# Nexus Runtimes

提供 Native 模型/工具执行循环和 OpenAI-compatible 流式适配器；外部 Runtime 仍为占位。实现按 `native/engine`、`native/context`、`native/models` 分工，应用入口注入模型、工具网关和持久化端口。由 worker 装配运行，配置见 [worker](../../apps/worker/README.md)。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)
- [双项目源码差距审计](docs/native-reference-audit.md)
