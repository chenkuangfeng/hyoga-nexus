## 向量连接错误

参考 WeKnora e1f9a6166 的 `internal/models/api/openaiembeddings/client.go` 与 `endpoint.go` 对协议错误和传输失败的区分。沿用 Nexus 的结构化错误分类和拒绝响应体上限，将 SDK 异常转换为稳定错误。连接测试对向量请求拒绝说明 `/embeddings` 和模型类型要求。
