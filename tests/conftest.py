"""Test fixtures — run against the real Postgres+pgvector (retrieval SQL needs it)."""
import uuid

import pytest

from cci_core.bootstrap import init_db
from cci_core.db import get_engine, get_sessionmaker
from cci_core.models import Base, Creator, CreatorStatus


@pytest.fixture(scope="session", autouse=True)
def _database():
    engine = get_engine()
    Base.metadata.drop_all(engine)
    init_db()
    yield
    engine.dispose()


@pytest.fixture()
def session():
    s = get_sessionmaker()()
    yield s
    s.rollback()
    s.close()


@pytest.fixture()
def creator(session):
    c = Creator(
        handle=f"test-{uuid.uuid4().hex[:8]}",
        display_name="Test Creator",
        status=CreatorStatus.active,
    )
    session.add(c)
    session.commit()
    return c


@pytest.fixture()
def seeded_creator(creator, session):
    """Creator with the synthetic demo corpus indexed (fake providers)."""
    from cci_workers.seed import seed_demo

    seed_demo(creator.id)
    session.expire_all()
    return creator
