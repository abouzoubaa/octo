"""Wave J: language detection, configurable FTS, start-here paths."""
import pytest
from fastapi.testclient import TestClient

from cci_api.main import create_app
from cci_core.language import detect_language


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


# ----------------------------------------------------------- language detection


def test_detect_language():
    assert detect_language("how do you handle price objections with your clients") == "en"
    assert detect_language("cómo manejar las objeciones de precio con tus clientes") == "es"
    assert detect_language("comment gérer les objections de prix avec vos clients") == "fr"
    assert detect_language("") == "en"  # uncertainty → English


def test_fts_config_is_configurable():
    from cci_core.config import get_settings

    # default English; an operator sets 'simple' for multilingual deployments
    assert get_settings().fts_config == "english"


def test_search_surfaces_language(client, seeded_creator, session):
    # demo posts are English; the result carries the detected language
    from cci_core.language import detect_language
    from cci_core.models import Post
    from sqlalchemy import select

    # backfill language on seeded posts (seed_demo bypasses ingestion)
    for p in session.scalars(select(Post).where(Post.creator_id == seeded_creator.id)):
        if p.caption:
            p.language = detect_language(p.caption)
    session.commit()
    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "how to handle price objections"}).json()
    assert data["results"]
    assert data["results"][0]["language"] == "en"


# ----------------------------------------------------------- start-here paths


@pytest.fixture()
def with_radar(seeded_creator, session):
    from cci_workers.enrich import process_all_pending
    from cci_workers.radar import build_radar

    process_all_pending(seeded_creator.id)
    build_radar(seeded_creator.id, backlog=True)
    session.commit()
    return seeded_creator


def test_start_here_paths(client, with_radar):
    data = client.get(f"/api/{with_radar.handle}/start-here").json()
    assert "paths" in data and "hint" in data
    assert data["paths"]  # at least some suggested entry points
    assert all("query" in p and "label" in p for p in data["paths"])
    assert len(data["paths"]) <= 5
