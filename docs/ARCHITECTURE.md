# Sift — Architecture Overview & Workflow Pipeline

How the system is put together, and how data flows end to end — from a creator
connecting an account to a closed demand loop. Companion to `MASTER_SPEC.md`
(what it does) and `CURRENT_STATE.md` (what's built). A diagram-rich PDF version
is at `docs/ARCHITECTURE.pdf`.

---

## 1. System at a glance

Sift is a Python + TypeScript monorepo with a clean separation between **surfaces**
(what people touch), **application logic** (Python packages), **background workers**
(RQ jobs), and a **data plane** (Postgres + Redis + object storage). Every AI call and
every platform call goes through a thin **provider/connector interface**, so vendors
are swappable by configuration.

### Layers (top → bottom)

- **Surfaces** — fan search pages (Qwik, near-zero-JS), the creator **Studio** dashboard
  (Qwik City SSR), and the operator/admin surface.
- **API edge** — FastAPI routers: `public` (fan search/answer), `public_api` (scoped
  `/v1` knowledge API), `oauth`, `webhooks`, `admin`, `agent`, `billing`.
- **Application packages**
  - `cci_retrieval` — chunking, hybrid search, grounded answer card, intent.
  - `cci_agent` — demand intelligence, drafting, repurposing, engagement, inbox,
    intelligence, causal, claims, brand, revenue, scale, team, crm, canonical.
  - `cci_providers` — LLM, embeddings, transcription, OCR, rerank (interfaces + offline
    fakes). Billing (Stripe interface + fake) lives in `cci_core.billing`.
  - `cci_core` — models, DB, config, privacy/PII, safety (injection), cost, billing,
    GDPR, the **connector framework**, deep links, storage.
- **Workers (RQ, three lanes)** — `ingest` (backfills, media, transcribe/OCR/enrich/
  index), `realtime` (webhook comment → DM), `periodic` (radar, digests, incremental
  sync); orchestrated by `scheduler.tick()`.
- **Data plane** — **PostgreSQL + pgvector** (relational + vectors in one DB), **Redis**
  (queues + locks), **S3-compatible** object storage (media).
- **External** — Instagram / YouTube / TikTok APIs + newsletter / podcast / Discord
  demand sources; LLM / embeddings / STT / OCR / rerank providers; Stripe.

### Component map

| Area | Module(s) | Responsibility |
|---|---|---|
| Fan/Studio UI | `apps/web` (Qwik) | Search pages + creator Studio (SSR) |
| API | `apps/api/cci_api/routers/*` | HTTP surface (public, agent, admin, oauth, webhooks, billing) |
| Retrieval | `cci_retrieval/{search,answer,chunking,indexer,intent}` | Hybrid search + grounded cited answer |
| Agent | `cci_agent/*` (18 modules) | Demand intelligence + the full agent layer |
| Connectors | `cci_core/connectors/*` | Capability registry + IG/YouTube/TikTok + demand sources |
| Providers | `cci_providers/*` | Swappable AI + billing interfaces (offline fakes) |
| Workers | `apps/workers/cci_workers/*` | Ingest, sync, enrich, DM, radar, digest, scheduler |
| Data/core | `cci_core/{models,db,privacy,safety,cost,billing,gdpr}` | Schema, security, metering |

---

## 2. The product loop (the company)

The whole system is one cycle. v1 *listens & serves*; the agent layer *advises,
executes, closes*:

```
audience question → grounded cited answer → deep-link visit → logged demand signal
       ↑                                                              ↓
  better answers ← better corpus ← new content ← creator insight (Demand Radar)
```

---

## 3. The complete workflow pipeline (end to end)

| # | Stage | Trigger | Modules | Output |
|---|---|---|---|---|
| 1 | **Connect** | Creator OAuth / operator token | `oauth`, `admin`, `PlatformAccount` | Authorized, capability-tagged account |
| 2 | **Sync / Ingest** | Manual, "Sync all", or hourly | connectors → `sync_native` / `ingest_instagram` / `ingest_youtube` / `ingest_import` | `Post` + `Comment` rows (idempotent, PII-redacted, pseudonymized) |
| 3 | **Enrich** | Per new post | `enrich` (Whisper STT, OCR, LLM summary/topics/keywords, language) | `Transcript`, enriched metadata |
| 4 | **Index** | After enrich | `chunking`, `indexer` (embeddings) | `Chunk` rows: pgvector embedding + `tsv` FTS |
| 5 | **Serve** | Fan search / answer | `search` (FTS + vector + RRF + rerank) → `answer` | Cited answer card, or "no strong answer" |
| 6 | **Listen** | Comment webhook | `webhooks` → `intent` → retrieval | Routed question, demand signal logged |
| 7 | **Respond** | Approved DM | `dm.dispatch_approved` (capability gate + advisory lock + 7-day window + cap) | One public reply + one private DM (answer + deep link) |
| 8 | **Learn** | Weekly / backlog | `radar.build_radar` → `demand` (integrity, opportunity score) | `DemandTopic` evidence cards |
| 9 | **Reconcile** | On radar read | coverage strength → `_reconcile_demand` | gap / partial / well + covering permalink |
| 10 | **Act** | Creator one-tap | `drafting`, `repurposing` (Sift & Shift), `engagement` (reply, Loop-Closer), `briefing` | Drafts, series, replies, re-promotions |
| 11 | **Close** | Publish / re-promote | state machine → `loop_closed`; `Outcome` logged | North-star: closed loops/wk (made vs re-promoted) |
| 12 | **Measure** | Every change | `cci_eval` (citation gate), `events`, `cost` | Eval pass/fail, metrics, metered spend |

### Sub-pipeline A — Ingestion

`connector.backfill_content()` → `sync_native` (SAVEPOINT per item) → `Post` upsert →
`enrich` (transcribe → OCR → LLM enrich → `detect_language`) → `chunking` → embed →
`indexer` writes `Chunk(embedding, tsv)`. Idempotent by `(creator, platform,
external_id)`. Deletion purges chunks (stale citations kill trust).

### Sub-pipeline B — Retrieval & answer

`search(q)` → Postgres **FTS** + pgvector **cosine** → **RRF** fusion → optional
**rerank** → `retrieval_confidence`. Above threshold → `answer` builds a grounded,
**cited** card (voice is a post-retrieval rewrite); below → "no strong answer" / archive
link. The same layer serves the fan search bar, the answer card, and the comment-to-DM
intent route.

### Sub-pipeline C — Demand → action loop

Signals (searches + comments + external sources) → cluster/dedup → **integrity**
(unique askers, organic/prompted, persistence, sentiment, manipulation risk,
exposure-normalized) → **Opportunity Score** (explainable) → **reconciliation** (vs the
creator's archive) → agent action (draft / series / Sift & Shift / re-promote) → state
machine to `loop_closed` → `Outcome` logged → north-star. Causal layer (interventions,
holdouts, baselines, CIs) measures whether it worked.

---

## 3b. The agent layer — implemented feature catalog

`cci_agent` is not one box: it is the full "chief of staff" feature set, ~70 endpoints
across 18 modules. Every feature below is **implemented and exposed via the `agent`
router** (`/agent/...`). Grouped by the agent-layer domains.

### Foundations (§02)
| Feature | Module · function | Endpoint |
|---|---|---|
| Demand clustering & dedup | `radar.build_radar` | `/admin/.../radar/build` |
| Voice memory | `agent_foundations.capture_voice` | `POST/GET /creators/{id}/voice` |
| Offer-awareness | `monetization.offer_cta`, offers | `POST/GET /creators/{id}/offers` |
| Rules & preferences | `agent_foundations.get_rules` | `GET/PUT /creators/{id}/rules` |
| Permission ladder | `permissions.*` | `GET/PUT /permissions`, `POST /automation/pause` |
| Demand-item state machine | `agent_foundations.transition_demand` | `POST /demand/{id}/transition` |
| Intent / outcome event log | `Outcome`, `events` | `GET /creators/{id}/outcomes` |

### §03 Audience & demand intelligence
| Feature | Module · function | Endpoint |
|---|---|---|
| The Briefing | `briefing.build_briefing` | `GET /creators/{id}/briefing` |
| Content gap map | `briefing.content_gap_map` | `GET /creators/{id}/gap-map` |
| Persona segmentation | `intelligence.segment_personas` | `GET /creators/{id}/personas` |
| Sentiment & emotion | `intelligence.score_sentiment/sentiment_summary` | `GET /creators/{id}/sentiment` |
| Trend detection | `intelligence.detect_trends` | `GET /creators/{id}/trends` |
| Cross-platform demand synthesis | `radar` external signals + demand sources | `POST /creators/{id}/external-signal` |
| Competitor demand radar *(opt-in)* | `growth.competitor_radar` | `GET /creators/{id}/competitor-radar` |
| Opportunity Score (explainable) | `demand.opportunity_score/score_topic` | `GET /demand/{id}/opportunity` |
| Demand Certificate | `demand.demand_certificate` | `GET /demand/{id}/certificate` |
| Demand pipeline + north-star | `demand.closed_loops` | `GET /creators/{id}/demand/pipeline` · `/creators/{id}/north-star` |

### §04 Content production
| Feature | Module · function | Endpoint |
|---|---|---|
| Content briefs | `drafting.generate_brief` | (via draft) |
| Draft generator (script + hooks) | `drafting.generate_draft` | `POST /demand/{id}/draft`, `GET /drafts`, `POST /drafts/{id}/decide` |
| Creator recall search | `drafting.creator_recall` | `GET /creators/{id}/recall` |
| Multi-format repurposing | `repurposing.repurpose` | `POST /posts/{id}/repurpose` |
| Sift & Shift | `repurposing.sift_and_shift_opportunities/draft_shift` | `GET /sift-and-shift`, `POST /posts/{id}/shift` |
| Series builder | `repurposing.build_series` | `POST /demand/{id}/series` |
| Performance prediction | `scale.predict_performance` | `GET /drafts/{id}/predict` |
| Content calendar / planner | `scale.content_calendar` | `GET /creators/{id}/calendar` |
| Thumbnail & visual intelligence | `scale.thumbnail_concepts` | (library only — no endpoint yet) |
| Canonical answers (cross-platform) | `canonical.group_variants` | `POST /creators/{id}/canonical/group` · `GET /creators/{id}/canonical` |
| Versioned claim layer | `claims.extract_claims/supersede/detect_contradictions` | `GET /claims`, `/claims/{id}/approve`, `/detect-contradictions` |

### §05 Engagement & inbox
| Feature | Module · function | Endpoint |
|---|---|---|
| Intent-labelled queue | `inbox.labelled_inbox/label_message` | `GET /creators/{id}/inbox` |
| Bounded clarifying question | `inbox.bounded_clarify` | in the public search response (no-strong-answer) + fan-page chips |
| No-answer waitlist | `inbox.add_to_waitlist` | `POST /api/{handle}/waitlist` + fan-page email form |
| Saved playbooks | `inbox.match_playbook` | `POST/GET /creators/{id}/playbooks` · applied in the comment→DM pipeline |
| Reply assistant | `engagement.draft_reply` | (agentic-DM path — thread dispatcher ◑) |
| Agentic DM (approval mode) | `engagement.handle_dm_followup/can_auto_approve/bulk_approve` | `POST /creators/{id}/dm/bulk-approve` |
| Community delegation | `engagement.delegation_candidate` | hint in `GET /admin/creators/{id}/dm-queue` |
| "Not now, but…" queue | `engagement.defer_question/due_deferrals` | `POST /defer`, `GET /deferrals/due` |
| Loop-Closer | `engagement.close_loop` | `POST /demand/{id}/close-loop` |

### §06 Monetization & revenue
| Feature | Module · function | Endpoint |
|---|---|---|
| Auto-affiliate injection | `monetization.inject_affiliate/with_utm` | applied at draft approval (`POST /drafts/{id}/decide`) |
| Offer-aware CTAs | `monetization.offer_cta` | (answers/recs) |
| Affiliate optimisation | `revenue.affiliate_optimisation` | `GET /creators/{id}/affiliate-optimisation` |
| Sponsor matchmaker & pitch | `revenue.sponsor_report` | `GET /creators/{id}/sponsor-report` |
| Dynamic pricing & offer insights | `scale.pricing_insights` | `GET /creators/{id}/pricing-insights` |
| Revenue forecasting & goals | `scale.revenue_forecast` | `GET /creators/{id}/revenue-forecast` |

### §07 Brand & reputation
| Feature | Module · function | Endpoint |
|---|---|---|
| Crisis / sentiment-shift detection | `brand.detect_crisis` | `GET /creators/{id}/crisis-check` |
| Voice consistency scoring | `brand.voice_consistency_score` | `POST /creators/{id}/voice-score` |
| Plagiarism / unauthorised-use *(opt-in)* | `growth.plagiarism_scan` | `POST /creators/{id}/plagiarism-scan` |

### §08 Growth & strategy
| Feature | Module · function | Endpoint |
|---|---|---|
| Content strategy advisor | `intelligence.strategy_advisor` | `POST /creators/{id}/strategy` |
| Peer benchmarking *(opt-in)* | `growth.peer_benchmark` | `GET /creators/{id}/benchmark` |
| Education & skill planning | `scale.education_plan` | `GET /creators/{id}/education-plan` |

### §09 Operations & ecosystem
| Feature | Module · function | Endpoint |
|---|---|---|
| Task / project export | `growth.export_task` | `POST /demand/{id}/export-task` |
| Customer CRM | `crm.customer_profiles/lifecycle_segments` | `GET /creators/{id}/customers`, `/lifecycle` |
| Team & role-based access | `team.add_member/has_capability/audit` | `POST/GET /creators/{id}/team` |
| Public API & dev ecosystem | `team.mint_api_key/verify_api_key` + `public_api` | `POST /api-keys`, `GET /v1/public/*` |

### Fan-side surfaces (public router — no login wall)
| Feature | Endpoint |
|---|---|
| Search + grounded answer (+ clarify) | `GET /api/{handle}/search` |
| Deep-link answer resolution | `GET /api/{handle}/answer/{answer_id}` |
| Start-here paths / popular / topics | `GET /api/{handle}/start-here` · `/popular` · `/topics` |
| No-answer waitlist + open cohorts | `POST /api/{handle}/waitlist` · `GET /api/{handle}/cohorts` |
| Outcome feedback ("did this help?") | `POST /api/{handle}/feedback` |
| Click signal + affiliate redirect | `POST /api/{handle}/events/click` · `GET /buy/{product_id}` |
| Save-for-later (client-side) | fan page ☆ Save (localStorage) |
| Cross-platform archive import | `POST /agent/creators/{id}/import` |

### Causal layer (cross-cutting measurement)
| Feature | Module · function | Endpoint |
|---|---|---|
| Interventions, holdouts, lift, CIs | `causal.create_intervention/holdout_lift/matched_baseline/performance_interval` | `GET /interventions`, `/lift`, `POST /interventions/{id}/outcome` |

> *Scaffolded* features (peer benchmarking, competitor radar, plagiarism) ship the
> opt-in gate, the privacy guarantee (topic-level/aggregate only, never identity
> matching), and the response shape, returning the creator's own stats vs placeholder
> aggregates until a real multi-creator panel exists.

## 4. Jobs, queues & the scheduler

Three RQ lanes keep a heavy backfill from starving the DM loop:

- **ingest** — backfills, media download, transcribe/OCR/enrich/index.
- **realtime** — webhook-driven comment → DM processing.
- **periodic** — radar clustering, digests, incremental/native sync.

`scheduler.tick()` (every ~5 min) enqueues: DM dispatch (per-creator advisory lock),
hourly incremental + native sync, weekly radar + digest (Mon 07:00 UTC), daily token
refresh (06:00 UTC).

---

## 5. Cross-cutting concerns

- **Security** — creator-scoped everything; OAuth tokens encrypted at rest
  (`EncryptedString`); fail-closed boot on insecure secrets; webhook signature verified;
  prompt-injection hardening on agent prompts; DM dispatch advisory lock.
- **Privacy** — per-creator pseudonyms (dedicated secret), PII redaction, GDPR
  export/erase, opt-in RLS.
- **Cost** — per-creator AI metering with op tags, per-plan cost cap, separate
  anonymous-answer abuse ceiling.
- **Portability** — every AI + platform call behind an interface; Postgres + pgvector;
  S3; offline fakes by default. Migrations 0001–0004 via Alembic.
