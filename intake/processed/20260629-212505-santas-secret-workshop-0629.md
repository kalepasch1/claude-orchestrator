PROJECT: santas-secret-workshop

# Repo: /Users/kpasch/Documents/hisanta (the Expo/RN kids' good-deeds app; default branch master).

- id: memorybook-preview-keepsake-tone
  title: Align the MemoryBookPreview modal to the calmer keepsake tone
  material: no
  model: haiku
  depends: []
  proof: `npx tsc --noEmit` exits 0
  prompt: |
    A prior session shipped the keepsake Memory Book (components/family/KeepsakeBook.tsx) +
    seasonal theming (constants/seasons.ts, getKeepsakeAccent/useSeasonTheme) and wired the
    seasonal accent into app/(family)/memory-book/[childId].tsx.
    The older MemoryBookPreview modal (used in sparks.tsx) still has its own non-seasonal styling and
    an "Your story starts now!" empty state that doesn't match the calmer keepsake voice.
    Deliverable: restyle MemoryBookPreview to the keepsake tone — reuse the existing T.type/T.space
    tokens + getKeepsakeAccent(useSeasonTheme()) for the header accent, and soften the empty-state
    copy to match KeepsakeBook ("Your story starts here"). Token-driven (no scattered hardcoded hex),
    age-appropriate/calm, a11y (accessibilityLabel/role on interactive + image elements),
    reduced-motion safe. Verify the app typechecks clean.

OPERATOR:
  - One-time scratch cleanup (mount blocked rm in the Cowork sandbox): `rm .tc-verify.js`.
