"""Tool batches with read concurrency, per-key serialization and mutation barriers.

Derived from internal/agent/act.go e1f9a6166 (MIT) for the read/mutation barriers, and extended with
openspec 2026-11-07-tool-expansion, section 2: a tool may decide per call (`ToolDefinition.concurrency`)
whether the call overlaps with its neighbours (`parallel`), waits for everything before it and runs alone
(`exclusive`), or queues behind earlier calls with the same key (`serial`, for example a file path; WeKnora
`file_mutation_queue.go`). Tools that declare nothing keep the old rule: only explicitly read-only, idempotent
tools overlap. Results and lifecycle events always preserve model order.
"""
import asyncio
import json

from nexus_core.runtime import ConcurrencyHint, ToolDisposition

#: Calls that may overlap in one group, as before.
MAX_PARALLEL = 8
_PARALLEL = ConcurrencyHint('parallel')
_EXCLUSIVE = ConcurrencyHint('exclusive')


def classify(call, definition, gateway) -> ConcurrencyHint:
    """How `call` may be scheduled next to its siblings.

    Without a `concurrency` declaration the call overlaps only when its tool is read-only, idempotent and
    needs neither side effects nor approval. A declaration is called with the arguments as the model sent them
    (key arguments such as paths are strings, so coercion does not change them); unparsable arguments, a
    raising declaration or a malformed hint all mean `exclusive`. A call that may suspend for approval is
    always `exclusive`: a suspended batch is resumed from the first pending call, and siblings that already
    ran in parallel would run again.
    """
    if definition is None:
        return _EXCLUSIVE
    if definition.concurrency is None:
        safe = (definition.read_only and definition.idempotent
                and not definition.side_effects and not definition.requires_approval)
        return _PARALLEL if safe else _EXCLUSIVE
    try:
        arguments = json.loads(call.arguments or '{}')
        hint = definition.concurrency(arguments) if isinstance(arguments, dict) else _EXCLUSIVE
    except Exception:  # a tool's own declaration must never break the batch
        return _EXCLUSIVE
    if not isinstance(hint, ConcurrencyHint) or hint.mode == 'exclusive':
        return _EXCLUSIVE
    if hint.mode == 'serial' and not hint.key:
        return _EXCLUSIVE
    if hint.mode not in ('parallel', 'serial') or definition.requires_approval:
        return _EXCLUSIVE
    if definition.side_effects or definition.risk not in ('read', 'probe'):
        may_suspend = getattr(gateway, 'may_suspend', None)
        if may_suspend is None or may_suspend(call):
            return _EXCLUSIVE
    return hint


async def _after(previous, operation):
    """Run `operation` once `previous` has settled, whatever its outcome."""
    if previous is not None:
        await asyncio.wait((previous,))
    return await operation


async def execute_batch(calls, definitions, gateway, token, hook, turn, parallel: bool = False):
    """Yield ordered results, draining safe overlapping calls before every mutation or wait-capable call."""
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
        end, hints = index, []
        if parallel:
            while end < len(calls) and end - index < MAX_PARALLEL:
                hint = classify(calls[end], declared.get(calls[end].name), gateway)
                if hint.mode == 'exclusive':
                    break
                hints.append(hint)
                end += 1
        if end == index:
            result = await execute(calls[index])
            yield index, result
            if result.disposition != ToolDisposition.CONTINUE:
                return
            index += 1
        else:
            tails, tasks = {}, []
            for call, hint in zip(calls[index:end], hints):
                previous = tails.get(hint.key) if hint.mode == 'serial' else None
                task = asyncio.ensure_future(_after(previous, execute(call)))
                if hint.mode == 'serial':
                    tails[hint.key] = task
                tasks.append(task)
            results = await asyncio.gather(*tasks)
            for offset, result in enumerate(results):
                yield index + offset, result
            index = end
