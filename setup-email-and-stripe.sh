#!/usr/bin/env bash
# setup-email-and-stripe.sh — one-command wiring for Tomorrow email + Apparently Stripe.
# Run from ~/Documents/beethoven/claude-orchestrator:   bash setup-email-and-stripe.sh
# Never prints secret values. Requires: vercel CLI logged in (kalepasch1), curl, python3.
set -euo pipefail
APPARENTLY=~/Documents/apparently
TOMORROW=~/Documents/tomorrow/tomorrow
TEAM="team_oqdBAmSCW7AKVngjcbAPVe0t"
APP_DOMAIN="${APP_DOMAIN:-https://apparentlylaw.com}"

val() { grep -m1 "^$2=" "$1/.env" | cut -d= -f2- | tr -d '"' | tr -d "'"; }

echo "== 1/4 Tomorrow email (Resend, from kale@heretomorrow.us)"
RESEND_KEY="$(val "$APPARENTLY" RESEND_API_KEY)"
[ -n "$RESEND_KEY" ] || { echo "FATAL: RESEND_API_KEY not found in apparently/.env"; exit 1; }
cd "$TOMORROW"
for kv in "EMAIL_PROVIDER=resend" "EMAIL_FROM=kale@heretomorrow.us" \
          "EMAIL_FROM_NAME=Here Tomorrow" "EMAIL_SENDING_ENABLED=true"; do
  k="${kv%%=*}"; v="${kv#*=}"
  vercel env rm "$k" production --yes --scope "$TEAM" >/dev/null 2>&1 || true
  printf '%s' "$v" | vercel env add "$k" production --scope "$TEAM" >/dev/null
  grep -q "^$k=" .env 2>/dev/null && sed -i '' "s|^$k=.*|$k=$v|" .env || echo "$k=$v" >> .env
done
vercel env rm RESEND_API_KEY production --yes --scope "$TEAM" >/dev/null 2>&1 || true
printf '%s' "$RESEND_KEY" | vercel env add RESEND_API_KEY production --scope "$TEAM" >/dev/null
grep -q "^RESEND_API_KEY=" .env 2>/dev/null || echo "RESEND_API_KEY=$RESEND_KEY" >> .env
echo "   done (4 config vars + key set in Vercel prod + .env)"

echo "== 2/4 Resend domain check (heretomorrow.us must be verified to send)"
DOMAINS=$(curl -s https://api.resend.com/domains -H "Authorization: Bearer $RESEND_KEY")
if echo "$DOMAINS" | grep -q '"heretomorrow.us"'; then
  echo "$DOMAINS" | python3 -c "import sys,json;d=json.load(sys.stdin);print('   heretomorrow.us status:', next((x['status'] for x in d.get('data',[]) if x['name']=='heretomorrow.us'),'?'))"
else
  echo "   ⚠️  heretomorrow.us NOT in this Resend account. Adding it now..."
  curl -s -X POST https://api.resend.com/domains -H "Authorization: Bearer $RESEND_KEY" \
       -H "Content-Type: application/json" -d '{"name":"heretomorrow.us"}' \
    | python3 -c "import sys,json;d=json.load(sys.stdin);recs=d.get('records',[]);print('   Added. Set these DNS records at your registrar, then click Verify in resend.com/domains:');[print('   ',r.get('record'),r.get('name'),'->',r.get('value','')[:60]) for r in recs]"
fi

echo "== 3/4 Apparently Stripe webhook (live payments path /api/billing/webhook)"
SK="$(val "$APPARENTLY" STRIPE_SECRET_KEY)"
[ -n "$SK" ] || { echo "FATAL: STRIPE_SECRET_KEY not found in apparently/.env"; exit 1; }
HOOK_URL="$APP_DOMAIN/api/billing/webhook"
EXISTING=$(curl -s https://api.stripe.com/v1/webhook_endpoints -u "$SK:" | python3 -c "import sys,json;d=json.load(sys.stdin);print(sum(1 for e in d.get('data',[]) if e.get('url')=='$HOOK_URL' and e.get('status')=='enabled'))")
if [ "$EXISTING" -ge 1 ]; then
  echo "   webhook already registered + enabled for $HOOK_URL"
else
  NEW=$(curl -s -X POST https://api.stripe.com/v1/webhook_endpoints -u "$SK:" \
    -d "url=$HOOK_URL" \
    -d "enabled_events[]=checkout.session.completed" \
    -d "enabled_events[]=invoice.paid" -d "enabled_events[]=invoice.payment_failed" \
    -d "enabled_events[]=customer.subscription.updated" \
    -d "enabled_events[]=customer.subscription.deleted" \
    -d "enabled_events[]=payment_intent.succeeded" -d "enabled_events[]=charge.refunded")
  WHSEC=$(echo "$NEW" | python3 -c "import sys,json;print(json.load(sys.stdin).get('secret',''))")
  [ -n "$WHSEC" ] || { echo "FATAL: webhook create failed: $(echo "$NEW" | head -c 200)"; exit 1; }
  cd "$APPARENTLY"
  vercel env rm STRIPE_WEBHOOK_SECRET production --yes --scope "$TEAM" >/dev/null 2>&1 || true
  printf '%s' "$WHSEC" | vercel env add STRIPE_WEBHOOK_SECRET production --scope "$TEAM" >/dev/null
  sed -i '' "s|^STRIPE_WEBHOOK_SECRET=.*|STRIPE_WEBHOOK_SECRET=$WHSEC|" .env 2>/dev/null || echo "STRIPE_WEBHOOK_SECRET=$WHSEC" >> .env
  echo "   webhook created for $HOOK_URL; signing secret set in Vercel prod + .env"
fi

echo "== 4/4 \$1 live end-to-end test checkout"
LINK=$(curl -s -X POST https://api.stripe.com/v1/checkout/sessions -u "$SK:" \
  -d "mode=payment" -d "line_items[0][price_data][currency]=usd" \
  -d "line_items[0][price_data][product_data][name]=E2E launch test" \
  -d "line_items[0][price_data][unit_amount]=100" -d "line_items[0][quantity]=1" \
  -d "success_url=$APP_DOMAIN/?e2e=paid" -d "cancel_url=$APP_DOMAIN/?e2e=cancelled" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('url',''))")
echo "   PAY THIS (\$1, your card, then refund from the Stripe dashboard if desired):"
echo "   $LINK"
echo ""
echo "DONE. Redeploy Tomorrow + Apparently in Vercel (env applies on next build):"
echo "  cd $TOMORROW && vercel redeploy --prod 2>/dev/null || vercel --prod"
echo "  cd $APPARENTLY && vercel redeploy --prod 2>/dev/null || vercel --prod"
