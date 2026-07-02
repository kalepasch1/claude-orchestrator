PROJECT: apparently

- id: darwin-regulatory-change-feed
  title: Emit governed regulatory-change signals from regulator-intel into the living-compliance pipeline
  material: yes
  model: sonnet
  depends: []
  proof: `npx vitest run server/__tests__/regulatoryChangeFeed.test.ts` exits 0
  prompt: |
    Apparently already harvests regulator-intel (govinfo / regulations.gov / courtlistener) and runs a
    corpus-authority digest. Turn a detected, material rule change into a structured signal that the
    kernel's living-compliance pipeline consumes (which recompiles + re-attests the affected product's
    constitution, human-ratified). Additive; the kernel vendor + DARWIN_KERNEL_ADOPTION.md apply.
    Steps:
    1. Add server/utils/darwin/regulatoryChangeFeed.ts: from a corpus/regulator-intel finding, build a
       RegulatoryChange { jurisdiction, topic, affectedProducts[], summary, citation, effectiveDate,
       severity }. Only emit when grounded by a verbatim citation (reuse the Document-Intake grounding
       rule — no citation, no signal).
    2. Persist each change as a row + (when the kernel is vendored) call
       @darwin/kernel/governance.applyRegulatoryChange() to produce a proposed-constitution + change
       attestation for human ratification; never auto-ratify. Fail-soft if the kernel/table is absent.
    3. Add server/__tests__/regulatoryChangeFeed.test.ts: an ungrounded finding emits NO signal; a
       grounded cap-tightening finding emits a RegulatoryChange with the citation and the right
       affectedProducts.

OPERATOR:
  - Vendor @darwin/kernel into apparently (see DARWIN_KERNEL_ADOPTION.md) if not already done by the darwin-kernel adoption tasks.
  - Schedule the feed off the existing regulator-intel refresh cron; route proposed constitution changes to the human ratification queue (cooling-off), never auto-apply.
