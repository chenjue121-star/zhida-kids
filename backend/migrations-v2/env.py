"""Explicit migrations for the isolated v2 database only."""
from __future__ import annotations

import os
from pathlib import Path

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

config = context.config
root = Path(__file__).resolve().parents[1]
url = config.attributes.get("database_url") or os.environ.get("V2_DATABASE_URL") or dotenv_values(root / ".env.v2").get("V2_DATABASE_URL")
if not url:
    raise ValueError("V2_DATABASE_URL is required for isolated v2 migrations")
parsed = make_url(url)
if parsed.get_backend_name() != "sqlite" and not (parsed.database or "").startswith("zhida_kids_v2_"):
    raise ValueError("Migrations require an isolated zhida_kids_v2_ database")

from app.v2.core.database import Base
from app.v2.identity import models as identity_models
from app.v2.families import models as family_models
from app.v2.children import models as child_models
from app.v2.preferences import models as preference_models
from app.v2.media import models as media_models
from app.v2.wardrobe import models as wardrobe_models
from app.v2.recognition import models as recognition_models
from app.v2.outfits import models as outfit_models
from app.v2.release import models as release_models

target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(connection=supplied_connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(url, poolclass=pool.NullPool)
        try:
            with engine.connect() as connection:
                context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            engine.dispose()
