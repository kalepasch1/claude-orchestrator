"""
prompt_distiller.py — Compress winning merged patterns into tighter prompts.

Analyses successfully merged task outcomes, extracts the effective prompt
patterns, and distils them into compact templates that achieve equivalent
quality at lower token cost. Tracks token savings over time.
"""

import re
import json
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class MergedOutcome:
    """A successfully merged task with its prompt and token usage."""
    task_id: str
    slug: str
    prompt: str
    prompt_tokens: int
    completion_tokens: int
    merged_at: str  # ISO timestamp
    quality_score: float = 1.0  # 0-1, from verify pass rate


@dataclass
class DistilledPattern:
    """A compressed prompt pattern extracted from winning outcomes."""
    pattern_id: str
    template: str
    source_slugs: list[str] = field(default_factory=list)
    avg_token_saving_pct: float = 0.0
    usage_count: int = 0
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.pattern_id:
            self.pattern_id = hashlib.sha256(self.template.encode()).hexdigest()[:12]


# ── Prompt compression ────────────────────────────────────────────────────────

# Common verbose patterns and their compact replacements
COMPRESSION_RULES: list[tuple[str, str]] = [
    # Strip agentic repair / remediation boilerplate
    (r"AGENTIC-REPAIR DIRECTIVE.*?(?=\n\n|\Z)", ""),
    (r"AUTO-REMEDIATION DIRECTIVE.*?(?=\n\n|\Z)", ""),
    (r"PREFLIGHT DIRECTIVE.*?(?=\n\n|\Z)", ""),
    (r"Required completion behavior:.*?(?=\n\n|\Z)", ""),
    (r"Failure context:\n```.*?```", ""),
    # Strip redundant instructions
    (r"Do not stop at analysis or manual review\.[^\n]*\n?", ""),
    (r"Make a concrete, tested change and COMMIT it[^\n]*\n?", ""),
    (r"Make the smallest complete code change[^\n]*\n?", ""),
    # Collapse whitespace
    (r"\n{3,}", "\n\n"),
    (r"[ \t]+\n", "\n"),
]


def compress_prompt(raw_prompt: str) -> str:
    """Apply compression rules to strip boilerplate and reduce token count."""
    result = raw_prompt
    for pattern, replacement in COMPRESSION_RULES:
        result = re.sub(pattern, replacement, result, flags=re.DOTALL)
    return result.strip()


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return max(1, len(text) // 4)


# ── Pattern extraction ────────────────────────────────────────────────────────

def extract_core_spec(prompt: str) -> str:
    """Extract the core specification from a prompt, stripping directives."""
    # Take everything before the first directive marker
    markers = ["PRIOR ATTEMPT FAILED", "AUTO-REMEDIATION", "AGENTIC-REPAIR",
               "PREFLIGHT DIRECTIVE", "Failure context:"]
    earliest = len(prompt)
    for marker in markers:
        idx = prompt.find(marker)
        if idx != -1 and idx < earliest:
            earliest = idx
    return prompt[:earliest].strip()


# ── Savings tracker ───────────────────────────────────────────────────────────

@dataclass
class DistillationReport:
    """Tracks token savings from prompt distillation over time."""
    total_prompts_processed: int = 0
    total_original_tokens: int = 0
    total_compressed_tokens: int = 0
    patterns_extracted: int = 0
    savings_by_date: dict[str, float] = field(default_factory=dict)

    @property
    def total_saving_pct(self) -> float:
        if self.total_original_tokens == 0:
            return 0.0
        return (1 - self.total_compressed_tokens / self.total_original_tokens) * 100

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_saving_pct"] = self.total_saving_pct
        return d


def distill_batch(outcomes: list[MergedOutcome]) -> tuple[list[DistilledPattern], DistillationReport]:
    """
    Process a batch of merged outcomes, extract patterns, and report savings.
    """
    report = DistillationReport()
    patterns: dict[str, DistilledPattern] = {}

    for outcome in outcomes:
        original_tokens = estimate_tokens(outcome.prompt)
        compressed = compress_prompt(outcome.prompt)
        compressed_tokens = estimate_tokens(compressed)

        report.total_prompts_processed += 1
        report.total_original_tokens += original_tokens
        report.total_compressed_tokens += compressed_tokens

        # Extract core spec as pattern template
        core = extract_core_spec(outcome.prompt)
        if not core:
            continue

        pid = hashlib.sha256(core.encode()).hexdigest()[:12]
        if pid not in patterns:
            saving_pct = (1 - compressed_tokens / max(1, original_tokens)) * 100
            patterns[pid] = DistilledPattern(
                pattern_id=pid,
                template=core,
                source_slugs=[outcome.slug],
                avg_token_saving_pct=saving_pct,
                usage_count=1,
            )
        else:
            patterns[pid].source_slugs.append(outcome.slug)
            patterns[pid].usage_count += 1

    report.patterns_extracted = len(patterns)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report.savings_by_date[today] = report.total_saving_pct

    return list(patterns.values()), report
