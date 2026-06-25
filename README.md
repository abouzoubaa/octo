# Creator Content Intelligence — "Sift"

A demand-to-outcome operating system for creators. It started as a search-first
archive (retrieval + grounded answer cards) and now spans an **agent layer** and a
**cross-platform connector framework**: a creator connects their accounts, every
post/caption/transcript/comment becomes searchable, and every fan question becomes
a demand signal that **Demand Radar** turns into a weekly, per-platform plan — which
the creator acts on (draft / series / Sift & Shift / re-promote) and closes the loop.

📄 Current state: [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) ·
Original plan: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) ·
Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)

## Repository layout

```
apps/
  api/        FastAPI — public search/answer API, webhooks, admin + agent + DM approval queue
  web/        Qwik City — fan-facing search pages + the creator Studio dashboard
  workers/    RQ jobs — ingest, transcribe, OCR, enrich, index, Demand Radar, native sync, DM dispatch
packages/
  core/       domain models (creator-scoped), DB, config, platform clients, connector framework, billing, privacy
  providers/  thin swappable interfaces: LLM, embeddings, transcription, OCR, rerank
  retrieval/  chunking, hybrid search (FTS + pgvector + RRF + rerank), grounded answer card, intent
  agent/      demand intelligence, reconciliation, repurposing/series, canonical answers, causal layer
eval/         labelled-question harness — citation correctness gates DM automation
infra/        docker-compose (pg16+pgvector, redis, minio), Dockerfiles, alembic migrations
tests/        pytest suite (297 tests, runs against real Postgres+pgvector)
```

## Quick start

```bash
cp .env.example .env            # defaults work locally; AI providers default to offline fakes
make dev-infra                  # postgres+pgvector, redis, minio
make install && make migrate
make demo                       # demo creator + corpus + Demand Radar + eval run
make api                        # http://localhost:8000  (docs at /docs)
make web                        # http://localhost:3000/alex — the fan-facing page
```

Try it:

```bash
curl 'http://localhost:8000/api/alex/search?q=where+is+the+reel+about+price+objections'
```

## Onboarding a real creator (v1 = manual)

```bash
cci-ingest create-creator <handle> "<Display Name>" --ig-user-id <IG_USER_ID>
cci-ingest set-token <handle> instagram <LONG_LIVED_TOKEN>   # Instagram Login, Standard Access
cci-ingest backfill <handle>      # every post + every comment (cursor watermarks)
cci-ingest process <handle>       # transcribe → OCR → enrich → index
cci-ingest radar <handle> --backlog   # cold-start evidence cards from the comment backlog
cci-eval import <handle> questions.yaml && cci-eval run <handle> --gate
```

Comment-to-DM stays in **approval mode** (`/admin/creators/{id}/dm-queue`) until
`cci-eval run --gate` passes citation correctness on the held-out set.

## Principles (non-negotiable)

- **One loop**: search and the answer card are interfaces; Demand Radar is the asset.
- **Grounded or silent**: every answer cites its source; low confidence → "no strong answer";
  DMs fall back to the archive link, never a shaky answer in the creator's voice.
- **Compliance**: official APIs only, one private reply per comment within 7 days,
  honor the DM rate cap, never scrape.
- **Portability**: every AI call behind a provider interface; plain Postgres+pgvector;
  S3-compatible storage; vendor swap = configuration.
- **Creator-scoped everything**, pseudonymous audience data, deletion-first indexing.
