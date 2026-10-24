# Run Streaming and Conversation Workbench

## ADDED Requirements

### Requirement: Persisted Run event delivery
Runtime text, progress, tool, input and terminal events MUST be persisted before being delivered to subscribers. Each Run MUST use a monotonically increasing sequence. Reconnecting from a sequence cursor MUST replay stored events only and MUST NOT restart model or tool execution.

#### Scenario: Client reconnects during generation
- **WHEN** a client reconnects with its last observed event sequence
- **THEN** the API returns later persisted events in order and does not create another Run

#### Scenario: Event persistence fails
- **WHEN** a Runtime event cannot be persisted
- **THEN** the event is not reported as delivered and the Run follows an explicit retry/failure path

### Requirement: Server-sent Run event stream
The Run events API MUST provide authorized, sequence-based SSE consumption in addition to paged event history. A stream connection MUST NOT own Run execution or queue consumption.

#### Scenario: Subscriber opens an authorized stream
- **WHEN** a Session owner requests the SSE stream for a Run in the same Workspace
- **THEN** the API streams persisted events after the requested cursor while preserving event IDs and sequence values

#### Scenario: Subscriber lacks Run access
- **WHEN** a principal requests an event stream for a Run outside its authorized scope
- **THEN** the API denies access using the platform's non-enumerating behavior

### Requirement: Native conversation workbench
The Vue 3/TypeScript/Element Plus workbench MUST consume typed Run events and clearly display assistant text, tool lifecycle and public result summaries, waiting input, cancellation, failure, interruption and completion. Reconnect MUST use the cursor and MUST NOT resubmit the user's prompt. Untrusted Markdown, code and file names MUST be safely rendered.

#### Scenario: Tool is running during a streamed response
- **WHEN** the workbench receives a persisted tool-started event
- **THEN** it displays the tool's public status and later updates that same invocation from completion/failure events

#### Scenario: Network connection drops
- **WHEN** the SSE connection is interrupted while a Run is non-terminal
- **THEN** the workbench preserves the Run identity and resumes events from the last seen sequence without resubmitting the prompt

#### Scenario: Run waits for user input
- **WHEN** the workbench receives an input-requested event
- **THEN** it presents the pending question and submits a typed, idempotent response command

#### Scenario: User stops a Run
- **WHEN** the user requests cancellation
- **THEN** the workbench shows a cancellation-pending state until a durable terminal/uncertain state is received

### Requirement: Accessible execution status
Execution states MUST be understandable without relying only on color. Keyboard focus and actions MUST remain usable; asynchronous state announcements MUST be concise and must not move focus or announce every token delta as a competing status message.

#### Scenario: Screen reader observes Run state change
- **WHEN** a Run changes to waiting input, failed, interrupted, cancelled or completed
- **THEN** the workbench announces a concise contextual status and keeps focus stable

#### Scenario: User operates the workbench by keyboard
- **WHEN** the user navigates messages, input, send and stop controls using a keyboard
- **THEN** controls have accessible names, visible focus, logical order and usable disabled/loading feedback
