## ADDED Requirements

### Requirement: 企业共享模型管理
管理应用 SHALL 按 `models:manage` 提供当前企业共享 Provider、模型配置、模型版本和企业默认模型管理。页面和客户端 SHALL 仅展示 tenant scope 的 Provider，不得读取或修改成员个人模型；所有请求 SHALL 使用当前企业路径，身份、企业或权限变化后 SHALL 丢弃迟到的响应。

#### Scenario: 管理入口权限
- **WHEN** 用户没有当前企业 `models:manage` 权限
- **THEN** 模型导航和智能体编辑器中的模型管理跳转均不可用，并显示权限提示

#### Scenario: 保存共享 Provider
- **WHEN** 管理员创建或更新企业 Provider
- **THEN** API Key 仅在提交时写入，页面不回显密钥；修改 API 地址时要求重新提交密钥，个人 Provider 不出现在目录中

#### Scenario: 追加模型版本及默认值
- **WHEN** 管理员编辑已有模型或设置某类型默认模型
- **THEN** 编辑追加不可变版本且模型类型不可变；默认值只能指向当前企业同类型模型的当前版本，服务端拒绝无效引用

#### Scenario: 停用和连接测试
- **WHEN** 管理员停用模型或执行连接测试
- **THEN** 停用保留历史版本并清理相关默认值；测试仅对聊天模型发送最小请求并明确可能产生费用，其他类型由服务端返回不支持，错误信息不泄露密钥
