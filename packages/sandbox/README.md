# nexus_sandbox

沙箱后端、租约与隔离验收，供 `sandbox` 工具组使用。提案：`openspec/changes/2026-11-07-tool-expansion`。

## 使用

1. 在 `configs/nexus.toml` 写 `[sandbox]`（见 `configs/nexus.example.toml`），`enabled = true`。
2. 确保镜像已在本机（沙箱从不自动拉取），且包含 `sh`、`timeout`、`python3`。
3. 运行 `uv run python -m nexus_worker --sandbox-check`，全部通过后写入验收报告。
4. 在智能体编辑器里打开「沙箱」工具组并勾选需要的工具。部署、验收、智能体开关三者缺一，工具都不会出现。

`local` 后端不隔离，只用于开发，需要 `allow_local = true` 和开发认证模式，且不能运行验收。

## 模块

见 [设计](docs/design.md)。
