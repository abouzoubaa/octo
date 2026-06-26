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
  - `cci_providers` — LLM, embeddings, transcription, OCR, rerank, billing (interfaces +
    offline fakes).
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
