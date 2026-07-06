PROJECT: apparently

- id: cade-index-opinion-precedent
  title: Index finalized opinions as firm precedent for the position engine
  material: no
  model: sonnet
  depends: []
  proof: npm run build && npm test
  prompt: |
    The scaffolding already exists: server/utils/corpus-precedent.ts exports
    indexWorkProductPrecedent() which indexes our own finalized opinions as `firm_work_product`
    precedent (the drafts-as-precedent moat). It is NOT yet called on the opinion-finalize path.
    Wire it in: when an opinion is finalized (the handler that flips an opinion to final /
    the POST /api/firm-api/opinions/draft finalize branch, and/or wherever opinion state becomes
    'final'), call indexWorkProductPrecedent(opinion) fail-soft (never block finalize on an index
    error; log via server/utils/logger.ts). Ensure it is idempotent (re-finalizing the same opinion
    does not double-index — key on opinion id). Then make the position engine's Red-team retrieval
    include these firm-work-product precedents (buildLiveRegulatoryContext / corpusAuthorityDigest
    already flow into the Red context — confirm firm_work_product rows are retrievable there). Add a
    unit test that finalizing an opinion calls the indexer once and that a firm_work_product row is
    queryable. Keep `npm run build` + typecheck green.

OPERATOR:
  - None (uses existing corpus tables + service client).
