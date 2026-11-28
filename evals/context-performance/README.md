# 上下文与 token 性能基线（固定会话集）

对应 [OpenSpec 变更 2026-11-01-context-token-performance](../../openspec/changes/2026-11-01-context-token-performance/tasks.md) 第一节（基线）。

## 内容

- `cases.py`：20 段固定会话，覆盖单次与多次工具调用、短到超长的输出、多轮对话、依赖上一轮工具结果的追问。会话集固定：修改已有用例会使历史基线失效，需要新增用例。
- `harness.py`：在独立内存数据库中，通过真实 worker 路径（`run_once`）逐段执行，记录每回合的数据库事务数、`run_events` 条数、模型请求数、送入模型的字符数和耗时。

## 运行

在仓库根目录执行：

```bash
uv run python evals/context-performance/harness.py                       # 全部 20 段
uv run python evals/context-performance/harness.py --case followup-9000  # 单段
uv run python evals/context-performance/harness.py --behavior '{"tool_output_inline_limit": 4000}'
uv run python evals/context-performance/harness.py --json out.json       # 每回合明细
```

`--behavior` 以 JSON 对象合并进 Native 行为设置，用于比较不同策略配置。`followup-no-reader-*` 关闭读取工具绑定，用于对比旧的 4000 字符截断。

## 当前状态

- 默认模型是脚本化的（`ScriptedModel`），因此输出的是**平台侧**指标：事务数、事件数、输入字符数、耗时。它**不反映回答质量**，也不能用来比较模型正确率。
- 尚未采集：`cached_tokens`、模型耗时、真实 token 用量。这些需要配置真实供应商后，通过 `run_case(case, model_factory=...)` 替换模型工厂采集。
- `baseline.md` 尚未生成。在真实模型上采集后再写入，不使用脚本化结果冒充基线。
- 质量评测（追问正确率）见同一变更的第六节，需要真实模型。

## 提示前缀结构对比

执行 `uv run python evals/context-performance/prompt_prefix_benchmark.py`，复用 `cases.py` 的 20 段固定语料，对比工作记忆在历史前与尾部时的共同消息前缀字节数。结果写入 `prompt-prefix-results.json`，解释与验证限制见 [报告](prompt-prefix-report.md)。此脚本不调用真实模型，也不报告缓存 token 或回答质量。
