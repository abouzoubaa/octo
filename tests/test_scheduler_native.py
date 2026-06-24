"""Periodic native-connector sync enqueue (YouTube etc.; Instagram excluded).

enqueue_native_syncs is global (every active creator), so assertions are scoped to
this test's creator rather than the total count — other tests commit accounts too.
"""
from cci_core.models import OAuthToken, PlatformAccount
from cci_workers.scheduler import enqueue_native_syncs


class FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func_path, *args, **kwargs):
        self.calls.append((func_path, args))


def _connect(session, creator_id, platform, mode="native", with_token=True):
    session.add(PlatformAccount(creator_id=creator_id, platform=platform,
                                external_account_id=f"acct-{platform}", mode=mode))
    if with_token:
        session.add(OAuthToken(creator_id=creator_id, platform=platform, access_token="t"))


def _calls_for(q, creator_id):
    return [args for _f, args in q.calls if args and args[0] == creator_id]


def test_enqueues_authorized_youtube(creator, session):
    _connect(session, creator.id, "youtube")
    session.commit()
    q = FakeQueue()
    enqueue_native_syncs(q)
    assert _calls_for(q, creator.id) == [(creator.id, "youtube")]


def test_skips_instagram(creator, session):
    _connect(session, creator.id, "instagram")
    session.commit()
    q = FakeQueue()
    enqueue_native_syncs(q)
    assert _calls_for(q, creator.id) == []  # IG has its own incremental path


def test_skips_unauthorized_account(creator, session):
    _connect(session, creator.id, "youtube", with_token=False)  # connected, no token
    session.commit()
    q = FakeQueue()
    enqueue_native_syncs(q)
    assert _calls_for(q, creator.id) == []  # no OAuth token → not joined


def test_skips_import_mode_accounts(creator, session):
    _connect(session, creator.id, "tiktok", mode="import")  # archive, not native
    session.commit()
    q = FakeQueue()
    enqueue_native_syncs(q)
    assert _calls_for(q, creator.id) == []
