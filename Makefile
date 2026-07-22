BASE_URL ?= http://localhost:3000
E2E_SUPABASE_URL ?=
E2E_SESSION_JSON ?=

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
	npx --prefix web playwright test

test:
	npm --prefix web run test

.PHONY: test test-e2e
