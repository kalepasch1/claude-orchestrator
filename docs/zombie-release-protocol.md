# Zombie Release Protocol

## Overview
Tasks stuck in RUNNING state beyond their heartbeat window (90 minutes)
are automatically released back to QUEUED by the executor's zombie-release step.

## Mechanism
At the start of each executor loop (Step 0b), a SQL update identifies tasks where:
- `state = 'RUNNING'`
- `updated_at < now() - interval '90 minutes'`
- `account LIKE 'cowork-executor%'`

These are reset to QUEUED with a note indicating zombie release.

## Why 90 Minutes
Balances between giving slow tasks time to complete and not blocking the queue.
Most tasks complete in under 10 minutes; 90 minutes accounts for large repos
and network delays without creating excessive idle time.
