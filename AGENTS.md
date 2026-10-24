# Development rules

- Python 3.11+ for all first-party backend, runtime adapters, connectors, and domain logic. Vue 3 + TypeScript + Element Plus for web.
- Read docs/architecture.md, docs/directory-layout.md, and the relevant phase in docs/roadmap.md before feature work.
- Before changing foundational platform or Native runtime behavior, read docs/reference-analysis.md and inspect the pinned WeKnora and GenericAgent implementations. WeKnora is the platform organization and capability reference; GenericAgent is the Native execution-loop, tool-dispatch, lifecycle, and memory/SOP reference. Preserve their relevant behavior and extension points: do not simplify, remove, or downscope core capabilities. Changes must be additive and backward-compatible; document unavoidable stack/security adaptations and show that they preserve or extend behavior. Do not copy source code without checking its license and recording attribution.
- Read rules/backend.md for backend, platform, runtime, persistence, and API work; read rules/frontend.md for web UI work. Read both when a change crosses the API/UI boundary.
- core contains shared contracts and must not depend on other local packages or vendor SDKs.
- Generic packages must not import guanlan. Compose domain extensions at application entry points.
- platform manages agents, sessions, resources and authorization; runtimes owns execution. Do not wrap SDK loops in a second Native loop.
- Keep vendor SDK types inside runtime adapters and platform-specific message types inside connectors.
- Skill instructions do not grant permissions. Validate authorized resources at actual tool execution and document access.
- Separate knowledge documents, user/agent memory, and structured stock datasets.
- Keep skills content in top-level skills/, implementation in packages/skills; software tests in tests/, quality cases in evals/, financial backtests in guanlan/backtesting.
- Never commit credentials, data dumps or third-party source repositories. Record pinned versions and attribution if code is reused later.
- Distinguish planned scaffolding from implemented functionality. Add package dependencies only when code actually uses them.
- At the end of every completed task, review the entire working tree, commit all pending non-sensitive changes, and push the current branch to GitHub. Do not omit unrelated pending changes; never commit credentials, data dumps, or third-party source repositories. If commit or push cannot complete, report the exact blocker and leave the changes intact.
- Use uv sync --locked --extra dev and relevant pytest checks; run npm ci / npm run build for frontend changes. Documentation-only edits need link and diff checks, not full runtime testing.
