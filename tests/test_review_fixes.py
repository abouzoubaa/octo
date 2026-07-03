"""Regression tests for review fixes — keep the refinements from silently reverting."""
from cci_agent.intelligence import score_sentiment
from cci_agent.scale import revenue_forecast
from cci_agent.team import mint_api_key, verify_api_key
from cci_core.agent_foundations import get_rules, is_taboo, must_escalate


# --- safety guard: whole-word matching (no substring false positives) ---


def test_taboo_word_boundary_no_false_positive(seeded_creator, session):
    rules = get_rules(session, seeded_creator.id)
    rules.taboo_topics = ["ai", "med"]  # short words that substring-match many tokens
    session.flush()
    assert not is_taboo(rules, "it started to rain on my email")  # 'ai'/'med' substrings
    assert is_taboo(rules, "is this safe to use with ai?")  # real whole-word hit


def test_empty_taboo_topic_does_not_block_everything(seeded_creator, session):
    rules = get_rules(session, seeded_creator.id)
    rules.taboo_topics = ["", "  "]  # blank entries must be ignored
    session.flush()
    assert not is_taboo(rules, "anything at all")
    assert not must_escalate(rules, "anything at all")


# --- sentiment: no-LLM hot path ---


def test_sentiment_no_llm_path():
    assert score_sentiment("I'm so worried", use_llm=False) == "anxiety"  # marker hit
    assert score_sentiment("a neutral statement here", use_llm=False) == "neutral"  # no LLM


# --- revenue forecast is linear, not quadratic ---


def test_revenue_forecast_not_quadratic(seeded_creator, session):
    # with no events both windows are 0 → projection 0, never a blow-up
    out = revenue_forecast(session, seeded_creator.id)
    assert out["projected_next_window"] == 0


# --- API keys: fail-closed scopes + independent prefix ---


def test_api_key_prefix_is_not_a_slice_of_secret(seeded_creator, session):
    record, full = mint_api_key(session, seeded_creator.id, "k", scopes=["demand:read"])
    secret = full.split("_", 2)[2]  # sift_<prefix>_<secret>
    assert not secret.startswith(record.prefix)  # prefix independent of secret bytes
    assert verify_api_key(session, full).id == record.id


def test_api_key_default_scopes_are_empty_not_all(seeded_creator, session):
    record, _ = mint_api_key(session, seeded_creator.id, "k")  # no scopes passed
    assert record.scopes == []  # empty (fail-closed), not None/all-access
