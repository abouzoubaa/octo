"""YouTube ingestion — owned/authorized channels only (captions need edit rights)."""
from __future__ import annotations

import logging
import re

from sqlalchemy import select

from cci_core.config import get_settings
from cci_core.db import session_scope
from cci_core.models import Creator, OAuthToken, Post, Transcript
from cci_core.youtube import YouTubeClient

log = logging.getLogger(__name__)


def backfill_channel(creator_id: str) -> dict:
    stats = {"videos": 0, "captions": 0}
    with session_scope() as session:
        creator = session.get(Creator, creator_id)
        if creator is None or not creator.yt_channel_id:
            raise RuntimeError("Creator missing or no YouTube channel configured")
        token = session.scalar(
            select(OAuthToken).where(
                OAuthToken.creator_id == creator.id, OAuthToken.platform == "youtube"
            )
        )
        client = YouTubeClient(
            api_key=get_settings().yt_api_key,
            oauth_token=token.access_token if token else None,
        )
        for item in client.iter_videos(creator.yt_channel_id):
            video_id = item["contentDetails"]["videoId"]
            snippet = item["snippet"]
            post = session.scalar(
                select(Post).where(
                    Post.creator_id == creator.id,
                    Post.platform == "youtube",
                    Post.external_id == video_id,
                )
            )
            if post is None:
                post = Post(creator_id=creator.id, platform="youtube", external_id=video_id)
                session.add(post)
            post.type = "video"
            post.caption = f"{snippet.get('title', '')}\n\n{snippet.get('description', '')}".strip()
            post.permalink = f"https://www.youtube.com/watch?v={video_id}"
            stats["videos"] += 1
            if token and _ingest_caption(session, client, post, video_id):
                stats["captions"] += 1
            session.flush()
    return stats


def _ingest_caption(session, client: YouTubeClient, post: Post, video_id: str) -> bool:
    existing = session.scalar(select(Transcript).where(Transcript.post_id == post.id))
    if existing is not None:
        return False
    try:
        captions = client.list_captions(video_id)
        if not captions:
            return False
        srt = client.download_caption(captions[0]["id"])
    except Exception as exc:
        log.warning("caption fetch failed for %s: %s", video_id, exc)
        return False
    segments = parse_srt(srt)
    session.add(
        Transcript(
            post_id=post.id,
            source="yt_caption",
            text=" ".join(s["text"] for s in segments),
            segments=segments,
        )
    )
    return True


_SRT_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(srt: str) -> list[dict]:
    """Minimal SRT → [{start, end, text}] parser."""
    segments: list[dict] = []
    for block in re.split(r"\n\s*\n", srt.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        ts_line = next((ln for ln in lines if "-->" in ln), None)
        if not ts_line:
            continue
        times = _SRT_TS.findall(ts_line)
        if len(times) < 2:
            continue
        start = _to_seconds(times[0])
        end = _to_seconds(times[1])
        text_lines = lines[lines.index(ts_line) + 1 :]
        text = " ".join(text_lines).strip()
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return segments


def _to_seconds(parts: tuple[str, str, str, str]) -> float:
    h, m, s, ms = (int(p) for p in parts)
    return h * 3600 + m * 60 + s + ms / 1000.0
