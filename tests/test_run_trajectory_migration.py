"""Model request trajectory table migration round-trip."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_run_trajectory_records_migration_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'trajectory.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'b72e6c39ad10')

    engine = create_engine(url)
    command.upgrade(config, 'head')
    assert {'run_trajectory_records'} <= set(inspect(engine).get_table_names())
    assert {'run_id', 'sequence', 'turn', 'attempt', 'request_snapshot', 'response_snapshot',
            'usage', 'run_total_tokens', 'started_at', 'completed_at'} <= {
                column['name'] for column in inspect(engine).get_columns('run_trajectory_records')}

    command.downgrade(config, 'b72e6c39ad10')
    assert 'run_trajectory_records' not in inspect(engine).get_table_names()
