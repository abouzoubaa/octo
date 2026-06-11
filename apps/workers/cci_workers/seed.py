"""Synthetic demo corpus for local development — a fitness-coach creator.

Lets you exercise the whole loop (search → answer card → radar) with fake
providers and no Instagram connection.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cci_core.db import session_scope
from cci_core.models import Comment, Post, Product, Transcript
from cci_core.privacy import pseudonymize
from cci_retrieval.indexer import index_post
from cci_retrieval.intent import detect_intent

POSTS = [
    ("reel", "3 high-protein breakfasts you can make in under 10 minutes — no eggs needed! "
             "Greek yogurt parfait with whey, cottage cheese toast with hemp seeds, and my "
             "famous protein oats. Save this for busy mornings. #highprotein #breakfast",
     "So the first one is a greek yogurt parfait, you just layer yogurt, a scoop of whey "
     "and berries. Second, cottage cheese on sourdough with hemp seeds, about thirty grams "
     "of protein. Third, overnight protein oats: oats, casein, almond milk, done."),
    ("reel", "How to handle price objections when selling your coaching — the exact script "
             "I use. Stop discounting, start reframing value. #salestips #coaching",
     "When someone says it's too expensive, never drop your price. Ask them: expensive "
     "compared to what? Anchor against the cost of staying stuck, then restate the outcome."),
    ("reel", "My full push day routine — chest, shoulders, triceps. Beginner friendly, "
             "45 minutes. Comment PLAN and I'll send it to you! #pushday #workout",
     "We start with flat barbell bench, four sets of eight. Then incline dumbbell press, "
     "seated shoulder press, lateral raises, and finish with rope pushdowns."),
    ("image", "Meal prep Sunday! Five lunches in 60 minutes: chicken, rice, broccoli with "
              "three different sauces so you never get bored. Containers linked in bio.", None),
    ("reel", "Why you're not losing fat in a calorie deficit — the 4 mistakes I see every "
             "week: weekend overeating, liquid calories, underestimating portions, and "
             "too little protein. #fatloss #nutrition",
     "Mistake one: you're only in a deficit Monday to Friday. Mistake two: lattes and "
     "juices count. Mistake three: weigh your food for two weeks. Mistake four: protein "
     "keeps you full — aim for two grams per kilo."),
]

COMMENTS = [
    (0, "What can I eat before work that isn't eggs?"),
    (0, "Where's the post about protein oats?"),
    (0, "🔥🔥🔥"),
    (1, "How do I respond when they ghost me after the price?"),
    (1, "This is gold, thank you!"),
    (2, "PLAN"),
    (2, "Can beginners do this twice a week?"),
    (3, "Which containers do you use?"),
    (4, "How much protein should I eat to lose fat?"),
    (4, "What about weekends, any tips?"),
]

PRODUCTS = [("Whey protein powder", "https://example.com/aff/whey"),
            ("Meal prep containers", "https://example.com/aff/containers")]


def seed_demo(creator_id: str) -> dict:
    now = datetime.now(timezone.utc)
    stats = {"posts": 0, "comments": 0, "chunks": 0, "products": 0}
    with session_scope() as session:
        for name, url in PRODUCTS:
            session.add(Product(creator_id=creator_id, name=name, affiliate_url=url, approved=True))
            stats["products"] += 1

        post_rows: list[Post] = []
        for i, (ptype, caption, transcript) in enumerate(POSTS):
            post = Post(
                creator_id=creator_id, platform="instagram", external_id=f"demo-{i}",
                type=ptype, caption=caption,
                permalink=f"https://instagram.com/p/demo{i}",
                posted_at=now - timedelta(days=30 * (len(POSTS) - i)),
            )
            session.add(post)
            session.flush()
            if transcript:
                session.add(Transcript(
                    post_id=post.id, source="whisper", text=transcript,
                    segments=[{"start": 0.0, "end": 30.0, "text": transcript}],
                ))
            post_rows.append(post)
            stats["posts"] += 1

        for post_idx, text in COMMENTS:
            intent = detect_intent(text, trigger_keywords=["PLAN"])
            session.add(Comment(
                creator_id=creator_id, post_id=post_rows[post_idx].id,
                external_id=f"demo-c-{stats['comments']}",
                author_pseudonym=pseudonymize(f"fan{stats['comments']}", creator_id),
                text=text, created_at=now - timedelta(days=stats["comments"]),
                is_question=intent.intent == "question", intent=intent.intent,
            ))
            stats["comments"] += 1

        for post in post_rows:
            stats["chunks"] += index_post(session, post)
    return stats
