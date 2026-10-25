# 数据库部署配置

#### Requirement: 自动读取 configs 数据库配置

从仓库根目录执行 API、worker 与 Alembic 时，系统 SHALL 自动读取 configs/nexus.toml 的 [database].url，不要求 --env-file、不自动读取 .env。

#### Scenario: 直接启动 worker

- GIVEN configs/nexus.toml 包含有效数据库 URL 且数据库已迁移
- WHEN 执行 uv run python -m nexus_worker --once
- THEN worker 使用文件中的数据库，无需 NEXUS_DATABASE_URL。

#### Requirement: 一致的来源优先级

系统 SHALL 使用显式连接串、文件连接串、既有环境变量的优先顺序。文件缺失或未定义数据库项时 MAY 使用 NEXUS_DATABASE_URL，所有来源缺失时 SHALL 明确提示配置路径与字段。

#### Requirement: 配置错误可诊断且不泄露秘密

文件格式、字段类型或空值错误 SHALL 明确失败，不静默改连其他数据库；错误与日志 SHALL 不包含连接串中的凭据和原始配置片段。API SHALL 保持既有健康、就绪与平台未配置数据库的响应语义。

#### Requirement: 配置文件交付

仓库 SHALL 提供不含真实凭据的 TOML 示例、忽略真实本地文件，并记录 API、worker、迁移的直接启动方式及其他部署配置边界。
