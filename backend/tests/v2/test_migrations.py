"""Migration checks are isolated from old tests/conftest.py via --confcutdir."""
from pathlib import Path
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def config_for(url):
    config = Config(str(ROOT / "alembic-v2.ini"))
    config.attributes["database_url"] = url
    return config


def test_migration_round_trip(tmp_path):
    assert (ROOT / "alembic-v2.ini").exists(), "v2 migration environment is required"
    url = f"sqlite:///{tmp_path / 'v2.sqlite'}"
    config = config_for(url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    before = set(inspect(engine).get_table_names())
    assert {"users", "families", "memberships", "invitations", "children"} <= before
    assert {'clothing', 'child_clothing', 'clothing_removals', 'media_assets', 'intake_batches',
            'intake_items', 'intake_candidates', 'recognition_attempts', 'wardrobe_operations'} <= before
    assert {'outfit_recommendations', 'outfit_recommendation_requests', 'outfit_plans',
            'outfit_plan_revisions', 'outfit_reservations'} <= before
    assert {'preference_feedback_events', 'legacy_source_records'} <= before
    assert {'inferred_tags', 'suppression_cutoffs', 'learning_version'} <= {c['name'] for c in inspect(engine).get_columns('preference_profiles')}
    assert 'status' in {c['name'] for c in inspect(engine).get_columns('outfit_plans')}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0005_personalization_calendar"
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) == before
    engine.dispose()


def test_refuses_old_database_before_connecting():
    import pytest
    config = config_for("mysql+pymysql://invalid:invalid@127.0.0.1/zhida_kids")
    with pytest.raises(ValueError, match="isolated"):
        command.upgrade(config, "head")


def test_mysql_migration_round_trip():
    from dotenv import dotenv_values
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.v2.core.database import load_metadata
    import pytest

    source = os.environ.get("V2_TEST_DATABASE_URL") or dotenv_values(ROOT / ".env.v2").get("V2_TEST_DATABASE_URL")
    if not source:
        pytest.skip("Configure the isolated V2_TEST_DATABASE_URL for MySQL verification")
    parsed = make_url(source)
    assert parsed.get_backend_name() == "mysql"
    assert parsed.database == "zhida_kids_v2_test", "Refusing a non-isolated test database"
    url = parsed.set(database="zhida_kids_v2_migration_test").render_as_string(hide_password=False)
    config = config_for(url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), load_metadata()) == []
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), load_metadata()) == []
    finally:
        engine.dispose()
