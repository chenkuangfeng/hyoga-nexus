# 从 configs 自动读取数据库配置

## 原因与范围

用户要求程序自动读取 configs 下的配置文件，直接运行 worker，无需加载 .env。当前 API、worker、数据库工厂和 Alembic 分别读取环境变量，上一轮文档中的 --env-file 方式不满足需求。

## 变更

- 默认从工作目录下的 configs/nexus.toml 读取 [database].url；支持 Windows PowerShell 与 Linux 的仓库根目录启动。
- API、worker、Alembic 使用同一配置解析逻辑；不自动加载 .env。
- 优先级为显式传入连接串 > 配置文件 database.url > 已设置的 NEXUS_DATABASE_URL（兼容现有部署）。配置文件优先于环境变量，避免本地配置被旧环境覆盖。
- 提供 configs/nexus.example.toml、忽略真实 configs/nexus.toml，更新启动与迁移说明，撤回上一轮将 .env 作为数据库推荐入口的说明。
- 不改变数据库模型、任务执行语义或 API 数据契约；其他认证、模型和加密部署配置仍沿用原机制。本次仅涉及基础部署数据库配置，因此不通过用户设置页管理。

## 状态

待用户确认；仅创建提案，尚未实施。
