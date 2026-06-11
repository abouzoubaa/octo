"""Synthetic demo corpora for local development.

Lets you exercise the whole loop (search → answer card → radar) with fake
providers and no Instagram connection. Subjects map to the plan's early
high-repetition-question niches: `fitness` (coach) and `travel` (planner).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cci_core.db import session_scope
from cci_core.models import Comment, Post, Product, Transcript
from cci_core.privacy import pseudonymize
from cci_retrieval.indexer import index_post
from cci_retrieval.intent import detect_intent

FITNESS_POSTS = [
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

FITNESS_COMMENTS = [
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

FITNESS_PRODUCTS = [
    ("Whey protein powder", "https://example.com/aff/whey"),
    ("Meal prep containers", "https://example.com/aff/containers"),
]

TRAVEL_POSTS = [
    ("reel", "Tokyo on $60 a day — my exact budget breakdown: capsule hotel in Asakusa, "
             "7-Eleven breakfasts, standing sushi bars, and the ¥800 izakaya trick. "
             "Full itinerary on my page. #tokyo #budgettravel",
     "Here's the actual math: capsule hotel twenty-eight dollars a night, breakfast at "
     "seven eleven for three bucks, lunch is a standing sushi bar for nine, and dinner "
     "at a local izakaya around twelve. Trains, temples, and the rest is free walking."),
    ("reel", "How I find flights 70% cheaper — the 3 rules: book Tuesday to Thursday "
             "departures, use the whole-month view, and fly into the secondary airport. "
             "Comment FLIGHTS and I'll DM you my full checklist. #cheapflights #travelhacks",
     "Rule one, midweek departures are almost always cheaper than weekends. Rule two, "
     "open the whole month view and let the calendar tell you when to fly. Rule three, "
     "check the secondary airport — Milan Bergamo instead of Malpensa saved me ninety euros."),
    ("reel", "Carry-on only for 3 weeks — my full packing list: 5 tops, 3 bottoms, "
             "packing cubes, a travel adapter that does 4 countries, and merino socks "
             "you can wash in a sink. #packinglight #carryon",
     "Everything fits in a forty litre bag: five tops, three bottoms, one jacket, "
     "packing cubes to compress it all, the universal adapter, and merino socks — "
     "wash them in the sink, dry overnight, wear them for years."),
    ("image", "Hidden beaches of the Algarve 🇵🇹 — skip Benagil's crowds and drive 10 "
              "minutes to Praia da Marinha at 8am. Map pins saved in my highlight.", None),
    ("reel", "Schengen visa mistakes that get applications rejected — wrong travel "
             "insurance minimums, bank statements under 3 months, and booking flights "
             "before approval. #schengen #visatips",
     "Three killers: travel insurance below thirty thousand euro coverage, bank "
     "statements that don't go back three months, and non-refundable flights booked "
     "before the visa is approved. Use a hold reservation instead."),
]

TRAVEL_COMMENTS = [
    (0, "Where's the reel about Tokyo on a budget?"),
    (0, "How much did the whole week cost you?"),
    (0, "😍😍😍"),
    (1, "FLIGHTS"),
    (1, "Does the month view work on the app too?"),
    (2, "What size backpack is that?"),
    (2, "Can you do a winter version of this list?"),
    (3, "Is Praia da Marinha doable without a car?"),
    (4, "Which travel insurance do you actually use?"),
    (4, "Do bank statements need to be stamped?"),
]

TRAVEL_PRODUCTS = [
    ("Packing cubes set", "https://example.com/aff/packing-cubes"),
    ("Universal travel adapter", "https://example.com/aff/adapter"),
    ("Travel insurance (annual)", "https://example.com/aff/insurance"),
]

SUBJECTS: dict[str, tuple[list, list, list]] = {
    "fitness": (FITNESS_POSTS, FITNESS_COMMENTS, FITNESS_PRODUCTS),
    "travel": (TRAVEL_POSTS, TRAVEL_COMMENTS, TRAVEL_PRODUCTS),
}


def seed_demo(creator_id: str, subject: str = "fitness") -> dict:
    if subject not in SUBJECTS:
        raise ValueError(f"unknown subject '{subject}' — pick one of {sorted(SUBJECTS)}")
    posts_data, comments_data, products_data = SUBJECTS[subject]

    now = datetime.now(timezone.utc)
    stats = {"subject": subject, "posts": 0, "comments": 0, "chunks": 0, "products": 0}
    with session_scope() as session:
        for name, url in products_data:
            session.add(Product(creator_id=creator_id, name=name, affiliate_url=url, approved=True))
            stats["products"] += 1

        post_rows: list[Post] = []
        for i, (ptype, caption, transcript) in enumerate(posts_data):
            post = Post(
                creator_id=creator_id, platform="instagram", external_id=f"demo-{i}",
                type=ptype, caption=caption,
                permalink=f"https://instagram.com/p/demo{i}",
                posted_at=now - timedelta(days=30 * (len(posts_data) - i)),
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

        trigger = "FLIGHTS" if subject == "travel" else "PLAN"
        for post_idx, text in comments_data:
            intent = detect_intent(text, trigger_keywords=[trigger])
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
