"""Shared contracts for the barks modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class Result:
    ok: bool
    error: str = ""
    data: Any = None


@dataclass
class Claim:
    text: str
    source_span: tuple[int, int] = (0, 0)


@dataclass
class OutreachDraft:
    claims: list = field(default_factory=list)
    body: str = ""


@dataclass
class HumanGateTask:
    description: str
    status: str = "PENDING"  # PENDING / APPROVED / DENIED


@dataclass
class GiftOpportunity:
    name: str
    deadline: date
    requirements: list = field(default_factory=list)


@dataclass
class GrantApplication:
    opportunity_name: str
    deadline: date
    draft_text: str = ""
    gates: list = field(default_factory=list)
    submittable: bool = False
