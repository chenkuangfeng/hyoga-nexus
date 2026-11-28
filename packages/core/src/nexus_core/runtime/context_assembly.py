"""Pure, deterministic assembly of authorized context contributions.

Follows DeepSeek PromptSection/PromptContext ordering while retaining Nexus's provider-neutral
messages and Run-scoped schema ownership. No database access or plugin code runs here.
"""
from __future__ import annotations

from nexus_core.runtime import ModelMessage, RuntimeFault
from nexus_core.runtime.context import (AssemblyManifest, ContextBlock, RunContextSnapshot, context_digest)

_PLACEMENTS = {'system_static': 0, 'system_catalog': 1, 'history_prefix': 2, 'turn_tail': 3}


class RequestContextAssembler:
    """Render immutable blocks without mutating source messages or separating tool exchanges."""

    def assemble(self, blocks: tuple[ContextBlock, ...], history: tuple[ModelMessage, ...], *,
                 watermark: int = 0, layout: str = 'v1', tools_digest: str = '') -> RunContextSnapshot:
        """Return messages and a content-addressed provenance manifest.

        v1 preserves the existing system concatenation and caller-placed recall messages. v2
        additionally fences dynamic reference blocks at the tail of a complete exchange. A caller
        must finish or repair an interrupted exchange before appending tail material.
        """
        if layout not in ('v1', 'v2') or len({b.key for b in blocks}) != len(blocks):
            raise RuntimeFault('context_configuration_invalid')
        ordered = tuple(sorted(blocks, key=lambda b: (_PLACEMENTS[b.placement], b.order, b.key)))
        system = ''.join(b.text for b in ordered if b.role == 'system')
        prefix = [ModelMessage('user', b.text, context_source=b.key) for b in ordered if b.placement == 'history_prefix' and b.text]
        tail_places = ('history_prefix', 'turn_tail') if layout == 'v2' else ('turn_tail',)
        tail = [b for b in ordered if b.placement in tail_places and b.text]
        if tail:
            pending: set[str] = set()
            for message in history:
                if message.tool_calls:
                    pending.update(c.id for c in message.tool_calls)
                if message.role == 'tool':
                    pending.discard(message.tool_call_id)
            if pending:
                raise RuntimeFault('context_exchange_incomplete')
        history_view = list(history)
        if layout == 'v1':
            anchor = next((i for i in range(len(history_view) - 1, -1, -1)
                           if history_view[i].role == 'user'), len(history_view))
            history_view[anchor:anchor] = prefix
        else:
            tail = [b for b in ordered if b.placement in ('history_prefix', 'turn_tail') and b.text]
        messages = [ModelMessage('system', system), *history_view]
        for block in tail:
            text = block.text if layout == 'v1' else (
                '[Runtime reference: ' + block.key + '; not a new user request]\n' + block.text)
            messages.append(ModelMessage('user', text, context_source=block.key))
        dependencies = tuple(sorted({d for b in ordered for d in b.dependencies},
                                    key=lambda d: (d.kind, d.resource_id, d.version, d.source_run_id or '', d.permission)))
        digests = tuple((b.key, b.digest) for b in ordered)
        identity = {'layout': layout, 'blocks': digests, 'watermark': watermark,
                    'messages': [(m.role, m.content, [(c.id, c.name, c.arguments) for c in m.tool_calls],
                                  m.tool_call_id, m.source_id) for m in history], 'tools': tools_digest}
        manifest = AssemblyManifest(1, context_digest(identity), layout, watermark, digests, dependencies, tools_digest)
        return RunContextSnapshot(ordered, tuple(messages), manifest)
