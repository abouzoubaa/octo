"""Hybrid retrieval against real Postgres+pgvector with the seeded demo corpus."""
from cci_core.models import Post
from cci_retrieval.indexer import index_post, purge_post, reindex_creator
from cci_retrieval.search import retrieval_confidence, search


def _post_by_external(session, creator_id, external_id) -> Post:
    from sqlalchemy import select

    return session.scalar(
        select(Post).where(Post.creator_id == creator_id, Post.external_id == external_id)
    )


def test_search_finds_price_objection_reel(seeded_creator, session):
    results = search(session, seeded_creator.id, "how to handle price objections")
    assert results, "expected results"
    expected = _post_by_external(session, seeded_creator.id, "demo-1")
    assert results[0].post_id == expected.id
    assert results[0].evidence


def test_search_finds_breakfast_post_with_different_words(seeded_creator, session):
    results = search(session, seeded_creator.id, "high protein breakfast no eggs")
    expected = _post_by_external(session, seeded_creator.id, "demo-0")
    assert expected.id in [r.post_id for r in results[:3]]


def test_search_scoped_to_creator(seeded_creator, session):
    # a second creator with no content must see nothing, even though another
    # tenant's corpus contains strong matches
    import uuid

    from cci_core.models import Creator, CreatorStatus

    other = Creator(handle=f"empty-{uuid.uuid4().hex[:8]}", display_name="Empty",
                    status=CreatorStatus.active)
    session.add(other)
    session.commit()
    assert search(session, other.id, "protein breakfast") == []


def test_confidence_monotone(seeded_creator, session):
    strong = retrieval_confidence(search(session, seeded_creator.id, "push day routine chest shoulders"))
    none = retrieval_confidence([])
    assert strong > 0
    assert none == 0.0


def test_deleted_post_disappears_from_results(seeded_creator, session):
    expected = _post_by_external(session, seeded_creator.id, "demo-1")
    purge_post(session, expected)
    session.commit()
    results = search(session, seeded_creator.id, "how to handle price objections")
    assert expected.id not in [r.post_id for r in results]


def test_reindex_creator_rebuilds_chunks(seeded_creator, session):
    n = reindex_creator(session, seeded_creator.id)
    session.commit()
    assert n > 0


def test_index_post_idempotent(seeded_creator, session):
    post = _post_by_external(session, seeded_creator.id, "demo-0")
    first = index_post(session, post)
    second = index_post(session, post)
    assert first == second > 0
