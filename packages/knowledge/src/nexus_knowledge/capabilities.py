"""Knowledge capability catalog: every WeKnora knowledge feature, with its implementation state.

openspec 2026-11-06-knowledge-base K0 (decision 5). Nexus keeps the whole WeKnora knowledge feature set
visible; the web client renders each item from this catalog. An item is ``available`` only when code that
implements it has called :func:`mark_available` (usually at import of the implementing module), so the
catalog never claims a feature by hand. Everything else is ``planned`` with the stage (K1-K7) that will
deliver it, or ``None`` for items with no scheduled stage yet.

``verified`` separates code that ran against the real service from code written without an environment
(decision 1: PostgreSQL, Qdrant, Elasticsearch and Milvus are implemented but verified only once a real
environment is available).

Runtime readiness (an implemented engine that is not configured, a missing pgvector extension, no embedding
model) is a different question answered by the capability gate in K1; it never turns a planned item into
an available one or the reverse.

Reference: WeKnora ``internal/types`` (knowledgebase, indexing_strategy, vectorstore, storagebackend,
datasource) and ``internal/infrastructure/docparser/engines.go`` at ``e1f9a6166``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Group = Literal[
    'kb_type', 'indexing', 'vector_engine', 'storage_provider', 'parser_engine', 'graph_store', 'graph_mode',
    'datasource', 'kb_feature',
]

GROUPS: tuple[Group, ...] = (
    'kb_type', 'indexing', 'vector_engine', 'storage_provider', 'parser_engine', 'graph_store', 'graph_mode',
    'datasource', 'kb_feature',
)


@dataclass(frozen=True, slots=True)
class CapabilityItem:
    """One catalog entry. ``key`` is unique within its group; ``stage`` is the planned stage or None."""

    group: Group
    key: str
    label: str
    stage: str | None


def _items(group: Group, stage: str | None, pairs: list[tuple[str, str]]) -> list[CapabilityItem]:
    return [CapabilityItem(group, key, label, stage) for key, label in pairs]


#: The full feature set, in display order inside each group.
CATALOG: tuple[CapabilityItem, ...] = tuple(
    _items('kb_type', 'K1', [('document', '文档库')])
    + _items('kb_type', 'K3', [('faq', 'FAQ 库')])
    + _items('kb_type', 'K6', [('wiki', 'Wiki 库')])
    + _items('indexing', 'K1', [('vector', '向量索引'), ('keyword', '关键词索引')])
    + _items('indexing', 'K2', [('graph', '图谱')])
    + _items('indexing', 'K6', [('wiki', 'Wiki')])
    + _items('vector_engine', 'K1', [
        ('sqlite', 'SQLite'), ('postgres', 'PostgreSQL (pgvector)'), ('qdrant', 'Qdrant'),
        ('elasticsearch', 'Elasticsearch'), ('milvus', 'Milvus')])
    + _items('vector_engine', None, [
        ('opensearch', 'OpenSearch'), ('weaviate', 'Weaviate'), ('doris', 'Apache Doris'),
        ('tencent_vectordb', '腾讯云 VectorDB'), ('infinity', 'Infinity'), ('chroma', 'Chroma'),
        ('redis', 'Redis Stack'), ('dashvector', '阿里云 DashVector'), ('pinecone', 'Pinecone')])
    + _items('storage_provider', 'K1', [('local', '本地目录')])
    + _items('storage_provider', None, [
        ('minio', 'MinIO'), ('s3', 'Amazon S3'), ('cos', '腾讯云 COS'), ('oss', '阿里云 OSS'),
        ('tos', '火山引擎 TOS')])
    + _items('parser_engine', 'K1', [('builtin', '内置解析')])
    + _items('parser_engine', 'K4', [
        ('simple', '纯文本'), ('markitdown', 'MarkItDown'), ('anydoc', 'AnyDoc'), ('mineru', 'MinerU'),
        ('mineru_cloud', 'MinerU 云服务'), ('paddleocr_vl', 'PaddleOCR-VL'),
        ('paddleocr_vl_cloud', 'PaddleOCR-VL 云服务')])
    + _items('graph_store', 'K2', [('builtin', '内置图存储'), ('neo4j', 'Neo4j')])
    + _items('graph_mode', 'K2', [
        ('entity', '实体关系图谱'), ('graphrag_light', 'GraphRAG Light'), ('graphrag_general', 'GraphRAG General')])
    + _items('datasource', 'K7', [
        ('feishu', '飞书'), ('lark', 'Lark'), ('feishu_drive', '飞书云盘'), ('lark_drive', 'Lark Drive'),
        ('notion', 'Notion'), ('confluence', 'Confluence'), ('yuque', '语雀'), ('github', 'GitHub'),
        ('gitlab', 'GitLab'), ('google_drive', 'Google Drive'), ('onedrive', 'OneDrive'),
        ('dingtalk', '钉钉'), ('web_crawler', '网页抓取'), ('slack', 'Slack'), ('imap', 'IMAP 邮箱'),
        ('rss', 'RSS'), ('ima', 'IMA'), ('seafile', 'Seafile')])
    + _items('kb_feature', 'K1', [
        ('documents', '文档管理'), ('upload', '上传文档'), ('chunking', '分块设置'), ('embedding_model', 'Embedding 模型'),
        ('vector_store_registry', '向量库管理'), ('storage_backend_registry', '存储后端管理'),
        ('retrieval_test', '检索测试'), ('share', '共享'), ('activity', '活动日志'), ('citations', '引用')])
    + _items('kb_feature', 'K2', [('graph_settings', '图谱设置'), ('graph_browser', '图谱浏览')])
    + _items('kb_feature', 'K3', [('faq_entries', 'FAQ 条目'), ('faq_import', 'FAQ 导入')])
    + _items('kb_feature', 'K4', [
        ('parser_rules', '解析引擎规则'), ('chunking_strategy', '分块策略'), ('parent_child', '父子分块'),
        ('chunking_debug', '分块调试'), ('image_processing', '图片处理'), ('vlm', '图片理解 (VLM)'),
        ('asr', '语音转写 (ASR)'), ('image_gallery', '图片库')])
    + _items('kb_feature', 'K5', [
        ('tags', '标签'), ('auto_tag', '自动打标'), ('folders', '文件夹'), ('pin', '置顶'),
        ('summary', '文档摘要'), ('question_generation', '提问生成'), ('profile', '库画像'), ('rerank', '重排'),
        ('metadata_filter', '元数据过滤'), ('synonyms', '同义词'), ('structure_tools', '结构导航工具')])
    + _items('kb_feature', 'K6', [('wiki_pages', 'Wiki 页面')])
    + _items('kb_feature', 'K7', [('datasource_sync', '数据源同步')])
)

_INDEX: dict[tuple[str, str], CapabilityItem] = {(item.group, item.key): item for item in CATALOG}
if len(_INDEX) != len(CATALOG):  # pragma: no cover - guards edits of the table above
    raise RuntimeError('duplicate knowledge capability key')

#: (group, key) -> verified. Filled by implementing modules; never edited by hand.
_AVAILABLE: dict[tuple[str, str], bool] = {}


def mark_available(group: Group, key: str, *, verified: bool = True) -> None:
    """Declare that code implementing ``group/key`` is installed. Unknown keys are a programming error."""
    if (group, key) not in _INDEX:
        raise KeyError(f'unknown knowledge capability: {group}/{key}')
    _AVAILABLE[(group, key)] = verified


def reset_for_tests() -> None:
    """Forget every availability mark (tests only)."""
    _AVAILABLE.clear()


def is_available(group: str, key: str) -> bool:
    return (group, key) in _AVAILABLE


def require_available(group: str, key: str) -> None:
    """Raise :class:`CapabilityPlanned` when a write selects a feature that is not implemented yet."""
    if (group, key) not in _INDEX:
        raise ValueError(f'unknown {group}: {key}')
    if (group, key) not in _AVAILABLE:
        raise CapabilityPlanned(_INDEX[(group, key)])


class CapabilityPlanned(Exception):
    """A request chose a cataloged feature that has no implementation yet (HTTP 422 ``capability_planned``)."""

    def __init__(self, item: CapabilityItem) -> None:
        super().__init__(f'{item.group}/{item.key} is planned ({item.stage or "unscheduled"})')
        self.item = item


def snapshot() -> list[dict[str, object]]:
    """Catalog as plain dicts: ``group, key, label, stage, status ('available'|'planned'), verified``."""
    out: list[dict[str, object]] = []
    for item in CATALOG:
        verified = _AVAILABLE.get((item.group, item.key))
        out.append({
            'group': item.group, 'key': item.key, 'label': item.label, 'stage': item.stage,
            'status': 'planned' if verified is None else 'available',
            'verified': bool(verified),
        })
    return out
