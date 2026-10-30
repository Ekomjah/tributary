# Tributary developer commands.
SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend

PG_CONTAINER := tributary-pg-test
PG_PORT := 55432
PG_URL := postgresql+psycopg://tributary:tributary@127.0.0.1:$(PG_PORT)/tributary_test

.PHONY: help setup setup-api setup-client db-init db-migrate db-revision \
	pg-start pg-stop db-init-postgres \
	dev dev-api dev-client \
	test-api test-api-postgres lint-api format-api check-api \
	lint-client typecheck-client test-client build-client check-client \
	ci clean

help: ## Show available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: setup-api setup-client ## Install backend and frontend dependencies

setup-api: ## Install backend dependencies with uv
	cd $(BACKEND_DIR) && uv sync --group dev

setup-client: ## Install frontend dependencies with pnpm
	cd $(FRONTEND_DIR) && pnpm install

db-init: ## Create the database and apply migrations
	cd $(BACKEND_DIR) && uv run tributary init-db

db-migrate: ## Apply pending Alembic migrations
	cd $(BACKEND_DIR) && uv run tributary init-db

db-revision: ## Autogenerate a migration (make db-revision m="add users")
	cd $(BACKEND_DIR) && uv run alembic revision --autogenerate -m "$(m)"

pg-start: ## Start a disposable PostgreSQL 16 for the Postgres suite
	@docker rm -f $(PG_CONTAINER) >/dev/null 2>&1 || true
	@docker run --rm -d --name $(PG_CONTAINER) \
		-e POSTGRES_USER=tributary \
		-e POSTGRES_PASSWORD=tributary \
		-e POSTGRES_DB=tributary_test \
		-p $(PG_PORT):5432 \
		--tmpfs /var/lib/postgresql/data \
		postgres:16-alpine >/dev/null
	@for i in $$(seq 1 30); do \
		if docker exec $(PG_CONTAINER) pg_isready -U tributary -d tributary_test \
			>/dev/null 2>&1; then exit 0; fi; \
		sleep 1; \
	done; \
	echo "PostgreSQL did not become ready on port $(PG_PORT)" >&2; exit 1

pg-stop: ## Stop and remove the disposable PostgreSQL container
	-@docker stop $(PG_CONTAINER) >/dev/null

db-init-postgres: ## Apply migrations to the disposable PostgreSQL database
	cd $(BACKEND_DIR) && DATABASE=postgres DATABASE_URL="$(PG_URL)" \
		uv run tributary init-db

dev: ## Run the API and the reader together
	@$(MAKE) --no-print-directory -j2 dev-api dev-client

dev-api: db-init ## Run the API at http://127.0.0.1:8000
	cd $(BACKEND_DIR) && uv run tributary serve

dev-client: ## Run the reader at http://localhost:3000
	cd $(FRONTEND_DIR) && pnpm dev

test-api: ## Run the backend test suite
	cd $(BACKEND_DIR) && uv run pytest

test-api-postgres: pg-start ## Run the backend suite against PostgreSQL
	cd $(BACKEND_DIR) && TRIBUTARY_TEST_DATABASE_URL="$(PG_URL)" uv run pytest

lint-api: ## Lint the backend with ruff
	cd $(BACKEND_DIR) && uv run ruff check .

format-api: ## Format the backend with ruff
	cd $(BACKEND_DIR) && uv run ruff format .

check-api: lint-api test-api ## Lint and test the backend

lint-client: ## Lint the frontend with ESLint
	cd $(FRONTEND_DIR) && pnpm lint

typecheck-client: ## Type-check the frontend with tsc
	cd $(FRONTEND_DIR) && pnpm exec tsc --noEmit

test-client: ## Run the frontend tests with Vitest
	cd $(FRONTEND_DIR) && pnpm test

build-client: ## Build the frontend for production
	cd $(FRONTEND_DIR) && pnpm build

check-client: lint-client test-client build-client ## Lint, test and build the frontend

ci: check-api check-client ## Run everything CI runs

clean: ## Remove build and test caches
	rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.ruff_cache $(FRONTEND_DIR)/.next
	find $(BACKEND_DIR) -type d -name __pycache__ -prune -exec rm -rf {} +
