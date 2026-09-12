"""Child lanes graduating to their own accounts.

A child's lane starts fully supervised and graduates in stages —
SUPERVISED -> ASSISTED -> INDEPENDENT. Graduation is deliberately not
automatic on age alone: a guardian must approve each step, and the child must
meet the age floor for the target stage.

FAILS CLOSED: a graduation requested by a non-guardian, below the age floor,
or on a malformed lane leaves the lane exactly where it was.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Iterable

from passport import has_authority_over

log = logging.getLogger(__name__)

#: Ordered stages, least to most independent.
STAGE_SUPERVISED = "supervised"
STAGE_ASSISTED = "assisted"
STAGE_INDEPENDENT = "independent"
_STAGE_ORDER = (STAGE_SUPERVISED, STAGE_ASSISTED, STAGE_INDEPENDENT)

#: Minimum age for each stage. A child below the floor cannot graduate into it.
STAGE_AGE_FLOOR = {
    STAGE_SUPERVISED: 0,
    STAGE_ASSISTED: 13,
    STAGE_INDEPENDENT: 18,
}


@dataclass
class ChildLane:
    """A child's supervised lane within the household mesh."""
    child_id: str = ""
    household_id: str = ""
    stage: str = STAGE_SUPERVISED
    age: int = 0
    own_account_id: str = ""

    @property
    def has_own_account(self) -> bool:
        """True once the lane has graduated and been given an account."""
        return self.stage == STAGE_INDEPENDENT and bool(self.own_account_id.strip())


def _stage_index(lane: Any) -> int:
    """Position of ``lane``'s stage; -1 if unrecognized."""
    stage = getattr(lane, "stage", None)
    if not isinstance(stage, str):
        return -1
    try:
        return _STAGE_ORDER.index(stage.strip().lower())
    except ValueError:
        return -1


def _valid_lane(lane: Any) -> bool:
    """True for a lane with a usable child_id and a recognized stage."""
    if lane is None:
        return False
    child_id = getattr(lane, "child_id", None)
    if not isinstance(child_id, str) or not child_id.strip():
        return False
    return _stage_index(lane) >= 0


def graduate(
    passports: Iterable[Any], lane: Any, guardian_id: str
) -> tuple[Any, str]:
    """Advance ``lane`` one stage. Returns ``(lane, reason)``.

    FAILS CLOSED — every refusal returns the ORIGINAL lane unchanged.
    """
    try:
        if not _valid_lane(lane):
            log.warning("child_lanes: malformed lane %r; denying", lane)
            return lane, "denied: malformed lane"
        if not isinstance(guardian_id, str) or not guardian_id.strip():
            return lane, "denied: no guardian identified"

        guardian = guardian_id.strip()
        child = lane.child_id.strip()

        if guardian == child:
            return lane, "denied: a child cannot graduate their own lane"

        if not has_authority_over(passports, guardian, child):
            log.warning(
                "child_lanes: %s has no guardian_of edge to %s; denying",
                guardian, child,
            )
            return lane, f"denied: {guardian} is not a guardian of {child}"

        index = _stage_index(lane)
        if index >= len(_STAGE_ORDER) - 1:
            return lane, "no-op: lane is already independent"

        target = _STAGE_ORDER[index + 1]
        floor = STAGE_AGE_FLOOR[target]
        try:
            age = int(getattr(lane, "age", 0) or 0)
        except (TypeError, ValueError):
            return lane, "denied: lane has an unreadable age"

        if age < floor:
            return lane, f"denied: {target} requires age {floor}, lane is {age}"

        return replace(lane, stage=target), (
            f"granted: {child} graduated {_STAGE_ORDER[index]} -> {target} by {guardian}"
        )
    except Exception as exc:
        log.warning("child_lanes: graduation failed (%s); denying", exc)
        return lane, f"denied: graduation errored ({exc})"


def open_own_account(
    passports: Iterable[Any], lane: Any, guardian_id: str, account_id: str
) -> tuple[Any, str]:
    """Attach an own-account to an independent lane.

    FAILS CLOSED: refuses unless the lane has already reached INDEPENDENT and
    the actor holds authority over the child.
    """
    try:
        if not _valid_lane(lane):
            return lane, "denied: malformed lane"
        if not isinstance(account_id, str) or not account_id.strip():
            return lane, "denied: no account identified"
        if not isinstance(guardian_id, str) or not guardian_id.strip():
            return lane, "denied: no guardian identified"

        guardian = guardian_id.strip()
        child = lane.child_id.strip()

        if not has_authority_over(passports, guardian, child):
            return lane, f"denied: {guardian} is not a guardian of {child}"

        if _stage_index(lane) < len(_STAGE_ORDER) - 1:
            return lane, "denied: lane must reach independent before opening an account"

        return replace(lane, own_account_id=account_id.strip()), (
            f"granted: {child} opened own account {account_id.strip()}"
        )
    except Exception as exc:
        log.warning("child_lanes: account open failed (%s); denying", exc)
        return lane, f"denied: account open errored ({exc})"


def lanes_ready_to_graduate(lanes: Iterable[Any]) -> list[Any]:
    """Lanes that meet the age floor for their next stage.

    Advisory only — a guardian still has to call :func:`graduate`.
    """
    out: list[Any] = []
    for lane in list(lanes or []):
        if not _valid_lane(lane):
            log.warning("child_lanes: skipping malformed lane %r", lane)
            continue
        index = _stage_index(lane)
        if index >= len(_STAGE_ORDER) - 1:
            continue
        try:
            age = int(getattr(lane, "age", 0) or 0)
        except (TypeError, ValueError):
            continue
        if age >= STAGE_AGE_FLOOR[_STAGE_ORDER[index + 1]]:
            out.append(lane)
    return out
