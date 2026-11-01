"""Personal Native defaults with optimistic versions; user settings never grant tool access."""
from dataclasses import asdict, fields
from nexus_core.native import NativePolicy
from nexus_core.runtime import ExecutionBudget
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import NativePreferenceRecord
from nexus_platform.errors import Conflict
from nexus_platform.authz.audit import audit


LABELS = {
    'max_rounds': '最大回合数', 'max_tokens': '总 Token 预算', 'max_output_tokens': '每次输出上限',
    'max_seconds': '活跃执行时间（秒）', 'model_timeout_seconds': '模型超时（秒）',
    'max_errors': '工具错误上限', 'max_context_chars': '上下文字符预算',
    'enabled_tools': '新智能体绑定的工具',
    'fallback_models': '故障转移模型', 'routing_spring_seconds': '回归主模型冷却（秒）',
    'empty_retries': '空响应恢复次数', 'repeated_limit': '重复或截断上限',
    'clarify_code': '仅代码回复时确认后续动作', 'working_memory': '每回合工作记忆',
    'model_retries': '模型传输重试次数', 'retry_delay_seconds': '重试初始间隔（秒）',
    'max_retry_delay_seconds': '重试间隔上限（秒）', 'parallel_reads': '允许已声明的安全只读并发',
    'summarize_context': '使用模型生成历史摘要', 'reminder_interval': '工作检查点提醒间隔',
    'memory_interval': '长期记忆提醒间隔', 'durable_checkpoint_interval': '持久检查点提醒间隔',
    'user_direction_interval': '询问用户方向间隔', 'project_name': '项目名称', 'project_context': '项目规则与记忆指针',
    'working_memory_tail': '工作记忆放在历史尾部（实验）', 'tool_output_inline_limit': '工具输出外置阈值（字符）',
    'tool_preview_chars': '外置后的预览长度（字符）', 'tool_output_page_chars': '分页读取每页上限（字符）',
    'tool_result_window_rounds': '工具结果保留的模型调用轮数', 'compact_high_ratio': '触发压缩的上下文比例',
    'compact_low_ratio': '压缩后的目标上下文比例', 'summary_max_chars': '单条摘要字符上限',
    'compaction_model_profile_version_id': '压缩摘要使用的模型（空为智能体模型）',
}


def defaults() -> dict:
    """Return fresh serializable baseline settings; callers can edit only versioned personal defaults."""
    return {'budgets': asdict(ExecutionBudget()), 'behavior': asdict(NativePolicy())}


def _with_defaults(stored: dict) -> dict:
    """Fill keys added after a row was saved, so older records still render a complete form.

    Stored rows are never rewritten here; the next save persists the full set.
    """
    baseline = defaults()
    return {group: baseline[group] | dict(stored.get(group, {})) for group in baseline}


def validate(settings: dict) -> dict:
    """Reject unknown keys, wrong scalar types and excessive budgets before persistence."""
    if set(settings) != {'budgets', 'behavior'} or not all(isinstance(v, dict) for v in settings.values()):
        raise ValueError('Expected Native budgets and behavior objects')
    baseline = defaults()
    for group, values in settings.items():
        if set(values) - set(baseline[group]):
            raise ValueError('Unknown Native setting')
    budgets = baseline['budgets'] | settings['budgets']
    for key, value in budgets.items():
        if type(value) not in (int, float) or (type(baseline['budgets'][key]) is int and type(value) is not int):
            raise ValueError('Invalid Native budget type')
    if budgets['max_rounds'] > 1000 or budgets['max_tokens'] > 10000000 or budgets['max_output_tokens'] > 128000 or budgets['max_seconds'] > 86400:
        raise ValueError('Native budget exceeds service limits')
    ExecutionBudget(**budgets)
    behavior = asdict(NativePolicy(**(baseline['behavior'] | settings['behavior'])))
    return {'budgets': budgets, 'behavior': behavior}


def view(db, user_id, tenant_id) -> dict:
    """Read current preference in the caller's transaction, including typed form metadata."""
    row = db.get(NativePreferenceRecord, (tenant_id, user_id))
    settings = _with_defaults(row.settings) if row else defaults()
    schema = {group: [{'name': key, 'label': LABELS[key], 'type': 'boolean' if type(value) is bool else 'number' if type(value) in (int, float) else 'tools' if key == 'enabled_tools' else 'models' if isinstance(value, list) else 'string'}
                      for key, value in values.items()] for group, values in defaults().items()}
    from nexus_core.native import BUILTIN_TOOL_NAMES
    from nexus_platform.persistence.models import PlatformResourceRecord
    from nexus_platform.identity.service import require_membership
    from nexus_platform.tenants.service import ADMIN_ROLES
    from sqlalchemy import select
    enabled = set(db.scalars(select(PlatformResourceRecord.resource_id).where(PlatformResourceRecord.tenant_id == tenant_id, PlatformResourceRecord.kind == 'tool', PlatformResourceRecord.version_id == 'v1', PlatformResourceRecord.active.is_(True))))
    membership = require_membership(db, tenant_id, user_id)
    return {'version': row.version if row else 0, 'settings': settings, 'fields': schema,
            'available_tools': [{'id': name, 'label': name, 'enabled': name in enabled} for name in BUILTIN_TOOL_NAMES],
            'can_enable_tools': membership.role in ADMIN_ROLES}


def load(db, principal, tenant_id) -> dict:
    """Authorize and return personal defaults; no other user's settings are exposed."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return view(db, user.id, tenant_id)


def save(db, principal, tenant_id, settings: dict, expected_version: int) -> dict:
    """Optimistically save validated defaults; concurrent edits must reload instead of overwrite."""
    settings = validate(settings)
    from sqlalchemy import select
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        row = db.scalar(select(NativePreferenceRecord).where(NativePreferenceRecord.tenant_id == tenant_id,
            NativePreferenceRecord.user_id == user.id).with_for_update())
        if (row.version if row else 0) != expected_version:
            raise Conflict('Native settings changed; reload before saving')
        from nexus_platform.models.provider_settings import authorize_model
        from uuid import UUID
        from nexus_platform.authz.resources import authorize_resource
        for name in settings['behavior']['enabled_tools']:
            authorize_resource(db, tenant_id, 'tool', name, resource_version_id='v1')
        for model_id in settings['behavior']['fallback_models']:
            authorize_model(db, tenant_id, user.id, UUID(model_id))
        compaction_model = settings['behavior']['compaction_model_profile_version_id']
        if compaction_model:
            authorize_model(db, tenant_id, user.id, UUID(compaction_model))
        if row:
            row.settings = settings; row.version += 1
        else:
            row = NativePreferenceRecord(tenant_id=tenant_id, user_id=user.id, settings=settings, version=1)
            db.add(row)
        db.flush()
        audit(db, tenant_id, user.id, 'native.settings_updated', 'native_preferences', str(user.id), {'version': row.version})
        return view(db, user.id, tenant_id)
