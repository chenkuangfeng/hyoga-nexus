"""Typed authorized context transformations; SDK and persistence objects are excluded."""
from dataclasses import dataclass
from typing import Literal
from ..runtime.models import ModelMessage

@dataclass(frozen=True)
class HookContext:
    """Authorized model-visible messages offered to a trusted context transformer.

    No SDK clients, credentials, mutable locals or database handles are exposed. A returned
    message set cannot grant tools; the engine obtains definitions independently each turn.
    """
    run_id: str
    phase: Literal['agent.before', 'turn.before', 'turn.after', 'agent.after']
    turn: int
    messages: tuple[ModelMessage, ...]


@dataclass(frozen=True)
class HookTransform:
    """Append explicit model context or enqueue completion prompts; never change authority."""
    append_messages: tuple[ModelMessage, ...] = ()
    done_prompts: tuple[str, ...] = ()
