# shelf-audit — one-command entry points. Windows: run from Git Bash / WSL, or use the commands inside.
SHELL := /bin/bash
PY ?= python
ARTYOM ?= ../../Work/Artyom
CONFIG ?= evals/configs/baseline.yaml

.PHONY: help setup data models catalog index up down logs test test-backend test-frontend test-all lint gitleaks \
        eval eval-replay rag-sanity rag-parity guard-eval golden replay-cache demo demo-up

help:           ## this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n",$$1,$$2}'

setup:          ## python deps for backend/bot/mcp (uv) + frontend (npm)
	cd backend && uv pip install -e ".[dev]"
	cd bot && uv pip install -e ".[dev]"
	cd mcp_server && uv pip install -e ".[dev]"
	cd frontend && npm ci

data:           ## copy customer data from the working folder (ARTYOM=...) into ./data (not git)
	$(PY) data/scripts/fetch_data.py --source "$(ARTYOM)"

models:         ## SigLIP ONNX into data/models (HF, or ARTYOM/models_onnx if present)
	$(PY) data/scripts/fetch_models.py $(if $(wildcard $(ARTYOM)/models_onnx),--from-dir "$(ARTYOM)/models_onnx",)

catalog:        ## PDF + reference folders -> data/catalog/catalog.jsonl
	cd backend && $(PY) -m app.rag.ingest

index: catalog  ## embed refs (SigLIP + HSV) -> pgvector (if DATABASE_URL) + data/catalog/index.npz
	cd backend && $(PY) -m app.rag.build_index

up:             ## docker compose: postgres + api + frontend + mcp  (cabinet: http://localhost:8080)
	docker compose up -d --build
	docker compose --profile setup run --rm index

down:           ## stop
	docker compose down

logs:
	docker compose logs -f api

test-backend:   ## backend tests (JS parity needs node; pg tests need DATABASE_URL)
	cd backend && $(PY) -m pytest -q

test-frontend:
	cd frontend && npm run typecheck && npm test && npm run build

test-all: test-backend test-frontend  ## everything
	cd evals && $(PY) -m pytest -q
	cd bot && $(PY) -m pytest -q
	cd mcp_server && $(PY) -m pytest -q
	$(PY) -m pytest -q skills/shelf-audit-report/scripts

test: test-backend

lint:
	ruff check .

gitleaks:       ## secret scan of the working tree (also runs in pre-commit and CI)
	gitleaks detect --no-git --source . --config .gitleaks.toml --redact -v

golden:         ## rebuild evals/golden/*.json from the original GT files (ARTYOM=...)
	$(PY) evals/tools/build_golden.py --artyom "$(ARTYOM)"

replay-cache:   ## recorded n8n answers -> evals/cache (for the *_replay configs and the demo API; needs `make data`)
	for c in evals/configs/n8n_*_replay*.yaml evals/configs/smoke_replay.yaml; do $(PY) evals/tools/n8n_to_cache.py --config $$c; done
	$(PY) evals/tools/n8n_to_cache.py --config evals/configs/demo_replay.yaml --salt ''   # the API runs with an empty salt

eval:           ## live eval: make eval CONFIG=evals/configs/ab1_topk.yaml  (needs GEMINI_API_KEY; answers cached)
	$(PY) -m evals.run --config $(CONFIG)

eval-replay: replay-cache  ## "before migration" metrics from recorded n8n answers (no key; *_fcheck/_check need SigLIP)
	for v in v74 v75 v75b; do for arm in "" _pass1 _gate _gate_fcheck _check; do \
	  $(PY) -m evals.run --config evals/configs/n8n_$${v}_replay$${arm}.yaml; done; done

rag-sanity:     ## retrieval top-1 on the 129 labelled units (expects ≈93% on the 24.08 ref set)
	$(PY) evals/rag_sanity.py

rag-parity:     ## pgvector vs the .npz snapshot: same top-3 on the 129 units (needs DATABASE_URL + make index)
	$(PY) evals/rag_parity.py

guard-eval:     ## guardrail precision / recall on generated negatives
	$(PY) evals/guard_eval.py

demo: replay-cache  ## API locally without Docker in replay mode (recorded answers, no key): http://localhost:8000/docs
	cd backend && LLM_MODE=replay PASS2_REFS=all $(PY) -m uvicorn app.api.main:app --port 8000

demo-up: replay-cache  ## whole stack in Docker, answering from recorded runs (no key): http://localhost:8080
	LLM_MODE=replay PASS2_REFS=all docker compose up -d --build
	docker compose --profile setup run --rm index
