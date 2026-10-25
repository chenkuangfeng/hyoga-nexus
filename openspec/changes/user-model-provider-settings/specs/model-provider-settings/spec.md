### ADDED Requirements

#### Requirement: Multiple scoped providers and models
Users MUST be able to manage multiple personal providers and models. Workspace administrators MUST be able to manage shared providers. Supported execution protocol MUST be explicitly identified. Personal resources MUST remain private at listing, agent publication, run creation and execution boundaries.

#### Scenario: Unauthorized access
- WHEN a user requests another user's provider or credential-backed execution
- THEN access is denied without exposing the secret or private configuration.

#### Requirement: Write-only secrets
API Keys MUST be encrypted at rest using a deployment-managed key. Responses, logs, audits, validation errors and browser storage MUST NOT contain plaintext secrets. Existing environment credential references MUST remain supported.

#### Scenario: Missing deployment key
- WHEN encrypted credential storage or resolution is requested without a valid deployment key
- THEN the operation fails clearly without storing plaintext or generating a fallback key.

#### Requirement: Default selection
New agent model selection MUST use explicit selection before personal default before workspace default. Default changes MUST NOT change published agents, existing sessions or active runs. Unauthorized or disabled models MUST NOT be selected.

#### Scenario: Default changes
- WHEN the user selects a different default model
- THEN new agent creation preselects it while existing sessions retain their model version.

#### Requirement: Bounded connection testing
Connection tests MUST require resource authorization, enforce bounded requests and return sanitized results. Provider requests MUST enforce network destination policy, prevent redirect bypass and protect private network destinations.

#### Scenario: Invalid destination
- WHEN a provider points to a forbidden destination
- THEN testing and runtime execution reject it before sending a credential.

#### Requirement: Configuration lifecycle
Edits MUST preserve immutable model versions. Deletion MUST disable future use, preserve historical metadata and resolve affected default references explicitly.
