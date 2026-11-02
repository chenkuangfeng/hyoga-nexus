# 模型管理设计（草稿）

状态：草稿，待 proposal.md 的四项决定确认后细化。本文件中的方案以建议选项为准。

## 1. 前端结构

- `views/settings/ModelSettingsView.vue`：改为类型标签页 + 卡片网格。标签页计数由 `useModelSettings` 从已加载的模型列表派生，不单独请求。
- 新增 `components/ModelEditorDrawer.vue`：添加与编辑共用。左侧不设分区，按"类型、来源、服务商、模型、连接、高级选项、实际调用方式"纵向排列。
- 新增 `data/modelPresets.ts`：静态预设，结构为 `{ type, provider, name, contextWindow?, dimension?, capabilities[] }`。预设只填充表单，不写入后端。
- `api/modelSettings.ts`：新增 `testDraft(tenantId, body)`，调用未保存配置的测试接口。
- `types/modelSettings.ts`：`ConfiguredModel` 增加 `model_type`；`ModelSettings.defaults` 改为按类型的映射。

## 2. 后端与持久化

- `ModelProfileRecord` 增加 `model_type`（字符串枚举，默认 `chat`）。迁移：`ALTER` 增加列，已有行回填 `chat`，之后设为非空。
- `ModelDefaultRecord` 主键由 `(tenant_id, scope_key)` 改为 `(tenant_id, scope_key, model_type)`。迁移时已有行归为 `chat`。
- `validate_model_options` 的白名单不变；新增 `model_type` 的校验，只接受上述五个值。
- 新增 `POST /api/v1/tenants/{tenant_id}/model-settings/test`：
  - 请求体与保存接口相同（`protocol`、`base_url`、`api_key`、`model_name`、`stream`、`temperature`、`reasoning_effort`、`text_tools`），不落库。
  - 权限与保存相同（`manage=True`）。
  - 复用现有的限频（同一提供商 10 秒一次）与 15 秒总超时。
  - 响应只包含 `ok`、`latency_ms` 与一个固定错误码，不回显生成内容或原始供应商错误。
- 非 `chat` 类型的测试：本阶段只做可达性检查（发起 `models` 列表或最小请求，视供应商而定）。若某供应商不支持，返回 `unsupported_for_type`，不视为失败。

## 3. 数据与安全

- 密钥仍由 `StoredCredentialResolver` 加密保存；测试接口只在内存中解密，不写入审计详情。
- 审计：测试接口沿用 `provider.connection_test` 动作，详情不含表单内容。
- 授权：保存与测试都要求能管理该作用域的提供商；个人作用域与空间作用域规则不变。

## 4. 迁移顺序

1. 迁移：`model_profiles.model_type`、`model_defaults.model_type`，回填 `chat`。
2. 后端：模型校验、默认模型按类型读写、测试接口。
3. 前端：列表与抽屉、默认设置。
4. 测试：迁移前后的默认值保留；测试接口的限频与超时；前端浏览器测试。

## 5. 不做的事

- 不引入服务端模型目录或 Ollama 来源。
- 不改变对话运行时的模型选择规则。本阶段只增加类型维度，对话类型的默认值读取路径保持不变（需在实施前核对 `provider_settings.py` 与运行时的实际读取位置）。
