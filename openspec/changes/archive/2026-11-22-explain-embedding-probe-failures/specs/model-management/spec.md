## ADDED Requirements

### Requirement: 向量连接错误诊断

向量模型连接测试 SHALL 区分上游请求拒绝、认证失败、限流、超时与网络故障，并返回安全提示。

#### Scenario: 向量接口拒绝请求
- **WHEN** 向量端点返回 404 或其他请求拒绝
- **THEN** 连接测试报告 `model_request_rejected` 并提示核对 `/embeddings` 能力和向量模型 ID
