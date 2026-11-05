# API 设计

入口 `main.py` 装配平台、智能体编辑器与模型设置等 router，身份和数据库通过依赖注入取得。

模型设置前缀：`/api/v1/tenants/{tenant_id}/model-settings`。

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| 空路径 | GET | 查询有权供应商、模型、默认与空间管理能力 |
| `/providers` | POST | 创建供应商与加密 Key |
| `/providers/{id}` | PUT / DELETE | 修改/轮换或停用 |
| `/providers/{id}/models` | POST | 添加模型 |
| `/providers/{id}/models/{profile_id}` | PUT / DELETE | 生成模型版本或停用 |
| `/default` | PUT | 设置/清除 personal 或 tenant 默认 |
| `/agents` | POST | 显式模型或默认模型创建并发布 Native 智能体 |
| `/providers/{id}/models/{profile_id}/test` | POST | 有界流式连接测试 |

Key 字段使用 SecretStr，仅写入加密服务；请求校验不回传原始输入。测试间隔每供应商至少 10 秒（事务锁），总超时 15 秒、输出 32 token、无自动重试，不回传模型内容或供应商原始异常。网络策略由 Runtime 共用 transport 执行。

数据库依赖与就绪检查通过 platform 数据库工厂读取工作目录 `configs/nexus.toml`，不加载 `.env`；非法或缺失配置保持既有 503 语义，健康检查不依赖数据库。配置解析错误不包含秘密。

智能体编辑器（`http/agent_editor.py`，前缀 `/api/v1/tenants/{tenant_id}`）：

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `/agent-tools` | GET | 内置工具目录（分组、风险等级、只读、需审批、空间是否启用）、调用者的默认工具与是否可启用工具；成员可读，非成员 404 |
| `/agents/{agent_id}` | DELETE | 归档智能体（需 `agents:write` 与该智能体的 `manage`），审计 `agent.archived`；已归档智能体不出现在列表，新建会话与提交 Run 返回 409，已有会话消息仍可读取 |
| `/agents/{agent_id}/copy` | POST | 把草稿复制为新的未发布智能体，不复制版本与共享，绑定与模型按调用者重新授权 |

智能体草稿的 `budgets.generation` 只接受 `temperature`（0–2）与 `reasoning_effort`（`off/auto/minimal/low/medium/high/xhigh/max`），其他键或越界值返回 422。Native 运行准备阶段与故障转移模型以智能体值覆盖模型档案的同名选项（`auto` 沿用模型档案，`off` 不发送思考参数）；上下文压缩使用的摘要模型不受影响。
