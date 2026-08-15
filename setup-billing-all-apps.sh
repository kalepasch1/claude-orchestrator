#!/usr/bin/env bash
# setup-billing-all-apps.sh — Stripe products/prices/webhooks for apparently,
# apparently-law, and pareto. Idempotent by product name lookup. Never prints secrets.
set -euo pipefail
APPARENTLY=~/Documents/apparently
TEAM="team_oqdBAmSCW7AKVngjcbAPVe0t"
SK=$(grep -m1 '^STRIPE_SECRET_KEY=' "$APPARENTLY/.env" | cut -d= -f2-)
[ -n "$SK" ] || { echo "FATAL: no STRIPE_SECRET_KEY"; exit 1; }

api() { curl -s -u "$SK:" "$@"; }

# link_project <vercel-project-name> — echoes a tmpdir linked to that project
link_project() {
  local d; d=$(mktemp -d)
  ( cd "$d" && vercel link --yes --project "$1" --scope "$TEAM" >/dev/null 2>&1 )
  echo "$d"
}
envadd() { # envadd <linked-dir> <key> <value>
  ( cd "$1" && vercel env rm "$2" production --yes --scope "$TEAM" >/dev/null 2>&1 || true
    printf '%s' "$3" | vercel env add "$2" production --scope "$TEAM" >/dev/null 2>&1 )     && echo "  $2 -> set" || echo "  $2 -> FAILED"
}

jqget() { python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('$1',''))"; }

# find_or_create_price <product_name> <price_json_args...> — echoes price id
ensure_price() {
  local pname="$1"; shift
  local pid
  pid=$(api "https://api.stripe.com/v1/products/search" --data-urlencode "query=name:'$pname'" -G | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['data'][0]['id'] if d.get('data') else '')")
  if [ -z "$pid" ]; then
    pid=$(api https://api.stripe.com/v1/products -d "name=$pname" | jqget id)
    echo "  created product: $pname ($pid)" >&2
  fi
  local price
  price=$(api "https://api.stripe.com/v1/prices" -G -d "product=$pid" -d "active=true" -d "limit=1" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['data'][0]['id'] if d.get('data') else '')")
  if [ -z "$price" ]; then
    price=$(api https://api.stripe.com/v1/prices -d "product=$pid" "$@" | jqget id)
    echo "  created price for $pname: $price" >&2
  fi
  echo "$price"
}

setenv() { # setenv <project-dir-or-name> <key> <value> [also_env_file]
  local proj="$1" k="$2" v="$3" envf="${4:-}"
  ( cd "$APPARENTLY" && vercel env rm "$k" production --yes --scope "$TEAM" >/dev/null 2>&1 || true )
  ( cd "$APPARENTLY" && printf '%s' "$v" | vercel env add "$k" production --scope "$TEAM" >/dev/null ) 2>/dev/null || true
  # note: cd into the right project dir handled by caller via VERCEL_PROJECT override below
  [ -n "$envf" ] && { grep -q "^$k=" "$envf" 2>/dev/null && sed -i '' "s|^$k=.*|$k=$v|" "$envf" || echo "$k=$v" >> "$envf"; }
  echo "  $k -> set"
}

echo "== APPARENTLY (apparently.cc) token packs + metered =="
P_TOK_S=$(ensure_price "Apparently Tokens 1000"  -d "unit_amount=1000"  -d "currency=usd")
P_TOK_M=$(ensure_price "Apparently Tokens 6000"  -d "unit_amount=5000"  -d "currency=usd")
P_TOK_L=$(ensure_price "Apparently Tokens 15000" -d "unit_amount=10000" -d "currency=usd")
P_METER=$(ensure_price "Apparently Usage" -d "currency=usd" -d "recurring[interval]=month" -d "recurring[usage_type]=metered" -d "unit_amount_decimal=2")
cd "$APPARENTLY"
for kv in "TOKEN_PACK_SMALL_PRICE_ID=$P_TOK_S" "TOKEN_PACK_MEDIUM_PRICE_ID=$P_TOK_M" \
          "TOKEN_PACK_LARGE_PRICE_ID=$P_TOK_L" "STRIPE_METERED_PRICE_ID=$P_METER"; do
  k="${kv%%=*}"; v="${kv#*=}"
  vercel env rm "$k" production --yes --scope "$TEAM" >/dev/null 2>&1 || true
  printf '%s' "$v" | vercel env add "$k" production --scope "$TEAM" >/dev/null
  grep -q "^$k=" .env && sed -i '' "s|^$k=.*|$k=$v|" .env || echo "$k=$v" >> .env
  echo "  $k=$v"
done
echo "  (existing STRIPE_STARTER_PRICE_ID / STRIPE_PRO_PRICE_ID subscriptions kept)"

echo "== APPARENTLY LAW (apparentlylaw.com) packs + subscription + webhook =="
L_TOK_S=$(ensure_price "Apparently Law Tokens 1000"  -d "unit_amount=1000"  -d "currency=usd")
L_TOK_M=$(ensure_price "Apparently Law Tokens 6000"  -d "unit_amount=5000"  -d "currency=usd")
L_SUB=$(ensure_price "Apparently Law Counsel Monthly" -d "unit_amount=19900" -d "currency=usd" -d "recurring[interval]=month")
L_METER=$(ensure_price "Apparently Law Usage" -d "currency=usd" -d "recurring[interval]=month" -d "recurring[usage_type]=metered" -d "unit_amount_decimal=2")
# fresh webhook w/ captured secret (the earlier one's secret was never captured — delete + recreate)
OLD=$(api https://api.stripe.com/v1/webhook_endpoints | python3 -c "import sys,json;d=json.load(sys.stdin);print(next((e['id'] for e in d.get('data',[]) if e.get('url')=='https://apparentlylaw.com/api/billing/webhook'),''))")
[ -n "$OLD" ] && api -X DELETE "https://api.stripe.com/v1/webhook_endpoints/$OLD" >/dev/null && echo "  old uncaptured endpoint deleted"
NEWW=$(api -X POST https://api.stripe.com/v1/webhook_endpoints -d "url=https://apparentlylaw.com/api/billing/webhook" \
  -d "enabled_events[]=checkout.session.completed" -d "enabled_events[]=invoice.paid" \
  -d "enabled_events[]=invoice.payment_failed" -d "enabled_events[]=customer.subscription.updated" \
  -d "enabled_events[]=customer.subscription.deleted" -d "enabled_events[]=payment_intent.succeeded" \
  -d "enabled_events[]=charge.refunded")
LWH=$(echo "$NEWW" | jqget secret)
LAWDIR=$(link_project apparently-law)
envadd "$LAWDIR" TOKEN_PACK_SMALL_PRICE_ID "$L_TOK_S"
envadd "$LAWDIR" TOKEN_PACK_MEDIUM_PRICE_ID "$L_TOK_M"
envadd "$LAWDIR" STRIPE_COUNSEL_PRICE_ID "$L_SUB"
envadd "$LAWDIR" STRIPE_METERED_PRICE_ID "$L_METER"
if [ -n "$LWH" ]; then
  envadd "$LAWDIR" STRIPE_WEBHOOK_SECRET "$LWH"
  envadd "$LAWDIR" STRIPE_SECRET_KEY "$SK"
fi
rm -rf "$LAWDIR"

echo "== PARETO (joinpareto.us) consumer subscriptions =="
PP_M=$(ensure_price "Pareto Plus Monthly" -d "unit_amount=999"  -d "currency=usd" -d "recurring[interval]=month")
PP_Y=$(ensure_price "Pareto Plus Annual"  -d "unit_amount=7900" -d "currency=usd" -d "recurring[interval]=year")
PARDIR=$(link_project pareto-2080)
envadd "$PARDIR" STRIPE_PLUS_MONTHLY_PRICE_ID "$PP_M"
envadd "$PARDIR" STRIPE_PLUS_ANNUAL_PRICE_ID "$PP_Y"
envadd "$PARDIR" STRIPE_SECRET_KEY "$SK"
rm -rf "$PARDIR"
echo ""
echo "DONE. Price IDs above are safe to share; queued app shards consume these env names."
