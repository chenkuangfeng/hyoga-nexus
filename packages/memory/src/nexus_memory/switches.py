"""Long-term memory switches: the space, the member and the agent each decide whether memory is used.

Reference: WeKnora ``internal/application/service/memory/service.go`` ``enabledScope`` and
``internal/types/memory.go`` ``ApplyAgentMemoryPreference`` (version ``e1f9a6166``). Memory is available
only when all three levels allow it; a single level turned off is enough to stop every read and write
for that Run. Turning memory off never deletes entries, drafts, versions or tombstones.

This module is pure: callers read the stored settings and pass plain values in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

#: Builtin tools that read or write long-term memory. They are removed from a Run's tool definitions
#: and refused by the gateway when memory is off, even if the agent version binds them.
#: Includes the past-conversation tools (stage 4, decision 4): they follow the memory switches.
MEMORY_TOOL_NAMES = frozenset({'read_memory', 'search_memory', 'propose_memory_draft', 'start_long_term_update',
                               'search_conversations', 'read_conversation'})

#: ``explicit`` keeps only drafts the model proposes; ``auto`` also lets members run automatic capture.
WRITE_MODES = ('explicit', 'auto')
#: Defaults when a space has no settings row: memory on, automatic capture allowed (decision 1),
#: so spaces that existed before the switches keep their behavior.
DEFAULT_SPACE_ENABLED = True
DEFAULT_WRITE_MODE = 'auto'

#: Key of the agent group in ``budgets``; ``{"enabled": false}`` turns memory off for that agent.
AGENT_BUDGET_KEY = 'memory'

Reason = Literal['space_disabled', 'agent_disabled', 'user_disabled']


@dataclass(frozen=True)
class MemoryState:
    """Effective memory state for one owner, optionally for one agent version.

    ``reason`` names the first level that turned memory off, in the order space, agent, member;
    it is ``None`` when memory is available. ``capture_allowed`` additionally requires ``auto`` mode.
    """

    available: bool
    write_mode: str
    reason: Reason | None

    @property
    def capture_allowed(self) -> bool:
        return self.available and self.write_mode == 'auto'


def agent_preference(budgets: Mapping[str, Any] | None) -> bool | None:
    """The agent's memory preference: ``False`` when it turned memory off, ``None`` when it inherits.

    Only an explicit ``False`` turns memory off. Stored values that are not booleans come only from rows
    written before validation existed and are treated as inheriting, never as an error at run time.
    """
    group = (budgets or {}).get(AGENT_BUDGET_KEY)
    if isinstance(group, dict) and group.get('enabled') is False:
        return False
    return None


def recall_enabled(budgets: Mapping[str, Any] | None) -> bool:
    """Whether memory is automatically searched on every user turn; default off."""
    group = (budgets or {}).get(AGENT_BUDGET_KEY)
    return isinstance(group, dict) and group.get('recall') is True


def profile_injection_enabled(budgets: Mapping[str, Any] | None) -> bool:
    """Whether approved profile facts are injected into every model request; default off."""
    group = (budgets or {}).get(AGENT_BUDGET_KEY)
    return isinstance(group, dict) and group.get('profile') is True


def resident_kinds(budgets: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return the configured always-on categories, with safe defaults for old agents."""
    group = (budgets or {}).get(AGENT_BUDGET_KEY)
    kinds = group.get('context_kinds') if isinstance(group, dict) else None
    if isinstance(kinds, list):
        return tuple(kind for kind in ('preference', 'personal_info') if kind in kinds)
    return ('preference', 'personal_info')


def resolve(*, space_enabled: bool, write_mode: str, user_enabled: bool,
            agent_enabled: bool | None = None) -> MemoryState:
    """Combine the three switches. ``agent_enabled=None`` means no agent context or the agent inherits."""
    mode = write_mode if write_mode in WRITE_MODES else DEFAULT_WRITE_MODE
    if not space_enabled:
        return MemoryState(False, mode, 'space_disabled')
    if agent_enabled is False:
        return MemoryState(False, mode, 'agent_disabled')
    if not user_enabled:
        return MemoryState(False, mode, 'user_disabled')
    return MemoryState(True, mode, None)


def validate_agent_budget(budgets: Mapping[str, Any]) -> None:
    """Validate the optional memory, automatic-recall and profile-injection switches.

    ``recall`` (openspec 2026-11-06-memory-evolution D3) turns per-turn memory recall off for the agent.

    Raises ``ValueError`` (reported as 422) without echoing the submitted value.
    """
    group = budgets.get(AGENT_BUDGET_KEY)
    if group is None:
        return
    if not isinstance(group, dict):
        raise ValueError('Agent memory settings must be an object')
    if set(group) - {'enabled', 'recall', 'profile', 'context_kinds', 'capture_enabled',
                     'capture_model_version_id', 'capacity_policy'}:
        raise ValueError('Unknown agent memory setting')
    if 'enabled' in group and not isinstance(group['enabled'], bool):
        raise ValueError('Agent memory enabled must be a boolean')
    if 'recall' in group and not isinstance(group['recall'], bool):
        raise ValueError('Agent memory recall must be a boolean')
    if 'profile' in group and not isinstance(group['profile'], bool):
        raise ValueError('Agent profile injection must be a boolean')
    if 'context_kinds' in group and (not isinstance(group['context_kinds'], list)
            or any(kind not in ('preference', 'personal_info') for kind in group['context_kinds'])
            or len(set(group['context_kinds'])) != len(group['context_kinds'])):
        raise ValueError('Agent memory context categories are invalid')
    if 'capture_enabled' in group and not isinstance(group['capture_enabled'], bool):
        raise ValueError('Agent memory capture enabled must be a boolean')
    model_id = group.get('capture_model_version_id')
    if model_id is not None and model_id != '':
        from uuid import UUID
        try:
            UUID(str(model_id))
        except (TypeError, ValueError):
            raise ValueError('Agent memory capture model version is invalid') from None
    if group.get('capacity_policy', 'reject') not in ('reject', 'evict_auto'):
        raise ValueError('Agent memory capacity policy is invalid')
