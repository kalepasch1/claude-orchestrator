# Legal Gate Policy

## Overview
Certain task classes require owner-only review before merge. The legal
gate prevents automated systems from making changes that could force
licensing, registration, custody, transmission, or advice obligations.

## Trigger Conditions
A task is flagged `owner-only` when the change would:
1. Force licensing or registration requirements
2. Involve custody of user assets or secrets
3. Require transmission of sensitive data
4. Constitute regulated advice (financial, legal, medical)
5. Need a secret or credential to function

## Handling
- Tasks with legal gate are routed to the approval inbox
- They cannot auto-merge even with green tests
- Owner must explicitly approve before release train picks them up
