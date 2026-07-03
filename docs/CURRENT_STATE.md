# Sift — Current State (what's actually built)

The roadmaps in this folder are forward-looking. **This document is the inventory of
what exists in the codebase today.** It is the source of truth when the roadmaps and
reality disagree.

Snapshot: 297 passing tests (real Postgres + pgvector), ruff-clean, three Alembic
migrations, offline-by-default AI providers (fakes) so the whole system runs and
tests without network or API keys.

---

## 1. Retrieval core (the original v1)

- Per-creator ingestion: posts, captions, media, transcripts (Whisper iface), OCR.
- Chunking + **hybrid search**: Postgres FTS + pgvector cosine, fused with RRF, plus an
  optional **reranker** stage (provider interface; offline fake).
- **Grounded answer card** with citations and an explicit "no strong answer" state.
- Language-aware search; "start here" paths for cold topics.
- **Eval gate**: a labelled-question harness; citation correctness gates DM automation.

## 2. Agent layer (`packages/agent`)

- **Demand Radar**: clusters audience questions into weekly demand topics.
- **Demand Integrity**: unique askers, organic vs CTA-prompted, persistence, sentiment,
  intent, manipulation-risk and exposure-normalized demand (asks per 1k impressions).
- **Explainable Opportunity Score** (components exposed, not a black box).
- **Reconciliation**: each topic is classified against the creator's own archive —
  `well` / `partial` / `gap` (strength thresholds matching the briefing's gap map),
  with the covering permalink surfaced.
- **Actions**: grounded **draft**, **series** builder (persisted as draft stubs),
  **Sift & Shift** (answer covered on one platform but not another, with demand),
  and **re-promote** (close a loop with already-made content).
- **Outcome log + state machine**: demand topics move new → idea → drafting → published
  → loop_closed (or are dismissed); re-promote is a second closure path. The **north-star**
  is closed loops/creator/week, now broken down **made vs re-promoted**.
- **Voice memory**, **offers**, **CreatorRules**, **permission ladder**.
- **Causal layer**: interventions, holdouts, baselines, confidence intervals, holdout lift.
- **Versioned claim layer** (freshness/contradiction), **Demand Certificate**, canonical
  knowledge endpoint, **trust firewall** (why-selected + disclosure), prompt-injection
  hardening, cost metering.

## 3. Cross-platform connector framework (`packages/core/cci_core/connectors`)

- **Connector contract + capability registry**: `content.read`, `comments.read`,
  `messages.send`, `comments.reply`, `demand.read`, `content.publish`, … Product logic
  asks the registry what an account can do rather than assuming a uniform loop.
- **Native connectors** (injectable HTTP transport → tested with fakes, no network):
  - **YouTube** — Data API v3: uploads-playlist walk (paginated), comment threads
    (paginated, 403-resilient on comments-disabled videos), comment replies.
  - **Instagram** — Graph API via the existing client: media + comments backfill,
    cursor walk with caps, replies.
  - **TikTok** — Display API v2: archive mode (content only) vs full-loop (comments +
    replies, where approved). Capability-gated.
- **Demand sources**: newsletter / podcast / Discord as `demand.read`-only inputs that
  feed Demand Radar (ExternalSignal → radar synthesis).
- **`sync_native` worker**: maps any connector's output into Posts + Comments
  idempotently (PII-redacted, pseudonymized, question/sentiment-classified), stamps
  `last_synced_at`. Driven manually ("Sync now"), all-at-once ("Sync all"), or hourly
  by the scheduler.
- **Canonical answers** (`CanonicalContent`): variant grouping across platforms; per-platform
  demand segmentation (`everywhere` / `platform:x` / `search_only`).

## 4. Surfaces

- **Fan pages** (Qwik): search-first, near-zero-JS creator pages.
- **Creator Studio** (Qwik SSR dashboard):
  - Opportunity queue ranked by Opportunity Score, **filterable by platform × gap/answered**,
    with reconciliation hints and per-card actions (make / draft / series / re-promote / ignore);
    resolved loops drop out of the queue.
  - North-star stat with the made/re-promoted breakdown.
  - **Platforms page**: connectors + capabilities, connection + `last_synced_at` status,
    Sync now / Sync all, canonical answers, Sift & Shift queue (configurable target),
    and per-platform top demand.
  - Inbox, Drafts (with deep-links), briefing.

## 5. Platform / ops

- SQLAlchemy 2.0 models, all creator-scoped; **Alembic** (0001 baseline, 0002 schema-sync,
  0003 last_synced_at); EncryptedString (Fernet/MultiFernet) for OAuth tokens; optional RLS.
- **Billing**: Plan enum (free/creator/pro), feature gating, quotas; Stripe behind an
  interface with an offline fake.
- GDPR export/erase + PII redaction; webhook idempotency; rate limiting; RQ job reliability.
- CI/CD + observability; k8s + Render deploy manifests.

---

## Honest gaps (not built / environment-bound)

- **No live OAuth consent flow** — tokens are set via the admin endpoint; a hosted
  Google/Meta/TikTok consent round-trip isn't wired (and can't be exercised offline).
- **Connectors are verified against faithful fakes**, not live APIs — live quirks (quota,
  pagination edge cases, auth refresh) are unexercised here.
- **No frontend test suite** — all 297 tests are Python; Qwik loader logic is build-checked
  and visually verified, not unit-tested.
- Deferred by deliberate scope decision: payments-beyond-gating, a content compiler, a
  creator marketplace, sponsor-funded resolution.
