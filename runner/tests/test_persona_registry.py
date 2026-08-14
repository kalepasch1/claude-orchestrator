"""PersonaRegistry: scores live once, compound across apps, and refuse thin evidence."""
import pytest

import persona_registry
from v4_contracts import (
    MAX_CALIBRATION_STEP,
    MIN_CALIBRATION_SAMPLES,
    NEUTRAL_RELIABILITY,
    Persona,
    PersonaOutcome,
    PersonaRegistry,
)


@pytest.fixture
def reg():
    persona_registry.reset_for_testing()
    yield persona_registry.InMemoryPersonaRegistry(store={})
    persona_registry.reset_for_testing()


def outcomes(subject, n, succeeded, app="tomorrow", weight=1.0):
    return [PersonaOutcome(subject=subject, app=app, succeeded=succeeded, weight=weight)
            for _ in range(n)]


def test_implementation_satisfies_the_protocol(reg):
    """The Protocol is the contract; an implementation that drifts is the defect."""
    assert isinstance(reg, PersonaRegistry)
    assert isinstance(persona_registry.DbPersonaRegistry(), PersonaRegistry)


def test_unknown_subject_reads_neutral_and_never_raises(reg):
    persona = reg.get("never-seen")

    assert persona.subject == "never-seen"
    assert persona.reliability == NEUTRAL_RELIABILITY
    assert persona.samples == 0
    assert persona.contributors == []


def test_thin_evidence_is_reported_but_never_written(reg):
    result = reg.record_outcomes(outcomes("s", MIN_CALIBRATION_SAMPLES - 1, True))

    assert result["s"].usable is False
    assert "insufficient evidence" in result["s"].reason
    assert reg.get("s").reliability == NEUTRAL_RELIABILITY, "must not be written"
    assert reg.get("s").samples == 0


def test_sustained_success_raises_and_failure_lowers(reg):
    reg.record_outcomes(outcomes("up", 20, True))
    reg.record_outcomes(outcomes("down", 20, False))

    assert reg.get("up").reliability > NEUTRAL_RELIABILITY
    assert reg.get("down").reliability < NEUTRAL_RELIABILITY


def test_one_pass_cannot_rewrite_a_long_lived_persona(reg):
    reg.upsert(Persona(subject="veteran", reliability=0.95, samples=500))

    reg.record_outcomes(outcomes("veteran", 50, False))

    moved = abs(reg.get("veteran").reliability - 0.95)
    assert moved <= MAX_CALIBRATION_STEP + 1e-9


def test_reliability_is_clamped_to_the_unit_interval(reg):
    reg.upsert(Persona(subject="hi", reliability=1.0))
    reg.upsert(Persona(subject="lo", reliability=0.0))

    reg.record_outcomes(outcomes("hi", 50, True))
    reg.record_outcomes(outcomes("lo", 50, False))

    assert 0.0 <= reg.get("hi").reliability <= 1.0
    assert 0.0 <= reg.get("lo").reliability <= 1.0


def test_calibration_compounds_across_apps(reg):
    """The whole point: one score, every app contributing to it."""
    mixed = (outcomes("s", 3, True, app="tomorrow")
             + outcomes("s", 3, True, app="apparently")
             + outcomes("s", 2, True, app="smarter"))

    reg.record_outcomes(mixed)

    persona = reg.get("s")
    assert persona.contributors == ["apparently", "smarter", "tomorrow"]
    assert persona.samples == 8


def test_repeated_passes_accumulate_samples(reg):
    reg.record_outcomes(outcomes("s", 10, True))
    first = reg.get("s")
    reg.record_outcomes(outcomes("s", 10, True))
    second = reg.get("s")

    assert second.samples == first.samples + 10
    assert second.reliability >= first.reliability


def test_calibrate_is_read_only(reg):
    calibration = reg.calibrate("s", outcomes("s", 20, True))

    assert calibration.usable is True
    assert reg.get("s").reliability == NEUTRAL_RELIABILITY, "calibrate must not write"


def test_outcomes_are_isolated_per_subject(reg):
    reg.record_outcomes(outcomes("a", 20, True) + outcomes("b", 20, False))

    assert reg.get("a").reliability > NEUTRAL_RELIABILITY
    assert reg.get("b").reliability < NEUTRAL_RELIABILITY


def test_zero_weight_outcomes_do_not_drag_the_rate(reg):
    mixed = outcomes("s", 5, True) + outcomes("s", 5, False, weight=0.0)

    result = reg.record_outcomes(mixed)

    assert result["s"].observed_rate == 1.0


def test_malformed_outcomes_do_not_raise(reg):
    assert reg.record_outcomes([]) == {}
    assert reg.record_outcomes(None) == {}
    assert reg.record_outcomes([PersonaOutcome(subject="", app="x", succeeded=True)]) == {}


def test_db_registry_falls_back_to_memory_when_the_db_is_unreachable(monkeypatch):
    """A DB outage must degrade to 'no cross-app memory', not wedge every caller."""
    persona_registry.reset_for_testing()
    monkeypatch.setattr(persona_registry, "_db", lambda: None)
    reg = persona_registry.DbPersonaRegistry()

    reg.record_outcomes(outcomes("s", 20, True))

    assert reg.get("s").reliability > NEUTRAL_RELIABILITY
    persona_registry.reset_for_testing()


def test_module_level_functions_delegate_to_the_singleton(monkeypatch):
    """Scores live ONCE — the module functions must not open a second store."""
    persona_registry.reset_for_testing()
    monkeypatch.setattr(persona_registry, "_db", lambda: None)

    persona_registry.record_outcomes(outcomes("s", 20, True))

    assert persona_registry.get("s").reliability > NEUTRAL_RELIABILITY
    assert [p.subject for p in persona_registry.all_personas()] == ["s"]
    persona_registry.reset_for_testing()
