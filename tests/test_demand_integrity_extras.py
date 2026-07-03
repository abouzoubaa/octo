"""Wave I: manipulation/duplication risk + exposure-normalized demand."""

from cci_agent.demand import compute_integrity, demand_certificate
from cci_core.models import Comment, DemandTopic, Post


def _comment(session, creator_id, text, pseudo, external):
    c = Comment(creator_id=creator_id, external_id=external, author_pseudonym=pseudo,
                text=text, is_question=True)
    session.add(c)
    session.flush()
    return c


def test_manipulation_risk_high_for_duplicated_concentrated(seeded_creator, session):
    # one person posting the same comment many times = highly manipulable
    cs = [_comment(session, seeded_creator.id, "PLAN", "botA", f"m{i}") for i in range(5)]
    cluster = [("comment", c.text, c.id) for c in cs]
    integ = compute_integrity(session, seeded_creator.id, cluster, "push day", "2026-W24")
    assert integ["duplication_rate"] > 0.7  # 5 identical → high duplication
    assert integ["manipulation_risk"] > 0.6  # prompted + duplicate + concentrated


def test_manipulation_risk_low_for_organic_diverse(seeded_creator, session):
    cs = [
        _comment(session, seeded_creator.id, "how do I structure a push day?", "p1", "o1"),
        _comment(session, seeded_creator.id, "what about pull day splits?", "p2", "o2"),
        _comment(session, seeded_creator.id, "is twice a week enough for chest?", "p3", "o3"),
    ]
    cluster = [("comment", c.text, c.id) for c in cs]
    integ = compute_integrity(session, seeded_creator.id, cluster, "training", "2026-W24")
    assert integ["duplication_rate"] == 0.0  # all distinct
    assert integ["manipulation_risk"] < 0.2  # diverse, organic, distinct authors


def test_exposure_normalized_none_without_impressions(seeded_creator, session):
    c = _comment(session, seeded_creator.id, "a question about protein", "p1", "e1")
    cluster = [("comment", c.text, c.id)]
    integ = compute_integrity(session, seeded_creator.id, cluster, "protein", "2026-W24")
    assert integ["demand_per_1k_impressions"] is None  # no insights data → None, not 0


def test_exposure_normalized_computed_with_impressions(seeded_creator, session):
    post = Post(creator_id=seeded_creator.id, platform="instagram", external_id="imp-1",
                type="reel", caption="protein post", impressions=10_000)
    session.add(post)
    session.flush()
    cs = [Comment(creator_id=seeded_creator.id, post_id=post.id, external_id=f"ie{i}",
                  author_pseudonym=f"p{i}", text=f"protein question {i}", is_question=True)
          for i in range(5)]
    session.add_all(cs)
    session.flush()
    cluster = [("comment", c.text, c.id) for c in cs]
    integ = compute_integrity(session, seeded_creator.id, cluster, "protein", "2026-W24")
    # 5 organic asks / 10000 impressions * 1000 = 0.5 per 1k
    assert integ["demand_per_1k_impressions"] == 0.5


def test_certificate_discounts_manipulated_demand(seeded_creator, session):
    clean = DemandTopic(creator_id=seeded_creator.id, label="clean", week="2026-W24",
                        search_count=10, comment_count=10, unique_askers=18,
                        persistence_weeks=4, prompted_count=0, manipulation_risk=0.0)
    dirty = DemandTopic(creator_id=seeded_creator.id, label="dirty", week="2026-W24",
                        search_count=10, comment_count=10, unique_askers=18,
                        persistence_weeks=4, prompted_count=0, manipulation_risk=0.9)
    session.add_all([clean, dirty])
    session.flush()
    c_clean = demand_certificate(session, clean)
    c_dirty = demand_certificate(session, dirty)
    assert c_dirty["confidence"] < c_clean["confidence"]  # manipulated demand discounted
    assert c_dirty["manipulation_risk"] == 0.9
