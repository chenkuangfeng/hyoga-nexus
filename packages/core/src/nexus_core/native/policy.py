"""Immutable user-configured Native policy and validation; never grants authority."""
from dataclasses import dataclass, field

BUILTIN_TOOL_NAMES = ('ask_user', 'update_working_checkpoint', 'propose_memory_draft', 'start_long_term_update', 'read_memory')


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
    model_retries: int = 2
    retry_delay_seconds: float = 1
    max_retry_delay_seconds: float = 60
    parallel_reads: bool = False
    summarize_context: bool = False
    reminder_interval: int = 17
    memory_interval: int = 15
    durable_checkpoint_interval: int = 41
    user_direction_interval: int = 175
    enabled_tools: list[str] = field(default_factory=list)
    fallback_models: list[str] = field(default_factory=list)
    routing_spring_seconds: int = 300
    project_name: str = ''
    project_context: str = ''

    def __post_init__(self):
        if not isinstance(self.enabled_tools, list) or any(name not in BUILTIN_TOOL_NAMES for name in self.enabled_tools) or len(set(self.enabled_tools)) != len(self.enabled_tools):
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
        for name in ('repeated_limit', 'reminder_interval', 'memory_interval',
                     'durable_checkpoint_interval', 'user_direction_interval'):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= 1000:
                raise ValueError('Native intervals must be integers between 1 and 1000')
        for name in ('clarify_code', 'working_memory', 'parallel_reads', 'summarize_context'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('Native switches must be boolean')
        import math
        for value in (self.retry_delay_seconds, self.max_retry_delay_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 60:
                raise ValueError('Retry delay must be finite and between 0 and 60 seconds')
        if not isinstance(self.project_name, str) or len(self.project_name) > 160 or not isinstance(self.project_context, str) or len(self.project_context) > 8000:
            raise ValueError('Project context is too large')
