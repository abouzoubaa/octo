"""Canonical Answer Objects (Wave M): group repurposed posts as variants of ONE idea.

Creators publish the same idea as a YouTube video, three TikToks, a Reel, a
newsletter. Counting those as five independent answers is a correctness bug — and
"Sift & Shift" (answered on platform A, missing on platform B) needs to know they're
variants. We group by transcript/caption embedding similarity (+ shared URLs) and
attach each post to a CanonicalContent, then expose which platforms a canonical covers.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.models import CanonicalContent, Post, Transcript
from cci_providers import get_embedding_provider

SIM_THRESHOLD = 0.62  # cosine over combined caption+transcript text


def _post_text(session: Session, post: Post) -> str:
    parts = [post.caption or ""]
    t = session.scalar(select(Transcript).where(Transcript.post_id == post.id))
    if t:
        parts.append(t.text)
    return "\n".join(p for p in parts if p.strip())


def group_variants(session: Session, creator_id: str) -> int:
    """Cluster the creator's posts into Canonical Answer Objects. Idempotent: re-runs
    re-cluster from scratch. Returns the number of canonical objects."""
    posts = session.scalars(
        select(Post).where(Post.creator_id == creator_id, Post.status == "active")).all()
    texts = [(p, _post_text(session, p)) for p in posts]
    texts = [(p, t) for p, t in texts if t.strip()]
    if not texts:
        return 0

    vectors = np.array(get_embedding_provider().embed([t for _, t in texts]), dtype=float)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms

    # greedy single-link clustering by cosine similarity
    n = len(texts)
    cluster_of = [-1] * n
    clusters: list[list[int]] = []
    for i in range(n):
        if cluster_of[i] != -1:
            continue
        cid = len(clusters)
        clusters.append([i])
        cluster_of[i] = cid
        for j in range(i + 1, n):
            if cluster_of[j] == -1 and float(vectors[i] @ vectors[j]) >= SIM_THRESHOLD:
                cluster_of[j] = cid
                clusters[cid].append(j)

    # clear prior grouping for these posts, then (re)build canonical objects
    session.execute(
        select(CanonicalContent).where(CanonicalContent.creator_id == creator_id))
    for p in posts:
        p.canonical_id = None
    # remove orphaned canonicals for this creator
    for c in session.scalars(
            select(CanonicalContent).where(CanonicalContent.creator_id == creator_id)):
        session.delete(c)
    session.flush()

    created = 0
    for members in clusters:
        rep_post, rep_text = max((texts[m] for m in members), key=lambda pt: len(pt[1]))
        canonical = CanonicalContent(
            creator_id=creator_id,
            title=(rep_post.caption or rep_text)[:256].split("\n")[0],
            topic=" ".join(rep_text.lower().split()[:4]),
        )
        session.add(canonical)
        session.flush()
        for m in members:
            texts[m][0].canonical_id = canonical.id
        created += 1
    session.flush()
    return created


def variants_of(session: Session, canonical_id: str) -> list[Post]:
    return list(session.scalars(select(Post).where(Post.canonical_id == canonical_id)))


def platforms_covered(session: Session, canonical_id: str) -> set[str]:
    return {p.platform for p in variants_of(session, canonical_id)}


def canonical_summary(session: Session, creator_id: str) -> list[dict]:
    """Each canonical answer with its variant count and the platforms it covers."""
    rows = session.scalars(
        select(CanonicalContent).where(CanonicalContent.creator_id == creator_id)).all()
    out = []
    for c in rows:
        variants = variants_of(session, c.id)
        out.append({
            "id": c.id, "title": c.title, "topic": c.topic,
            "variant_count": len(variants),
            "platforms": sorted({v.platform for v in variants}),
        })
    out.sort(key=lambda d: d["variant_count"], reverse=True)
    return out
