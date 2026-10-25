### ADDED Requirements

#### Requirement: Disabled by default
Sandbox execution MUST be disabled by default. Disabled configuration MUST NOT connect to Docker or register execution tools. Enablement MUST require explicit configuration and target-environment isolation verification, and MUST preserve existing authorization and approval requirements.

#### Scenario: Backend not verified
- WHEN configuration requests execution but isolation has not been verified
- THEN execution is rejected without running user code.

#### Requirement: Bounded isolated execution
The backend MUST isolate executions and enforce timeout, cancellation, memory, CPU, PID and output limits. It MUST default to no network and MUST NOT expose host credentials, host shell or container management sockets.

#### Scenario: Cancellation
- WHEN an execution is cancelled or exceeds its deadline
- THEN its container is stopped and cleaned up, with a stable outcome and no blind replay.

#### Requirement: Honest verification status
Mock verification MUST NOT be reported as deployed isolation verification. PostgreSQL acceptance MUST remain pending until the final environment acceptance stage.
