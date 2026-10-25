## ADDED Requirements

### Requirement: Complete traceable reference migration
Native migration MUST preserve every inventoried applicable behavior and extension point from the locked GenericAgent and WeKnora source and tests. Direct source reuse or equivalent translation MUST retain provenance and required notices. Unreviewed, unimplemented and explicitly deferred items MUST be tracked separately and MUST NOT be reported as complete.

#### Scenario: An upstream branch has not been ported
- WHEN an audited branch lacks a destination implementation or behavioral evidence
- THEN the migration remains incomplete and records the source, gap and planned destination.

### Requirement: Modular single-loop execution
Native MUST have one actual model/tool execution loop. Orchestration, completion policy, model protocols, tools, context/memory, hooks, approval and recovery MUST have distinct responsibilities and test boundaries. Existing public imports and authorized execution behavior MUST remain compatible.

#### Scenario: Adding a completion rule
- WHEN a reference completion branch is migrated
- THEN it is implemented and tested in the completion policy without embedding model transport, memory storage or tool implementations in the orchestrator.

### Requirement: Reference completion and working context semantics
Native MUST preserve GenericAgent no-tool recovery, completion extensions and working-context behavior, and MUST incorporate the reviewed WeKnora termination, truncation, compaction and recovery branches according to an explicitly approved conflict mapping. Empty output MUST NOT silently succeed.

#### Scenario: Empty natural stop
- WHEN a model returns empty content without tool calls
- THEN bounded recovery follows the configured policy without emitting a successful terminal result before an actual answer or explicit failure.

### Requirement: Complete tool and hook compatibility
Tool migration MUST preserve input semantics, intermediate progress and final results. Hooks MUST support authorized structured context transformations and lifecycle registration/cleanup. Original checkpoint key_info and ask_user candidates MUST have complete end-to-end mappings while existing interfaces remain supported.

#### Scenario: Candidate-based question
- WHEN ask_user supplies candidates
- THEN authorized persistence, events and the user interface retain them and resume the same Run without replaying prior tools.

### Requirement: Complete governed memory lifecycle
Memory and SOP migration MUST preserve discovery, authorized reading, consolidation, index synchronization and future reuse. Required review and version publication MUST be implemented as a complete lifecycle; a draft-only interface MUST NOT count as full reference compatibility.

#### Scenario: Consolidating reusable findings
- WHEN verified findings are proposed for long-term memory
- THEN their provenance and scope are retained through review, publication and index updates, and future authorized runs can discover and read the published version.

### Requirement: Controlled recovery and approvals
Recovery MUST preserve completed tool outcomes and MUST NOT blindly replay uncertain side effects. Steer and approval inputs MUST be authorized and persisted before consumption. Action grants MUST remain distinct from resource sharing grants.

#### Scenario: Persistence failure during steer delivery
- WHEN a running user's correction cannot be persisted
- THEN it is neither consumed nor injected ahead of the failed item, and no premature terminal success is emitted.

### Requirement: Frontend-first compatible configuration
Ordinary user configuration MUST have a frontend settings entry with server validation, persistence, versions, defaults and personal/workspace authorization. Usability extensions MAY be added while preserving reference capabilities. Deployment-only exceptions MUST have documented concrete reasons.

#### Scenario: Configuring retry behavior
- WHEN an authorized user changes a daily retry or behavior setting
- THEN it can be configured through the frontend and applies through an explicit version/default selection without silently mutating existing published sessions.

### Requirement: Explicit deferred capabilities
Sandbox execution and dependent code/file/browser tools MUST remain unavailable until their previously deferred implementation and isolation verification are explicitly authorized and completed. Their absence MUST remain visible in the parity inventory.

#### Scenario: Deferred execution capability is requested
- WHEN a Run requests a tool whose isolation backend is unimplemented
- THEN execution is refused without falling back to host code or files, and the migration item remains incomplete.
