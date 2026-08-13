# Claude Orchestrator — top-level convenience targets

# E2E configuration (override on CLI or via env)
BASE_URL          ?= http://localhost:3000
E2E_SUPABASE_URL  ?=
E2E_SESSION_JSON  ?=

.PHONY: test-e2e install-e2e lock lock-check install-deps check-build-tools

## check-build-tools: verify the C toolchain needed to build native extensions
##
## Probes by actually compiling a program — `gcc --version` succeeding is not
## proof of a usable toolchain when the SDK/headers are absent. Fails only on
## genuinely required tools (compiler, make); cmake and Python headers are
## reported as warnings.
check-build-tools:
	@bash scripts/check-build-tools.sh

## install-deps: install the exact locked Python dependency set
##
## Toolchain-checked first: a source build of any unwheeled dependency needs a
## working compiler, and failing here is far clearer than a pip build error.
install-deps: check-build-tools
	python3 -m pip install --break-system-packages -r requirements.lock

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
