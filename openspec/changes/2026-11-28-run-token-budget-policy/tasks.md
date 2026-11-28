# Tasks

- [x] Update the runtime budget contract: allow `max_tokens=0`, default it to unlimited, and preserve positive hard caps.
- [x] Update Native orchestration and summarization budget checks so unlimited Runs use the context/output policies without a cumulative-token stop.
- [x] Update delegated subagent budgeting for an unlimited parent while preserving bounded allocation for capped parents.
- [x] Update settings labels/validation and user-facing documentation for the opt-in cumulative cap.
- [x] Add regression coverage for unlimited runs, configured caps, and subagent inheritance.
- [x] Compare WeKnora, Hermes, and Nexus post-compaction message flow and overflow fallback from source; document the findings.
- [x] Reuse the latest authorization-valid session summary in each new Run and serialize forward-only summary checkpoints.
- [x] On provider context overflow, force compact, trim older tool results, and retry the request at most once.
- [x] Add regression tests for forced overflow recovery and one-retry termination; retain existing cross-Run summary and authorization regressions.
- [x] Run focused backend validation and inspect the final diff.
