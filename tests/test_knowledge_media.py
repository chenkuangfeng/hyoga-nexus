"""Images, scanned PDFs and audio through fake vision / speech clients (openspec 2026-11-06-knowledge-base K4.2).

The real providers are not exercised here: these tests check the pipeline logic around the model clients.
"""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_platform.knowledge import media, service

from test_knowledge_domain import _pdf
from test_knowledge_service import OWNER, drain, env, find, upload  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)


class FakeVision:
    calls = []

    async def describe(self, image, mime, system, prompt, max_tokens=1500):
        FakeVision.calls.append((mime, prompt))
        return json.dumps({'description': '一张展示季度销售额的柱状图', 'text': '第一季度 120 万'}, ensure_ascii=False)

    async def close(self):
        pass


class FakeSpeech:
    async def transcribe(self, audio, filename, language=None):
        return f'会议录音转写：下周发布新版本（{language or "auto"}）'

    async def close(self):
        pass


@pytest.fixture
def media_env(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_model_of_type', lambda *args: None)
    FakeVision.calls.clear()
    media.set_media_factory(vision=lambda *a: FakeVision(), speech=lambda *a: FakeSpeech())
    settings = {'vlm_config': {'enabled': True, 'model_id': str(uuid4()), 'description_language': '中文'},
                'asr_config': {'enabled': True, 'model_id': str(uuid4()), 'language': 'zh'}}
    with factory() as db, db.begin():
        kb_id = service.create_base(db, tenant_id, owner, visibility='tenant', name='多媒体', settings=settings,
                                    indexing={'vector': False, 'keyword': True}).id
    yield factory, tenant_id, owner, member, kb_id
    media.set_media_factory()


def test_images_and_audio_become_searchable_text(media_env):
    factory, tenant_id, owner, member, kb_id = media_env
    upload(factory, tenant_id, owner, kb_id, '销售.png', b'\x89PNG fake image bytes')
    upload(factory, tenant_id, owner, kb_id, '会议.mp3', b'ID3 fake audio bytes')
    drain(factory)
    image_hit = find(factory, tenant_id, member, '柱状图').hits[0]
    assert image_hit.filename == '销售.png' and '第一季度 120 万' in image_hit.content
    assert FakeVision.calls[0][0] == 'image/png' and '中文' in FakeVision.calls[0][1]
    assert find(factory, tenant_id, member, '发布新版本').hits[0].content.endswith('（zh）')


def test_media_uploads_need_their_models(env):
    factory, tenant_id, _, owner, member, _ = env
    with factory() as db, db.begin():
        kb_id = service.create_base(db, tenant_id, owner, visibility='tenant', name='纯文本', indexing={'vector': False, 'keyword': True}).id
    with factory() as db:
        with pytest.raises(ValueError, match='VLM'):
            service.prepare_upload(db, tenant_id, owner, kb_id, 'a.png', b'x', 100)
        with pytest.raises(ValueError, match='ASR'):
            service.prepare_upload(db, tenant_id, owner, kb_id, 'a.mp3', b'x', 100)
        with pytest.raises(ValueError, match='unsupported'):
            service.prepare_upload(db, tenant_id, owner, kb_id, 'a.exe', b'x', 100)


def test_model_settings_are_validated(env, monkeypatch):
    factory, tenant_id, _, owner, member, _ = env
    monkeypatch.setattr(service, '_authorize_model_of_type', lambda *args: None)
    with factory() as db, db.begin():
        with pytest.raises(ValueError, match='vision model'):
            service.create_base(db, tenant_id, owner, visibility='tenant', name='x', indexing={'vector': False, 'keyword': True},
                                settings={'vlm_config': {'enabled': True}})
        with pytest.raises(ValueError, match='speech model'):
            service.create_base(db, tenant_id, owner, visibility='tenant', name='y', indexing={'vector': False, 'keyword': True},
                                settings={'asr_config': {'enabled': True}})


def test_scanned_pdf_falls_back_to_page_images(media_env, monkeypatch):
    factory, tenant_id, owner, member, kb_id = media_env
    monkeypatch.setattr(media, 'pdf_page_images', lambda data, limit=media.MAX_PDF_PAGES: [(1, b'img', 'image/jpeg'),
                                                                                           (2, b'img', 'image/jpeg')])
    upload(factory, tenant_id, owner, kb_id, '扫描件.pdf', _pdf(['']))  # no text layer
    drain(factory)
    hit = find(factory, tenant_id, member, '季度销售额').hits[0]
    assert hit.filename == '扫描件.pdf' and hit.page in (1, 2)


def test_scanned_pdf_without_a_vision_model_fails_with_a_reason(env):
    from sqlalchemy import select
    from nexus_platform.persistence.models import KnowledgeDocumentVersionRecord
    factory, tenant_id, _, owner, member, _ = env
    with factory() as db, db.begin():
        kb_id = service.create_base(db, tenant_id, owner, visibility='tenant', name='无视觉', indexing={'vector': False, 'keyword': True}).id
    upload(factory, tenant_id, owner, kb_id, '扫描件.pdf', _pdf(['']))
    drain(factory)
    with factory() as db:
        version = db.scalar(select(KnowledgeDocumentVersionRecord))
        assert (version.state, version.error_code) == ('failed', 'empty_text')


def test_gallery_lists_image_documents_with_captions(media_env):
    factory, tenant_id, owner, member, kb_id = media_env
    upload(factory, tenant_id, owner, kb_id, '销售.png', b'\x89PNG fake')
    upload(factory, tenant_id, owner, kb_id, '说明.md', '# 说明\n普通文档'.encode())
    drain(factory)

    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: OWNER
    try:
        with TestClient(app) as client:
            path = f'/api/v1/tenants/{tenant_id}/knowledge/bases/{kb_id}/images'
            listing = client.get(path).json()
            assert listing['total'] == 1 and listing['items'][0]['source_name'] == '销售.png'
            assert '柱状图' in listing['items'][0]['caption']
            assert listing['items'][0]['url'].endswith('/download')
            assert client.get(path, params={'keyword': '不存在'}).json()['total'] == 0
            caps = {(i['group'], i['key']): i for i in client.get(f'/api/v1/tenants/{tenant_id}/knowledge/capabilities').json()['items']}
            assert (caps[('kb_feature', 'vlm')]['status'], caps[('kb_feature', 'vlm')]['verified']) == ('available', False)
    finally:
        app.dependency_overrides.clear()
