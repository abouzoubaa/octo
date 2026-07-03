"""Reranking stage: providers + integration into hybrid search."""
import pytest

from cci_providers.reranking import FakeReranker, LLMReranker
from cci_retrieval.search import search


def test_fake_reranker_orders_by_relevance():
    r = FakeReranker()
    passages = [
        "completely unrelated content about taxes",
        "high protein breakfast ideas with eggs and yogurt",
        "a short note",
    ]
    scores = r.rerank("high protein breakfast", passages)
    assert scores[1] == max(scores)  # the on-topic passage wins
    assert scores[0] < scores[1]


def test_fake_reranker_empty_query():
    assert FakeReranker().rerank("", ["anything"]) == [0.0]


def test_llm_reranker_offline(monkeypatch):
    from cci_providers import get_llm

    r = LLMReranker(get_llm())  # FakeLLM
    scores = r.rerank("protein breakfast", ["protein breakfast recipe", "unrelated text"])
    assert len(scores) == 2
    assert scores[0] >= scores[1]


def test_llm_reranker_handles_garbage(monkeypatch):
    class _BadLLM:
        name = "bad"

        def complete(self, *a, **k):
            return "not json at all"

    scores = LLMReranker(_BadLLM()).rerank("q", ["a", "b"])
    assert scores == [0.0, 0.0]  # graceful neutral fallback, never raises


@pytest.fixture()
def _rerank_on(monkeypatch):
    from cci_core.config import get_settings
    from cci_providers import registry

    monkeypatch.setattr(get_settings(), "rerank_provider", "fake")
    registry.get_reranker.cache_clear()
    yield
    registry.get_reranker.cache_clear()


def test_search_with_reranking_still_finds_post(seeded_creator, session, _rerank_on):
    """With the reranker enabled, the right post is still top-ranked."""
    results = search(session, seeded_creator.id, "how to handle price objections")
    assert results
    from sqlalchemy import select

    from cci_core.models import Post

    expected = session.scalar(select(Post).where(
        Post.creator_id == seeded_creator.id, Post.external_id == "demo-1"))
    assert results[0].post_id == expected.id


def test_search_reranking_disabled_by_default(seeded_creator, session):
    # default rerank_provider='none' → get_reranker() returns None, search unaffected
    from cci_providers import get_reranker

    assert get_reranker() is None
    assert search(session, seeded_creator.id, "push day workout")
