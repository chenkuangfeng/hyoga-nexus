"""Tool-call loop detection (openspec 2026-11-06-tool-call-hardening, section C; decision 2).

A model that keeps calling the same tool with the same arguments and gets the same result is stuck; so is
one that cycles through two to four such calls, or one whose tool keeps failing. Without a guard it runs
until the round or error budget is spent. Logic follows hermes-agent `ToolCallGuardrailController`
(agent/tool_guardrails.py) and deepseek-harness `repeat-tool-reminder`:

- signature = sha256(tool name, canonical argument JSON, first 2000 characters of the result);
- repeats = the longer of the consecutive identical streak and the trailing laps of a period-2..4 cycle;
- a reminder at `warn_at` and again two repeats later; `tool_loop_detected` at `stop_at`;
- consecutive failures of one tool: reminder at `warn_at`, `tool_loop_detected` at `failure_stop_at`;
  a success of that tool, or of any other tool with side effects, clears the failure count;
- new user input clears everything (`reset`).

Pure state machine over a JSON-serializable dict kept in `progress.state['tool_guard']`, so counts survive
a resume after approval or input. A threshold of 0 turns that check off.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

#: Signatures kept for cycle detection, and the result prefix that enters a signature.
HISTORY_LIMIT = 64
RESULT_PREFIX = 2000
MAX_PERIOD = 4
STATE_KEY = 'tool_guard'


@dataclass(frozen=True)
class GuardDecision:
    """`notice` is a continuation for the model; `stop` is the RuntimeFault code that ends the Run."""
    notice: str | None = None
    stop: str | None = None


def signature(name: str, arguments: str, result: str) -> str:
    try:
        canonical = json.dumps(json.loads(arguments or '{}'), sort_keys=True, ensure_ascii=False)
    except (ValueError, RecursionError):
        canonical = arguments or ''
    digest = hashlib.sha256()
    for part in (name, canonical, (result or '')[:RESULT_PREFIX]):
        digest.update(part.encode('utf-8', 'replace'))
        digest.update(b'\0')
    return digest.hexdigest()


class ToolLoopGuard:
    def __init__(self, state: dict, *, warn_at: int, stop_at: int, failure_stop_at: int):
        self.warn_at, self.stop_at, self.failure_stop_at = warn_at, stop_at, failure_stop_at
        self.data = state.setdefault(STATE_KEY, {'history': [], 'failures': {}})

    def reset(self) -> None:
        """New user input: the model has fresh direction, so earlier repeats no longer count."""
        self.data['history'] = []
        self.data['failures'] = {}

    def observe(self, name: str, arguments: str, result: str, *, failed: bool, side_effects: bool) -> GuardDecision:
        history: list[str] = self.data['history']
        history.append(signature(name, arguments, result))
        del history[:-HISTORY_LIMIT]
        failures: dict[str, int] = self.data['failures']
        if failed:
            failures[name] = failures.get(name, 0) + 1
        else:
            failures.pop(name, None)
            if side_effects:
                failures.clear()  # a successful action changed something: earlier failures may now succeed

        repeats = max(self._streak(history), self._cycle_laps(history))
        if self.stop_at and repeats >= self.stop_at:
            return GuardDecision(stop='tool_loop_detected')
        failed_count = failures.get(name, 0)
        if failed and self.failure_stop_at and failed_count >= self.failure_stop_at:
            return GuardDecision(stop='tool_loop_detected')
        if self.warn_at and repeats in (self.warn_at, self.warn_at + 2):
            return GuardDecision(notice=(
                f'[提醒] 工具 {name} 已经以相同参数被调用 {repeats} 次并得到相同结果，继续重复不会有新进展。'
                '请换一种做法：调整参数、换用其他工具，或基于已有结果直接作答。'
                + (f'重复达到 {self.stop_at} 次时本次运行会被终止。' if self.stop_at else '')))
        if failed and self.warn_at and failed_count == self.warn_at:
            return GuardDecision(notice=(
                f'[提醒] 工具 {name} 已连续失败 {failed_count} 次。请先根据错误信息修正参数或改用其他方法，'
                '不要原样重试。' + (f'连续失败 {self.failure_stop_at} 次时本次运行会被终止。' if self.failure_stop_at else '')))
        return GuardDecision()

    @staticmethod
    def _streak(history: list[str]) -> int:
        count = 0
        for item in reversed(history):
            if item != history[-1]:
                break
            count += 1
        return count

    @staticmethod
    def _cycle_laps(history: list[str]) -> int:
        """Trailing laps of the smallest repeating cycle of period 2..MAX_PERIOD ending at the latest call."""
        best = 0
        for period in range(2, MAX_PERIOD + 1):
            if len(history) < period * 2:
                continue
            tail = history[-period:]
            if len(set(tail)) == 1:
                continue  # a constant run is the streak's job
            laps = 1
            while len(history) >= period * (laps + 1) and history[-period * (laps + 1):-period * laps] == tail:
                laps += 1
            if laps >= 2:
                best = max(best, laps)
                break
        return best
