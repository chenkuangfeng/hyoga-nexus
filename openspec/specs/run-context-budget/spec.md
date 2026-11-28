# Run 上下文预算

## Requirements

### Requirement: Run context is bounded by configured model and agent windows
The system SHALL allow administrators to configure a model context window in K tokens and agents to follow that model window or configure a K-token ceiling. The effective window SHALL be the smaller configured value, default to 200K when the model window is absent, and drive Native context compaction and request fitting in estimated tokens.

#### Scenario: Agent follows model context window
- **WHEN** an agent has no context ceiling and its model profile has a 128K context window
- **THEN** Native execution uses a 128000-token context ceiling

#### Scenario: Agent caps the model context window
- **WHEN** an agent sets a 128K ceiling and its model profile is configured for 256K
- **THEN** Native execution uses a 128000-token context ceiling

#### Scenario: Agent ceiling exceeds the model window
- **WHEN** an agent sets a 256K ceiling and its model profile is configured for 128K
- **THEN** Native execution is capped at 128000 tokens

### Requirement: Cumulative Run token use is optional
The system SHALL allow a Run to continue beyond 16000 cumulative tokens when no explicit cumulative token cap is configured, while preserving configured positive hard caps and per-request/context/runtime limits.
