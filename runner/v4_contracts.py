"""v4 cross-app contracts — the shared abstractions that must live exactly once.

The v4 remediation's whole point is that persona definitions and reliability
scores "live once; all apps consume; calibration compounds portfolio-wide". A
contract that each app redefines for itself is the opposite of that, and is the
defect that produced two divergent copies of hisanta.contracts.family.

So the Protocol is declared here, in the orchestrator's runner where the fleet
already keeps its shared control-plane types, and every implementation conforms
to it rather than inventing its own shape.

Protocols only — no behaviour, no I/O. Implementations live beside their storage
(see runner/persona_registry.py).
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Protocol, runtime_checkable

# Below this many observations a reliability score is NOT trustworthy and must
# not drive a decision. Calibrating on n<=2 is how one unlucky outcome
# permanently mislabels a good counterparty.
MIN_CALIBRATION_SAMPLES = 5

# Ceiling on how far one calibration pass may move a score. A persona built over
# months must not be rewritten by a single bad week.
MAX_CALIBRATION_STEP = 0.2

NEUTRAL_RELIABILITY = 0.5


@dataclass
class Persona:
    """A cross-app subject whose reliability compounds across every product.

    `reliability` is 0..1 on the SAME scale as the darwin-kernel `reliability`
    passport claim, so a score calibrated here can be emitted as a claim, and a
    claim can seed a persona, with no unit conversion in either direction.
    """
    subject: str
    reliability: float = NEUTRAL_RELIABILITY
    samples: int = 0
    contributors: List[str] = field(default_factory=list)
    updated_at: Optional[str] = None
    detail: Dict[str, object] = field(default_factory=dict)


@dataclass
class PersonaOutcome:
    """A realised outcome as observed by one app."""
    subject: str
    app: str
    succeeded: bool
    weight: float = 1.0
    observed_at: Optional[str] = None


@dataclass
class Calibration:
    """What calibration concluded, BEFORE anything is written back."""
    subject: str
    observed_rate: float
    samples: int
    contributors: List[str]
    proposed: float
    usable: bool
    reason: str


@runtime_checkable
class PersonaRegistry(Protocol):
    """The one place persona definitions and reliability scores live.

    Implementations must be safe to call concurrently from multiple apps and
    must never raise on a missing subject — an unknown persona reads as neutral,
    not as an error, so a consuming app never has to special-case first contact.
    """

    def get(self, subject: str) -> Persona:
        """Return the persona for `subject`, neutral if never seen. Never raises."""
        ...

    def upsert(self, persona: Persona) -> Persona:
        """Store `persona` and return what was stored."""
        ...

    def record_outcomes(self, outcomes: Iterable[PersonaOutcome]) -> Dict[str, Calibration]:
        """Fold outcomes into their personas. Returns the calibration per subject.

        Must be a no-op for any subject below MIN_CALIBRATION_SAMPLES: thin
        evidence is reported, never written.
        """
        ...

    def calibrate(self, subject: str,
                  outcomes: Iterable[PersonaOutcome]) -> Calibration:
        """Compute the calibration for `subject` WITHOUT writing it back."""
        ...

    def all(self) -> List[Persona]:
        """Every persona currently held."""
        ...
