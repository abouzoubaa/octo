"""Database bootstrap: extensions, schema, indexes.

v1 keeps migrations simple: idempotent create-from-metadata plus explicit
indexes. When the schema starts evolving under live data, graduate to Alembic.
"""
from sqlalchemy import text

from cci_core.db import get_engine
from cci_core.models import Base


def init_db() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # GIN index for the full-text half of hybrid search
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING gin (tsv)"))
    print("database initialised ✔")
