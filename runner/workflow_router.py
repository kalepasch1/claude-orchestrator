#!/usr/bin/env python3
"""Adaptive workflow router (2026-07-28).

The orchestrator historically forced EVERY objective through the same heavy pipeline:
shard into many small tasks -> cold agent per task -> verify -> QA -> serialized merge
train. That is optimal for broad, independent, multi-area work that runs unattended, but
it is pure overhead for a coherent single-body build (where one capable agent holding full
context is far faster) or for trivial/mechanical changes.

This module classifies each objective and returns an ExecutionProfile that tunes HOW the
work is decomposed and executed, so the fleet optimizes for the RIGHT thing per task:
speed, throughput, safety, or cost. It is deliberately deterministic + dependency-free so
it can never stall planning; the default profile reproduces the historical behavior, so an
unclassified objective behaves exactly as before.

Extending: add a profile to WORKFLOW_PROFILES and a branch to classify(). New "intelligence
pathways" (e.g. a research-spike lane, a docs-only lane, a data-migration lane) are just new
profiles — the planner honors profile.shard / model_hint / max_tasks uniformly.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, asdict


@dataclass
class ExecutionProfile:
    mode: str            # fast_coherent | parallel_fleet | governed_heavy | cheap_bulk | research
    shard: str           # none | light | full   — how planner decomposes the objective
    max_tasks: int       # hard cap on task count for this objective
    model_hint: str      # opus | sonnet | haiku — default model for tasks lacking their own
    verify_depth: str    # none | light | full   — advisory to the verify stage
    qa: bool             # whether the QA reviewer pass should run
    merge_target: str    # dev | main            — where the batch integrates (advisory)
    batch_size: int      # merge-train batch hint (advisory; sensitive work stays small)
    parallelism: str     # low | normal | high   — lane hint
    material: bool        # force materiality gates on every task
    rationale: str = ""

    def as_dict(self):
        return asdict(self)


# Registry — the default (parallel_fleet) reproduces historical behavior exactly.
WORKFLOW_PROFILES = {
    # Coherent single-body build in one repo: a few large opus tasks that keep context,
    # light verification, no QA gate, fast integration. This is the "build it like Cowork
    # does — one mind, in sequence" lane. FASTEST for coherent non-material work.
    "fast_coherent":  ExecutionProfile("fast_coherent",  "light", 3,  "opus",   "light", False, "dev", 8, "low",    False,
                                       "coherent single-repo body; keep context, minimize merge-train hops"),
    # Broad, independent, multi-area work: full section shard, many parallel sonnet tasks.
    "parallel_fleet": ExecutionProfile("parallel_fleet", "full",  24, "sonnet", "full",  True,  "dev", 3, "high",   False,
                                       "broad/independent work benefits from wide parallelism"),
    # Material / legal / compliance / swaps / pricing / auth / migrations: full gates + QA,
    # but grouped into fewer, larger, opus tasks so gated work still moves (fewer merge
    # cycles, more coherence) WITHOUT weakening any safety gate.
    "governed_heavy": ExecutionProfile("governed_heavy", "light", 6,  "opus",   "full",  True,  "dev", 1, "normal", True,
                                       "material work: full gates + QA, coherent opus tasks, sensitive batching"),
    # Trivial/mechanical: one cheap haiku task, minimal ceremony.
    "cheap_bulk":     ExecutionProfile("cheap_bulk",     "none",  1,  "haiku",  "light", False, "dev", 12, "normal", False,
                                       "trivial mechanical change; minimize cost + ceremony"),
    # Research / spike / audit: one strong task, no code-merge, no QA — produces findings.
    "research":       ExecutionProfile("research",       "none",  1,  "opus",   "none",  False, "dev", 4, "low",    False,
                                       "investigation/spike: produce findings, not a merge"),
}

DEFAULT_MODE = "parallel_fleet"

# --- signal detectors -------------------------------------------------------

_MATERIAL_RE = re.compile(
    r"\b(complian\w+|regulat\w+|legal|counsel|licens\w+|swap|ecp|hedge|tranche|standby|"
    r"pricing|token[- ]?pric|securit\w+|reg\s?d|migration|schema|rls|auth|payment|stripe|"
    r"plaid|otc|insurance|malpractice|kyc|aml|sanction|fund(s|ing)?\b|custod\w+)\b", re.I)

_RESEARCH_RE = re.compile(r"\b(research|investigate|spike|explore|audit|analy[sz]e|assess|evaluate)\b", re.I)
_BUILD_RE    = re.compile(r"\b(implement|build|add|create|wire|fix|refactor|migrate|ship|write code|endpoint|component|page)\b", re.I)
_TRIVIAL_RE  = re.compile(r"\b(rename|typo|bump|lint|format|comment|copy\s?edit|whitespace|readme)\b", re.I)
_OVERRIDE_RE = re.compile(r"^\s*WORKFLOW:\s*([a-z_]+)\s*$", re.I | re.M)


def _count_sections(text: str) -> int:
    return len(re.findall(r'(?m)^\s*(?:#{2,4}\s+\S|\d+[.)]\s+\S)', text or ""))


def _is_material(text: str) -> bool:
    return bool(_MATERIAL_RE.search(text or ""))


# --- classification ---------------------------------------------------------

def classify(text: str, *, project: str | None = None, projects=None,
             material: bool | None = None) -> str:
    """Return a workflow mode name. Deterministic; safe on any input."""
    text = text or ""
    # 0) explicit override wins — an author or operator can force a lane.
    env_override = os.environ.get("PLAN_WORKFLOW", "").strip().lower()
    m = _OVERRIDE_RE.search(text)
    forced = (m.group(1).lower() if m else "") or env_override
    if forced in WORKFLOW_PROFILES:
        return forced

    n = len(text)
    sections = _count_sections(text)
    mat = _is_material(text) if material is None else bool(material)

    # 1) material/legal/compliance -> governance lane regardless of size.
    if mat:
        return "governed_heavy"
    # 2) pure research/spike (asks to investigate, not to build).
    if _RESEARCH_RE.search(text) and not _BUILD_RE.search(text):
        return "research"
    # 3) trivial/mechanical + short.
    if n < 500 and _TRIVIAL_RE.search(text) and sections <= 1:
        return "cheap_bulk"
    # 4) coherent single body: few sections OR small — one mind, fast.
    proj_count = len(projects or ([project] if project else []))
    if proj_count <= 1 and (sections <= 4 or n < 4000):
        return "fast_coherent"
    # 5) broad/independent -> wide parallel fleet (historical default).
    return DEFAULT_MODE


def profile_for(text: str, *, project: str | None = None, projects=None,
                material: bool | None = None) -> ExecutionProfile:
    mode = classify(text, project=project, projects=projects, material=material)
    prof = WORKFLOW_PROFILES.get(mode, WORKFLOW_PROFILES[DEFAULT_MODE])
    # material always forces the material flag on, even if a lighter lane was chosen.
    if (material is True or _is_material(text)) and not prof.material:
        prof = ExecutionProfile(**{**prof.as_dict(), "material": True})
    return prof
