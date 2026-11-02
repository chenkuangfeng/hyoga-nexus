"""P2 migrations preserve P1 records and can be applied repeatedly."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_native_migration_preserves_existing_p1_data(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'native-migration.db')
    config = Config('alembic.ini')
    config.attributes["database_url"] = url
    command.upgrade(config, '9608e45573e5')
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id,issuer,subject,status,created_at) VALUES (:id,'test','existing','active',CURRENT_TIMESTAMP)"),
                   {'id': '00000000000000000000000000000001'})
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
    with engine.connect() as db:
        # The identity split keeps the P1 subject as an identity with empty scope and as the display name.
        assert db.execute(text("SELECT provider, scope, external_id FROM user_identities")).one() == ('test', '', 'existing')
        assert db.execute(text('SELECT display_name FROM users')).scalar_one() == 'existing'
        tables = {row[0] for row in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {'native_run_states', 'run_input_requests', 'session_checkpoints', 'memory_drafts', 'model_providers', 'provider_models', 'provider_credentials', 'model_defaults',
                'action_approvals', 'context_summaries', 'native_preferences', 'run_directives', 'memory_entries', 'memory_versions'} <= tables
        columns = {row[1] for row in db.execute(text('PRAGMA table_info(messages)'))}
        assert 'runtime_metadata' in columns
        input_columns = {row[1] for row in db.execute(text('PRAGMA table_info(run_input_requests)'))}
        assert 'candidates' in input_columns
    command.downgrade(config, '9608e45573e5')
    with engine.connect() as db:
        assert db.execute(text('SELECT subject FROM users')).scalar_one() == 'existing'
    command.upgrade(config, 'head')
    engine.dispose()
