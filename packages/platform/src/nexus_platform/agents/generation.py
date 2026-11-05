"""Agent-level generation parameters stored in ``budgets['generation']``.

Reference: WeKnora ``CustomAgentConfig`` keeps ``temperature`` and ``reasoning_effort`` on the agent.
Nexus model profiles also carry these keys in their ``options``. The agent value wins when set; an
unset key falls back to the model profile. Values are snapshotted with the published agent version,
so editing an agent never changes Runs of versions already in use.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

GENERATION_KEY = 'generation'
#: ``off`` disables reasoning for this agent: the merged options carry no ``reasoning_effort``.
#: ``auto`` follows the model profile (no override); other levels are sent to the provider as is.
REASONING_EFFORTS = ('off', 'auto', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
TEMPERATURE_RANGE = (0.0, 2.0)


def validate_generation(budgets: Mapping[str, Any]) -> None:
    """Reject unknown keys and out-of-range values in ``budgets['generation']``.

    A missing or empty group is valid. Raises ``ValueError`` (reported as 422) with a message that
    names the offending key but never echoes the submitted value.
    """
    generation = budgets.get(GENERATION_KEY)
    if generation is None:
        return
    if not isinstance(generation, dict):
        raise ValueError('Agent generation settings must be an object')
    unknown = set(generation) - {'temperature', 'reasoning_effort'}
    if unknown:
        raise ValueError('Unknown agent generation setting')
    temperature = generation.get('temperature')
    if temperature is not None:
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
            raise ValueError('temperature must be a number')
        low, high = TEMPERATURE_RANGE
        if not low <= temperature <= high:
            raise ValueError('temperature must be between 0 and 2')
    effort = generation.get('reasoning_effort')
    if effort is not None and effort not in REASONING_EFFORTS:
        raise ValueError('reasoning_effort is not supported')


def merged_model_options(options: Mapping[str, Any], budgets: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return model profile options overridden by the agent's generation settings.

    Unset agent keys and ``reasoning_effort = auto`` keep the profile value. ``reasoning_effort = off`` removes the key so the
    provider request carries no reasoning parameter. Invalid stored values are ignored rather than
    sent, because a published version was already validated and only legacy rows could differ.
    """
    merged = dict(options or {})
    generation = (budgets or {}).get(GENERATION_KEY)
    if not isinstance(generation, dict):
        return merged
    temperature = generation.get('temperature')
    if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
        merged['temperature'] = temperature
    effort = generation.get('reasoning_effort')
    if effort == 'off':
        merged.pop('reasoning_effort', None)
    elif effort in REASONING_EFFORTS and effort != 'auto':
        merged['reasoning_effort'] = effort
    return merged
