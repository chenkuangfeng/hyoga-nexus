"""The platform keeps changing checkpoints out of system without dropping source authorization."""
from nexus_core.platform import utc_now
from nexus_platform.persistence.models import WorkingCheckpointRecord
from nexus_platform.runs.preparation import ContextPreparationService
from nexus_platform.runs.service import claim_next

from test_native_runtime import stack
from test_platform import database  # noqa: F401


def test_checkpoint_is_a_tail_reference_after_user_history(database):  # noqa: F811
    _, _, session, run, _ = stack(database)
    with database() as db, db.begin():
        db.add(WorkingCheckpointRecord(session_id=session.id, tenant_id=run.tenant_id,
                                       source_run_id=run.id, content='CHECKPOINT FACT', updated_at=utc_now()))
    task = claim_next(database, 'worker')
    context = ContextPreparationService(database).prepare(task, 'worker')
    assert context is not None
    assert 'CHECKPOINT FACT' not in context.messages[0].content
    assert context.messages[-1].role == 'user'
    assert context.messages[-1].content.endswith('CHECKPOINT FACT')
    assert 'not new instructions' in context.messages[-1].content
    block = next(block for block in context.context_blocks if block.key == 'session:checkpoint')
    assert block.role == 'user' and block.placement == 'turn_tail'
    assert context.messages[-2].content == 'Hello'
