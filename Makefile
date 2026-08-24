# Claude Orchestrator — top-level convenience targets

# E2E configuration (override on CLI or via env)
BASE_URL          ?= http://localhost:3000
E2E_SUPABASE_URL  ?=
E2E_SESSION_JSON  ?=

.PHONY: test-e2e install-e2e lock lock-check install-deps install-all-deps verify-deps \
        prepare-worktree check-worktree

## prepare-worktree: link node_modules from the main checkout into an agent worktree
##
## A fresh worktree has only tracked files, so every node workspace comes up with
## node_modules missing and `verify-deps` fails on six manifests. Linking costs
## milliseconds; `npm install` per worktree costs minutes and ~1GB for a branch
## that lives for one task. No-op in the main checkout.
prepare-worktree:
	bash scripts/prepare-worktree.sh

## check-worktree: fail if this worktree still has unlinked node workspaces
check-worktree:
	bash scripts/prepare-worktree.sh --check

## install-deps: install the exact locked Python dependency set
install-deps:
	python3 -m pip install --break-system-packages -r requirements.lock

## install-all-deps: install every language manifest (python + all node workspaces)
install-all-deps:
	bash scripts/install-language-deps.sh

## verify-deps: fail if any declared dependency is missing from the environment
verify-deps:
	bash scripts/install-language-deps.sh --verify

## lock: regenerate requirements.lock from the currently installed set
lock:
	python3 scripts/lockfile.py generate

## lock-check: fail if the installed set has drifted from requirements.lock
lock-check:
	python3 scripts/lockfile.py verify


## install-e2e: install Playwright and download the Chromium browser binary
install-e2e:
	npm --prefix web install
	npx --prefix web playwright install chromium --with-deps

## test-e2e: run all critical-path E2E journey tests
##
## Unauthenticated journeys (J1–J6) always run.
## Authenticated journeys (J7–J10) run when E2E_SUPABASE_URL and E2E_SESSION_JSON are set:
##
##   make test-e2e \
##     BASE_URL=https://my-staging.vercel.app \
##     E2E_SUPABASE_URL=https://abc123.supabase.co \
##     E2E_SESSION_JSON='{"access_token":"...","refresh_token":"...","expires_at":1234567890,"user":{...}}'
test-e2e:
	@echo "Running E2E tests against: $(BASE_URL)"
	BASE_URL=$(BASE_URL) \
	E2E_SUPABASE_URL=$(E2E_SUPABASE_URL) \
	E2E_SESSION_JSON=$(E2E_SESSION_JSON) \
	npm --prefix web run test:e2e
