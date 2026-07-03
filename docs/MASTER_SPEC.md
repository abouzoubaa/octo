# Sift — Master Specification & Build Status

> **What this document is.** A faithful merge of the two source specifications —
> **Creator Content Intelligence — v1 spec (rev 6)** and **Sift — The Agent Layer
> (proposal, rev 2)** — combined into one reference, with everything that has since
> been added in the codebase, and a complete implementation-status matrix at the end
> (Part IV). Nothing from either source spec has been dropped; the two are reproduced
> in full (Parts I and II), Part III records what the build added beyond them, and
> Part IV maps every feature to its current build state.
>
> Sources: `creatorcontentintelligencev6.pdf`, `siftagentlayerproposalv2.pdf` (June 2026).

---

# Part I — Creator Content Intelligence · v1 Specification (rev 6)

*A search-first archive for each creator — powered by retrieval, amplified by
comment-to-DM, and monetized through demand intelligence. Standalone external
platform, field-checked against the 2026 Meta and YouTube API reality.*

## 00 · The thesis

The defensible product is not "AI search for Instagram posts." It is the **feedback
loop between audience demand and creator production**. Search gets users in,
comment-to-DM amplifies reach, and the searches and comments themselves become the
asset: insight into what an audience wants next. Built as **one loop**, not three
pillars. The search bar and the answer/chatbot are interfaces; **Demand Radar is the
monetizable asset**.

**Positioning.** Not "an AI chatbot trained on your content." Closer to **Search
Console for your creator business** — see what your audience wants, what your content
already answers, and what to make next. Ties to ROI: better content, fewer repeated
DMs, higher product/affiliate conversion, clearer content calendar.

## 01 · The product is one loop

A single cycle: (1) audience question → (2) grounded, cited answer → (3) deep link +
visit → (4) logged demand signal → (5) creator insight (Demand Radar) → (6) new
content → (7) better corpus → (8) better answers. Each turn makes the next stronger.

| Feature | Role in the loop | v1 form |
|---|---|---|
| **Search bar** | Interface — the front door (pull) | Plain-language search over the whole archive, with cited results |
| **AI answer / chatbot** | Interface — not the star | A grounded **answer card** (cited, bounded, with a "no strong answer" state) — not open-ended chat |
| **Demand Radar** | The monetizable asset | Audience demand turned into evidence cards: what they ask, what is covered, what to make next |

**Where this sits.** Delphi (AI clones; replays the archive, no demand intelligence) ·
ManyChat & co. (keyword → static link; ours reads the question, retrieves, answers,
feeds the radar) · Linktree/Beacons (a menu, not a search engine) · Instagram/Meta AI
(optimizes Meta's engagement, exposes no demand data). **The wedge is the loop
itself**: none connect what fans ask to what the creator makes next.

## 02 · Who it's for: the minimum viable creator

≥ **100 evergreen posts** with recurring answerable questions · **visible comment
demand** ("where's the post about X?") · ≥ one **monetizable path** (course, coaching,
product, affiliate, newsletter) · enough **trust** that followers ask for
recommendations · **connectable** (an account you own, or a creator willing to OAuth
in and hold a role for v1). Best early niches: high-repetition-question creators —
fitness, nutrition, travel, beauty/skincare, creator-business, language teachers,
productivity, B2B consultants. Avoid regulated / high-liability categories at first.

## 03 · Distribution: the link leads, comments amplify

**Primary channel — the direct link (front door):** bio link (IG allows up to 5) ·
a permanent **"Search" Highlight** (Story link sticker saved to a Highlight stays
clickable indefinitely) · a **search-first landing page** (opens on the search bar) ·
a **pinned reel** · built for the **in-app browser** (instant load, focused search box,
no login wall). The Highlight and pinned reel are audience-onboarding surfaces.

**Capture layer — comment-to-DM:** for passive/new viewers; a specific CTA ("Comment
PLAN and I'll send the exact routine") beats "ask me anything"; when retrieval
confidence is low, the DM **falls back to a friendly archive link** — never a shaky
answer in the creator's voice. An amplifier, not the front door. **Deep links** tie
the two together: the DM link opens the platform with the answer loaded, and those are
the same shareable URLs.

## 04 · Demand Radar, made concrete

Decision-ready: every insight is an **evidence card** turnable into a post idea in
under a minute — *Topic · Signal (e.g. 17 searches, 9 comments, +42% WoW) · Current
coverage · Audience language · Recommended content · Linked products · Confidence*.
**Cold start:** first cards come from the **historical comment backlog**. **Delivery:**
push a **weekly digest** (email or DM) — the radar comes to the creator.

## 05 · Retrieval is the hard part, not the chatbot

Lives or dies on: transcription & OCR coverage · chunking + metadata extraction ·
**citation accuracy** (a fluent answer that cites the wrong reel is brand risk) ·
ranking & reranking · a reliable **"no good answer found"** behaviour · freshness &
contradiction handling. **Two consequences:** (1) make **citation correctness a
first-class metric and a gate** — no comment-to-DM automation goes live until it
passes on a held-out set; (2) keep the **retrieval answer separate from the
creator-style answer** — correctness, citations, relevance first; voice second.

## 06 · Scope: ruthless for v1

**In scope:** the demand loop end-to-end · one owned account, every record
creator-scoped · link-first distribution + comment-to-DM capture · comments ingested
from day one · an evaluation harness (40–60 labelled questions) from week one ·
deletion / reindexing + an approval mode for DM · a light monetization hook (product
mentions → creator-approved affiliate links). **Out of scope (defer):** open-ended
chat · voice cloning / audio replies · full multi-tenant billing & self-serve
onboarding · per-creator custom domains · broad analytics dashboards & mobile apps ·
a dedicated vector DB (pgvector is plenty).

## 07 · Architecture and data flow

1. **Onboard** — connect the owned Business/Creator account via OAuth; create namespace + link.
2. **Ingest** — media, captions, metadata, comments from day one; download media; transcribe (Whisper); OCR.
3. **Enrich (LLM)** — summary, topics, keywords, product/location mentions; creator-scoped.
4. **Index** — chunk + embed into pgvector beside relational rows; design for deletion & reindex.
5. **Evaluate** — 40–60 labelled questions run on every OCR/chunking/embedding/reranking change; citation correctness gates DM automation.
6. **Serve** — search-first landing + grounded answer card on one hybrid retrieval layer; every result deep-linkable.
7. **Listen** — a Messaging API webhook receives comments; intent detection routes through the same retrieval layer.
8. **Respond** — public reply + a single private DM (answer + deep link); approval mode first; low-confidence → plain archive link.
9. **Learn** — every query/comment/click clusters into Demand Radar evidence cards.
10. **Monetize** — product mentions map to creator-approved affiliate links, surfaced on results and in answers.

**The data reality.** IG API with **Instagram Login** (Business/Creator, no Facebook
Page; scopes `instagram_business_basic/_manage_comments/_manage_messages/_content_publish`)
· **Standard Access** covers owned/app-role accounts (POC starts today); **App Review**
gates external creators — submit in parallel, request only scopes the demo uses ·
**private replies bounded**: one message per comment within 7 days, follow-ups only if
the person replies, ~200 DMs/hour/account cap · **comment reads paginated** (~50/page,
cursor-based, no timestamp filter — walk cursors, keep a watermark) · **do not scrape**
· **YouTube** easy only for owned/authorized channels (caption download needs edit
permission).

## 08 · Recommended stack

Ingestion (IG API via Instagram Login + YouTube Data API) · Transcription/OCR
(faster-whisper + PaddleOCR behind one provider interface) · Enrichment + answer card
(any frontier LLM behind a thin provider interface, LiteLLM-style) · Embeddings (one
versioned model at a time; model+version+dims per chunk) · Storage + vectors
(PostgreSQL + pgvector) · Search (**hybrid: Postgres full-text + pgvector cosine,
reranked**) · Event analytics (PostHog or plain Postgres event tables) · Evaluation
harness · Comment/DM loop (IG Messaging API + webhook) · Per-creator routing
(path-based namespaces `yourapp.com/<creator>`) · Backend/jobs (**Python FastAPI +
RQ/Celery**; Rust for hot paths) · Frontend (**Qwik / Qwik City**) · Hosting
(containers, managed/self-hosted Postgres, S3-compatible storage).

**Portability principles (non-negotiable):** model-agnostic (every AI call behind a
provider interface) · embedding swaps are planned re-embed events · infra-agnostic
(Docker, plain Postgres+pgvector, S3) · no silent lock-in.

## 09 · Build sequence (≈ ten weeks)

| Phase | Focus | Exit / gate |
|---|---|---|
| 0 · Unblock data | Create app; connect owned account (Standard Access); submit App Review in parallel; YouTube key | Media + comments pullable same week |
| 1 · Ingest + evaluate (wk 1–2) | Ingest IG (+ owned YouTube), transcribe, OCR, enrich, embed, store citations; stand up labelled set | 100+ items indexed; eval harness running |
| 2 · Search-first link (wk 3–4) | One search box, cited result cards, deep links | Beats native IG search on the labelled set |
| 3 · Demand Radar (wk 5–6) | Cluster comments + searches into evidence cards | Creator marks which of 10 they'd make |
| 4 · Answer card (wk 7) | Grounded, cited card with "no strong answer" | Citation correctness passes the gate |
| 5 · Comment-to-DM (wk 8–9) | Few posts, specific triggers, value-first DM, approval mode | A real comment yields a compliant auto-DM |
| 6 · Monetization proof (wk 10) | Map product mentions to creator-approved links; track clicks | ≥ 1 live affiliate link; click data |

## 10 · Metrics that matter

Ingestion (% posts with usable caption/transcript/OCR) · Search quality (top-3
retrieval accuracy on labelled questions) · Answer quality (citation correctness,
unsupported-claim rate) · Audience UX (search-to-click, repeat searches,
time-to-answer) · Deep links (share/open rate per URL) · Comment-to-DM (trigger rate,
DM send success, deep-link click) · Demand Radar (% insights marked "useful") ·
Creator ROI (posts from insights, affiliate/product clicks, support time saved) ·
Safety ("no answer found" accuracy, hallucination rate, stale-citation rate).
**The two early metrics that decide it:** can a real follower find the right old post
faster than through Instagram? Does the creator act on Demand Radar without being
persuaded?

## 11 · The moat: creator demand memory

Embeddings are not a moat. The moat is **creator demand memory** — knowing what a
specific creator's audience keeps asking, what content satisfies it, which gaps convert
into successful posts, and which products map to those needs. Compounds with audience
language, content-gap history, post-performance outcomes, affiliate mappings, and
shared deep links.

## 12 · Risks and how to de-risk

API/App Review dependency (run POC on Standard Access; submit review day one; ingest
owned YouTube in parallel) · Weak creator pull (make it part of the weekly content
workflow; require Highlight + pinned reel) · Insufficient audience usage (ingest
comments from day one) · Hallucination/brand damage (strict grounding, visible
citations, citation gate before automation) · Overbuilding the chatbot (cited answer
card on proven retrieval, not open chat) · DM-automation compliance (official API
only; one value-first reply per comment within 7 days; never unsolicited) · Meta ships
it natively (own the cross-platform corpus, creator-side demand intelligence, the
affiliate/deep-link layer — the relationship is the account, not the API) ·
Privacy/GDPR (keep audience queries pseudonymous & aggregate; ship a privacy policy +
deletion path before public launch).

## 13 · Monetization: surfaces and pricing

Every search and DM'd question is **declared intent** — monetize the intent, not the
tool. Affiliate mapping is the v1 proof of ROI; the rest are an expansion ladder on the
existing retrieval layer.

| Surface | What it does | Tag |
|---|---|---|
| Email capture bridge | "Get the full checklist by email" on answer cards and in DMs | v1.5 |
| Storefront search | Premium content marked; teaser + route to checkout | v1.5 |
| Embeddable widget | The search box on the creator's site + a "Powered by" footer | v1.5 |
| Insight → draft generator | One tap on a Radar card → reel script, hook, caption | v2 |
| Sponsor pitch reports | Auto one-pager from Radar data ("412 questions about creatine") | v2 |
| Paid Q&A on "no answer" | The failure state becomes revenue; the question still feeds Radar | v2 |

**Pricing tiers (hypothesis):** Free (public search page + "Powered by") · Creator
(~$49–99/mo: Demand Radar weekly digest, grounded answer card, affiliate mapping, email
capture) · Pro (~$149–299/mo: comment-to-DM automation, storefront search, draft
generator, sponsor reports, multi-platform ingestion). Manual onboarding first.

## 14 · Build / don't-build decision

**Build if:** a real follower finds old content faster than native IG search · the
creator marks Radar insights genuinely useful and acts · comment-to-DM produces
incremental visits without compliance problems. **Pause/pivot if:** search usage stays
low after promotion · insights feel obvious · the system cannot reliably cite the right
source.

> *The company is the loop between what an audience asks and what a creator makes next.
> Search gets them in, comment-to-DM amplifies, and demand intelligence is what
> creators pay for.*

---

# Part II — Sift, the Agent Layer (proposal, rev 2)

*The full feature blueprint — from a search tool to a chief of staff for creators.
Additive to the v1 spec; v1 ships unchanged; every feature phased v1 → v3.*

## 00 · The shift

v1 *shows* a creator what their audience wants; an agent *acts* on it — recommends,
drafts, replies, and closes the loop, always with approval. A creator's day comes down
to three recurring questions, which the agent answers continuously: **What does my
audience want?** (§03) · **What should I make next?** (§04) · **What should I reply to
right now?** (§05). Three more domains run the business around the loop: Monetization
(§06), Brand & Reputation (§07), Growth & Strategy (§08), Operations & Ecosystem (§09).
The missing pieces over v1 are **agency** and **proactivity**.

## 01 · The agent loop

**Listen** (capture every search & comment — v1) → **Sift** (cluster intent, strip
noise, spot trends) → **Serve** (grounded cited answer to the fan — v1) → **Advise**
(turn demand into a drafted recommendation) → **Execute** (draft content, replies,
links for one-tap approval) → **Close** (tell the original asker their question was
answered, and measure whether it worked). The loop closes when the asker hears back,
seeding the next question.

## 02 · Foundations the agent learns from

| Feature | What it does | Tag |
|---|---|---|
| **Demand clustering & dedup** | Merges semantically similar questions into one cluster ("142 asked this"). Underpins every radar view | v1 |
| **Voice memory** | Stores approved replies/hooks and draft edits so generated content stays on-voice | v1 capture |
| **Offer-awareness** | Creator tags products/offers/campaigns; Sift routes every CTA/affiliate suggestion to the right one | v1.5 |
| **Rules & preferences** | Tone, taboo topics, escalation rules, monetization priorities | v1.5 |
| **Demand-item state machine** | Each "useful" card moves Idea → Drafting → Published → Loop-closed | v1 |
| **Intent / outcome event log** | Logs who asked what, what was served, what the creator did, what happened next | v1 |

> **The only thing that touches v1:** build the state machine and the intent/outcome
> event log into the v1 schema now, plus start capturing demand clusters and voice
> examples. Cheap, and the difference between a feature set and a rebuild.

## 03 · Audience & demand intelligence

| Feature | What it does | Tag |
|---|---|---|
| **The Briefing** | A pushed digest: top signals with ready hooks in voice, a re-promotion pick, open gaps, trend/resurfacing alerts, urgent inbox replies, one fully drafted post | v1.5 |
| **Content gap map** | What the creator has answered well / partially / contradicted / never addressed — a strategic map | v1.5 |
| **Persona segmentation** | Clusters the audience by behaviour, gives each segment its own demand feed, flags one-group bias | v2 |
| **Sentiment & emotion** | Reads emotional tenor (anxiety, confusion, excitement, frustration) | v2 |
| **Trend detection** | Rising themes and old posts suddenly searched; weekly, with spike alerts above a threshold | v2 |
| **Cross-platform demand synthesis** | Ingests newsletter replies, forwarded DMs, podcast comments; answers "asked everywhere?" and "asked only on YouTube?" | v2 |
| **Competitor demand radar** | Opt-in, aggregate: how a similar creator answered the same demand | v3 |

## 04 · Content production

| Feature | What it does | Tag |
|---|---|---|
| **Content briefs** | One-page brief from a demand cluster: exact phrasing, coverage gaps, hook + CTA, source-post links | v1.5 |
| **Draft generator (script + hooks)** | Ready-to-shoot reel script + hooks grounded in the creator's content and audience's literal words | v1.5 |
| **Creator recall search** | Creator-only "where did I say that?" — exact sentence, link, reuse ideas | v1.5 |
| **Multi-format repurposing + Sift & Shift** | One piece → IG carousel, X thread, newsletter, TikTok hooks; "Sift & Shift" migrates a YouTube-only topic to an IG carousel | v2 |
| **Series builder** | Repeated demand → a planned arc: parts, FAQ post, DM follow-up, offer tie-in | v2 |
| **Performance prediction** | Scores a draft against the creator's own top-10% structural patterns | v3 |
| **Content calendar / planner** | Cadence-aware queue: format per topic, posting window, over-saturation flags, reactive window | v3 |
| **Thumbnail & visual intelligence** | Thumbnail concepts + scoring against historical CTR | v3 |

## 05 · Engagement & inbox

| Feature | What it does | Tag |
|---|---|---|
| **Intent-labelled queue** | One prioritised queue: content request, purchase intent, support, collab lead | v1.5 |
| **Bounded clarifying question** | One either/or to disambiguate a vague search — not open chat | v1.5 |
| **No-answer waitlist** | Low-confidence → "want a heads-up when Alex covers this?" Captures an email, feeds the gap map | v1.5 |
| **Saved playbooks** | "When I get this kind of question, do this" templates | v1.5 |
| **Reply assistant** | Drafts public/DM replies + follow-ups, grounded in citations, in approved tone | v2 |
| **Agentic DM (approval mode)** | Multi-turn DM within Meta's one-message/7-day limit; bulk-approve daily; "always approve this type" | v2 |
| **Community delegation** | When a follower answered well, like their comment instead of spending the single-DM quota | v2 |
| **"Not now, but…" queue** | Defer a valid question; Sift holds it, drafts when due, re-contacts the asker within limits | v2 |
| **Loop-Closer** | When the creator publishes what an asker requested, notify the original asker (compliant channels only) | v2 |

## 06 · Monetization & revenue

| Feature | What it does | Tag |
|---|---|---|
| **Auto-affiliate injection** | At caption time, append the mapped affiliate link + UTM | v1.5 |
| **Offer-aware CTAs** | Attach the right current offer/affiliate CTA to answers and recommendations | v1.5 |
| **Affiliate optimisation** | A/B-test placement, anchor text, pairings; surface winners | v2 |
| **Sponsor matchmaker & pitch** | Demand → proof for brands; match interests to programs; draft a pitch in the audience's language | v2 |
| **Dynamic pricing & offer insights** | Pre-purchase questions, objections, bundle signals, price-sensitivity by segment | v3 |
| **Revenue forecasting & goals** | Project income across affiliate/products/sponsorships; flag off-track; turn a goal into a plan | v3 |
| **Brand partnership portal** | A two-sided surface where brands discover creators by audience profile | v3 · scale |

## 07 · Brand & reputation

| Feature | What it does | Tag |
|---|---|---|
| **Crisis / sentiment-shift detection** | Watch for negative-sentiment spikes, controversy, external mentions; alert early with a response framework | v2 |
| **Voice consistency scoring** | Score new content (esp. from contractors) against the voice model, with deviation notes | v2 |
| **Plagiarism / unauthorised-use monitoring** | Detect reposts/scrapers; offer takedown + outreach | v3 |

## 08 · Growth & strategy

| Feature | What it does | Tag |
|---|---|---|
| **Content strategy advisor** | Strategic questions grounded in Sift's data: expand vs double down, segment growth, evergreen vs trend balance | v2 |
| **Peer benchmarking** | Contextualise against peers (opt-in/aggregate): what top performers cover that they don't | v3 |
| **Education & skill planning** | Skill gaps from performance patterns; a 1/3/5-year development plan | v3 |

## 09 · Operations & ecosystem

| Feature | What it does | Tag |
|---|---|---|
| **Task / project integration** | Radar card → tracked task synced with Notion/Asana/Linear; completion links to the published post | v3 |
| **Customer CRM** | Unified customer profiles for paid products; lifecycle marketing | v3 |
| **Team & role-based access** | Owner / content-creator / analytics-only (VA) / contractor roles + approval workflows + audit trail | v3 |
| **Creator marketplace** | Collaboration discovery by audience overlap; creator-to-creator affiliate | v3 · scale |
| **Public API & dev ecosystem** | An API for third-party integrations on Sift's intelligence layer | v3 · scale |

## 10 · What to avoid (and why)

| Feature | Why excluded | Tag |
|---|---|---|
| **Open-ended chat** | Hallucination/brand risk; the bounded answer card captures the value safely | avoid |
| **Auto-posting without approval** | Too much trust too early; approval mode stays default through v3 | avoid |
| **Real-time trend alerts** | Low signal-to-noise for one creator; revisit above a query-volume threshold | threshold |
| **Native video editing** | Scope creep; production stays at scripts/hooks/clip references | avoid |
| **Cross-platform identity resolution** | Privacy-radioactive under GDPR; do topic-level synthesis, never individual matching | privacy |

**Gated on scale, not the calendar:** the brand partnership portal, creator
marketplace, and public API only matter at multi-creator scale — pursue once the
single-creator loop is proven and repeatable.

## 11 · Guardrails that carry over

Retrieval correctness is **the gate** (citation correctness on a held-out set before
any automation) · **voice is a post-retrieval rewrite** (rewrite a correct cited
answer; never generate novel claims) · **approval mode by default** · **DM limits
shape the Close step** (one creator-initiated message per comment within 7 days) ·
**privacy stays aggregate and opt-in** (pseudonymous & clustered demand; opt-in
cross-platform/competitor; deletion path + policy before launch).

## 12 · Positioning

From "Search Console for your creator business" (passive, analytical) to **"Your AI
chief of staff — Sift listens to your audience, tells you what they want, and helps
you build it."** Short: *"The memory and the roadmap for your creator business."*

## 13 · Sequencing

| Phase | What lands |
|---|---|
| **v1 · unchanged** | Search-first archive, Demand Radar, comment-to-DM. Groundwork: state machine, intent/outcome log, demand clustering, voice-memory capture |
| **v1.5 · assist** | The Briefing, content gap map, content briefs, draft + hook generator, creator recall, bounded clarifying, no-answer waitlist, intent-labelled inbox, saved playbooks, auto-affiliate, offer-aware CTAs, offer/rules tagging |
| **v2 · agent** | Reply assistant, agentic DM, community delegation, Loop-Closer, "not now" queue, persona segmentation, sentiment, trend detection, cross-platform synthesis, repurposing + Sift & Shift, series builder, sponsor matchmaker + pitch, affiliate optimisation, strategy advisor, crisis detection, voice scoring |
| **v3 · scale** | Performance prediction, content calendar, thumbnail intelligence, dynamic pricing, revenue forecasting, customer CRM, task/PM integration, team/roles, peer benchmarking, education/skill planning, competitor radar, plagiarism monitoring, brand portal, marketplace, public API |

---

# Part III — What the build added (beyond the two specs)

The implementation kept the entire spec above and went further on three axes the
source docs only gestured at. These are **built and tested**, not planned.

## A · Cross-platform connector framework

The specs assume Instagram (+ owned YouTube). The build generalised this into a
**connector contract + capability registry** so product logic asks what an account can
*do* rather than assuming a uniform loop:

- **Capabilities** — `content.read`, `media.read`, `captions.read`, `comments.read`,
  `comments.reply`, `messages.send`, `demand.read`, `analytics.read`, `events.webhook`,
  `content.publish`, `deletions.receive`.
- **Native connectors** (injectable HTTP transport → tested against fakes, no network):
  **YouTube** (Data API v3 — uploads-playlist walk, comment threads, replies, both
  paginated, 403-resilient), **Instagram** (Graph API — media + comments backfill,
  capped cursor walk, replies), **TikTok** (Display API v2 — *archive* mode = content
  only, vs *full-loop* = comments + replies where approved; **per-account** capability
  via `PlatformAccount.full_loop`).
- **Demand sources** — newsletter / podcast / Discord as `demand.read`-only inputs that
  feed Demand Radar (this is the spec's §03 *cross-platform demand synthesis*, realised
  via an `ExternalSignal → radar` path).
- **`sync_native` worker** — maps any connector's output into Posts + Comments
  idempotently (PII-redacted, pseudonymised, question/sentiment-classified, per-item
  SAVEPOINT isolation), stamps `last_synced_at`. Driven **manually** ("Sync now"),
  **all-at-once** ("Sync all"), or **hourly** by the scheduler.
- **Canonical answers** (`CanonicalContent`) — variant grouping across platforms; the
  basis for **Sift & Shift** and per-platform demand segmentation
  (`everywhere` / `platform:x` / `search_only`).

## B · Demand-integrity & explainability (hardening the "asset")

- **Demand Integrity** — unique askers, organic vs CTA-prompted, persistence, sentiment,
  intent, **manipulation risk** (how inflatable), **exposure-normalized demand** (asks
  per 1k impressions).
- **Explainable Opportunity Score** — components exposed, not a black box.
- **Reconciliation** — every radar card classified against the creator's own archive:
  `well` / `partial` / `gap`, with the covering permalink surfaced ("you've already
  answered this — re-promote" vs "genuine gap — make it").
- **North-star metric** — closed loops / creator / week, broken down **made vs
  re-promoted**; **re-promote** is a second loop-closure path.
- **Versioned claim layer** (freshness/contradiction), **causal layer** (interventions,
  holdouts, baselines, confidence intervals, holdout lift), **trust firewall**
  (why-selected + disclosure flags), **Demand Certificate**, canonical knowledge
  endpoint.

## C · Productionisation & security

- SQLAlchemy 2.0 models, all creator-scoped; **Alembic** migrations 0001–0004;
  `EncryptedString` (Fernet/MultiFernet) for OAuth tokens; opt-in RLS.
- **Billing** — Plan enum (free/creator/pro), feature gating, quotas; Stripe behind an
  interface + offline fake. **AI cost metering** across agent generators with op tags +
  per-plan cost cap; a **separate anonymous-answer abuse ceiling** so the free answer
  card stays free but a fan page can't drive unbounded LLM cost.
- GDPR export/erase + PII redaction · **dedicated pseudonym secret** (decoupled from the
  admin token) · webhook idempotency + signature **fail-closed** in production ·
  **fail-closed boot** on insecure default secrets · **prompt-injection hardening**
  (untrusted audience text wrapped + guarded on every agent LLM call) · rate limiting ·
  RQ job reliability · **DM-dispatch advisory lock** (no double-send / cap-bypass).
- CI/CD + observability; k8s + Render deploy manifests.
- **Offline by default** — Fake providers for LLM/embeddings/transcription/OCR/rerank/
  billing, so the whole system runs and tests with no network or API keys.

## D · Surfaces

- **Fan pages** (Qwik, near-zero-JS) — search-first, grounded answer card, deep links.
- **Creator Studio** (Qwik SSR) — opportunity queue ranked by Opportunity Score,
  **filterable by platform × gap/answered**, with per-card actions (make / draft /
  series / re-promote / ignore); the **Platforms** page (connectors + capabilities,
  connection + last-synced status, Sync now / Sync all, canonical answers, Sift & Shift,
  per-platform top demand); Inbox, Drafts (deep-linked), Briefing, north-star breakdown.

## E · Test & quality posture

**311 Python tests** (against real Postgres + pgvector) + **9 frontend tests** (Vitest),
ruff-clean, four migrations applying cleanly, and a five-dimension adversarial code
review (security/tenancy, persistence/migrations, API surface, workers/connectors,
retrieval/agent) with all findings fixed.

---

# Part IV — Implementation status (every feature)

Legend: **✅ built** · **◑ partial / basic** · **⛔ not built (deferred)** ·
**🚫 deliberately avoided**.

## v1 spec (rev 6)

| § | Item | Status | Where / note |
|---|---|---|---|
| 01 | Search bar (hybrid, cited) | ✅ | `cci_retrieval` (FTS + pgvector + RRF + rerank) |
| 01 | Grounded answer card ("no strong answer") | ✅ | `answer.py` |
| 01 | Demand Radar (evidence cards) | ✅ | `radar.py`, `demand.py` |
| 03 | Search-first landing + deep links | ✅ | `apps/web` fan pages, `deep_links.py` |
| 03 | Comment-to-DM capture + low-confidence fallback | ✅ | `dm.py` (approval mode) |
| 04 | Cold start from comment backlog | ✅ | `build_radar(backlog=True)` |
| 04 | Weekly digest delivery | ✅ | `digest.py` + scheduler |
| 05 | Transcription / OCR / chunking / rerank | ✅ | providers + `cci_retrieval` |
| 05 | Citation correctness gate | ✅ | `cci_eval` harness (now fails closed on vacuous pass) |
| 06 | Eval harness (40–60 labelled) | ✅ | `cci_eval` |
| 06 | Deletion / reindex + approval mode | ✅ | `indexer.py`, GDPR, DM approval |
| 06 | Affiliate links (light monetization) | ✅ | products + affiliate redirect |
| 07 | Onboard→…→Monetize (10-step flow) | ✅ | end-to-end |
| 07 | Instagram Login / Standard Access / scopes | ◑ | client + OAuth flow built; **no live consent round-trip** (env-bound) |
| 08 | Hybrid search, Postgres+pgvector, Qwik, FastAPI+RQ | ✅ | as specified |
| 08 | Provider interfaces / portability principles | ✅ | `cci_providers` (all swappable, offline fakes) |
| 10 | Metrics + events | ✅ | `events.py`, metrics endpoints |
| 12 | Privacy/GDPR (pseudonymous, deletion, policy) | ✅ | `privacy.py`, `gdpr.py`, legal docs |
| 13 | Email capture bridge | ✅ | `WaitlistEntry` |
| 13 | Storefront search / embeddable widget | ⛔ | deferred (premarket) |
| 13 | Pricing tiers (free/creator/pro) | ✅ | `billing.py` Plan enum + gating |

## Agent layer (rev 2)

| § | Feature | Tag | Status | Where / note |
|---|---|---|---|---|
| 02 | Demand clustering & dedup | v1 | ✅ | `radar.py` |
| 02 | Voice memory | v1 | ✅ | `VoiceExample`, `capture_voice` |
| 02 | Offer-awareness | v1.5 | ✅ | `Offer`, offer-aware CTAs |
| 02 | Rules & preferences | v1.5 | ✅ | `CreatorRules` |
| 02 | Demand-item state machine | v1 | ✅ | `DemandState` + transitions |
| 02 | Permission ladder | — | ✅ | `permissions.py` — per-action levels, `GET/PUT /permissions`, pause switch |
| 02 | Intent / outcome event log | v1 | ✅ | `Outcome`, `Event` |
| 03 | The Briefing | v1.5 | ✅ | `briefing.py` |
| 03 | Content gap map | v1.5 | ✅ | `content_gap_map` + coverage/reconciliation |
| 03 | Persona segmentation | v2 | ✅ | `intelligence.py` |
| 03 | Sentiment & emotion | v2 | ✅ | `score_sentiment` |
| 03 | Trend detection | v2 | ✅ | `intelligence.py` (weekly; threshold-gated spikes) |
| 03 | Cross-platform demand synthesis | v2 | ✅ | demand sources + `ExternalSignal` → radar |
| 03 | Competitor demand radar | v3 | ◑ | `growth.competitor_radar` — opt-in gate + endpoint live; aggregates are placeholders pending a multi-creator panel |
| 04 | Content briefs | v1.5 | ✅ | `generate_brief` |
| 04 | Draft generator (script + hooks) | v1.5 | ✅ | `generate_draft` (cost-metered) |
| 04 | Creator recall search | v1.5 | ✅ | `creator_recall` |
| 04 | Multi-format repurposing + Sift & Shift | v2 | ✅ | `repurposing.py` |
| 04 | Series builder | v2 | ✅ | `build_series` (persists draft stubs) |
| 04 | Performance prediction | v3 | ◑ | `predict_performance` (basic; needs history to be reliable) |
| 04 | Content calendar / planner | v3 | ◑ | `content_calendar` (basic) |
| 04 | Thumbnail & visual intelligence | v3 | ◑ | `thumbnail_concepts` (concepts; no CTR model) |
| 05 | Intent-labelled queue | v1.5 | ✅ | `label_message`, `/inbox` |
| 05 | Bounded clarifying question | v1.5 | ✅ | `bounded_clarify` — in the public search response on no-strong-answer; fan page renders the either/or chips |
| 05 | No-answer waitlist | v1.5 | ✅ | `WaitlistEntry` + fan-page email form on no-strong-answer (shows cohort size) |
| 05 | Saved playbooks | v1.5 | ✅ | `Playbook` CRUD + `match_playbook` applied in the comment→DM pipeline (matched template, still approval mode) |
| 05 | Reply assistant | v2 | ◑ | `engagement.draft_reply` — drives the agentic-DM path (itself ◑); comment-DM uses the grounded answer card directly |
| 05 | Agentic DM (approval mode) | v2 | ◑ | `handle_dm_followup`, `can_auto_approve`, `bulk_approve` (thread dispatcher not wired) |
| 05 | Community delegation | v2 | ✅ | `delegation_candidate` — surfaced as a hint in the DM approval queue (the like itself is manual: no official comment-like API) |
| 05 | "Not now, but…" queue | v2 | ✅ | `defer_question`, `DeferredItem`, `due_deferrals` |
| 05 | Loop-Closer | v2 | ✅ | `close_loop` + re-promote/outcomes |
| 06 | Auto-affiliate injection | v1.5 | ✅ | `inject_affiliate` applied at draft approval (caption-time proxy — auto-posting is deliberately avoided) |
| 06 | Offer-aware CTAs | v1.5 | ✅ | offers → CTAs |
| 06 | Affiliate optimisation | v2 | ✅ | `affiliate_optimisation` |
| 06 | Sponsor matchmaker & pitch | v2 | ✅ | `sponsor_report` |
| 06 | Dynamic pricing & offer insights | v3 | ◑ | `pricing_insights` (basic) |
| 06 | Revenue forecasting & goals | v3 | ◑ | `revenue_forecast` (basic) |
| 06 | Brand partnership portal | v3·scale | ⛔ | deferred (scale-gated) |
| 07 | Crisis / sentiment-shift detection | v2 | ◑ | `brand.py` (sentiment-shift; no external-web watch) |
| 07 | Voice consistency scoring | v2 | ✅ | `brand.py` |
| 07 | Plagiarism / unauthorised-use monitoring | v3 | ◑ | `growth.plagiarism_scan` — real pgvector-similarity repost detector via endpoint; no external-web watch |
| 08 | Content strategy advisor | v2 | ✅ | `strategy_advisor` |
| 08 | Peer benchmarking | v3 | ◑ | `growth.peer_benchmark` — opt-in gate + endpoint live; peer norms are placeholders pending a real panel |
| 08 | Education & skill planning | v3 | ◑ | `education_plan` (basic) |
| 09 | Task / project integration | v3 | ◑ | `growth.export_task` endpoint (task payload export); no external PM sync |
| 09 | Customer CRM | v3 | ◑ | `/customers` endpoint (basic profiles) |
| 09 | Team & role-based access | v3 | ✅ | `TeamMember` + roles + `ApiKey` + audit log |
| 09 | Creator marketplace | v3·scale | ⛔ | deferred (scale-gated) |
| 09 | Public API & dev ecosystem | v3·scale | ✅ | `public_api.py` `/v1/public/*` with scoped API keys |
| 10 | Open-ended chat | avoid | 🚫 | grounded answer card instead |
| 10 | Auto-posting without approval | avoid | 🚫 | approval mode default |
| 10 | Real-time trend alerts | threshold | 🚫 | threshold-gated only |
| 10 | Native video editing | avoid | 🚫 | scripts/hooks only |
| 10 | Cross-platform identity resolution | privacy | 🚫 | topic-level synthesis only |
| 11 | Guardrails (gate, voice-rewrite, approval, DM limits, privacy) | — | ✅ | enforced throughout (citation gate, post-retrieval rewrite, approval mode, 7-day/cap, pseudonymity) |

## Build additions (Part III) — all ✅

Connector framework + capability registry · YouTube/Instagram/TikTok native connectors
· TikTok per-account full-loop · demand sources → radar · `sync_native` (manual / all /
scheduled) + last-synced · canonical answers + per-platform segmentation · reconciliation
+ re-promote + closed-loop breakdown · demand integrity (manipulation risk,
exposure-normalized) · opportunity score · claim layer · causal layer · trust firewall
· demand certificate · knowledge endpoint · billing + quotas + cost metering + abuse
ceiling · GDPR + pseudonym secret · fail-closed secrets/webhook · injection hardening ·
DM advisory lock · migrations 0001–0004 · Studio dashboard + fan pages · 311 + 9 tests,
five-dimension review.

## Summary

Every **v1** and **v1.5** feature is **built**; the **v2** agent layer is **built**;
**v3** is **mostly built** (basic implementations of prediction, calendar, thumbnails,
pricing, forecasting, education, CRM; team/roles and public API fully built). The scale-gated
items (competitor radar, peer benchmarking, plagiarism scan, task export) exist as
**opt-in-gated scaffolds with live endpoints** (placeholder aggregates pending a
multi-creator panel); only the **brand portal and creator marketplace** remain fully
deferred, and the **deliberately-avoided** items remain correctly unbuilt. Beyond
the specs, the build added a full cross-platform connector framework, demand-integrity
and explainability layers, and a production security/billing/observability posture.
