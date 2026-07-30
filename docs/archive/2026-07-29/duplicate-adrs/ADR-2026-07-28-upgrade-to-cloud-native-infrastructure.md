# Upgrade to Cloud-Native Infrastructure

**Date:** 2026-07-28
**Status:** Accepted
**Proof hash:** `9bdbc8e84038f0700127af1c12a878b11ae3611e4eb421a33e99bda025d9510f`

## Decision

ESCALATE (high-stakes debate)

## Contributors

{'chair': 'Chief Cloud Architect', 'expert': 'Architecture & Scalability', 'weight': 1.4, 'verdict': 'conditional', 'key_risk': 'none', 'position': 'The proposal lacks a concrete orchestration layer for runner identity and session continuity, which is essential to prevent state loss and split-brain during scaling. Scaling stateful runners on plain', 'conviction': 9.0}, {'chair': 'Director of Cloud Economics', 'expert': 'Finance & Unit Economics', 'weight': 1.4, 'verdict': 'oppose', 'key_risk': 'None', 'position': 'The committee cannot support the proposal to migrate all runners to cloud VMs and managed databases without rigorous financial planning and cost optimization controls, as this would replicate the TCO-', 'conviction': 9.0}, {'chair': 'Chief Privacy Officer', 'expert': 'Legal & Compliance', 'weight': 1.4, 'verdict': 'conditional', 'key_risk': 'none', 'position': 'The committee strongly supports migrating the Supabase backend to managed cloud databases only if mandatory jurisdictional controls are fully implemented and verified. Without these, the migration wou', 'conviction': 9.0}, {'chair': 'VP of Customer Success', 'expert': 'Business Development & Marketing', 'weight': 1.3, 'verdict': 'conditional', 'key_risk': 'none', 'position': 'The committee strongly supports migrating to a cloud‑native infrastructure for its scalability and reliability gains, but unanimously insists that the migration must be executed with zero downtime and', 'conviction': 8.0}

## Factions

[{'share': 0.745, 'stance': 'conditional', 'experts': ['Architecture & Scalability', 'Legal & Compliance', 'Business Development & Marketing'], 'argument': 'The proposal lacks a concrete orchestration layer for runner identity and session continuity, which is essential to prevent state loss and split-brain during scaling. Scaling stateful runners on plain'}, {'share': 0.255, 'stance': 'oppose', 'experts': ['Finance & Unit Economics'], 'argument': 'The committee cannot support the proposal to migrate all runners to cloud VMs and managed databases without rigorous financial planning and cost optimization controls, as this would replicate the TCO-'}]

## Counter-arguments (dissent)

['Finance & Unit Economics: None']
