#!/usr/bin/env python3
"""
price_arbitrage.py - keep the fleet riding the cheapest capable frontier as provider prices/quality
move. Maintains provider_prices (price + rolling quality) and, when a provider becomes cheaper at
equal/better quality — or degrades — rebalances the routing preference the triage layer uses.

  * refresh_quality(): roll each provider's recent quality from app_operations into provider_prices.
  * rank(task_class): return providers ordered by quality-per-dollar for that capability need.
  * run(): refresh, then for each (app,operation) in app_op_routes, if a materially cheaper equal-quality
    provider exists, update the recommended route (and log the arbitrage move).

Prices come from provider_prices (seed once; update when a provider changes pricing). Non-agentic only;
Anthropic stays on subscription and is never arbitraged here.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MIN_QUALITY = float(os.environ.get("ARB_MIN_QUALITY", "7.0"))
SAVINGS_MIN = float(os.environ.get("ARB_SAVINGS_MIN", "0.2"))  # require >=20% cheaper to switch


def refresh_quality():
    rows = db.select("app_operations", {"select": "provider,model,quality_score",
                                        "quality_score": "not.is.null",
                                        "order": "created_at.desc", "limit": "2000"}) or []
    agg = {}
    for r in rows:
        k = (r["provider"], r["model"])
        a = agg.setdefault(k, [0.0, 0])
        a[0] += float(r.get("quality_score") or 0); a[1] += 1
    for (prov, model), (s, n) in agg.items():
        if n:
            db.insert("provider_prices", {"provider": prov, "model": model,
                      "avg_quality": round(s / n, 2), "updated_at": "now()"}, upsert=True)
    return len(agg)


def _price(row):
    pin = float(row.get("usd_per_mtok_in") or 0)
    pout = float(row.get("usd_per_mtok_out") or 0)
    return (pin + pout) / 2 if (pin or pout) else 0.0001  # ~free/local


def rank(min_quality=MIN_QUALITY):
    prices = db.select("provider_prices", {"select": "*"}) or []
    good = [p for p in prices if (p.get("avg_quality") or 0) >= min_quality or _price(p) < 0.001]
    # quality-per-dollar, cheapest-good first
    good.sort(key=lambda p: (_price(p), -float(p.get("avg_quality") or 0)))
    return good


def run():
    refresh_quality()
    frontier = rank()
    if not frontier:
        print("price_arbitrage: no price/quality data yet")
        return 0
    best = frontier[0]
    moves = 0
    for route in db.select("app_op_routes", {"select": "*"}) or []:
        cur_prices = [p for p in db.select("provider_prices",
                      {"select": "*", "provider": f"eq.{route['provider']}"}) or []]
        cur_cost = _price(cur_prices[0]) if cur_prices else 0.0001
        if _price(best) < cur_cost * (1 - SAVINGS_MIN) and best["provider"] != route["provider"]:
            db.insert("app_op_routes", {"app": route["app"], "operation": route["operation"],
                      "provider": best["provider"], "model": best["model"],
                      "reason": f"arbitrage: {best['provider']} cheaper at q>={MIN_QUALITY}",
                      "avg_quality": best.get("avg_quality"), "updated_at": "now()"}, upsert=True)
            moves += 1
    print(f"price_arbitrage: frontier leader {best['provider']}:{best['model']}; rebalanced {moves} routes")
    return moves


if __name__ == "__main__":
    import json
    print(json.dumps([{"provider": p["provider"], "model": p["model"],
                       "q": p.get("avg_quality"), "price": _price(p)} for p in rank()], indent=2))
