#!/usr/bin/env bash
# Growth OS activation preflight. Read-only checks — does NOT enable anything.
# Usage: bash growth-os/activate-preflight.sh
set -uo pipefail

ORCH_URL="${ORCH_SUPABASE_URL:-}"
KEY="${ORCH_SUPABASE_SERVICE_KEY:-${ORCH_SUPABASE_ANON_KEY:-}}"
fail=0
ok(){ echo "  ok   $1"; }
bad(){ echo "  MISS $1"; fail=1; }

echo "== env =="
for v in ORCH_SUPABASE_URL ORCH_SUPABASE_ANON_KEY ORCH_SUPABASE_SERVICE_KEY GROWTH_ACTOR_SALT; do
  [ -n "${!v:-}" ] && ok "$v" || bad "$v"
done
echo "  (optional) RESEND_API_KEY=${RESEND_API_KEY:+set} OUTREACH_FROM_EMAIL=${OUTREACH_FROM_EMAIL:-unset}"
echo "  (optional) IMAGE_GEN_URL=${IMAGE_GEN_URL:+set} VISION_SCORE_URL=${VISION_SCORE_URL:+set}"
echo "  (runner)   ENABLE_PROACTIVE_LOOPS=${ENABLE_PROACTIVE_LOOPS:-unset} ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:+set}"

if [ -z "$ORCH_URL" ] || [ -z "$KEY" ]; then
  echo "== cannot reach orchestrator without ORCH_SUPABASE_URL + a key; fix env above =="; exit 1
fi

echo "== connectivity + safety state =="
hdr=(-H "apikey: $KEY" -H "Authorization: Bearer $KEY")
gsw=$(curl -s "${hdr[@]}" "$ORCH_URL/rest/v1/growth_autonomy_switch?scope=eq.global&select=mode")
echo "  global switch: $gsw"
echo "$gsw" | grep -q '"off"' && ok "global switch OFF (safe)" || echo "  WARN global switch is not off"

loops=$(curl -s "${hdr[@]}" "$ORCH_URL/rest/v1/loops?project=eq.claude-orchestrator&select=type&type=in.(growth_learn,colosseum,bd_autopilot,creative_gen)")
echo "  growth loops: $loops"
for l in growth_learn colosseum bd_autopilot creative_gen; do echo "$loops" | grep -q "\"$l\"" && ok "loop $l" || bad "loop $l"; done

# RPC smoke test (read-only functions)
cf=$(curl -s "${hdr[@]}" -H "Content-Type: application/json" -X POST "$ORCH_URL/rest/v1/rpc/counterfactual_value" -d '{}')
echo "  counterfactual_value RPC -> $cf"

echo "== result =="
[ "$fail" -eq 0 ] && echo "PREFLIGHT PASS — safe to start the runner and stage one campaign in Approval mode." \
                  || echo "PREFLIGHT INCOMPLETE — set the MISS items above, then re-run."
exit $fail
