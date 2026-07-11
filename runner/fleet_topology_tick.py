#!/usr/bin/env python3
"""Periodic: fleet topology capacity report and recommendations."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def tick():
    try:
        import fleet_topology
        fleet_topology.invalidate()  # refresh
        cap = fleet_topology.current_capacity()
        if cap:
            print(f"[fleet-topo] machines={cap.get('machines',0)} subs={cap.get('subscriptions',0)} "
                  f"sub_throughput={cap.get('total_sub_throughput',0)}/hr "
                  f"total={cap.get('total_with_api',0)}/hr "
                  f"cost=${cap.get('monthly_sub_cost',0)}/mo")
    except Exception:
        pass

if __name__ == "__main__":
    tick()
