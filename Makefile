PY := .venv/bin/python
PIP := .venv/bin/pip

# The first python on this machine that is new enough. Override with `make PYTHON=... install`.
PYTHON ?= $(shell for p in python3.14 python3.13 python3.12 python3 python; do \
	command -v $$p >/dev/null 2>&1 && \
	$$p -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null && \
	{ echo $$p; break; }; done)

.PHONY: help venv install db-up db-down migrate seed dev test eval lint typecheck fmt check \
        web-dev web-install demo up local

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## create the virtualenv
	@test -n "$(PYTHON)" || { \
		echo "No python 3.12+ found. Install one, or run: make PYTHON=/path/to/python install"; \
		exit 1; }
	@echo "using $(PYTHON) ($$($(PYTHON) --version))"
	$(PYTHON) -m venv .venv

install: venv ## install python deps
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev]"
	@echo "ready. try: make demo"

web-install: ## install frontend deps
	cd web && npm install --no-audit --no-fund

local: install web-install ## everything needed to run it on this machine
	@echo
	@echo "  Now, in two terminals:"
	@echo "    make dev        # api  on http://localhost:8000"
	@echo "    make web-dev    # web  on http://localhost:3000"
	@echo

db-up: ## start postgres 16
	docker compose up -d db

db-down:
	docker compose down

migrate: ## run alembic migrations
	.venv/bin/alembic upgrade head

seed: ## seed skills and tasks for linear equations
	$(PY) -m warrant.seed

dev: ## serve the api on :8000
	.venv/bin/uvicorn warrant.api.main:app --reload --port 8000

test: ## run the test suite
	$(PY) -m pytest -q

eval: ## run the eval harness (offline, deterministic)
	$(PY) evals/run_eval.py

lint:
	.venv/bin/ruff check warrant evals tests
	.venv/bin/ruff format --check warrant evals tests

fmt:
	.venv/bin/ruff format warrant evals tests
	.venv/bin/ruff check --fix warrant evals tests

typecheck: ## mypy strict on the verifier
	.venv/bin/mypy warrant/verify

check: lint typecheck test eval ## everything CI runs

web-dev: ## serve the frontend on :3000
	cd web && npm run dev

demo: ## the 90 second demo, in the terminal
	$(PY) -m warrant.demo

lean-image: ## build the tier 2 sandbox image (M6)
	docker build -t $${WARRANT_LEAN_IMAGE:-warrant/lean:latest} docker/lean

coverage: ## report which tiers are settling the maths
	$(PY) evals/run_eval.py --json | $(PY) -c "import json,sys; d=json.load(sys.stdin); print(f\"tier 1-2: {d['tier_coverage']:.1%}  abstention: {d['abstention_rate']:.1%}\")"
