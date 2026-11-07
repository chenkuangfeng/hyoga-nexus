"""Web tools (openspec 2026-11-07-tool-expansion, section 6): SSRF protection, extraction, search backends."""
import asyncio

import httpx
import pytest

from nexus_core.deployment import DeploymentConfigError
from nexus_tools.builtins import web as web_module
from nexus_tools.web import fetch as fetching, search as searching
from nexus_tools.web.settings import WebSettings, load_settings


def run(coro):
    return asyncio.run(coro)


HOSTS = {'example.com': ['93.184.216.34'], 'internal.corp': ['10.0.0.5'], 'mixed.test': ['93.184.216.34', '192.168.1.9'],
         'meta.test': ['169.254.169.254'], 'v6.test': ['2606:2800:220:1:248:1893:25c8:1946'], 'mapped.test': ['::ffff:127.0.0.1']}


async def resolver(host, port):
    if host not in HOSTS:
        raise fetching.WebError('web_unreachable', 'the host name could not be resolved')
    return HOSTS[host]


# ------------------------------------------------------------------ URL and address checks

@pytest.mark.parametrize('url', ['ftp://example.com/x', 'file:///etc/passwd', 'javascript:alert(1)', 'http://user:pw@example.com/',
                                 'http:///nohost', 'https://example.com:22/', 'http://example.com:6379/', 'https://exa mple.com/',
                                 'https://example.com/' + 'a' * 2100, 'http://example.com:99999/'])
def test_unacceptable_urls_are_refused_before_any_lookup(url):
    with pytest.raises(fetching.WebError):
        fetching.check_url(url)


def test_acceptable_urls():
    assert fetching.check_url('https://example.com/a?b=1') == ('https', 'example.com', 443)
    assert fetching.check_url('http://example.com:8080/') == ('http', 'example.com', 8080)


@pytest.mark.parametrize('host', ['internal.corp', 'mixed.test', 'meta.test', 'mapped.test', '127.0.0.1', '10.1.2.3', '169.254.169.254',
                                  '::1', '0.0.0.0', '192.168.0.1', '100.64.0.1', 'fe80::1'])
def test_non_public_destinations_are_refused(host):
    with pytest.raises(fetching.WebError) as error:
        run(fetching.validate_destination(host, 443, resolver))
    assert error.value.code == 'web_destination_denied'


def test_public_destinations_pass():
    assert run(fetching.validate_destination('example.com', 443, resolver)) == '93.184.216.34'
    assert run(fetching.validate_destination('v6.test', 443, resolver)).startswith('2606')
    assert run(fetching.validate_destination('8.8.8.8', 443, resolver)) == '8.8.8.8'


# ------------------------------------------------------------------ fetching

PAGE = (b'<html><head><title> Hello  World </title><style>p{x:y}</style><script>alert(1)</script></head>'
        b'<body><h1>Heading</h1><p>First   para</p><noscript>no</noscript><div>Second</div></body></html>')


def fetch(url, handler, **kwargs):
    return run(fetching.fetch(url, max_bytes=kwargs.pop('max_bytes', 1_000_000), timeout=5, resolver=resolver,
                              transport=httpx.MockTransport(handler), **kwargs))


def test_html_is_reduced_to_title_and_visible_text():
    page = fetch('https://example.com/p', lambda r: httpx.Response(200, content=PAGE, headers={'content-type': 'text/html; charset=utf-8'}))
    assert page.title == 'Hello World' and page.text == 'Heading\n\nFirst para\n\nSecond' and not page.truncated
    assert 'alert' not in page.text and 'p{x:y}' not in page.text


def test_the_request_is_pinned_to_the_validated_address():
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers['host'], request.extensions.get('sni_hostname')))
        return httpx.Response(200, text='ok', headers={'content-type': 'text/plain'})
    fetch('https://example.com/p', handler)
    assert seen == [('93.184.216.34', 'example.com', 'example.com')]


def test_a_redirect_to_an_internal_host_is_refused_and_nothing_is_sent_to_it():
    hits = []

    def handler(request):
        hits.append(request.headers['host'])
        return httpx.Response(302, headers={'location': 'http://internal.corp/admin'})
    with pytest.raises(fetching.WebError) as error:
        fetch('https://example.com/start', handler)
    assert error.value.code == 'web_destination_denied' and hits == ['example.com']


def test_redirect_to_a_metadata_literal_and_to_a_bad_scheme_are_refused():
    for location in ('http://169.254.169.254/latest/meta-data', 'file:///etc/passwd'):
        with pytest.raises(fetching.WebError):
            fetch('https://example.com/', lambda r, location=location: httpx.Response(301, headers={'location': location}))


def test_public_redirects_are_followed_and_loops_end():
    def handler(request):
        if request.headers['host'] == 'example.com' and request.url.path == '/a':
            return httpx.Response(302, headers={'location': '/b'})
        return httpx.Response(200, text='final', headers={'content-type': 'text/plain'})
    page = fetch('https://example.com/a', handler)
    assert page.text == 'final' and page.url == 'https://example.com/b'
    with pytest.raises(fetching.WebError) as error:
        fetch('https://example.com/a', lambda r: httpx.Response(302, headers={'location': '/a'}))
    assert error.value.code == 'web_too_many_redirects'


def test_size_limit_content_types_and_http_errors():
    big = fetch('https://example.com/', lambda r: httpx.Response(200, content=b'x' * 50_000, headers={'content-type': 'text/plain'}),
                max_bytes=10_000)
    assert big.truncated and len(big.text) == 10_000
    for kind in ('image/png', 'application/pdf', 'application/octet-stream'):
        with pytest.raises(fetching.WebError) as error:
            fetch('https://example.com/', lambda r, kind=kind: httpx.Response(200, content=b'\x89PNG', headers={'content-type': kind}))
        assert error.value.code == 'web_unsupported_content_type'
    with pytest.raises(fetching.WebError) as error:
        fetch('https://example.com/', lambda r: httpx.Response(404))
    assert error.value.code == 'web_http_error' and '404' in error.value.detail
    assert fetch('https://example.com/', lambda r: httpx.Response(200, json={'a': 1})).text == '{"a":1}'


def test_unresolvable_hosts_are_reported():
    with pytest.raises(fetching.WebError) as error:
        fetch('https://nowhere.invalid/', lambda r: httpx.Response(200))
    assert error.value.code == 'web_unreachable'


# ------------------------------------------------------------------ search backends

def settings(**kwargs):
    return WebSettings(enabled=True, **kwargs)


def test_each_backend_builds_its_request_and_maps_results():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url.copy_with(query=None)), dict(request.url.params), request.headers.get('authorization'),
                     request.headers.get('x-subscription-token')))
        if 'tavily' in request.url.host:
            return httpx.Response(200, json={'results': [{'title': 'T', 'url': 'https://t.example', 'content': 'tavily snippet'}]})
        if 'brave' in request.url.host:
            return httpx.Response(200, json={'web': {'results': [{'title': 'B', 'url': 'https://b.example', 'description': 'brave snippet'}]}})
        return httpx.Response(200, json={'results': [{'title': 'S', 'url': 'https://s.example', 'content': 'searx snippet'}, {'title': 'no url'}]})
    transport = httpx.MockTransport(handler)
    tavily = run(searching.search(settings(search_backend='tavily', search_api_key='k1'), 'q', 3, transport=transport))
    brave = run(searching.search(settings(search_backend='brave', search_api_key='k2'), 'q', 3, transport=transport))
    searx = run(searching.search(settings(search_backend='searxng', search_url='http://10.0.0.7:8080/'), 'q', 3, transport=transport))
    assert [h.url for h in tavily + brave + searx] == ['https://t.example', 'https://b.example', 'https://s.example']
    assert seen[0][3] == 'Bearer k1' and seen[1][4] == 'k2' and seen[1][2] == {'q': 'q', 'count': '3'}
    assert seen[2][1] == 'http://10.0.0.7:8080/search' and seen[2][2]['format'] == 'json'


def test_search_errors_are_stable_codes():
    def code(backend_settings, handler):
        with pytest.raises(fetching.WebError) as error:
            run(searching.search(backend_settings, 'q', 3, transport=httpx.MockTransport(handler)))
        return error.value.code
    brave = settings(search_backend='brave', search_api_key='k')
    assert code(settings(), lambda r: httpx.Response(200)) == 'web_search_backend_missing'
    assert code(brave, lambda r: httpx.Response(401)) == 'web_search_unauthorized'
    assert code(brave, lambda r: httpx.Response(500)) == 'web_search_failed'
    assert code(brave, lambda r: httpx.Response(200, text='<html>')) == 'web_search_failed'

    def boom(request):
        raise httpx.ConnectError('down')
    assert code(brave, boom) == 'web_search_failed'


# ------------------------------------------------------------------ tools

@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(web_module, '_settings', lambda: settings(search_backend='tavily', search_api_key='k'))

    def handler(request):
        if 'tavily' in request.url.host:
            return httpx.Response(200, json={'results': [{'title': 'T', 'url': 'https://t.example', 'content': 'snippet'}]})
        return httpx.Response(200, content=PAGE, headers={'content-type': 'text/html'})
    return {t.definition.name: t for t in web_module.web_tools(transport=httpx.MockTransport(handler), resolver=resolver)}


def call(tool, **arguments):
    return run(tool.handler(arguments, None))


def test_results_are_marked_as_external_data(tools):
    searched = call(tools['web_search'], query='anything')
    fetched = call(tools['web_fetch'], url='https://example.com/p')
    for result in (searched, fetched):
        assert result.data.startswith(web_module.PREFIX) and result.error_code is None
    assert 'https://t.example' in searched.data and 'Hello World' in fetched.data and 'Heading' in fetched.data


def test_tool_errors_become_failed_results(tools):
    denied = call(tools['web_fetch'], url='http://internal.corp/')
    assert denied.error_code == 'web_destination_denied' and 'not publicly routable' in denied.data
    assert call(tools['web_fetch'], url='ftp://example.com/x').error_code == 'web_url_invalid'


def test_fetch_output_is_capped_by_max_chars(tools):
    result = call(tools['web_fetch'], url='https://example.com/p', max_chars=1000)
    assert len(result.data) < len(web_module.PREFIX) + 1200


def test_definitions_are_probe_risk_and_in_the_web_group():
    registry = __import__('nexus_tools.builtins', fromlist=['builtins']).builtins()
    for name in ('web_search', 'web_fetch'):
        definition = registry.get(name, 'v1').definition
        assert (definition.group, definition.risk, definition.read_only) == ('web', 'probe', True)


# ------------------------------------------------------------------ settings

def _config(tmp_path, body):
    path = tmp_path / 'nexus.toml'
    path.write_text(body, encoding='utf-8')
    return path


def test_settings_defaults_and_valid_values(tmp_path):
    assert load_settings(_config(tmp_path, '')).enabled is False
    loaded = load_settings(_config(tmp_path, '[web]\nenabled = true\nsearch_backend = "searxng"\nsearch_url = "http://10.0.0.7:8080"'))
    assert loaded.enabled and loaded.search_backend == 'searxng'


@pytest.mark.parametrize('body', ['[web]\nsearch_backend = "bing"', '[web]\nsearch_backend = "tavily"', '[web]\nsearch_backend = "searxng"',
                                  '[web]\nenabled = 1', '[web]\ntimeout_seconds = 0', '[web]\nsearch_url = "ftp://x"', '[web]\nsurprise = 1'])
def test_invalid_settings_are_rejected(tmp_path, body):
    with pytest.raises(DeploymentConfigError):
        load_settings(_config(tmp_path, body))
