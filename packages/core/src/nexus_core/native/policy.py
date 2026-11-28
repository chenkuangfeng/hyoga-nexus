"""Immutable user-configured Native policy and validation; never grants authority."""
import re
from dataclasses import dataclass, field

BUILTIN_TOOL_NAMES = ('ask_user', 'update_working_checkpoint', 'propose_memory_draft', 'start_long_term_update', 'read_memory', 'search_memory',
                      'search_conversations', 'read_conversation', 'read_tool_output', 'todo', 'load_skill', 'read_skill_file', 'exec_skill',
                      'skill_search', 'skill_manage', 'skill_save', 'skill_rollback',
                      'search_knowledge', 'read_document', 'list_documents', 'query_knowledge_graph', 'grep_chunks',
                      'document_outline', 'sandbox_list_files', 'sandbox_read_file', 'sandbox_search_files',
                      'sandbox_write_file', 'sandbox_edit_file', 'sandbox_exec', 'sandbox_exec_async', 'sandbox_job_wait',
                      'sandbox_job_cancel', 'web_search', 'web_fetch', 'delegate_task', 'vision_analyze', 'cronjob_list', 'cronjob_manage')
#: Tools that no longer exist. Saved settings and published agent versions may still name them: they are accepted,
#: and ignored when a Run is prepared. `run_skill_script` was replaced by `exec_skill` (openspec 2026-11-07-skill-evolution).
RETIRED_TOOL_NAMES = frozenset({'run_skill_script'})
#: Tools of the `sandbox` group (openspec 2026-11-07-tool-expansion, section 4).
SANDBOX_TOOL_NAMES = frozenset({'sandbox_list_files', 'sandbox_read_file', 'sandbox_search_files',
                                'sandbox_write_file', 'sandbox_edit_file', 'sandbox_exec', 'sandbox_exec_async',
                                'sandbox_job_wait', 'sandbox_job_cancel'})
#: Knowledge tools (openspec 2026-11-06-knowledge-base K1.8); offered only when the agent binds a knowledge base.
KNOWLEDGE_TOOL_NAMES = frozenset({'search_knowledge', 'read_document', 'list_documents', 'query_knowledge_graph',
                                  'grep_chunks', 'document_outline'})
#: Agent tool access levels (tool-call-hardening D11).
TOOL_ACCESS_LEVELS = ('read_only', 'standard', 'strict')
#: Builtin that pages through externalized tool output (P2). Its presence in a Run's bindings enables spilling.
TOOL_OUTPUT_READER = 'read_tool_output'
#: Hard cap on one externalized output; anything beyond it is not stored (keeps rows bounded).
TOOL_OUTPUT_STORE_LIMIT = 200_000


def _check_int(value, low: int, high: int, name: str) -> None:
    """Reject bools and non-integers; bounds are inclusive."""
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer between {low} and {high}')


@dataclass(frozen=True)
class NativePolicy:
    """Behavior settings translated from GA handlers and WeKnora response guards.

    Retry counts are bounded and charged to the existing Run budgets. Hooks and parallel
    reads are opt-in; an enabled policy never registers an unavailable execution backend.
    """
    empty_retries: int = 2
    repeated_limit: int = 3
    clarify_code: bool = True
    working_memory: bool = True
    #: Whether skills may run declared scripts. Effective only when the platform gate is open
    #: (development auth mode, local backend and [skills].allow_local_scripts); see proposal 2026-11-04-skill-scripts.
    skill_scripts: bool = True
    model_retries: int = 2
    # Continuation prompts sent after a length-truncated final answer (3.7). 0 accepts the truncated answer.
    max_continuations: int = 2
    retry_delay_seconds: float = 1
    max_retry_delay_seconds: float = 60
    parallel_reads: bool = True
    summarize_context: bool = True
    reminder_interval: int = 17
    memory_interval: int = 15
    durable_checkpoint_interval: int = 41
    user_direction_interval: int = 175
    enabled_tools: list[str] = field(default_factory=list)
    fallback_models: list[str] = field(default_factory=list)
    routing_spring_seconds: int = 300
    project_name: str = ''
    project_context: str = ''
    # Context and tool-output governance (openspec 2026-11-01-context-token-performance, design §14).
    # Byte-stable prefix placement of working memory is opt-in until the eval gate passes (P1).
    working_memory_tail: bool = False
    tool_output_inline_limit: int = 2000
    tool_preview_chars: int = 500
    tool_output_page_chars: int = 4000
    tool_result_window_rounds: int = 6
    compact_high_ratio: float = 1.0
    compact_low_ratio: float = 0.6
    summary_max_chars: int = 8000
    # Empty string means the agent's own model profile performs summarization.
    compaction_model_profile_version_id: str = ''
    # Streaming text is persisted as deltas in batches (P6). 0 ms restores one event per chunk.
    delta_flush_ms: int = 150
    delta_flush_chars: int = 256
    # Tool-call hardening (openspec 2026-11-06-tool-call-hardening, G18).
    #: `read_only` hides write/destructive tools; `standard` asks for destructive ones; `strict` asks for writes too.
    tool_access: str = 'standard'
    #: Public tool output allowed per model turn before later results are externalized; 0 turns it off.
    tool_turn_budget_chars: int = 20000
    #: Repeated identical tool calls: remind at this count, end the Run at the stop count; 0 turns each off.
    tool_repeat_warn_at: int = 3
    tool_repeat_stop_at: int = 8
    #: Consecutive failures of one tool that end the Run; 0 turns it off.
    tool_failure_stop_at: int = 5
    #: Warn (never block) when tool output looks like an injected instruction.
    tool_injection_scan: bool = True
    # Tool groups (openspec 2026-11-07-tool-expansion, R1). Missing groups take their `default_enabled`, so
    # versions saved before a group existed do not gain its tools. The switch only narrows access.
    tool_groups_enabled: dict[str, bool] = field(default_factory=dict)
    #: Default and ceiling of one sandbox command, and the output kept per stream. The deployment's
    #: `[sandbox].exec_timeout_max_seconds` still caps the timeout.
    #: Progressive tool loading (R4): deferrable tools (MCP and tools that declare it) whose schemas together reach
    #: this many tokens are reached through tool_search / tool_describe / tool_call. 0 turns it off.
    tool_search_min_tokens: int = 2500
    #: Model profile version used by `vision_analyze` (type vision). Empty: the tool reports that none is configured.
    vision_model_profile_version_id: str = ''
    sandbox_exec_timeout_seconds: int = 30
    sandbox_output_limit: int = 20000
    #: Name of the deployment's sandbox profile this agent runs on; empty takes the deployment's default profile.
    #: Only profiles the operator defined can be chosen (openspec 2026-11-07-skill-evolution, S2).
    sandbox_profile: str = ''

    def __post_init__(self):
        if not isinstance(self.enabled_tools, list) or any(name not in BUILTIN_TOOL_NAMES and name not in RETIRED_TOOL_NAMES for name in self.enabled_tools) or len(set(self.enabled_tools)) != len(self.enabled_tools):
            raise ValueError('Invalid or duplicate builtin tool selection')
        from uuid import UUID
        if not isinstance(self.fallback_models, list) or len(self.fallback_models) > 5:
            raise ValueError('At most five fallback models are allowed')
        try:
            for identifier in self.fallback_models:
                UUID(identifier)
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Fallback model identifiers must be UUIDs') from None
        if type(self.routing_spring_seconds) is not int or not 1 <= self.routing_spring_seconds <= 86400:
            raise ValueError('Model routing cooldown is invalid')
        for name in ('empty_retries', 'model_retries'):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 5:
                raise ValueError('Native retry counts must be integers between 0 and 5')
        if type(self.max_continuations) is not int or not 0 <= self.max_continuations <= 5:
            raise ValueError('Native continuation count must be an integer between 0 and 5')
        for name in ('repeated_limit', 'reminder_interval', 'memory_interval',
                     'durable_checkpoint_interval', 'user_direction_interval'):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= 1000:
                raise ValueError('Native intervals must be integers between 1 and 1000')
        for name in ('clarify_code', 'working_memory', 'skill_scripts', 'parallel_reads', 'summarize_context', 'working_memory_tail'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('Native switches must be boolean')
        _check_int(self.tool_output_inline_limit, 200, 100000, 'tool_output_inline_limit')
        _check_int(self.tool_preview_chars, 0, self.tool_output_inline_limit, 'tool_preview_chars')
        _check_int(self.tool_output_page_chars, 500, 20000, 'tool_output_page_chars')
        _check_int(self.tool_result_window_rounds, 1, 100, 'tool_result_window_rounds')
        _check_int(self.summary_max_chars, 500, 32000, 'summary_max_chars')
        _check_int(self.delta_flush_ms, 0, 5000, 'delta_flush_ms')
        _check_int(self.delta_flush_chars, 1, 10000, 'delta_flush_chars')
        if self.tool_access not in TOOL_ACCESS_LEVELS:
            raise ValueError('tool_access must be read_only, standard or strict')
        if self.tool_turn_budget_chars != 0:
            _check_int(self.tool_turn_budget_chars, 2000, 500000, 'tool_turn_budget_chars')
        for name in ('tool_repeat_warn_at', 'tool_repeat_stop_at', 'tool_failure_stop_at'):
            _check_int(getattr(self, name), 0, 50, name)
        if self.tool_repeat_warn_at and self.tool_repeat_stop_at and self.tool_repeat_warn_at >= self.tool_repeat_stop_at:
            raise ValueError('tool_repeat_warn_at must be below tool_repeat_stop_at')
        if type(self.tool_injection_scan) is not bool:
            raise ValueError('Native switches must be boolean')
        _check_int(self.tool_search_min_tokens, 0, 200000, 'tool_search_min_tokens')
        _check_int(self.sandbox_exec_timeout_seconds, 1, 3600, 'sandbox_exec_timeout_seconds')
        _check_int(self.sandbox_output_limit, 1000, 200000, 'sandbox_output_limit')
        if not isinstance(self.sandbox_profile, str) or (
                self.sandbox_profile and not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', self.sandbox_profile)):
            raise ValueError('sandbox_profile must be empty or a profile name')
        from .tool_groups import GROUP_IDS, group_of
        if (not isinstance(self.tool_groups_enabled, dict)
                or any(key not in GROUP_IDS or group_of(key).locked or type(value) is not bool
                       for key, value in self.tool_groups_enabled.items())):
            raise ValueError('tool_groups_enabled must map switchable tool group ids to booleans')
        for name in ('compact_high_ratio', 'compact_low_ratio'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.1 <= value <= 1.0:
                raise ValueError(f'{name} must be a number between 0.1 and 1.0')
        if not self.compact_low_ratio < self.compact_high_ratio or self.compact_high_ratio < 0.5:
            raise ValueError('Compaction low ratio must be below high ratio, and high ratio at least 0.5')
        if self.vision_model_profile_version_id:
            from uuid import UUID
            try:
                UUID(self.vision_model_profile_version_id)
            except (ValueError, TypeError, AttributeError):
                raise ValueError('Vision model identifier must be a UUID or empty') from None
        if self.compaction_model_profile_version_id:
            from uuid import UUID
            try:
                UUID(self.compaction_model_profile_version_id)
            except (ValueError, TypeError, AttributeError):
                raise ValueError('Compaction model identifier must be a UUID or empty') from None
        import math
        for value in (self.retry_delay_seconds, self.max_retry_delay_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 60:
                raise ValueError('Retry delay must be finite and between 0 and 60 seconds')
        if not isinstance(self.project_name, str) or len(self.project_name) > 160 or not isinstance(self.project_context, str) or len(self.project_context) > 8000:
            raise ValueError('Project context is too large')
