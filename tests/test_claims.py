"""Wave B: versioned claim layer — extraction, supersession, freshness."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from cci_agent.claims import (
    claim_freshness,
    detect_contradictions,
    extract_claims,
    supersede,
)
from cci_core.models import Claim, ClaimValidity, Post, Transcript


def _post(session, creator_id, caption, *, external="cl-1", days_ago=0, transcript=None):
    p = Post(creator_id=creator_id, platform="instagram", external_id=external,
             type="reel", caption=caption,
             posted_at=datetime.now(timezone.utc) - timedelta(days=days_ago))
    session.add(p)
    session.flush()
    if transcript:
        session.add(Transcript(post_id=p.id, source="whisper", text=transcript))
        session.flush()
    return p


def test_extract_claims_from_post(seeded_creator, session):
    post = _post(session, seeded_creator.id,
                 "Never drop your price when handling objections. Anchor against the cost "
                 "of staying stuck. Always restate the outcome clearly.")
    claims = extract_claims(session, post)
    assert claims
    assert all(c.post_id == post.id for c in claims)
    assert all(c.validity == ClaimValidity.current for c in claims)
    # idempotent
    assert extract_claims(session, post) == []


def test_extract_claims_empty_post(seeded_creator, session):
    post = _post(session, seeded_creator.id, "", external="empty")
    assert extract_claims(session, post) == []


def test_supersede_marks_old(seeded_creator, session):
    p_old = _post(session, seeded_creator.id, "old", external="o", days_ago=400)
    p_new = _post(session, seeded_creator.id, "new", external="n", days_ago=1)
    old = Claim(creator_id=seeded_creator.id, post_id=p_old.id, text="I recommend X",
                topic="supps", posted_at=p_old.posted_at)
    new = Claim(creator_id=seeded_creator.id, post_id=p_new.id, text="I recommend Y",
                topic="supps", posted_at=p_new.posted_at)
    session.add_all([old, new])
    session.flush()
    supersede(session, old, new)
    assert old.validity == ClaimValidity.superseded
    assert old.superseded_by == new.id


def test_claim_freshness_surfaces_update(seeded_creator, session):
    p_old = _post(session, seeded_creator.id, "old advice", external="fo", days_ago=400)
    p_new = _post(session, seeded_creator.id, "new advice", external="fn", days_ago=1)
    new = Claim(creator_id=seeded_creator.id, post_id=p_new.id, text="now use Y",
                posted_at=p_new.posted_at)
    session.add(new)
    session.flush()
    old = Claim(creator_id=seeded_creator.id, post_id=p_old.id, text="use X",
                validity=ClaimValidity.superseded, superseded_by=new.id,
                posted_at=p_old.posted_at)
    session.add(old)
    session.flush()
    notes = claim_freshness(session, [p_old.id])
    assert notes and notes[0]["outdated"] == "use X"
    assert notes[0]["current"] == "now use Y"
    # no superseded claims among these posts → no notes
    assert claim_freshness(session, [p_new.id]) == []


def test_detect_contradictions_marks_superseded(seeded_creator, session):
    # the FakeLLM judge flags supersession on update markers ('no longer', 'instead')
    p_old = _post(session, seeded_creator.id, "x", external="dco", days_ago=400)
    p_new = _post(session, seeded_creator.id, "y", external="dcn", days_ago=1)
    session.add(Claim(creator_id=seeded_creator.id, post_id=p_old.id, posted_at=p_old.posted_at,
                      text="I recommend creatine monohydrate for everyone"))
    session.add(Claim(creator_id=seeded_creator.id, post_id=p_new.id, posted_at=p_new.posted_at,
                      text="I no longer recommend creatine monohydrate; use a blend instead"))
    session.flush()
    n = detect_contradictions(session, seeded_creator.id)
    assert n == 1
    old = session.scalar(select(Claim).where(Claim.post_id == p_old.id))
    assert old.validity == ClaimValidity.superseded


def test_enrich_extracts_claims(creator, session):
    from cci_workers.enrich import process_post

    post = _post(session, creator.id, "Eat two grams of protein per kilo to build muscle. "
                 "Train each muscle twice a week for best results.", external="enr-claim")
    session.commit()
    stats = process_post(post.id)
    assert stats["claims"] >= 1
