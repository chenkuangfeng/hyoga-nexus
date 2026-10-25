# 设计

## 归属与依赖

在 platform 增加专职部署配置模块（建议 nexus_platform/configuration.py），使用 Python 3.11 内置 tomllib 和 pathlib，无新依赖。共享读取与校验数据库配置；core 不引入文件 I/O 配置职责。API/worker 组合入口、platform 数据库工厂及 migrations/platform/env.py 调用此模块，不修改进程环境变量，不把整个配置内容写入日志。

## 文件与加载规则

默认路径 Path.cwd() / "configs" / "nexus.toml"；相对 SQLite URL 继续按工作目录解析。明确要求从仓库根目录运行；安装后部署也在部署工作目录提供 configs/nexus.toml，不依赖源码文件位置猜测仓库路径。

```toml
[database]
url = "postgresql+psycopg://nexus:CHANGE_ME@127.0.0.1:5432/nexus"
```

显式 URL 优先。无显式 URL 时，文件存在则解析并校验 database 为表、url 为非空字符串；文件缺失或未定义数据库项时允许使用既有环境变量。存在但格式错误、类型错误或空 URL 应明确报配置错误，不静默退回其他数据库。所有来源均缺失时报出应配置的文件路径及字段；异常不包含连接串、密码或原始 TOML 片段。API 保持现有健康/就绪与未配置数据库错误语义，worker 在任务循环前报配置错误，Alembic 不再回落到 alembic.ini 的隐式数据库默认值。

## 安全与兼容

真实配置文件不提交；示例只有占位值。实施时保留本地已有连接配置，可将既有本地数据库值迁入被忽略的 TOML，不加载 .env 执行代码、不输出连接秘密。已有显式测试数据库注入保持有效。认证及加密配置不在本批扩展；文档明确现有环境变量仍需按部署要求设置。

本批是本项目部署配置适配，不迁移参考项目 Agent/平台业务算法，无需引入 GenericAgent 或 WeKnora 实现及依赖。

## 验证

覆盖配置优先级、文件缺失、空值/类型/TOML 错误、秘密不泄露和 Windows 路径兼容；验证 API/worker/Alembic 共用配置。使用临时 SQLite 做迁移与 worker --once 冒烟，不触碰已有业务库。PostgreSQL 真连接只在实际环境可用时验证并单独报告。
