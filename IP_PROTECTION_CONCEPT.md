# Multi-Model IP Protection Concept

## Problem

Founders increasingly worry that a single AI vendor could see enough prompts, code, product logic,
designs, customer workflow, and iteration history to reconstruct the strategic core of an app later.
This concern is sharper for products where design systems, workflows, or end-to-end codebases are
created inside one vendor's agentic environment. A design-native example is the anxiety that a tool
provider could learn enough from app-creation workflows to later launch adjacent first-party products,
as founders may imagine in categories around Figma-like design surfaces or Claude Design-like app
generation.

The goal is not to assume a vendor will misuse data. The goal is to reduce concentration risk: no one
model, vendor, proxy, or account should receive the whole invention unless the user deliberately chooses
that trust level.

## Proposed Architecture

1. Classify each task before routing:
   - public/routine: docs, formatting, generic bugfixes
   - confidential: unreleased product logic, business model, customer workflows, schemas, pricing, security
   - crown-jewel: core algorithms, proprietary UX flows, defensible product strategy, customer data

2. Partition context by need-to-know:
   - planner gets a redacted goal and interfaces, not full source
   - coder gets only the files needed for the change
   - reviewer gets diff plus test output, not the full repo
   - business/legal reviewers get summaries, not implementation details

3. Route by trust tier:
   - local models first for crown-jewel planning/review
   - enterprise/API providers with no-training terms for confidential work
   - consumer accounts only for public/routine work
   - no grey-market API proxies

4. Disable cross-provider fallback for sensitive prompts:
   - a failed provider should fail closed or retry locally
   - fallback can remain enabled for routine/public prompts

5. Keep provenance receipts:
   - record provider, model, prompt hash, file list, sensitivity, and purpose
   - store redacted prompt snapshots for audit
   - make it possible to answer: “Which vendor saw this feature?”

6. Reduce output ownership ambiguity:
   - require human-authored specs, acceptance criteria, review, and final selection
   - preserve human change history in commits
   - document AI assistance in internal invention records

## Founder-Facing Positioning

The pitch is “AI supply-chain privacy for product creation.” Instead of sending the full app to one
model, the orchestrator acts like a confidential work broker. It decomposes the job, redacts context,
routes each subtask to the least-exposed capable model, and keeps an audit trail.

This does not eliminate all legal or data-retention risk. It materially lowers concentration risk and
creates a governance layer a company can explain to customers, investors, counsel, and acquirers.

## Open Questions

- What sensitivity labels should be user-visible versus automatic?
- Should crown-jewel mode be local-only by default?
- Which vendor/account terms qualify for “confidential provider” status?
- What prompt/file receipt data is useful for audit without becoming another sensitive dataset?
- How should this interact with design tools where the visual artifact is the product moat?
