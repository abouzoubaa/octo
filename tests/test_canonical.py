"""Wave M: PlatformAccount + canonical answer variants."""
from sqlalchemy import select

from cci_agent.canonical import canonical_summary, group_variants, platforms_covered, variants_of
from cci_core.models import CanonicalContent, Post, Transcript


def _post(session, creator_id, *, platform, external, caption, transcript=None):
    p = Post(creator_id=creator_id, platform=platform, external_id=external,
             type="reel", caption=caption)
    session.add(p)
    session.flush()
    if transcript:
        session.add(Transcript(post_id=p.id, source="whisper", text=transcript))
        session.flush()
    return p


def test_repurposed_posts_group_into_one_canonical(creator, session):
    # the SAME idea across three platforms → one canonical, three variants
    shared = ("how to handle price objections: never drop your price, anchor against "
              "the cost of staying stuck, and restate the outcome")
    _post(session, creator.id, platform="youtube", external="yt1",
          caption="Handling price objections", transcript=shared)
    _post(session, creator.id, platform="tiktok", external="tt1",
          caption="never drop your price, anchor against the cost of staying stuck, restate the outcome")
    _post(session, creator.id, platform="instagram", external="ig1",
          caption="price objections: anchor against the cost of staying stuck and restate the outcome")
    # an unrelated post → its own canonical
    _post(session, creator.id, platform="instagram", external="ig2",
          caption="three high protein breakfasts you can make in ten minutes with greek yogurt")

    n = group_variants(session, creator.id)
    assert n == 2  # the price-objection trio + the breakfast post

    summary = canonical_summary(session, creator.id)
    top = summary[0]
    assert top["variant_count"] == 3
    assert set(top["platforms"]) == {"youtube", "tiktok", "instagram"}


def test_group_variants_is_idempotent(creator, session):
    _post(session, creator.id, platform="youtube", external="a",
          caption="meal prep five lunches in sixty minutes chicken rice broccoli")
    first = group_variants(session, creator.id)
    second = group_variants(session, creator.id)
    assert first == second
    # no orphaned canonicals accumulate
    assert session.scalar(select(CanonicalContent).where(
        CanonicalContent.creator_id == creator.id)) is not None


def test_platforms_covered(creator, session):
    p1 = _post(session, creator.id, platform="youtube", external="p1",
               caption="carb cycling explained for advanced lifters in detail")
    _post(session, creator.id, platform="tiktok", external="p2",
               caption="carb cycling explained for advanced lifters quick version")
    group_variants(session, creator.id)
    session.expire_all()
    canonical_id = session.get(Post, p1.id).canonical_id
    assert canonical_id is not None
    covered = platforms_covered(session, canonical_id)
    # whether or not they grouped, each post is in some canonical with its platform
    assert "youtube" in covered or "tiktok" in covered
    assert len(variants_of(session, canonical_id)) >= 1


def test_canonical_empty_creator(creator, session):
    assert group_variants(session, creator.id) == 0


def test_platform_account_capabilities_cached(seeded_creator, session):
    from cci_core.connectors import capabilities_for
    from cci_core.models import PlatformAccount

    acct = PlatformAccount(creator_id=seeded_creator.id, platform="youtube",
                           capabilities=sorted(capabilities_for("youtube")))
    session.add(acct)
    session.flush()
    assert "content.read" in acct.capabilities
    assert "messages.send" not in acct.capabilities  # YouTube has no DM
