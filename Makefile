# Tributary developer commands.
SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend

.PHONY: help setup setup-api setup-client db-init \
	dev dev-api dev-client \
	test-api lint-api format-api check-api \
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

db-init: ## Create the SQLite database and tables
	cd $(BACKEND_DIR) && uv run tributary init-db

dev: ## Run the API and the reader together
	@$(MAKE) --no-print-directory -j2 dev-api dev-client

dev-api: db-init ## Run the API at http://127.0.0.1:8000
	cd $(BACKEND_DIR) && uv run tributary serve

dev-client: ## Run the reader at http://localhost:3000
	cd $(FRONTEND_DIR) && pnpm dev

test-api: ## Run the backend test suite
	cd $(BACKEND_DIR) && uv run pytest

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
