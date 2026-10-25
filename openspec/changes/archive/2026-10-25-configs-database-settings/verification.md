# 验证结果

- `uv run --locked pytest -q`：276 passed，1 skipped；跳过 PostgreSQL 专项，未配置专用 `NEXUS_TEST_POSTGRES_URL`，因此未验证真实 PostgreSQL 迁移、并发领取和租约恢复。
- 新增配置测试覆盖来源优先级、显式注入、缺失字段、非法 TOML/类型/空值/连接串、错误脱敏和不加载 dotenv。
- 临时工作目录仅提供 configs/nexus.toml：Alembic 升级 head、API readiness、worker --once 均通过；不会连接或迁移本地既有数据库。
- 测试运行于 Linux；使用跨平台 pathlib 和标准库 TOML，未在真实 Windows 主机执行。PowerShell 首次配置步骤已写入 README。
- 真实本地配置已加入忽略规则，保留原连接值。未验证真实模型供应商；认证及其他部署设置机制未改变。
- 现有 Starlette/httpx 弃用警告 1 条，与配置行为无关。
