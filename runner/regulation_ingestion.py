"""Approved-source regulatory ingestion.

Wraps ``regulation_scanner.PredictiveRegulationScanner`` — which is deliberately
adapter-only — with the four things production needs and it does not have:

    source registry -> robots/terms-aware fetch -> content-version storage
                    -> change extraction (confidence + provenance)
                    -> compliance event publication

WHY THE SCANNER STAYS ADAPTER-ONLY
    ``PredictiveRegulationScanner`` raises unless a fetch callable is injected, and
    that is correct: it means the scanner itself can never reach the network, so no
    future edit to it can start scraping. This module supplies the ONE approved
    adapter, and the approval logic lives here where it can be audited, rather than
    inside the thing doing the scanning.

DO NOT SCRAPE OR FETCH UNAPPROVED SOURCES
    That is enforced three ways, not documented once:
      1. the registry is an allowlist and ``fetch`` refuses anything absent from it
      2. robots.txt is consulted and a disallow is fatal, not advisory
      3. a source whose terms forbid automated access is refused even if it is in
         the registry and robots permits — terms are the narrowest gate and win

    Each refusal raises a distinct exception so a caller cannot collapse them into
    one "fetch failed" branch and retry past the reason.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Protocol

from regulation_scanner import PredictiveRegulationScanner, RegulationChange


# --------------------------------------------------------------------------- #
# Source registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ApprovedSource:
    """One source we are permitted to read.

    ``terms_allow_automated_access`` defaults to False. An unreviewed source is a
    forbidden source: the failure we are guarding against is a source silently
    becoming fetchable because nobody filled a field in.
    """

    source_id: str
    url: str
    regulator_id: str
    jurisdiction: str
    terms_allow_automated_access: bool = False
    terms_reviewed_at: str | None = None
    terms_reviewed_by: str | None = None
    #: Minimum seconds between fetches, from the source's own stated crawl policy.
    min_interval_seconds: int = 3600


class SourceRegistry:
    """The allowlist. Nothing outside it is fetchable."""

    def __init__(self, sources: Iterable[ApprovedSource] = ()) -> None:
        self._by_id: dict[str, ApprovedSource] = {}
        self._by_url: dict[str, ApprovedSource] = {}
        for source in sources:
            self.register(source)

    def register(self, source: ApprovedSource) -> None:
        self._by_id[source.source_id] = source
        self._by_url[source.url] = source

    def get(self, source_id: str) -> ApprovedSource | None:
        return self._by_id.get(source_id)

    def by_url(self, url: str) -> ApprovedSource | None:
        return self._by_url.get(url)

    def approved_urls(self) -> list[str]:
        return sorted(self._by_url)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._by_id)


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #


class IngestionRefused(RuntimeError):
    """Base class so callers can catch the family, and subclasses so they cannot
    accidentally treat 'not approved' as a transient error and retry past it."""


class SourceNotApproved(IngestionRefused):
    def __init__(self, url: str) -> None:
        super().__init__(
            f"{url} is not in the approved-source registry. Unapproved sources are "
            f"never fetched, and this is not a transient failure to retry past."
        )


class RobotsDisallowed(IngestionRefused):
    def __init__(self, url: str, rule: str) -> None:
        super().__init__(
            f"robots.txt disallows {url} (rule: {rule}). A disallow is fatal here, "
            f"not advisory."
        )


class TermsForbidAutomatedAccess(IngestionRefused):
    def __init__(self, source_id: str) -> None:
        super().__init__(
            f"source {source_id} has no reviewed terms permitting automated access. "
            f"Terms are the narrowest gate and win over registry membership and "
            f"robots.txt alike; an unreviewed source is a forbidden source."
        )


class MalformedSourceResponse(IngestionRefused):
    """Raised for a response we will not store. Distinct from a refusal to fetch:
    we were allowed to look, and what came back is unusable."""


# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #


def path_of(url: str) -> str:
    without_scheme = re.sub(r"^[a-z]+://", "", url, flags=re.I)
    slash = without_scheme.find("/")
    return without_scheme[slash:] if slash != -1 else "/"


def robots_disallows(robots_txt: str, url: str, agent: str = "*") -> str | None:
    """Return the matching Disallow rule, or None.

    Deliberately conservative: an unparseable robots.txt is treated as disallowing
    everything. The alternative — treating a malformed policy as permission — gets
    the answer wrong in the one direction that matters.
    """
    if robots_txt is None:
        return "/"
    text = robots_txt.strip()
    if not text:
        return None

    target = path_of(url)
    applies = False
    matched: str | None = None
    saw_any_directive = False

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            applies = value == "*" or value.lower() == agent.lower()
            saw_any_directive = True
        elif key == "disallow" and applies:
            saw_any_directive = True
            if value == "":
                continue  # "Disallow:" with no path allows everything
            if target.startswith(value):
                matched = value
                break

    if not saw_any_directive:
        return "/"  # unparseable: refuse
    return matched


# --------------------------------------------------------------------------- #
# Content versions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ContentVersion:
    source_id: str
    content_hash: str
    #: Normalised text actually compared. Stored so a diff is reproducible.
    normalised: str
    fetched_at: str
    byte_length: int


class ContentVersionStore:
    """Append-only per source. Versions are never rewritten: an ingestion history
    that can be edited is not provenance."""

    def __init__(self) -> None:
        self._versions: dict[str, list[ContentVersion]] = {}

    def latest(self, source_id: str) -> ContentVersion | None:
        versions = self._versions.get(source_id)
        return versions[-1] if versions else None

    def append(self, version: ContentVersion) -> ContentVersion:
        self._versions.setdefault(version.source_id, []).append(version)
        return version

    def history(self, source_id: str) -> list[ContentVersion]:
        return list(self._versions.get(source_id, ()))

    def version_count(self, source_id: str) -> int:
        return len(self._versions.get(source_id, ()))


def normalise_content(text: str) -> str:
    """Collapse the noise that changes on every fetch without the content changing.

    Timestamps, session ids and whitespace churn produce a different hash on every
    poll, which turns a change detector into an alarm that is always on — and an
    alarm that is always on is one nobody reads.
    """
    out = text
    out = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?Z?\b", "<TS>", out)
    out = re.sub(r"(?i)\b(session|csrf|nonce|request)[-_ ]?id\W{0,3}[A-Za-z0-9_-]{8,}", "<ID>", out)
    out = re.sub(r"<!--.*?-->", "", out, flags=re.S)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


MIN_PLAUSIBLE_BYTES = 32


def validate_response(source_id: str, text: Any) -> str:
    """Reject what we will not store, with a reason.

    A blank page, an error page or a byte string is not a regulation. Storing one
    as a "version" would record a change on the way in AND another on the way out
    when the source recovers — two false alarms from one outage.
    """
    if text is None:
        raise MalformedSourceResponse(f"{source_id}: response was None")
    if not isinstance(text, str):
        raise MalformedSourceResponse(
            f"{source_id}: response was {type(text).__name__}, expected str"
        )
    stripped = text.strip()
    if not stripped:
        raise MalformedSourceResponse(f"{source_id}: response was empty")
    if len(stripped.encode("utf-8")) < MIN_PLAUSIBLE_BYTES:
        raise MalformedSourceResponse(
            f"{source_id}: response was {len(stripped)} chars, below the "
            f"{MIN_PLAUSIBLE_BYTES}-byte floor — almost certainly an error page, and "
            f"storing it would record a change now and another on recovery"
        )
    if re.match(r"^\s*(404|403|500|502|503)\b", stripped):
        raise MalformedSourceResponse(f"{source_id}: response looks like an HTTP error body")
    return text


# --------------------------------------------------------------------------- #
# Change extraction
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExtractedChange:
    source_id: str
    regulator_id: str
    jurisdiction: str
    #: "first_observation" | "changed" | "unchanged"
    kind: str
    #: 0..1
    confidence: float
    previous_hash: str | None
    current_hash: str
    #: Characters added/removed on the normalised text.
    delta_chars: int
    provenance: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def extract_change(
    source: ApprovedSource,
    previous: ContentVersion | None,
    current: ContentVersion,
) -> ExtractedChange:
    """Classify the observation, with a confidence and full provenance.

    FIRST OBSERVATION IS NOT A CHANGE, and its confidence is 0. We have one data
    point; calling that a change would fire an alert on every newly registered
    source and teach the reader to ignore the channel.

    Confidence for a real change scales with how much moved: a two-character
    difference on a 40 kB page is far more likely to be residual noise the
    normaliser missed than a substantive amendment, and saying so is more useful
    than a flat "changed: true".
    """
    provenance = {
        "source_id": source.source_id,
        "url": source.url,
        "regulator_id": source.regulator_id,
        "jurisdiction": source.jurisdiction,
        "fetched_at": current.fetched_at,
        "content_hash": current.content_hash,
        "previous_hash": previous.content_hash if previous else None,
        "terms_reviewed_at": source.terms_reviewed_at,
        "terms_reviewed_by": source.terms_reviewed_by,
        "byte_length": current.byte_length,
    }

    if previous is None:
        return ExtractedChange(
            source_id=source.source_id,
            regulator_id=source.regulator_id,
            jurisdiction=source.jurisdiction,
            kind="first_observation",
            confidence=0.0,
            previous_hash=None,
            current_hash=current.content_hash,
            delta_chars=0,
            provenance=provenance,
            reason=(
                "first observation of this source. Not a change — one data point "
                "cannot be a difference, and alerting here would fire on every newly "
                "registered source."
            ),
        )

    if previous.content_hash == current.content_hash:
        return ExtractedChange(
            source_id=source.source_id,
            regulator_id=source.regulator_id,
            jurisdiction=source.jurisdiction,
            kind="unchanged",
            confidence=1.0,
            previous_hash=previous.content_hash,
            current_hash=current.content_hash,
            delta_chars=0,
            provenance=provenance,
            reason="normalised content is byte-identical to the previous version.",
        )

    delta = abs(len(current.normalised) - len(previous.normalised))
    baseline = max(len(previous.normalised), 1)
    ratio = delta / baseline

    if delta == 0:
        confidence = 0.45
        reason = (
            "content differs but the length is identical — a substitution rather than "
            "an insertion. Real, but the smallest kind of real."
        )
    elif ratio < 0.001:
        confidence = 0.35
        reason = (
            f"{delta} character(s) moved on a {baseline}-character document "
            f"({ratio:.4%}). More likely residual noise the normaliser missed than a "
            f"substantive amendment."
        )
    elif ratio < 0.02:
        confidence = 0.7
        reason = f"{delta} character(s) moved ({ratio:.2%}) — a plausible amendment."
    else:
        confidence = 0.95
        reason = f"{delta} character(s) moved ({ratio:.2%}) — a substantial rewrite."

    return ExtractedChange(
        source_id=source.source_id,
        regulator_id=source.regulator_id,
        jurisdiction=source.jurisdiction,
        kind="changed",
        confidence=confidence,
        previous_hash=previous.content_hash,
        current_hash=current.content_hash,
        delta_chars=delta,
        provenance=provenance,
        reason=reason,
    )


# --------------------------------------------------------------------------- #
# The adapter
# --------------------------------------------------------------------------- #


class Clock(Protocol):  # pragma: no cover - typing only
    def __call__(self) -> str: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovedFetchAdapter:
    """The only fetch the scanner is ever given.

    ``transport`` is injected, so this module never opens a socket either — the
    approval decision and the network call stay separable, and a test can prove the
    refusals without a network.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        transport: Callable[[str], Any],
        robots_transport: Callable[[str], str] | None = None,
        user_agent: str = "*",
    ) -> None:
        self.registry = registry
        self.transport = transport
        self.robots_transport = robots_transport
        self.user_agent = user_agent
        self.refusals: list[tuple[str, str]] = []

    def _record_refusal(self, url: str, why: str) -> None:
        self.refusals.append((url, why))

    def __call__(self, url: str) -> str:
        source = self.registry.by_url(url)
        if source is None:
            self._record_refusal(url, "not_approved")
            raise SourceNotApproved(url)

        # Terms first: they are the narrowest gate, and checking them before we
        # fetch robots.txt means a forbidden source generates no traffic at all.
        if not source.terms_allow_automated_access:
            self._record_refusal(url, "terms_forbid")
            raise TermsForbidAutomatedAccess(source.source_id)

        if self.robots_transport is not None:
            robots = self.robots_transport(url)
            rule = robots_disallows(robots, url, self.user_agent)
            if rule is not None:
                self._record_refusal(url, "robots_disallow")
                raise RobotsDisallowed(url, rule)

        return validate_response(source.source_id, self.transport(url))


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #


@dataclass
class IngestionResult:
    changes: list[ExtractedChange] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    published: int = 0

    @property
    def summary(self) -> str:
        kinds: dict[str, int] = {}
        for change in self.changes:
            kinds[change.kind] = kinds.get(change.kind, 0) + 1
        return (
            f"{len(self.changes)} observation(s) {kinds}, "
            f"{len(self.refused)} refused, {self.published} published"
        )


class RegulationIngestion:
    """Registry -> approved fetch -> version store -> change extraction -> events."""

    #: Below this, an observation is recorded but not published. A channel that
    #: emits every 0.35-confidence flicker is a channel operators mute.
    PUBLISH_CONFIDENCE_FLOOR = 0.5

    def __init__(
        self,
        registry: SourceRegistry,
        adapter: ApprovedFetchAdapter,
        store: ContentVersionStore | None = None,
        publish: Callable[[str, dict[str, Any]], Any] | None = None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self.registry = registry
        self.adapter = adapter
        self.store = store or ContentVersionStore()
        self.publish = publish
        self.clock = clock
        self.scanner = PredictiveRegulationScanner(fetch=adapter)

    def ingest(self, source_ids: list[str]) -> IngestionResult:
        result = IngestionResult()

        for source_id in source_ids:
            source = self.registry.get(source_id)
            if source is None:
                result.refused.append(
                    {
                        "source_id": source_id,
                        "reason": "not_approved",
                        "detail": "absent from the approved-source registry",
                    }
                )
                continue

            try:
                text = self.adapter(source.url)
            except IngestionRefused as exc:
                result.refused.append(
                    {
                        "source_id": source_id,
                        "reason": type(exc).__name__,
                        "detail": str(exc),
                    }
                )
                continue

            normalised = normalise_content(text)
            version = ContentVersion(
                source_id=source_id,
                content_hash=hashlib.sha256(normalised.encode("utf-8")).hexdigest(),
                normalised=normalised,
                fetched_at=self.clock(),
                byte_length=len(text.encode("utf-8")),
            )

            previous = self.store.latest(source_id)
            change = extract_change(source, previous, version)

            # Store only when something moved. Appending an identical version on
            # every poll would make the history a poll log rather than a change
            # history, and the provenance would be unreadable within a week.
            if change.kind != "unchanged":
                self.store.append(version)

            result.changes.append(change)

            if self.publish is not None and self._should_publish(change):
                self.publish(
                    "regulation.ingested",
                    {
                        "source_id": change.source_id,
                        "regulator_id": change.regulator_id,
                        "jurisdiction": change.jurisdiction,
                        "kind": change.kind,
                        "confidence": change.confidence,
                        "previous_hash": change.previous_hash,
                        "current_hash": change.current_hash,
                        "delta_chars": change.delta_chars,
                        "reason": change.reason,
                        "provenance": change.provenance,
                    },
                )
                result.published += 1

        return result

    def _should_publish(self, change: ExtractedChange) -> bool:
        if change.kind == "unchanged":
            return False
        if change.kind == "first_observation":
            # Worth publishing once: it establishes provenance for the source and
            # is the only record that we started watching it.
            return True
        return change.confidence >= self.PUBLISH_CONFIDENCE_FLOOR


__all__ = [
    "ApprovedFetchAdapter",
    "ApprovedSource",
    "ContentVersion",
    "ContentVersionStore",
    "ExtractedChange",
    "IngestionRefused",
    "IngestionResult",
    "MalformedSourceResponse",
    "RegulationIngestion",
    "RobotsDisallowed",
    "SourceNotApproved",
    "SourceRegistry",
    "TermsForbidAutomatedAccess",
    "extract_change",
    "normalise_content",
    "robots_disallows",
    "validate_response",
]
