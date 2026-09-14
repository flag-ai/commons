"""Integration tests need a live PostgreSQL in TEST_DATABASE_URL."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ENV_URL = "TEST_DATABASE_URL"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get(ENV_URL)
    if not url:
        pytest.skip(f"{ENV_URL} not set")
    return url


@pytest.fixture
def alembic_scripts(tmp_path: Path) -> Path:
    """A minimal packaged-style Alembic script directory with one revision."""
    scripts = tmp_path / "migrations"
    (scripts / "versions").mkdir(parents=True)
    (scripts / "env.py").write_text(
        """
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
"""
    )
    (scripts / "script.py.mako").write_text("")
    (scripts / "versions" / "0001_baseline.py").write_text(
        """
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "flag_commons_it",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("flag_commons_it")
"""
    )
    return scripts
