# 模型管理设计（草稿）

状态：已确认（2026-11-02），方案即 proposal.md 中的建议选项 A。

## 1. 前端结构

- `views/settings/ModelSettingsView.vue`：改为类型标签页 + 卡片网格。标签页计数由 `useModelSettings` 从已加载的模型列表派生，不单独请求。
- 新增 `components/ModelEditorDrawer.vue`：添加与编辑共用。按"类型、服务商、模型、高级选项、实际调用方式"纵向排列。服务商下拉末尾为"自定义"，选择后在抽屉内填写名称、地址和 Key，保存时先建服务商再建模型；模型保存失败时服务商已建立，重试不会重复创建。
- 新增 `data/modelPresets.ts`：静态预设，结构为 `{ type, name, vision? }`。预设只填充模型名称，不写入后端；不含上下文长度，避免写入未经核对的数值。
- `api/modelSettings.ts`：新增 `testDraft(tenantId, body)`，调用未保存配置的测试接口。
- `types/modelSettings.ts`：`ConfiguredModel` 增加 `model_type`；`ModelSettings.defaults` 为 `scope → type → version_id`。

## 2. 后端与持久化

- `ModelProfileRecord` 增加 `model_type`（字符串枚举，默认 `chat`）。迁移：`ALTER` 增加列，已有行回填 `chat`，之后设为非空。
- `ModelDefaultRecord` 主键由 `(tenant_id, scope_key)` 改为 `(tenant_id, scope_key, model_type)`。迁移时重建表（建新表、复制、删除旧表），已有行归为 `chat`。
- `validate_model_options` 的白名单不变；新增 `model_type` 的校验，只接受上述五个值。
- 新增 `POST /api/v1/tenants/{tenant_id}/model-settings/test`：
  - 请求体与保存接口相同（`protocol`、`base_url`、`api_key`、`model_name`、`stream`、`temperature`、`reasoning_effort`、`text_tools`），不落库。
  - 权限与保存相同（`manage=True`）。
  - 复用现有的限频（同一提供商 10 秒一次）与 15 秒总超时。
  - 响应只包含 `ok`、`latency_ms` 与一个固定错误码，不回显生成内容或原始供应商错误。
- 非 `chat` 类型的测试：本阶段不向供应商发送请求，统一返回 `unsupported_for_type`，前端显示"将在知识库阶段提供"。这样不会因为非对话模型的接口差异而误报失败。
- 草稿测试的限频：没有提供商行可以记录时间，因此按（空间，用户）在进程内记录最近一次开始时间，间隔 10 秒。已保存提供商的测试仍使用 `last_test_at`。

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
