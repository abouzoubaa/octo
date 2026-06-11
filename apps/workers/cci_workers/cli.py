"""Operator CLI — manual onboarding is the v1 flow (plan: "manual first").

Usage:
  cci-ingest create-creator <handle> "<display name>" [--ig-user-id ID]
  cci-ingest set-token <handle> instagram <access_token>
  cci-ingest backfill <handle>            # full IG history: posts + comments
  cci-ingest backfill-youtube <handle>
  cci-ingest process <handle>             # transcribe/OCR/enrich/index pending posts
  cci-ingest radar <handle> [--backlog]   # build evidence cards (cold start: --backlog)
  cci-ingest digest <handle>              # render + send the weekly digest
  cci-ingest seed-demo <handle>           # tiny synthetic corpus for local dev
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from cci_core.db import session_scope
from cci_core.models import Creator, CreatorStatus, OAuthToken


def _get_creator(session, handle: str) -> Creator:
    creator = session.scalar(select(Creator).where(Creator.handle == handle))
    if creator is None:
        print(f"creator '{handle}' not found", file=sys.stderr)
        raise SystemExit(1)
    return creator


def main() -> None:
    parser = argparse.ArgumentParser(prog="cci-ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create-creator")
    p.add_argument("handle")
    p.add_argument("display_name")
    p.add_argument("--ig-user-id", default=None)
    p.add_argument("--yt-channel-id", default=None)

    p = sub.add_parser("set-token")
    p.add_argument("handle")
    p.add_argument("platform", choices=["instagram", "youtube"])
    p.add_argument("token")

    for name in ("backfill", "backfill-youtube", "process", "digest"):
        p = sub.add_parser(name)
        p.add_argument("handle")

    p = sub.add_parser("seed-demo")
    p.add_argument("handle")
    p.add_argument("--subject", default="fitness", choices=["fitness", "travel"])

    p = sub.add_parser("radar")
    p.add_argument("handle")
    p.add_argument("--backlog", action="store_true")

    args = parser.parse_args()

    if args.cmd == "create-creator":
        with session_scope() as session:
            creator = Creator(
                handle=args.handle, display_name=args.display_name,
                ig_user_id=args.ig_user_id, yt_channel_id=args.yt_channel_id,
                status=CreatorStatus.active,
            )
            session.add(creator)
            session.flush()
            print(f"created creator {creator.id} → /{creator.handle}")
        return

    with session_scope() as session:
        creator = _get_creator(session, args.handle)
        creator_id = creator.id

    if args.cmd == "set-token":
        with session_scope() as session:
            existing = session.scalar(
                select(OAuthToken).where(
                    OAuthToken.creator_id == creator_id, OAuthToken.platform == args.platform
                )
            )
            if existing:
                existing.access_token = args.token
            else:
                session.add(OAuthToken(creator_id=creator_id, platform=args.platform,
                                       access_token=args.token))
        print("token stored")
    elif args.cmd == "backfill":
        from cci_workers.ingest_instagram import backfill_creator

        print(backfill_creator(creator_id))
    elif args.cmd == "backfill-youtube":
        from cci_workers.ingest_youtube import backfill_channel

        print(backfill_channel(creator_id))
    elif args.cmd == "process":
        from cci_workers.enrich import process_all_pending

        print(f"processed {process_all_pending(creator_id)} posts")
    elif args.cmd == "radar":
        from cci_workers.radar import build_radar

        print(f"created {build_radar(creator_id, backlog=args.backlog)} evidence cards")
    elif args.cmd == "digest":
        from cci_workers.digest import render_digest

        print(render_digest(creator_id) or "(no cards this week)")
    elif args.cmd == "seed-demo":
        from cci_workers.seed import seed_demo

        print(seed_demo(creator_id, subject=args.subject))


if __name__ == "__main__":
    main()
