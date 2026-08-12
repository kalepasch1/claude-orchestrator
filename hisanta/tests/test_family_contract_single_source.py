"""The family domain must have exactly one definition, reachable by both paths.

`hisanta/hisanta/contracts/family.py` was a drifted duplicate of
`hisanta/contracts/family.py`. It is now a re-export shim. These tests are the
regression guard: if someone re-adds a local definition to the nested module,
object identity breaks here before it breaks an isinstance check at runtime.
"""
import hisanta.contracts.family as canonical
import hisanta.hisanta.contracts.family as nested


def test_nested_module_exports_the_canonical_objects_themselves():
    """Not merely equal shapes -- the same objects."""
    for name in nested.__all__:
        assert hasattr(canonical, name), f"{name} is re-exported but not defined canonically"
        assert getattr(nested, name) is getattr(canonical, name), (
            f"{name} diverged: the nested module defines its own copy again"
        )


def test_nested_module_defines_nothing_of_its_own():
    """A shim re-exports; it does not declare."""
    local = {
        name
        for name, obj in vars(nested).items()
        if not name.startswith("_")
        and getattr(obj, "__module__", None) == nested.__name__
    }
    assert local == set(), f"nested shim grew local definitions: {sorted(local)}"


def test_enum_identity_survives_the_nested_path():
    """The reason identity matters: cross-path enum comparison must hold."""
    assert nested.ConstitutionVerdict.ESCALATE is canonical.ConstitutionVerdict.ESCALATE
    assert nested.ConstitutionAction is canonical.ConstitutionVerdict
    assert nested.constitution_check("gift") is canonical.ConstitutionVerdict.ESCALATE
    assert nested.constitution_check("charge_child") is canonical.ConstitutionVerdict.DENY
    assert nested.constitution_check("read_story") is canonical.ConstitutionVerdict.ALLOW


def test_dataclass_instances_are_mutually_recognised():
    """An object built via the nested path is accepted by canonical isinstance."""
    quest = nested.Quest(kind=nested.QuestKind.READING)
    assert isinstance(quest, canonical.Quest)
    assert quest.kind is canonical.QuestKind.READING


def test_pii_free_fields_is_the_same_frozenset():
    assert nested.PII_FREE_FIELDS is canonical.PII_FREE_FIELDS
    assert "child_name" not in nested.PII_FREE_FIELDS
