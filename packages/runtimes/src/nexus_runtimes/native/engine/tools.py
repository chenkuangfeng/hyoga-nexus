"""Tool batches with WeKnora read concurrency and mutation barriers.

Derived from internal/agent/act.go e1f9a6166 (MIT). Only explicitly read-only,
idempotent tools may overlap; results and lifecycle events preserve model order.
"""
import asyncio
from nexus_core.runtime import ToolDisposition, ToolResult


async def execute_batch(calls, definitions, gateway, token, hook, turn, parallel: bool = False):
    """Yield ordered results, draining safe reads before every mutation or wait-capable call."""
    declared = {item.name: item for item in definitions}
    async def execute(call):
        token.check()
        await hook('tool.before', turn, call.name)
        try:
            return await gateway.execute(call, token)
        finally:
            await hook('tool.after', turn, call.name)
    index = 0
    while index < len(calls):
        end = index
        if parallel:
            while end < len(calls) and end - index < 8:
                definition = declared.get(calls[end].name)
                if not definition or not definition.read_only or not definition.idempotent or definition.side_effects or definition.requires_approval:
                    break
                end += 1
        if end == index:
            result = await execute(calls[index])
            yield index, result
            if result.disposition != ToolDisposition.CONTINUE:
                return
            index += 1
        else:
            results = await asyncio.gather(*(execute(call) for call in calls[index:end]))
            for offset, result in enumerate(results):
                yield index + offset, result
            index = end
