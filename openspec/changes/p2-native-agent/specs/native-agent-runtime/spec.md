# Native Agent Runtime

## ADDED Requirements

### Requirement: Native runtime dispatch
The worker MUST dispatch an authorized `native` Run to one Native Runtime Engine for execution. The Native Engine owns its model/tool loop. The platform MUST NOT add a second Native loop around that Engine; external Runtime adapters remain responsible for their own SDK/Harness loops.

#### Scenario: Native Run is dispatched
- **WHEN** a queued Run references an available Native AgentVersion and its current authorization is valid
- **THEN** the worker creates a run-scoped Native Runtime execution and records its lifecycle in the platform

#### Scenario: Runtime is unavailable
- **WHEN** the Run references a Runtime type or capability that is not configured
- **THEN** the Run ends or waits with a stable, explicit reason and is not reported as completed

### Requirement: Vendor-neutral model streaming
Core MUST define vendor-neutral model request, text delta, tool-call, completion and cancellation contracts. Provider SDK types and provider-native errors MUST stay within the concrete Native model adapter. Credentials MUST be resolved only for the execution boundary and MUST NOT appear in prompts, snapshots, events, logs or hook payloads.

#### Scenario: Provider response is streamed
- **WHEN** the Native adapter receives text or tool-call deltas from a configured provider
- **THEN** it translates them to stable Core contracts without exposing provider SDK objects

#### Scenario: Model credential is unavailable
- **WHEN** the credential reference cannot be resolved for the Run
- **THEN** the Run fails with a stable credential error and no credential value is logged or persisted

### Requirement: Multi-turn Native execution
The Native Engine MUST support budgeted model/tool turns, streamed assistant text, zero or more tool calls, tool results fed back to the model, and explicit completion or exit. Tool outcomes MUST preserve result data, continuation guidance and disposition semantics equivalent to GenericAgent `StepOutcome`. Unknown tools, malformed JSON and schema-invalid arguments MUST yield controlled error results and MUST NOT bypass authorization or report false success.

#### Scenario: Model asks for multiple tools
- **WHEN** one model response contains multiple valid tool calls
- **THEN** the Engine executes them in the declared order, records each result separately, and supplies the results to a subsequent model turn when continuation is requested

#### Scenario: Tool arguments are invalid
- **WHEN** a tool name is unknown or its arguments fail JSON/schema validation
- **THEN** the Engine records a controlled invocation error and may return the error to the model within the configured turn/error budget

#### Scenario: Tool requests explicit exit
- **WHEN** a tool returns an explicit exit disposition with a completion or failure reason
- **THEN** the Engine ends the loop with that reason and does not infer success from an empty continuation prompt

### Requirement: Authorized tool execution
Tools MUST be called only through the platform registry and authorization gateway. Immediately before each call the gateway MUST check current principal, Workspace, Run, AgentVersion, binding, ResourceGrant and tool policy. Model arguments, skill text and prior Run snapshots MUST NOT grant permissions. P2 MUST execute multiple calls sequentially; only a later explicitly declared read-only/idempotent tool capability may enable parallelism.

#### Scenario: Resource is revoked between tool calls
- **WHEN** a grant is revoked after an earlier tool call but before a subsequent call
- **THEN** the subsequent call is denied, audited and returned as a controlled authorization error

#### Scenario: Tool is not bound to the AgentVersion
- **WHEN** a model requests an otherwise registered tool that is absent from the authorized Run binding
- **THEN** the gateway refuses execution and records the denial

### Requirement: Tool invocation traceability
Every tool call MUST have a stable invocation ID, status transitions, controlled input/output summaries and a stable error category. A tool exception MUST NOT cause other calls to be recorded as successful. An uncertain side effect MUST NOT be automatically replayed.

#### Scenario: Tool succeeds
- **WHEN** an authorized Python tool completes
- **THEN** the platform records its invocation status and bounded public result summary associated with the Run

#### Scenario: Tool side effect result is unknown
- **WHEN** a worker loses contact after a side effect may have started but before its result is persisted
- **THEN** the invocation and Run are marked interrupted or otherwise explicitly uncertain and are not blindly replayed

### Requirement: Safe execution boundary
The Native Runtime MUST NOT execute uncontrolled host shell commands, Python `eval`, arbitrary host file access or arbitrary network requests. Arbitrary code execution MUST use a declared SandboxPort backend with verified isolation and resource limits. When no verified backend is configured, arbitrary code execution MUST be unavailable; a registered Python function MUST NOT be described as a sandbox.

#### Scenario: No isolated Sandbox backend is configured
- **WHEN** the Native tool registry is composed without a verified SandboxPort backend
- **THEN** arbitrary code and shell tools are not registered and capability discovery reports them unavailable

#### Scenario: Sandboxed tool execution
- **WHEN** an authorized code tool is enabled with a verified SandboxPort
- **THEN** it executes within the declared Workspace/Run boundary and enforces configured time, resource, filesystem and network limits

### Requirement: Session-scoped context and checkpoint
Each Session and Run MUST use isolated message history and working state. Assistant and tool messages MUST be persisted for later context. Run idempotency MUST prevent duplicate user message creation. Context compaction MUST preserve source messages and MUST NOT read another Session's data. Working checkpoints MUST be scoped to their Workspace and Session and be recoverable.

#### Scenario: User continues a Session
- **WHEN** a new Run is created in an existing Session
- **THEN** only that Session's authorized history and checkpoint are considered for context

#### Scenario: Client retries a Run request
- **WHEN** the same idempotency key and payload are submitted again
- **THEN** the existing Run is returned without appending a duplicate user message

### Requirement: Typed lifecycle hooks
The Native Runtime MUST expose typed, run-scoped before/after extension points for Agent, turn, model and tool lifecycle phases. Hook failures MUST be diagnosable and isolated; hooks MUST NOT bypass authorization, falsify a side-effect result or suppress a terminal failure. Arbitrary local variables and provider SDK objects MUST NOT be a stable hook API.

#### Scenario: Lifecycle hook fails
- **WHEN** an extension hook raises an exception
- **THEN** the failure is recorded for diagnostics while authorization and actual invocation outcome remain authoritative

#### Scenario: Run completes
- **WHEN** a Run ends for any terminal reason
- **THEN** its run-scoped hooks and resources are cleaned up and cannot affect another Run

### Requirement: Governed memory and SOP updates
The Native Runtime MUST support Session working checkpoints and explicit Memory/SOP provider extension points. Long-term memory or SOP updates MUST be staged as attributable drafts with a scope and diff; they MUST NOT modify shared published content until explicitly reviewed and version-published.

#### Scenario: Agent proposes a memory update
- **WHEN** a Run proposes a long-term memory or SOP change
- **THEN** the change is stored as a draft linked to its source Run and does not affect subsequent Runs before approval

#### Scenario: Checkpoint is restored
- **WHEN** a later Run in the same Session loads a checkpoint
- **THEN** the checkpoint is restored only after checking the same Workspace/Session scope

### Requirement: Waiting for user input
An explicit Native user question MUST transition the durable Run to `waiting_input` and persist an input request. A response MUST be an authorized, idempotent platform command that continues the Session context; the worker MUST NOT block indefinitely waiting for a browser or process-local callback.

#### Scenario: User responds to a pending question
- **WHEN** the authorized Session owner submits an unconsumed input request response
- **THEN** the platform persists the response and resumes or continues the Run through a durable command

#### Scenario: Input request has already been consumed
- **WHEN** a client repeats an input response with the same idempotency key
- **THEN** the existing response outcome is returned without resuming execution twice

### Requirement: Runtime budgets and cancellation
Every Native Run MUST enforce configured turn, duration and available token/usage budgets. Cancellation MUST propagate to model streaming and controlled tools. Queued cancellation, active cancellation, completed work and uncertain side effects MUST remain distinguishable. Unknown results MUST NOT be automatically replayed.

#### Scenario: User cancels an active model stream
- **WHEN** an authorized cancellation request arrives while a provider stream is active
- **THEN** the Runtime signals cancellation, records the observed outcome and does not start another model turn

#### Scenario: Run exceeds its turn budget
- **WHEN** the configured turn limit is reached
- **THEN** the Run terminates with an explicit budget error and does not claim successful completion

### Requirement: Stable execution errors
Provider timeout/rate limiting/invalid stream, missing credentials, context overflow, invalid tool arguments, authorization denial, tool timeout, Sandbox unavailability, budget exhaustion, cancellation and uncertain interruption MUST map to stable error codes and user-safe messages. Diagnostics MUST carry request/Run/invocation IDs without secrets, unrestricted tool input or hidden reasoning.

#### Scenario: Provider times out
- **WHEN** a provider request exceeds its configured deadline
- **THEN** the Run records a stable provider-timeout code and bounded diagnostic metadata

#### Scenario: Tool authorization is denied
- **WHEN** a current authorization check fails
- **THEN** the caller receives a stable authorization error without resource existence details outside its scope
