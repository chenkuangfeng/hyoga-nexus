"""vision_analyze (openspec 2026-11-07-tool-expansion, section 8.3)."""
import asyncio
from uuid import uuid4

import pytest

from nexus_core.native import NativePolicy
from nexus_core.runtime import RuntimeFault
from nexus_core.sandbox import SandboxError
from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.settings import SandboxSettings
from nexus_tools.builtins import builtins
from nexus_tools.builtins.media import PREFIX, media_tools
from nexus_tools.builtins.services import RunServices
from nexus_worker.vision import VisionAnalyzer


def run(coro):
    return asyncio.run(coro)


class Client:
    def __init__(self, answer='A red square.'):
        self.answer, self.calls, self.closed = answer, [], False

    async def describe(self, image, mime, system, prompt, max_tokens=1500):
        self.calls.append((image, mime, prompt))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    async def close(self):
        self.closed = True


@pytest.fixture
def session(tmp_path):
    settings = SandboxSettings(enabled=True, backend='local', workspace_root=str(tmp_path / 'sbx'), allow_local=True)
    session = SandboxManager(settings).session('t1', 's1')
    host = tmp_path / 'sbx' / 't1' / 's1' / 'workspace'
    (host / 'pic.png').write_bytes(b'\x89PNG fake')
    (host / 'notes.txt').write_text('hi')
    return session


def call(session, analyzer, **arguments):
    tool = next(media_tools())
    context = type('C', (), {'services': RunServices(object(), {}, session, vision=analyzer)})()
    return run(tool.handler(arguments, context))


def test_the_image_and_question_reach_the_vision_model_and_the_answer_is_marked_external(session):
    client = Client()
    analyzer = VisionAnalyzer(None, uuid4(), uuid4(), str(uuid4()), client_factory=lambda *a: client)
    result = call(session, analyzer, path='/workspace/pic.png', question='What colour?')
    assert result.data == PREFIX + 'A red square.' and result.error_code is None
    assert client.calls == [(b'\x89PNG fake', 'image/png', 'What colour?')] and client.closed


def test_missing_model_unreadable_files_and_model_failures_are_stable_codes(session):
    assert call(session, None, path='/workspace/pic.png').error_code == 'vision_model_missing'
    analyzer = VisionAnalyzer(None, uuid4(), uuid4(), str(uuid4()), client_factory=lambda *a: Client())
    assert call(session, analyzer, path='/workspace/notes.txt').error_code == 'sandbox_not_an_image'
    assert call(session, analyzer, path='/workspace/missing.png').error_code == 'sandbox_not_found'
    assert call(session, analyzer, path='/etc/passwd').error_code == 'sandbox_path_invalid'
    broken = VisionAnalyzer(None, uuid4(), uuid4(), str(uuid4()), client_factory=lambda *a: Client(RuntimeError('x')))
    assert call(session, broken, path='/workspace/pic.png').error_code == 'vision_failed'
    gone = VisionAnalyzer(None, uuid4(), uuid4(), str(uuid4()),
                          client_factory=lambda *a: (_ for _ in ()).throw(LookupError('revoked')))
    assert call(session, gone, path='/workspace/pic.png').error_code == 'vision_failed'


def test_without_a_sandbox_session_the_tool_reports_the_sandbox_is_missing():
    analyzer = VisionAnalyzer(None, uuid4(), uuid4(), str(uuid4()), client_factory=lambda *a: Client())
    assert call(None, analyzer, path='/workspace/pic.png').error_code == 'sandbox_unavailable'


def test_definition_group_and_policy_validation():
    definition = builtins().get('vision_analyze', 'v1').definition
    assert (definition.group, definition.risk) == ('media', 'probe')
    assert NativePolicy().vision_model_profile_version_id == ''
    NativePolicy(vision_model_profile_version_id=str(uuid4()))
    with pytest.raises(ValueError):
        NativePolicy(vision_model_profile_version_id='not-a-uuid')
