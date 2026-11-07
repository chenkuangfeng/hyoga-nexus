"""External parser engines (port of WeKnora ``internal/infrastructure/docparser``; openspec K4).

Each engine turns one file into Markdown by calling a document-parsing service, and the Markdown is then split
into sections like any other document (headings become section paths). Engines:

- ``mineru``: self-hosted MinerU, legacy ``POST {endpoint}/file_parse`` (multipart) → ``results[name].md_content``;
- ``mineru_cloud``: mineru.net v4 batch API: ``POST /file-urls/batch`` → ``PUT`` the file → poll
  ``GET /extract-results/batch/{id}`` → markdown inline or from ``full_zip_url``;
- ``paddleocr_vl``: self-hosted PaddleOCR-VL ``POST {endpoint}/layout-parsing`` (JSON, base64) →
  ``result.layoutParsingResults[].markdown.text``;
- ``paddleocr_vl_cloud``: AI Studio jobs API: ``POST /jobs`` (multipart) → poll ``GET /jobs/{id}`` → JSONL result.

Written from the WeKnora sources without access to the services: unit tests use mock transports; real-service
checks are pending. Network access goes through ``client_for(url)``, which the platform supplies with the same
pinned, redirect-free transport as model calls (so a saved endpoint is checked on every request). Images the
services return are not stored; local image references are dropped from the Markdown.

``config`` keys follow the settings page (``mineru_endpoint``, ``mineru_api_key``, ``paddleocr_vl_endpoint`` ...).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

import httpx

from .parse import ParseError, Section, parse_markdown

ClientFor = Callable[[str], httpx.AsyncClient]

MINERU_CLOUD_BASE = 'https://mineru.net/api/v4'
PADDLE_CLOUD_BASE = 'https://paddleocr.aistudio-app.com/api/v2/ocr/jobs'
POLL_INTERVAL = 3.0
CLOUD_TIMEOUT = 600.0
SELF_HOSTED_TIMEOUT = 600.0
MAX_ZIP_BYTES = 128 * 1024 * 1024

_LOCAL_IMAGE = re.compile(r'!\[[^\]]*\]\((?!https?:|data:)[^)]*\)')


class EngineError(ParseError):
    code = 'engine_failed'


def clean_markdown(text: str) -> str:
    """Drop image references that point at files we do not keep, unescape ``\\#`` headings."""
    text = _LOCAL_IMAGE.sub('', text or '')
    return re.sub(r'(?m)^\\(#{1,6}\s)', r'\1', text).strip()


def to_sections(markdown: str) -> list[Section]:
    return parse_markdown(clean_markdown(markdown))


def _flag(config: Mapping[str, Any], key: str, default: bool) -> bool:
    value = config.get(key)
    return default if value in (None, '') else value in (True, 'true', 'True', '1', 1)


def _text(config: Mapping[str, Any], key: str, default: str = '') -> str:
    value = str(config.get(key) or '').strip()
    return value or default


async def _request(client_for: ClientFor, method: str, url: str, **kwargs) -> httpx.Response:
    """One request with a client built for this URL's host (each host is checked and pinned separately)."""
    client = client_for(url)
    try:
        return await client.request(method, url, **kwargs)
    finally:
        await client.aclose()


async def _check(response: httpx.Response, what: str) -> httpx.Response:
    if response.status_code >= 400:
        raise EngineError(f'{what} HTTP {response.status_code}: {response.text[:300]}')
    return response


# ---------------------------------------------------------------- MinerU (self-hosted)

async def mineru(client_for: ClientFor, config: Mapping[str, Any], filename: str, data: bytes) -> str:
    endpoint = _text(config, 'mineru_endpoint').rstrip('/')
    fields = {
        'return_md': 'true', 'return_images': 'false', 'return_content_list': 'false', 'return_middle_json': 'false',
        'return_model_output': 'false', 'response_format_zip': 'false', 'start_page_id': '0', 'end_page_id': '99999',
        'table_enable': str(_flag(config, 'mineru_enable_table', True)).lower(),
        'formula_enable': str(_flag(config, 'mineru_enable_formula', True)).lower(),
        'parse_method': _text(config, 'mineru_parse_method', 'auto'),
        'backend': _text(config, 'mineru_model', 'pipeline'),
        'lang_list': _text(config, 'mineru_language', 'ch'),
    }
    server = _text(config, 'mineru_vlm_server_url')
    if server and fields['backend'].startswith(('vlm-http-client', 'hybrid-http-client')):
        fields['server_url'] = server
    headers = {'Authorization': f'Bearer {_text(config, "mineru_server_api_key")}'} if _text(config, 'mineru_server_api_key') else {}
    try:
        response = await _check(await _request(client_for, 'POST', f'{endpoint}/file_parse', data=fields, headers=headers,
                                               files={'files': (filename, data)}, timeout=SELF_HOSTED_TIMEOUT), 'MinerU')
        results = (response.json() or {}).get('results') or {}
    except httpx.HTTPError as exc:
        raise EngineError(f'MinerU request failed: {type(exc).__name__}') from exc
    stem = filename.rsplit('.', 1)[0]
    for key in (stem, filename, *results):
        entry = results.get(key)
        if isinstance(entry, dict) and entry.get('md_content'):
            return entry['md_content']
    return ''


# ---------------------------------------------------------------- MinerU cloud

def _markdown_from_zip(blob: bytes) -> str:
    if len(blob) > MAX_ZIP_BYTES:
        raise EngineError('MinerU result archive is too large')
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = [n for n in archive.namelist() if n.endswith('.md') and '..' not in n]
        if not names:
            raise EngineError('MinerU result archive has no markdown')
        name = next((n for n in names if n.endswith('full.md')), names[0])
        info = archive.getinfo(name)
        if info.file_size > MAX_ZIP_BYTES:
            raise EngineError('MinerU markdown is too large')
        return archive.read(name).decode('utf-8', errors='replace')


async def mineru_cloud(client_for: ClientFor, config: Mapping[str, Any], filename: str, data: bytes,
                       *, poll_interval: float = POLL_INTERVAL, timeout: float = CLOUD_TIMEOUT) -> str:
    token = _text(config, 'mineru_api_key')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    model = _text(config, 'mineru_cloud_model', 'pipeline')
    try:
        payload = {'files': [{'name': filename, 'data_id': base64.urlsafe_b64encode(filename.encode()).decode()[:32]}],
                   'model_version': 'MinerU-HTML' if filename.lower().endswith('.html') else model,
                   'is_ocr': _flag(config, 'mineru_cloud_enable_ocr', True),
                   'enable_formula': _flag(config, 'mineru_cloud_enable_formula', True),
                   'enable_table': _flag(config, 'mineru_cloud_enable_table', True),
                   'language': _text(config, 'mineru_cloud_language', 'ch')}
        applied = (await _check(await _request(client_for, 'POST', f'{MINERU_CLOUD_BASE}/file-urls/batch', json=payload,
                                               headers=headers, timeout=30), 'MinerU cloud')).json()
        if applied.get('code') != 0 or not (applied.get('data') or {}).get('file_urls'):
            raise EngineError(f'MinerU cloud refused the file: {applied.get("msg")}')
        batch, upload = applied['data']['batch_id'], applied['data']['file_urls'][0]
        await _check(await _request(client_for, 'PUT', upload, content=data, timeout=120), 'MinerU upload')
        waited = 0.0
        while waited <= timeout:
            polled = (await _check(await _request(client_for, 'GET', f'{MINERU_CLOUD_BASE}/extract-results/batch/{batch}',
                                                  headers=headers, timeout=30), 'MinerU cloud')).json()
            items = (polled.get('data') or {}).get('extract_result') or []
            item = (items[0] if isinstance(items, list) and items else items) or {}
            state = str(item.get('state') or '').lower()
            if state == 'failed':
                raise EngineError(f'MinerU cloud task failed: {item.get("err_msg")}')
            if state == 'done':
                inline = item.get('markdown') or item.get('content') or item.get('text')
                if inline:
                    return inline
                if not item.get('full_zip_url'):
                    raise EngineError('MinerU cloud finished without a result')
                archive = await _check(await _request(client_for, 'GET', item['full_zip_url'], timeout=120), 'MinerU result download')
                return _markdown_from_zip(archive.content)
            await asyncio.sleep(poll_interval)
            waited += max(poll_interval, 0.01)
        raise EngineError('MinerU cloud task timed out')
    except httpx.HTTPError as exc:
        raise EngineError(f'MinerU cloud request failed: {type(exc).__name__}') from exc


# ---------------------------------------------------------------- PaddleOCR-VL

def paddle_params(use_seal: bool, use_chart: bool) -> dict[str, Any]:
    return {
        'markdownIgnoreLabels': ['header', 'header_image', 'footer', 'footer_image', 'number', 'footnote', 'aside_text'],
        'useDocOrientationClassify': False, 'useDocUnwarping': False, 'useLayoutDetection': True,
        'useChartRecognition': use_chart, 'useSealRecognition': use_seal, 'useOcrForImageBlock': False,
        'mergeTables': True, 'relevelTitles': True, 'restructurePages': True, 'layoutShapeMode': 'auto',
        'promptLabel': 'ocr', 'layoutNms': True, 'repetitionPenalty': 1, 'temperature': 0, 'topP': 1,
        'minPixels': 147384, 'maxPixels': 2822400,
    }


def _paddle_markdown(result: Mapping[str, Any]) -> str:
    pages = ((result or {}).get('result') or {}).get('layoutParsingResults') or []
    return '\n\n'.join(t for t in ((p.get('markdown') or {}).get('text', '') for p in pages) if t and t.strip())


async def paddleocr_vl(client_for: ClientFor, config: Mapping[str, Any], filename: str, data: bytes) -> str:
    endpoint = _text(config, 'paddleocr_vl_endpoint').rstrip('/')
    payload = paddle_params(_flag(config, 'paddleocr_vl_use_seal_recognition', False),
                            _flag(config, 'paddleocr_vl_use_chart_recognition', False))
    payload.update({'file': base64.b64encode(data).decode(), 'fileType': 0 if filename.lower().endswith('.pdf') else 1,
                    'visualize': False})
    try:
        response = await _check(await _request(client_for, 'POST', f'{endpoint}/layout-parsing', json=payload,
                                               timeout=SELF_HOSTED_TIMEOUT), 'PaddleOCR-VL')
        body = response.json()
    except httpx.HTTPError as exc:
        raise EngineError(f'PaddleOCR-VL request failed: {type(exc).__name__}') from exc
    if body.get('errorCode'):
        raise EngineError(f'PaddleOCR-VL error {body.get("errorCode")}: {body.get("errorMsg")}')
    return _paddle_markdown(body)


async def paddleocr_vl_cloud(client_for: ClientFor, config: Mapping[str, Any], filename: str, data: bytes,
                             *, poll_interval: float = POLL_INTERVAL, timeout: float = CLOUD_TIMEOUT) -> str:
    token = _text(config, 'paddleocr_vl_cloud_token')
    headers = {'Authorization': f'bearer {token}'}
    payload = paddle_params(_flag(config, 'paddleocr_vl_cloud_use_seal_recognition', False),
                            _flag(config, 'paddleocr_vl_cloud_use_chart_recognition', False))
    try:
        submitted = (await _check(await _request(
            client_for, 'POST', PADDLE_CLOUD_BASE, headers=headers, timeout=60,
            data={'model': _text(config, 'paddleocr_vl_cloud_model', 'PaddleOCR-VL-1.6'),
                  'optionalPayload': json.dumps(payload)},
            files={'file': (filename.rsplit('/', 1)[-1], data)}), 'PaddleOCR-VL cloud')).json()
        job = (submitted.get('data') or {}).get('jobId')
        if not job:
            raise EngineError(f'PaddleOCR-VL cloud refused the file: {submitted.get("errorMsg")}')
        waited = 0.0
        while waited <= timeout:
            state = (await _check(await _request(client_for, 'GET', f'{PADDLE_CLOUD_BASE}/{job}', headers=headers, timeout=30),
                                  'PaddleOCR-VL cloud')).json().get('data') or {}
            name = str(state.get('state') or '').lower()
            if name == 'failed':
                raise EngineError(f'PaddleOCR-VL cloud job failed: {state.get("errorMsg")}')
            if name == 'done':
                url = (state.get('resultUrl') or {}).get('jsonUrl')
                if not url:
                    raise EngineError('PaddleOCR-VL cloud finished without a result')
                lines = (await _check(await _request(client_for, 'GET', url, timeout=120), 'PaddleOCR-VL result')).text.splitlines()
                parts = []
                for line in lines:
                    if line.strip():
                        parts.append(_paddle_markdown(json.loads(line)))
                return '\n\n'.join(p for p in parts if p)
            await asyncio.sleep(poll_interval)
            waited += max(poll_interval, 0.01)
        raise EngineError('PaddleOCR-VL cloud job timed out')
    except httpx.HTTPError as exc:
        raise EngineError(f'PaddleOCR-VL cloud request failed: {type(exc).__name__}') from exc


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class Engine:
    name: str
    description: str
    file_types: tuple[str, ...]
    #: Names of the config keys that must be set for the engine to run.
    required: tuple[str, ...]
    parse: Callable[..., Awaitable[str]]

    def unavailable_reason(self, config: Mapping[str, Any]) -> str:
        missing = [key for key in self.required if not _text(config, key)]
        return f'未配置：{", ".join(missing)}' if missing else ''


_DOC_TYPES = ('pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls', 'png', 'jpg', 'jpeg')
EXTERNAL: dict[str, Engine] = {e.name: e for e in (
    Engine('mineru', 'MinerU（自建）文档解析', _DOC_TYPES + ('html',), ('mineru_endpoint',), mineru),
    Engine('mineru_cloud', 'MinerU 云服务', _DOC_TYPES + ('html',), ('mineru_api_key',), mineru_cloud),
    Engine('paddleocr_vl', 'PaddleOCR-VL（自建）', ('pdf', 'png', 'jpg', 'jpeg', 'bmp', 'tiff'),
           ('paddleocr_vl_endpoint',), paddleocr_vl),
    Engine('paddleocr_vl_cloud', 'PaddleOCR-VL 云服务', ('pdf', 'png', 'jpg', 'jpeg', 'bmp', 'tiff'),
           ('paddleocr_vl_cloud_token',), paddleocr_vl_cloud),
)}

SECRET_KEYS = frozenset({'mineru_api_key', 'mineru_server_api_key', 'paddleocr_vl_cloud_token'})


async def parse_with(name: str, client_for: ClientFor, config: Mapping[str, Any], filename: str,
                     data: bytes) -> list[Section]:
    engine = EXTERNAL.get(name)
    if engine is None:
        raise EngineError(f'unknown parser engine: {name}')
    reason = engine.unavailable_reason(config)
    if reason:
        raise EngineError(f'{name} is not configured ({reason})')
    markdown = await engine.parse(client_for, config, filename, data)
    sections = [s for s in to_sections(markdown) if s.text.strip()]
    if not sections:
        raise ParseError(f'{name} returned no text')
    return sections
