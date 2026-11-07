"""Installing and exporting skill bundles (openspec 2026-11-07-skill-evolution, S3 3.3/3.6/3.10)."""
import io
import zipfile

import pytest
from sqlalchemy import select

from nexus_platform.errors import InvalidConfiguration, NotFound
from nexus_platform.persistence.models import SkillVersionRecord
from nexus_platform.skills.service import (
    export_bundle, install_bundle, publish, skill_files, skill_versions, version_bundle,
)
from nexus_skills import bundle
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_api import _client, teardown_function  # noqa: F401
from test_skills_platform import PRINCIPAL, _tenant

MD = '---\nname: packed\ndescription: From a zip\ntools: []\n---\nBody\n'


def _zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def test_an_uploaded_zip_becomes_a_version_with_text_and_binary_files(database):
    tenant, _ = _tenant(database)
    data = _zip([('packed/SKILL.md', MD), ('packed/refs/a.md', 'words'), ('packed/img/logo.png', b'\x89PNG\x00\x01')])
    with database() as db:
        result = install_bundle(db, PRINCIPAL, tenant.id, data)
    assert result['skill'] == 'packed' and result['binary_files'] == ['img/logo.png']
    with database() as db:
        version = db.scalar(select(SkillVersionRecord))
        assert version.trust == 'import' and version.build_state == 'ready'
        assert version.bundle_sha256 == bundle.digest(version.bundle)
        assert bundle.unpack(version.bundle).binary == {'img/logo.png': b'\x89PNG\x00\x01'}
        row = skill_versions(db, PRINCIPAL, tenant.id, 'packed')[0]
        assert row['has_bundle'] and row['build_state'] == 'ready'


def test_a_hostile_or_broken_zip_is_refused_with_a_stable_code(database):
    tenant, _ = _tenant(database)
    with database() as db, pytest.raises(InvalidConfiguration, match='bundle_invalid'):
        install_bundle(db, PRINCIPAL, tenant.id, b'nope')
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_path_invalid'):
        install_bundle(db, PRINCIPAL, tenant.id, _zip([('SKILL.md', MD), ('../x.md', 'x')]))
    with database() as db:
        assert db.scalar(select(SkillVersionRecord)) is None


def test_a_syntax_error_in_a_script_stops_the_install(database):
    tenant, _ = _tenant(database)
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_verify_failed:scripts/a.py'):
        install_bundle(db, PRINCIPAL, tenant.id, _zip([('SKILL.md', MD), ('scripts/a.py', 'def f(:\n')]))
    with database() as db:
        assert db.scalar(select(SkillVersionRecord)) is None


def test_a_binary_file_cannot_share_a_text_path_and_the_hash_covers_it(database):
    tenant, _ = _tenant(database)
    base = [('SKILL.md', MD), ('refs/a.md', 'words')]
    with database() as db:
        first = install_bundle(db, PRINCIPAL, tenant.id, _zip(base))
    with database() as db:
        second = install_bundle(db, PRINCIPAL, tenant.id, _zip(base + [('img/a.bin', b'\x00\x01')]))
    assert first['content_hash'] != second['content_hash']


def test_export_returns_the_stored_zip_and_rebuilds_for_older_versions(database):
    tenant, _ = _tenant(database)
    with database() as db:
        publish(db, PRINCIPAL, tenant.id, MD, {'refs/a.md': 'words'})
    with database() as db:
        name, number, data = export_bundle(db, PRINCIPAL, tenant.id, 'packed')
        assert (name, number) == ('packed', 1) and bundle.unpack(data).text == {'refs/a.md': 'words'}
    with database() as db:  # a version from before bundles existed has no stored zip
        row = db.scalar(select(SkillVersionRecord))
        row.bundle = row.bundle_sha256 = None
        db.commit()
    with database() as db:
        rebuilt = version_bundle(db, db.scalar(select(SkillVersionRecord)))
        assert bundle.unpack(rebuilt).skill_md == MD
        with pytest.raises(NotFound):
            export_bundle(db, PRINCIPAL, tenant.id, 'missing')


def test_upload_and_download_over_http(database):
    tenant, _ = _tenant(database)
    http = _client(database, PRINCIPAL)
    sent = http.post(f'/api/v1/tenants/{tenant.id}/skills/upload', content=_zip([('SKILL.md', MD)]),
                     headers={'content-type': 'application/zip'})
    assert sent.status_code == 201 and sent.json()['skill'] == 'packed'
    got = http.get(f'/api/v1/tenants/{tenant.id}/skills/packed/bundle')
    assert got.status_code == 200 and got.headers['content-type'] == 'application/zip'
    assert 'packed-v1.zip' in got.headers['content-disposition']
    assert bundle.unpack(got.content).skill_md == MD
    assert http.get(f'/api/v1/tenants/{tenant.id}/skills/packed/bundle?version=9').status_code == 404
    bad = http.post(f'/api/v1/tenants/{tenant.id}/skills/upload', content=b'junk')
    assert bad.status_code == 422 and 'bundle_invalid' in bad.json()['error']['message']


def test_an_oversized_upload_is_refused_by_its_declared_length(database, monkeypatch):
    tenant, _ = _tenant(database)
    monkeypatch.setattr(bundle, 'MAX_UPLOAD_BYTES', 10)
    http = _client(database, PRINCIPAL)
    response = http.post(f'/api/v1/tenants/{tenant.id}/skills/upload', content=b'x' * 50)
    assert response.status_code == 422 and 'bundle_too_large' in response.json()['error']['message']
