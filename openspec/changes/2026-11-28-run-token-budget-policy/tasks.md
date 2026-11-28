# Tasks

- [x] Update the runtime budget contract: allow `max_tokens=0`, default it to unlimited, and preserve positive hard caps.
- [x] Update Native orchestration and summarization budget checks so unlimited Runs use the context/output policies without a cumulative-token stop.
- [x] Update delegated subagent budgeting for an unlimited parent while preserving bounded allocation for capped parents.
- [x] Update settings labels/validation and user-facing documentation for the opt-in cumulative cap.
- [x] Add regression coverage for unlimited runs, configured caps, and subagent inheritance.
- [x] Compare WeKnora, Hermes, and Nexus post-compaction message flow and overflow fallback from source; document the findings.
- [x] Run focused backend validation and inspect the final diff.
