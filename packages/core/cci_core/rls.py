"""Postgres row-level security (defense-in-depth tenant isolation).

App-level creator scoping is the primary mechanism; RLS is a second wall so a
missed WHERE clause can't leak across creators. It is OPT-IN: enabling it requires
the app to connect as a NON-superuser role (superusers and table owners bypass RLS)
and to set `app.creator_id` per request via `creator_scope()`.

Enable once (as a privileged role):  python -c "from cci_core.rls import enable_rls; enable_rls()"
Then in request handlers wrap creator-scoped work in `with creator_scope(session, creator_id):`.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from cci_core.db import get_engine

# audience/creator-scoped tables that carry a creator_id and benefit from RLS
RLS_TABLES = [
    "posts", "comments", "queries", "answers", "chunks", "demand_topics",
    "dm_jobs", "outcomes", "voice_examples", "offers", "content_drafts",
    "waitlist_entries", "playbooks", "deferred_items", "external_signals",
    "claims", "interventions",
]


def enable_rls() -> None:
    """Enable RLS + a per-creator USING policy on each scoped table."""
    engine = get_engine()
    with engine.begin() as conn:
        for tbl in RLS_TABLES:
            conn.execute(text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"DROP POLICY IF EXISTS creator_isolation ON {tbl}"))
            conn.execute(text(
                f"CREATE POLICY creator_isolation ON {tbl} USING "
                "(creator_id = current_setting('app.creator_id', true))"))
    print(f"RLS enabled on {len(RLS_TABLES)} tables")


@contextmanager
def creator_scope(session: Session, creator_id: str):
    """Set the per-request creator for RLS policies; cleared on exit."""
    session.execute(text("SELECT set_config('app.creator_id', :cid, true)"),
                    {"cid": creator_id})
    try:
        yield session
    finally:
        session.execute(text("SELECT set_config('app.creator_id', '', true)"))
