"""GA no_tool and WeKnora completion guards, translated without executing model text.

Derived from GenericAgent ga.py do_no_tool/_retry_or_exit (a9a36b4, MIT) and
WeKnora observe.go/length_truncation tests (e1f9a6166, MIT).
"""
from dataclasses import dataclass
from enum import StrEnum
import re

from nexus_core.native import NativePolicy


@dataclass(frozen=True)
class CompletionVerdict:
    """One decision: answer, retry with a visible nudge, or explicit failure."""
    action: str
    prompt: str = ''
    error_code: str | None = None
    truncated: bool = False


def no_tool_prompt(content: str, clarify_code: bool = True) -> str:
    """Translate every GA no_tool rejection branch; plain explanatory code may finish."""
    if not content.strip():
        return '[ERROR] Blank response, regenerate an answer or use an authorized tool.'
    if ('[!!! 流异常中断' in content[-100:] or '!!!Error:' in content[50:][-100:]
            or (content.endswith('</summary>') and len(content) < 100)):
        return '[ERROR] Incomplete response. Regenerate without repeating completed operations.'
    tail = content.rstrip()[-50:]
    if ('DSML' in tail and '｜' in tail and tail.endswith('>')) or '<tool_use>' in content:
        return '[ERROR] Tool call format invalid; use the configured tool-call protocol.'
    if 'max_tokens !!!]' in content[-100:]:
        return '[ERROR] Output limit reached. Use smaller steps without repeating completed operations.'
    blocks = list(re.finditer(r'```[a-zA-Z0-9_]*\n[\s\S]{50,}?```', content))
    if clarify_code and len(blocks) == 1 and not content[blocks[0].end():].strip():
        residual = content[:blocks[0].start()]
        residual = re.sub(r'<(?:thinking|summary)>[\s\S]*?</(?:thinking|summary)>', '', residual, flags=re.I)
        if len(re.sub(r'\s+', '', residual)) <= 30:
            return ('The last reply only contained a large code block. If action is still required, '
                    'call an available authorized tool. If the request is only to explain/show code, '
                    'add a natural-language explanation and state that no execution is needed.')
    return ''


class CompletionPolicy:
    """Run-local, serializable empty/repetition guards; never convert exhaustion to success."""
    def __init__(self, policy: NativePolicy, state: dict[str, object]):
        self.policy, self.state = policy, state

    def evaluate(self, text: str, finish_reason: str) -> CompletionVerdict:
        """Distinguish length, content filtering, invalid/empty output and natural final answers."""
        if finish_reason == 'content_filter':
            return CompletionVerdict('fail', error_code='model_content_filtered')
        clean = re.sub(r'<think(?:ing)?>[\s\S]*?(?:</think(?:ing)?>|$)', '', text, flags=re.I).strip()
        if finish_reason in ('length', 'max_tokens') and clean:
            return CompletionVerdict('answer', truncated=True)
        prompt = no_tool_prompt(clean, self.policy.clarify_code)
        if prompt:
            failures = int(self.state.get('empty_failures', 0)) + 1
            self.state['empty_failures'] = failures
            if failures > self.policy.empty_retries:
                return CompletionVerdict('fail', error_code='model_response_unusable')
            return CompletionVerdict('retry', prompt)
        previous = str(self.state.get('previous_content', ''))
        repeats = int(self.state.get('repeats', 0)) + 1 if clean == previous else 1
        self.state.update(previous_content=clean, repeats=repeats, empty_failures=0)
        if repeats >= self.policy.repeated_limit:
            return CompletionVerdict('fail', error_code='model_stuck')
        return CompletionVerdict('answer')


class JudgeDecision(StrEnum):
    """Closed set of per-response decisions. The engine dispatches on these and nothing else.

    `ACCEPT_TRUNCATED` is a final answer that hit the output limit; the engine accepts it and records
    `answer.truncated` (continuation is not implemented, so this is not a retry).
    """
    EXECUTE_TOOLS = 'execute_tools'
    ACCEPT = 'accept'
    ACCEPT_TRUNCATED = 'accept_truncated'
    RETRY_EMPTY = 'retry_empty'
    INCOMPLETE_TOOL_CALL = 'incomplete_tool_call'
    STALLED = 'stalled'
    FAIL = 'fail'


@dataclass(frozen=True)
class Judgement:
    """A decision plus the data the engine needs to act on it (a visible prompt or a stable error code)."""
    decision: JudgeDecision
    prompt: str = ''
    error_code: str | None = None


class CompletionJudge:
    """Classify one model response into a JudgeDecision. Pure with respect to the store.

    Mutates only the Run-local `state` counters (truncated calls, empty failures, repeats), which the
    engine persists with its normal progress writes. Decisions are unchanged from the earlier inline
    branches; this class names them.
    """
    TRUNCATED_FINISH = ('length', 'max_tokens')

    def __init__(self, policy: NativePolicy, state: dict[str, object]):
        self.policy, self.state = policy, state
        self.text_guards = CompletionPolicy(policy, state)

    def judge(self, text: str, finish_reason: str, calls) -> Judgement:
        """Decide what the engine does next for this response. `calls` are the model-issued tool calls."""
        if calls and finish_reason in self.TRUNCATED_FINISH:
            # Arguments were cut off, so nothing may run; the engine reports this and asks for smaller calls.
            count = int(self.state.get('truncated_calls', 0)) + 1
            self.state['truncated_calls'] = count
            error = 'model_stuck' if count >= self.policy.repeated_limit else None
            return Judgement(JudgeDecision.INCOMPLETE_TOOL_CALL, error_code=error)
        if calls:
            return Judgement(JudgeDecision.EXECUTE_TOOLS)
        verdict = self.text_guards.evaluate(text, finish_reason)
        if verdict.action == 'fail':
            stuck = verdict.error_code == 'model_stuck'
            return Judgement(JudgeDecision.STALLED if stuck else JudgeDecision.FAIL, error_code=verdict.error_code)
        if verdict.action == 'retry':
            return Judgement(JudgeDecision.RETRY_EMPTY, prompt=verdict.prompt)
        return Judgement(JudgeDecision.ACCEPT_TRUNCATED if verdict.truncated else JudgeDecision.ACCEPT)
