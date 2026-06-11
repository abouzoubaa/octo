# Creator Content Intelligence

A search-first archive for each creator — powered by retrieval, amplified by
comment-to-DM, and monetized through demand intelligence.

A creator connects their Instagram (and/or YouTube) account; the app turns
everything they ever posted — videos, captions, spoken words, on-screen text —
into a searchable library at `yourapp.com/<creator>`. Fans ask in normal words
and get the right old posts back, plus a short grounded answer **with citations**.
Every question becomes a demand signal: **Demand Radar** tells the creator each
week what their audience wants next.

📄 Full plan: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)

## Repository layout

```
apps/
  api/        FastAPI — public search/answer API, IG webhooks, admin + DM approval queue
  web/        Qwik City — fan-facing search-first pages (near-zero JS for the IG in-app browser)
  workers/    RQ jobs — ingest, transcribe, OCR, enrich, index, Demand Radar, DM dispatch
packages/
  core/       domain models (creator-scoped), DB, config, IG/YT clients, privacy, deep links
  providers/  thin swappable interfaces: LLM, embeddings, transcription, OCR
  retrieval/  chunking, hybrid search (FTS + pgvector + RRF), grounded answer card, intent
eval/         labelled-question harness — citation correctness gates DM automation
infra/        docker-compose (pg16+pgvector, redis, minio), Dockerfiles, DB bootstrap
tests/        pytest suite (runs against real Postgres+pgvector)
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
