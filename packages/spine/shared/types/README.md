# packages/spine/shared/types

Shared domain types for the compounding-codegen platform spine.

This directory holds type and interface declarations only — no business logic,
no adapters, no DB imports. Sibling slices define the concrete types here
(`Compound`, `Wave`, `Event`, `PipelineNode`, `SpineContext`, …) and import them
from this path.

Git does not track empty directories; this README is what makes the directory
exist on the branch.
