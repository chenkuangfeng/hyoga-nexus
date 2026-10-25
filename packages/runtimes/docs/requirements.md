# Runtime 需求

Native Runtime 执行模型/工具循环，保留流式事件、工具顺序、预算、取消、等待输入、检查点与生命周期 hooks。厂商类型不泄漏到公共契约。

OpenAI-compatible 模型支持来自用户设置的多个供应商。对测试连接与正式调用统一限制目的地址；流式模型测试不代表所有供应商工具协议均兼容。外部 Runtime 与隔离 Sandbox 尚未接入。
