# Roadmap to a Full App

> **Superseded by [`ROADMAP.md`](ROADMAP.md)** — the unified roadmap merges this
> production-grade checklist (Axis A) with the Sift agent feature layer (Axis B)
> on one timeline. This file is kept as the detailed production-axis source.

What exists today is a working **v1 proof-of-concept**: the whole loop runs end
to end (search → cited answer → comment-to-DM → Demand Radar → affiliate links),
with 42 passing tests against real Postgres+pgvector. This document lists
**everything that still needs to be added** to turn that POC into a complete,
multi-tenant, self-serve product.

Each item is tagged by priority:
- 🔴 **P0** — required before any real external launch
- 🟠 **P1** — needed to scale past the first hand-held creator
- 🟢 **P2** — growth, polish, and the monetization expansion ladder

Legend for status: **stub** = placeholder exists, **missing** = not started,
**partial** = works but not production-grade.

---

## 1. Onboarding & Authentication

| Item | Priority | Status | Notes |
|---|---|---|---|
| Instagram OAuth sign-in flow (UI) | 🔴 P0 | missing | Today tokens are pasted via CLI/admin. Need the real "Connect Instagram" button → consent → callback → token exchange. The token-exchange helpers already exist in `instagram.py`. |
| YouTube OAuth flow | 🟠 P1 | missing | Same pattern for owned/authorized channels. |
| Long-lived token refresh job | 🔴 P0 | missing | IG long-lived tokens expire (~60 days); need a scheduled refresh before expiry or creators silently disconnect. |
| Token encryption at rest | 🔴 P0 | partial | Tokens are stored in plaintext columns. Encrypt with a KMS/secret key. |
| Creator self-serve signup + onboarding wizard | 🟠 P1 | missing | Guided flow: connect → backfill progress → label questions → publish link. |
| Creator login / session management | 🔴 P0 | missing | Real creator accounts (email+password or social login), not a single shared admin bearer token. |
| Role-based access (creator vs operator vs admin) | 🟠 P1 | missing | Current admin API is one global token. |

---

## 2. Multi-Tenancy, Billing & Plans

| Item | Priority | Status | Notes |
|---|---|---|---|
| Subscription billing (Stripe) | 🔴 P0 | missing | Creator (~$49–99/mo) and Pro (~$149–299/mo) tiers from the plan. Checkout, webhooks, dunning. |
| Plan-based feature gating | 🟠 P1 | missing | e.g. comment-to-DM + storefront search are Pro-only. |
| Usage metering & quotas | 🟠 P1 | missing | Cap AI spend per creator; meter searches/DMs for fair-use and cost control. |
| Free-trial / paid-pilot logic | 🟠 P1 | missing | Convert pilots to paid once Radar shows value. |
| Per-creator custom domains | 🟢 P2 | missing | Plan defers this; path-based `/<handle>` ships first. |

---

## 3. Creator Dashboard (web UI)

The admin surface is API-only today. Creators need a real interface.

| Item | Priority | Status | Notes |
|---|---|---|---|
| Demand Radar review UI | 🔴 P0 | missing | Evidence cards with "useful / not / made" buttons. API exists; no screen. |
| DM approval inbox | 🔴 P0 | missing | Approve/edit/reject queued replies. API exists; no screen. |
| Content/corpus browser | 🟠 P1 | missing | See ingested posts, transcript/OCR coverage, re-trigger processing, delete. |
| Product & affiliate manager | 🟠 P1 | missing | Add/approve products, set affiliate links, map to posts. |
| Metrics dashboard | 🟠 P1 | partial | Metrics endpoint exists; needs charts (searches, click-rate, no-answer rate, ROI). |
| Distribution setup checklist | 🟢 P2 | missing | Guide the bio link + "Search" Highlight + pinned reel behaviour change. |

---

## 4. Retrieval & Answer Quality (the moat)

The POC uses offline "fake" AI providers by default. Production quality depends on:

| Item | Priority | Status | Notes |
|---|---|---|---|
| Wire real LLM + embedding providers | 🔴 P0 | partial | Interfaces + Anthropic/OpenAI adapters exist; need real keys, model selection, prod config. |
| Real transcription (Whisper) at scale | 🔴 P0 | partial | Adapter exists; needs GPU/worker capacity and a media-download retry path (IG CDN URLs expire). |
| Real OCR (PaddleOCR) at scale | 🟠 P1 | partial | Adapter exists; tune keyframe sampling and cost. |
| Reranking model | 🟠 P1 | missing | Plan calls for a rerank stage; today it's RRF fusion only. Add a cross-encoder/LLM reranker. |
| Confidence-threshold calibration | 🔴 P0 | partial | Thresholds are hand-set; calibrate against the labelled set per creator/niche. |
| Larger evaluation sets + CI gate | 🔴 P0 | partial | Harness exists; need 40–60 labelled Qs per creator wired into CI to block regressions. |
| Freshness & contradiction handling | 🟠 P1 | missing | When newer posts supersede old advice, prefer/flag the current one. |
| Multilingual support | 🟢 P2 | missing | Swap to a multilingual embedding model + language-aware FTS config. |
| Creator-voice answer styling | 🟢 P2 | missing | Plan keeps this secondary; layer voice on top of the correct, cited answer. |

---

## 5. Comment-to-DM Automation

| Item | Priority | Status | Notes |
|---|---|---|---|
| Production webhook subscription setup | 🔴 P0 | partial | Receiver + signature check exist; need the Meta webhook subscription wired per creator. |
| Graduated auto-send (post-gate) | 🟠 P1 | partial | Approval mode works; add the automatic path once the citation gate passes, per-post opt-in. |
| Per-post trigger CTA management | 🟠 P1 | missing | UI to set "Comment PLAN…" triggers per post. |
| Rate-limit queue durability | 🟠 P1 | partial | Hourly cap enforced in-process; make the overflow queue durable across restarts. |
| DM delivery analytics | 🟢 P2 | partial | Events logged; surface send-success and click-through. |

---

## 6. Demand Radar & Insights

| Item | Priority | Status | Notes |
|---|---|---|---|
| Weekly digest email delivery | 🔴 P0 | stub | Currently prints to a log. Wire a real email provider (SES/Postmark/Resend). |
| Digest via DM option | 🟢 P2 | missing | Plan offers email *or* DM. |
| Better clustering quality | 🟠 P1 | partial | Greedy centroid clustering is fine for v1; evaluate HDBSCAN/embeddings tuning at volume. |
| Insight → draft generator (v2) | 🟢 P2 | missing | One-tap reel script/hook/caption from a Radar card. Premium tier. |
| Sponsor pitch reports (v2) | 🟢 P2 | missing | Auto one-pager: "412 questions about X this month." |

---

## 7. Monetization Expansion Ladder (plan §13)

| Item | Priority | Status | Notes |
|---|---|---|---|
| Affiliate mapping + click tracking | ✅ done | — | Already built (v1 proof of ROI). |
| Email capture bridge (v1.5) | 🟢 P2 | missing | "Get the full checklist by email" on answer cards + DMs; builds the creator's owned list. |
| Storefront search (v1.5) | 🟢 P2 | missing | Mark premium content; "covered in depth in module 3 →" teaser → checkout. |
| Embeddable search widget (v1.5) | 🟢 P2 | missing | The search box on the creator's own site + "Powered by" footer (referral loop). |
| Paid Q&A on "no answer" (v2) | 🟢 P2 | missing | Turn the failure state into a paid question / coaching funnel. |

---

## 8. Infrastructure & Operations

| Item | Priority | Status | Notes |
|---|---|---|---|
| Production deployment (cloud) | 🔴 P0 | partial | docker-compose exists for local; need managed Postgres, object storage, container hosting, TLS, a domain. |
| Database migrations tool (Alembic) | 🔴 P0 | partial | Today schema is create-from-metadata. Adopt versioned migrations before live data exists. |
| Secrets management | 🔴 P0 | missing | Move keys/tokens out of `.env` into a secrets manager. |
| CI/CD pipeline | 🔴 P0 | missing | Run tests + eval gate + lint on every push; automated deploys. |
| Background-job reliability | 🟠 P1 | partial | RQ + scheduler exist; add retries, dead-letter handling, and a durable scheduler (not the in-process loop). |
| Monitoring, logging, alerting | 🔴 P0 | missing | Error tracking (Sentry), uptime checks, AI-cost dashboards, queue depth alerts. |
| Event analytics pipeline | 🟠 P1 | partial | Events table exists; wire PostHog or a warehouse for product analytics. |
| Backups & disaster recovery | 🔴 P0 | missing | Automated DB backups + restore drills; media storage durability. |
| Rate limiting & abuse protection | 🟠 P1 | missing | Throttle the public search API; bot protection. |
| Caching / CDN for the fan page | 🟠 P1 | missing | Cache result pages; serve the Qwik app via CDN for in-app-browser speed. |

---

## 9. Legal, Privacy & Compliance

| Item | Priority | Status | Notes |
|---|---|---|---|
| Privacy policy + ToS | 🔴 P0 | missing | Required by Meta App Review and GDPR. |
| GDPR/CCPA deletion & export | 🔴 P0 | partial | Audience data is pseudonymized and post-deletion purges chunks; need a user-facing deletion/export request path. |
| Meta App Review submission | 🔴 P0 | missing | Advanced Access for external creators; request only scopes the demo uses. |
| Data processing agreements | 🟠 P1 | missing | DPAs with AI/infra subprocessors. |
| Content moderation / safety guardrails | 🟠 P1 | partial | "No answer" + citation gate reduce hallucination; add abuse/PII filters on audience input. |
| Cookie consent (where required) | 🟢 P2 | missing | If analytics cookies are used in applicable regions. |

---

## 10. Quality, Testing & Docs

| Item | Priority | Status | Notes |
|---|---|---|---|
| Backend test suite | ✅ done | — | 42 tests against real Postgres+pgvector. |
| Frontend tests (web app) | 🟠 P1 | missing | Component + end-to-end tests for the Qwik pages. |
| Load / performance testing | 🟠 P1 | missing | Validate search latency and webhook throughput on a viral post. |
| API documentation | 🟢 P2 | partial | FastAPI auto-docs exist; add a published API reference if exposing it. |
| Runbooks / on-call docs | 🟠 P1 | missing | How to handle token expiry, Meta outages, cost spikes. |

---

## Suggested Sequencing

**Phase A — make it real for one creator (mostly P0)**
Real AI keys → cloud deployment + managed Postgres → migrations → secrets →
monitoring/backups → privacy policy. (This matches `GOING_LIVE.md`.)

**Phase B — let creators run themselves (P0/P1)**
OAuth sign-in + token refresh → creator login & dashboard (Radar review + DM
inbox) → email digest delivery → Stripe billing → Meta App Review.

**Phase C — scale & differentiate (P1/P2)**
Reranking + freshness → plan gating & quotas → CI/CD + analytics → the
monetization ladder (email capture, storefront, widget) → draft generator &
sponsor reports.

---

*Companion documents: `IMPLEMENTATION_PLAN.md` (the technical v1 plan),
`GOING_LIVE.md` (plain-language launch checklist), `README.md` (how to run it).*
