.PHONY: install dev-infra migrate api worker scheduler web test eval seed demo lint

install:            ## install python deps (editable) + dev extras
	pip install -e ".[dev]"

dev-infra:          ## start postgres+pgvector, redis, minio
	docker compose -f infra/docker-compose.yml up -d db redis minio

migrate:            ## create extensions, tables, indexes
	cci-migrate

api:                ## run the FastAPI service
	cci-api

worker:             ## run an RQ worker (all queues)
	cci-worker

scheduler:          ## run the periodic scheduler loop
	python -c "from cci_workers.scheduler import schedule_forever; schedule_forever()"

web:                ## run the Qwik dev server
	cd apps/web && npm install && npm run dev

test:               ## run the test suite (needs dev-infra postgres)
	pytest -q

demo:               ## end-to-end local demo: creator + corpus + radar + eval set
	cci-ingest create-creator alex "Alex the Coach"
	cci-ingest seed-demo alex
	cci-ingest radar alex --backlog
	cci-eval import alex eval/questions.example.yaml
	cci-eval run alex
	@echo "→ try: curl 'http://localhost:8000/api/alex/search?q=price+objections'"

lint:
	ruff check .
