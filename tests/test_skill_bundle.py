"""Skill bundles: hostile archives are refused before anything is read, good ones round-trip (S3 3.3)."""
import io
import stat
import zipfile

import pytest

from nexus_skills import bundle
from nexus_skills.bundle import BundleError

MD = '---\nname: demo\ndescription: d\n---\nBody\n'


def _zip(entries, *, symlink=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
        for name, target in symlink:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)
    return buffer.getvalue()


def test_root_layout_and_wrapped_layout_read_the_same():
    plain = bundle.unpack(_zip([('SKILL.md', MD), ('scripts/a.py', 'print(1)')]))
    wrapped = bundle.unpack(_zip([('demo/SKILL.md', MD), ('demo/scripts/a.py', 'print(1)')]))
    assert plain.skill_md == wrapped.skill_md == MD
    assert plain.text == wrapped.text == {'scripts/a.py': 'print(1)'}


def test_binary_files_are_kept_apart_and_metadata_is_dropped():
    result = bundle.unpack(_zip([('SKILL.md', MD), ('img/a.png', b'\x89PNG\x00\xff'), ('.DS_Store', 'x'),
                                 ('__MACOSX/._a', 'x'), ('.hidden/x', 'x')]))
    assert result.binary == {'img/a.png': b'\x89PNG\x00\xff'} and result.text == {}
    assert len(result.ignored) == 3


@pytest.mark.parametrize('name', ['../evil.py', 'a/../../evil.py', '/abs.py', 'a\\b.py'])
def test_path_traversal_is_refused(name):
    with pytest.raises(BundleError):
        bundle.unpack(_zip([('SKILL.md', MD), (name, 'x')]))


def test_symbolic_links_are_refused():
    with pytest.raises(BundleError, match='bundle_symlink'):
        bundle.unpack(_zip([('SKILL.md', MD)], symlink=[('link', '/etc/passwd')]))


def test_duplicate_paths_are_refused():
    with pytest.raises(BundleError, match='skill_path_duplicate'):
        bundle.unpack(_zip([('SKILL.md', MD), ('a.md', '1'), ('./a.md', '2')]))


def test_a_decompression_bomb_is_refused_by_ratio():
    with pytest.raises(BundleError, match='bundle_ratio_suspicious'):
        bundle.unpack(_zip([('SKILL.md', MD), ('big.bin', b'\x00' * (8 * 1024 * 1024))]))


def test_too_many_entries_and_oversize_uploads_are_refused():
    with pytest.raises(BundleError, match='bundle_too_many_entries'):
        bundle.unpack(_zip([('SKILL.md', MD)] + [(f'f{i}.md', 'x') for i in range(bundle.MAX_ENTRIES)]))
    with pytest.raises(BundleError, match='bundle_too_large'):
        bundle.unpack(b'0' * 100, max_upload=10)


def test_not_a_zip_and_missing_skill_md_are_refused():
    with pytest.raises(BundleError, match='bundle_invalid'):
        bundle.unpack(b'not a zip')
    with pytest.raises(BundleError, match='bundle_skill_md_missing'):
        bundle.unpack(_zip([('README.md', 'x')]))


def test_two_top_level_folders_do_not_get_stripped():
    with pytest.raises(BundleError, match='bundle_skill_md_missing'):
        bundle.unpack(_zip([('a/SKILL.md', MD), ('b/x.md', 'x')]))


def test_pack_is_canonical_and_round_trips():
    first = bundle.pack(MD, {'b.md': 'b', 'a.md': 'a'}, {'x.bin': b'\x00\x01'})
    second = bundle.pack(MD, {'a.md': 'a', 'b.md': 'b'}, {'x.bin': b'\x00\x01'})
    assert first == second and bundle.digest(first) == bundle.digest(second)
    again = bundle.unpack(first)
    assert (again.skill_md, again.text, again.binary) == (MD, {'a.md': 'a', 'b.md': 'b'}, {'x.bin': b'\x00\x01'})
