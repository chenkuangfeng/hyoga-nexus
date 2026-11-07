"""Remote skill sources: parsing, repository cut-outs, guarded download and install (S3 3.9)."""
import io
import zipfile

import httpx
import pytest
from sqlalchemy import select

from nexus_core import egress
from nexus_core.platform import Principal
from nexus_platform.errors import InvalidConfiguration, PlatformError
from nexus_platform.persistence.models import SkillVersionRecord
from nexus_platform.skills import remote
from nexus_skills import bundle
from nexus_skills.source import SourceError, parse_source
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _tenant

MD = '---\nname: remote-skill\ndescription: From far away\ntools: []\n---\nBody\n'


def _zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


# ---- parsing ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize('text,kind,subdir,find,ref', [
    ('https://github.com/o/r', 'github', '', '', ''),
    ('https://github.com/o/r/tree/main/skills/x', 'github', 'skills/x', '', 'main'),
    ('github:o/r/skills/x@v1', 'github', 'skills/x', '', 'v1'),
    ('https://gitlab.com/g/p/-/tree/dev/a/b', 'gitlab', 'a/b', '', 'dev'),
    ('https://skills.sh/o/r/pdf', 'skills.sh', '', 'pdf', ''),
    ('clawhub:my-skill@1.2.0', 'registry', '', '', '1.2.0'),
    ('https://example.com/pack.zip', 'direct', '', '', ''),
])
def test_sources_are_normalized(text, kind, subdir, find, ref):
    source = parse_source(text)
    assert (source.kind, source.subdir, source.find_name, source.ref) == (kind, subdir, find, ref)
    assert source.url.startswith('https://')


@pytest.mark.parametrize('text', ['', 'ftp://x/y.zip', 'http://example.com/a.zip', 'https://user:pw@example.com/a',
                                  'github:only', 'github:o/r/../x', 'clawhub:Bad Slug', 'https://github.com/o',
                                  'https://skills.sh/o/r', 'a b', 'https://github.com/o/r/blob/main/x', 'x' * 600])
def test_malformed_sources_give_one_stable_code(text):
    with pytest.raises(SourceError) as stopped:
        parse_source(text)
    assert str(stopped.value) == 'skill_source_invalid'


# ---- repository cut-outs ----------------------------------------------------------------------------------

REPO = _zip([('o-r-abc123/README.md', 'repo'), ('o-r-abc123/skills/one/SKILL.md', MD),
             ('o-r-abc123/skills/one/scripts/a.py', 'print(1)'), ('o-r-abc123/skills/two/SKILL.md', MD),
             ('o-r-abc123/other/two/SKILL.md', MD)])


def test_a_folder_is_cut_out_of_a_repository_archive():
    cut = bundle.unpack(bundle.subtree(REPO, subdir='skills/one'))
    assert cut.skill_md == MD and cut.text == {'scripts/a.py': 'print(1)'}


def test_a_skill_is_found_by_name_and_ambiguity_is_an_error():
    assert bundle.unpack(bundle.subtree(REPO, find_name='one')).text == {'scripts/a.py': 'print(1)'}
    with pytest.raises(bundle.BundleError, match='bundle_skill_ambiguous'):
        bundle.subtree(REPO, find_name='two')
    with pytest.raises(bundle.BundleError, match='bundle_skill_not_found'):
        bundle.subtree(REPO, find_name='nope')
    with pytest.raises(bundle.BundleError, match='bundle_skill_not_found'):
        bundle.subtree(REPO, subdir='skills/zzz')


def test_entry_limits_apply_to_the_folder_not_the_whole_repository():
    big = _zip([('w/skills/x/SKILL.md', MD)] + [(f'w/other/f{i}.md', 'x') for i in range(bundle.MAX_ENTRIES + 5)])
    assert bundle.unpack(bundle.subtree(big, subdir='skills/x')).skill_md == MD  # the repository is larger than a skill may be
    with pytest.raises(bundle.BundleError, match='bundle_too_many_entries'):
        bundle.subtree(big)  # but taking the whole repository as one skill is not


def test_links_inside_a_repository_folder_are_refused():
    import stat
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('w/SKILL.md', MD)
        info = zipfile.ZipInfo('w/link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, '/etc/passwd')
    with pytest.raises(bundle.BundleError, match='bundle_symlink'):
        bundle.subtree(buffer.getvalue())


# ---- guarded download -------------------------------------------------------------------------------------

async def _public(host, port):
    return ['93.184.216.34']


def _download(handler, url='https://example.com/a.zip', **kwargs):
    import asyncio
    return asyncio.run(egress.download(url, max_bytes=1000, timeout=5, resolver=_public,
                                       transport=httpx.MockTransport(handler), **kwargs))


def test_private_and_metadata_addresses_are_refused():
    import asyncio

    async def private(host, port):
        return ['10.0.0.5']

    async def metadata(host, port):
        return ['93.184.216.34', '169.254.169.254']
    for resolver in (private, metadata):
        with pytest.raises(egress.EgressError, match='egress_destination_denied'):
            asyncio.run(egress.download('https://example.com/a.zip', max_bytes=10, timeout=5, resolver=resolver,
                                        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x'))))
    with pytest.raises(egress.EgressError, match='egress_destination_denied'):
        _download(lambda r: httpx.Response(200), url='https://127.0.0.1/a.zip')


def test_a_redirect_to_an_internal_address_is_refused():
    def handler(request):
        if request.url.host == '93.184.216.34':
            return httpx.Response(302, headers={'location': 'https://169.254.169.254/latest/meta-data'})
        return httpx.Response(200, content=b'secret')
    with pytest.raises(egress.EgressError, match='egress_destination_denied'):
        _download(handler)


def test_redirects_are_limited_and_an_oversized_body_is_stopped():
    with pytest.raises(egress.EgressError, match='egress_too_many_redirects'):
        _download(lambda r: httpx.Response(302, headers={'location': 'https://example.com/b'}))
    with pytest.raises(egress.EgressError, match='egress_too_large'):
        _download(lambda r: httpx.Response(200, content=b'x' * 5000), on_oversize='error')
    assert _download(lambda r: httpx.Response(200, content=b'x' * 5000)).truncated


def test_remote_fetch_translates_egress_failures(monkeypatch):
    monkeypatch.setattr(egress, 'default_resolver', _public)
    source = parse_source('https://example.com/a.zip')
    with pytest.raises(InvalidConfiguration, match='skill_source_http_error'):
        remote._fetch(source, transport=httpx.MockTransport(lambda r: httpx.Response(404)), resolver=_public)
    with pytest.raises(InvalidConfiguration, match='skill_source_denied'):
        remote._fetch(parse_source('https://example.com/a.zip'),
                      transport=httpx.MockTransport(lambda r: httpx.Response(200)),
                      resolver=lambda h, p: _private())


async def _private():
    return ['192.168.1.1']


# ---- install and update check -----------------------------------------------------------------------------

def test_install_needs_confirmation_and_an_administrator_before_any_fetch(database):
    tenant, _ = _tenant(database)
    calls = []

    def fetch(source):
        calls.append(source)
        return _zip([('SKILL.md', MD)])
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_source_confirmation_required'):
        remote.install_remote(db, PRINCIPAL, tenant.id, 'https://example.com/a.zip', confirm=False, fetch=fetch)
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_source_invalid'):
        remote.install_remote(db, PRINCIPAL, tenant.id, 'nonsense', confirm=True, fetch=fetch)
    with database() as db, pytest.raises(PlatformError):
        remote.install_remote(db, Principal(id='stranger', issuer='test'), tenant.id, 'https://example.com/a.zip',
                              confirm=True, fetch=fetch)
    assert calls == []


def test_install_records_the_origin_and_update_check_compares_content(database):
    tenant, _ = _tenant(database)
    archive = {'data': _zip([('o-r-1/skills/x/SKILL.md', MD), ('o-r-1/skills/x/refs/a.md', 'one')])}
    with database() as db:
        result = remote.install_remote(db, PRINCIPAL, tenant.id, 'github:o/r/skills/x@main', confirm=True,
                                       fetch=lambda source: archive['data'])
    assert result['skill'] == 'remote-skill'
    with database() as db:
        version = db.scalar(select(SkillVersionRecord))
        assert version.trust == 'import'
        assert version.extra['origin']['label'] == 'github:o/r/skills/x@main'
        assert len(version.extra['origin']['archive_sha256']) == 64
    with database() as db:
        same = remote.check_update(db, PRINCIPAL, tenant.id, 'remote-skill', fetch=lambda s: archive['data'])
    assert same['update_available'] is False
    archive['data'] = _zip([('o-r-2/skills/x/SKILL.md', MD), ('o-r-2/skills/x/refs/a.md', 'two')])
    with database() as db:
        changed = remote.check_update(db, PRINCIPAL, tenant.id, 'remote-skill', fetch=lambda s: archive['data'])
    assert changed['update_available'] is True
    with database() as db:  # nothing was applied
        assert len(db.scalars(select(SkillVersionRecord)).all()) == 1


def test_a_skill_without_an_origin_has_nothing_to_check(database):
    tenant, _ = _tenant(database)
    from nexus_platform.skills.service import publish
    with database() as db:
        publish(db, PRINCIPAL, tenant.id, MD, {})
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_has_no_remote_source'):
        remote.check_update(db, PRINCIPAL, tenant.id, 'remote-skill', fetch=lambda s: b'')


def test_install_remote_over_http(database, monkeypatch):
    tenant, _ = _tenant(database)
    from test_skills_api import _client
    monkeypatch.setattr(remote, '_fetch', lambda source, **kw: _zip([('SKILL.md', MD)]))
    http = _client(database, PRINCIPAL)
    base = f'/api/v1/tenants/{tenant.id}/skills'
    assert http.post(base + '/install-remote', json={'source': 'https://example.com/a.zip'}).status_code == 422
    done = http.post(base + '/install-remote', json={'source': 'https://example.com/a.zip', 'confirm': True})
    assert done.status_code == 201 and done.json()['skill'] == 'remote-skill'
    versions = http.get(base + '/remote-skill/versions').json()
    assert versions[0]['origin']['kind'] == 'direct'
