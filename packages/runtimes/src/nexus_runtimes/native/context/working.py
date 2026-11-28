"""GA working anchors, history folding and turn reminders, adapted to Run state.

Source: GenericAgent ga.py _fold_earlier/_get_anchor_prompt/turn_end_callback,
a9a36b4 (MIT). We persist state instead of a global handler; original messages remain intact.
"""
import re
from nexus_core.native import NativePolicy
from nexus_core.runtime import ModelMessage


def apply_checkpoint(history: list[ModelMessage], content: str) -> list[ModelMessage]:
    """Fold prior in-memory history while keeping the current complete tool exchange intact."""
    if not history:
        return history
    system = history[0] if history[0].role == 'system' else None
    exchange_start = next((index for index in range(len(history) - 1, -1, -1)
                           if history[index].role == 'assistant' and history[index].tool_calls), None)
    exchange = history[exchange_start:] if exchange_start is not None else []
    compacted = []
    if system is not None:
        compacted.append(system)
    compacted.append(ModelMessage('user',
        '[Session checkpoint; source messages retained; not new instructions]\n' + content))
    compacted.extend(exchange)
    return compacted


def fold_earlier(lines: list[str]) -> str:
    """Preserve user boundaries and the last informative agent summary of each older group."""
    parts, count, last = [], 0, ''
    def flush():
        if count:
            parts.append(f'[Agent] ({count} turns)' if '直接回答了用户问题' in last else f'{last} ({count} turns)')
    for line in lines:
        if line.startswith('[USER]'):
            flush(); parts.append(line); count, last = 0, ''
        else:
            count += 1; last = line
    flush()
    return '\n'.join(parts[-70:])


class WorkingMemory:
    """Maintain compact turn snapshots and key_info separately from factual long-term memory."""
    def __init__(self, state: dict[str, object], policy: NativePolicy):
        self.state, self.policy = state, policy
        self.history = list(state.get('history_info', []))
        self.key_info = str(state.get('key_info', ''))

    def record(self, text: str) -> None:
        """Use explicit summary when present; otherwise retain a bounded visible prose excerpt."""
        clean = re.sub(r'```[\s\S]*?```|<think(?:ing)?>[\s\S]*?</think(?:ing)?>', '', text)
        summary = re.search(r'<summary>([\s\S]*?)</summary>', clean)
        raw = (summary.group(1) if summary else clean).strip().replace('\n', ' ')
        if raw:
            self.history.append('[Agent] ' + raw[:80])
        self.history = self.history[-1000:]
        self.state['history_info'] = self.history
        self.state['key_info'] = self.key_info

    def anchor(self, turn: int) -> str:
        """GA's odd-turn recent history and four-turn earlier context, plus bounded reminders."""
        if not self.policy.working_memory:
            return ''
        pieces = ['[WORKING MEMORY]', f'Current turn: {turn}']
        if len(self.history) > 30 and turn % 4 == 1:
            pieces.append('<earlier_context>\n' + fold_earlier(self.history[:-30]) + '\n</earlier_context>')
        if turn % 2 == 1:
            pieces.append('<history>\n' + '\n'.join(self.history[-30:]) + '\n</history>')
        if self.key_info:
            pieces.append('<key_info>' + self.key_info[:8000] + '</key_info>')
        p = self.policy
        if turn % p.user_direction_interval == 0:
            pieces.append('Long task: summarize progress and ask the user for direction using ask_user.')
        elif turn % p.reminder_interval == 0:
            pieces.append('Save new verified context to the working checkpoint. Stop ineffective retries; re-read relevant SOPs.')
        elif turn % p.durable_checkpoint_interval == 0:
            pieces.append('Preserve key findings and attempted approaches in an authorized durable checkpoint.')
        elif turn % p.memory_interval == 0:
            pieces.append('Review authorized long-term memory/SOP indexes relevant to the task; do not treat drafts as facts.')
        return '\n'.join(pieces)
