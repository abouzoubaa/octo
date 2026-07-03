# Deploying Sift

Sift is infra-agnostic: Docker containers + plain Postgres (with pgvector) +
Redis + S3-compatible object storage. Manifests are provided for two common
targets; the architecture runs anywhere those four exist.

## Components

| Service | Command | Notes |
|---|---|---|
| `api` | `cci-api` | FastAPI — public search, OAuth, webhooks, admin, billing |
| `web` | node server | Qwik fan page + Sift Studio (calls the API server-side) |
| `worker` | `cci-worker` | RQ jobs: ingest, transcribe/OCR/enrich, DM dispatch, radar |
| `scheduler` | `schedule_forever()` | enqueues periodic jobs (single replica) |
| `migrate` | `alembic … upgrade head` | run once per release, before api/worker roll out |

## Pre-flight: secrets (REQUIRED before going live)

The app refuses insecure defaults in production. Generate real values:

```bash
# admin token + OAuth state secret
openssl rand -hex 32
# at-rest encryption key (Fernet)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then confirm nothing is left at a default:

```python
python -c "from cci_core.config import get_settings; \
import sys; p=get_settings().assert_production_secrets(); \
print('OK' if not p else p); sys.exit(1 if p else 0)"
```

Set `CCI_DEBUG=false` in production — this enables the fail-closed posture
(e.g. the billing webhook refuses the fake provider).

Required secrets: `CCI_ADMIN_TOKEN`, `CCI_ENCRYPTION_KEY`, `CCI_OAUTH_STATE_SECRET`,
`CCI_IG_APP_ID/SECRET`, `CCI_IG_WEBHOOK_VERIFY_TOKEN`, `CCI_LLM_API_KEY`,
`CCI_EMBEDDING_API_KEY`, `CCI_STRIPE_API_KEY/WEBHOOK_SECRET`, `CCI_S3_*`.

## Build & push images

```bash
docker build -f infra/Dockerfile.api    -t ghcr.io/yourorg/sift-api:TAG .
docker build -f infra/Dockerfile.worker -t ghcr.io/yourorg/sift-worker:TAG \
  --build-arg INSTALL_ML=1 .            # ML extra = faster-whisper + PaddleOCR
docker build -f infra/Dockerfile.web    -t ghcr.io/yourorg/sift-web:TAG apps/web
docker push ghcr.io/yourorg/sift-{api,worker,web}:TAG
```

## Option A — Kubernetes (`infra/deploy/k8s/`)

```bash
kubectl apply -f infra/deploy/k8s/00-config.yaml          # namespace + config
# create secrets from the CLI (preferred — see 10-secret.example.yaml header)
kubectl apply -f infra/deploy/k8s/20-migrate-job.yaml
kubectl -n sift wait --for=condition=complete job/sift-migrate --timeout=300s
kubectl apply -f infra/deploy/k8s/30-api.yaml \
              -f infra/deploy/k8s/40-web.yaml \
              -f infra/deploy/k8s/50-workers.yaml \
              -f infra/deploy/k8s/60-ingress.yaml
```

Point `CCI_DATABASE_URL`/`CCI_REDIS_URL`/`CCI_S3_*` at managed services (RDS/Cloud
SQL, ElastiCache/Memorystore, S3/GCS). The Postgres instance needs the `vector`
extension (`CREATE EXTENSION vector;`) — managed Postgres 16 supports pgvector.
Rolling updates are safe; run the migrate Job first when a release changes schema.

## Option B — Render (`infra/deploy/render.yaml`)

One blueprint provisions managed Postgres + Redis + api/web/worker/scheduler.
After `render blueprint launch`, set the `sync:false` secrets in the dashboard,
run `CREATE EXTENSION vector;` once on the database, and the `preDeployCommand`
applies migrations on every deploy.

## After deploy

- Point the Instagram app's OAuth redirect to `https://<host>/oauth/instagram/callback`
  and the webhook to `https://<host>/webhooks/instagram` (verify token = `CCI_IG_WEBHOOK_VERIFY_TOKEN`).
- Point the Stripe webhook to `https://<host>/billing/webhook` (secret = `CCI_STRIPE_WEBHOOK_SECRET`).
- Schedule `infra/backup.sh` (daily) for database backups.
- Scrape `GET /metrics`; watch `sift_requests_5xx_total` and `sift_rate_limited_total`.

## Scaling notes

- `api`/`web` scale horizontally (stateless). The in-process rate limiter is
  per-replica — move to a Redis-backed limiter when running many API replicas.
- `worker` is CPU-bound on transcription/OCR; give it headroom or a GPU node pool.
- `scheduler` stays at **one replica** (it only enqueues).
