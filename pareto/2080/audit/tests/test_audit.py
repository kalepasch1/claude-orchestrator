"""audit: standing bundles, tax-season assembly, and real shared contracts.

Two tests carry the weight. `test_fixture_year_assembles_complete_binder` is the
headline: a fixture year of financial actions must assemble a binder holding
both a drafted return and its evidence, with nothing missing.
`test_contract_types_come_from_the_shared_module` is why this package was ported
here at all — it fails the moment someone reintroduces a local stand-in for a
contract type. The rest pin the fail-soft contract, because a bundler that
raises on a missing receipt is a bundler nobody runs all year.
"""
import dataclasses
import json
import os
import sys

# '2080' is not a valid Python identifier — same sys.path convention as
# pareto/2080/contracts/test_contracts_smoke.py. The modules under test live one
# directory up; this file sits in `tests/` so write_guard's placement rule holds.
_AUDIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(_AUDIT_DIR), "contracts"))

import autonomy  # noqa: E402
import binder as bd  # noqa: E402
import bundler as bl  # noqa: E402


def fixture_year():
    """A year of financial actions, each carrying its documentation."""
    return [
        {"id": "a1", "kind": "wage", "amount": 120000.00, "date": "2080-01-31",
         "description": "salary", "docs": ["statement-w2-2080.pdf"]},
        {"id": "a2", "kind": "dividend", "amount": 3400.00, "date": "2080-03-15",
         "description": "brokerage dividends", "docs": ["statement-1099div.pdf"]},
        {"id": "a3", "kind": "trade", "amount": -1200.00, "date": "2080-05-02",
         "description": "sold 40 shares",
         "docs": ["confirmation-4402.pdf", "cost_basis-4402.csv"]},
        {"id": "a4", "kind": "donation", "amount": -5000.00, "date": "2080-07-04",
         "description": "food bank",
         "docs": ["acknowledgment_letter-foodbank.pdf"]},
        {"id": "a5", "kind": "business_expense", "amount": -2200.00,
         "date": "2080-09-19", "description": "conference",
         "docs": ["receipt-conf.pdf"]},
        {"id": "a6", "kind": "interest", "amount": 450.00, "date": "2080-12-31",
         "description": "savings interest", "docs": ["statement-bank.pdf"]},
    ]


# ── (1) the shared contracts, not local stand-ins ────────────────────────────

def test_contract_types_come_from_the_shared_module():
    """The point of the port: these must BE the contracts module's types."""
    assert bl.Receipt is autonomy.Receipt
    assert bl.AuditBundle is autonomy.AuditBundle
    assert bd.ComplianceBinder is autonomy.ComplianceBinder
    assert bl.AuditBundle.__module__ == "autonomy"
    assert os.path.abspath(autonomy.__file__) == os.path.join(
        os.path.dirname(_AUDIT_DIR), "contracts", "autonomy.py")


def test_contract_types_are_not_widened_by_this_package():
    """A same-named local class, or an added field, would show up right here."""
    assert {f.name for f in dataclasses.fields(autonomy.AuditBundle)} == {
        "bundle_id", "receipts", "period_start", "period_end", "notes"}
    assert {f.name for f in dataclasses.fields(autonomy.ComplianceBinder)} == {
        "binder_id", "jurisdiction", "bundles", "status"}
    assert {f.name for f in dataclasses.fields(autonomy.Receipt)} == {
        "explanation", "amount_saved", "action", "timestamp", "signature"}


def test_assembled_objects_are_instances_of_the_contract_types():
    standing = bl.bundle_actions(fixture_year(), year=2080)
    binder = bd.assemble_binder(standing)

    assert isinstance(standing.bundle, autonomy.AuditBundle)
    assert all(isinstance(r, autonomy.Receipt) for r in standing.receipts)
    assert isinstance(binder.compliance_binder, autonomy.ComplianceBinder)
    assert binder.compliance_binder.bundles == [standing.bundle]
    # The contract has no `year`; the year is carried as the period it covers.
    assert standing.bundle.period_start == "2080-01-01"
    assert standing.bundle.period_end == "2080-12-31"
    assert standing.bundle.bundle_id == "audit-defense-2080"


# ── (2) the headline: a whole year assembles a complete binder ────────────────

def test_fixture_year_assembles_complete_binder():
    standing = bl.bundle_actions(fixture_year(), year=2080)
    binder = bd.assemble_binder(standing)

    assert binder.complete is True
    assert binder.status == bd.STATUS_COMPLETE
    assert binder.compliance_binder.status == "complete"
    assert binder.year == 2080

    drafted = binder.drafted_return
    assert drafted["drafted"] is True
    assert drafted["action_count"] == 6
    # 120000 wage + 3400 dividend + 450 interest
    assert drafted["totals"]["income"] == 123850.00
    # -5000 donation + -2200 business expense
    assert drafted["totals"]["deductions"] == -7200.00
    assert drafted["totals"]["capital"] == -1200.00
    assert drafted["totals"]["taxable"] == 129850.00

    evidence = binder.evidence
    assert evidence["gap_count"] == 0
    assert evidence["artifact_count"] == 7
    assert set(evidence["by_line_item"]) == {"income", "capital", "deduction"}
    assert "Complete" in binder.summary
    assert standing.bundle.notes == "No documentation gaps recorded."


def test_every_action_is_traceable_from_return_to_evidence():
    standing = bl.bundle_actions(fixture_year(), year=2080)
    binder = bd.assemble_binder(standing)

    on_return = {aid for line in binder.drafted_return["line_items"]
                 for aid in line["action_ids"]}
    in_evidence = {row["action_id"]
                   for rows in binder.evidence["by_line_item"].values()
                   for row in rows}
    expected = {"a1", "a2", "a3", "a4", "a5", "a6"}
    assert on_return == in_evidence == expected


def test_receipts_pair_with_entries_and_carry_the_action_id():
    """The contract Receipt has no action_id, so `action` is what ties it back."""
    standing = bl.bundle_actions(fixture_year(), year=2080)

    assert len(standing.receipts) == len(standing.entries) == 6
    for entry, receipt in zip(standing.entries, standing.receipts):
        assert receipt.action == "%s:%s" % (entry.kind, entry.action_id)
        assert receipt.amount_saved == entry.amount
        assert receipt.timestamp == entry.packaged_at
        assert receipt.signature.startswith("sha256:")

    wage = standing.receipts[0]
    assert wage.action == "wage:a1"
    assert wage.explanation == (
        "wage a1 (2080-01-31): statement-w2-2080.pdf")


# ── (3) fail-soft: gaps are named, never raised ───────────────────────────────

def test_missing_documentation_records_a_gap_and_never_raises():
    actions = fixture_year()
    actions.append({"id": "a7", "kind": "donation", "amount": -900.00,
                    "date": "2080-11-02", "description": "undocumented gift"})

    standing = bl.bundle_actions(actions, year=2080)
    binder = bd.assemble_binder(standing)

    assert binder.complete is False
    assert binder.status == bd.STATUS_DRAFT
    assert binder.evidence["gap_count"] == 1
    gap = binder.evidence["gaps"][0]
    assert gap["action_id"] == "a7"
    assert gap["gap"] == "GAP:acknowledgment_letter"
    # The action is still on the return — a gap hides nothing.
    assert binder.drafted_return["action_count"] == 7
    assert "Incomplete" in binder.summary
    # The gap reaches the contract bundle's only free-text field.
    assert standing.bundle.notes == (
        "1 of 7 action(s) missing documentation: a7 -> GAP:acknowledgment_letter")
    assert "missing GAP:acknowledgment_letter" in standing.receipts[-1].explanation


def test_empty_and_malformed_input_is_fail_soft():
    for bad in (None, [], "", 0):
        standing = bl.bundle_actions(bad, year=2080)
        binder = bd.assemble_binder(standing)
        assert standing.entries == []
        assert binder.drafted_return["action_count"] == 0
        assert binder.complete is False
        assert binder.evidence["gaps"] == []

    standing = bl.bundle_actions([None, {}, {"kind": "wage"}], year=2080)
    assert len(standing.entries) == 3
    assert [e.action_id for e in standing.entries] == [
        "action-1", "action-2", "action-3"]
    assert standing.entries[0].gaps == ["GAP:no_documentation"]
    assert standing.entries[2].gaps == ["GAP:statement"]
    assert bd.draft_return(standing)["action_count"] == 3


def test_package_action_returns_the_entry_and_appends_a_receipt():
    standing = bl.bundle_actions([], year=2080)
    entry = bl.package_action(standing, fixture_year()[0])
    assert entry.action_id == "a1"
    assert entry.artifacts == ["statement-w2-2080.pdf"]
    assert entry.gaps == []
    assert entry.complete is True
    assert len(standing.entries) == 1
    assert len(standing.receipts) == 1

    gapped = bl.package_action(standing, {"id": "x", "kind": "expense", "amount": 1})
    assert gapped.gaps == ["GAP:receipt"]
    assert gapped.complete is False


# ── (4) the standing file: append-only, all year ──────────────────────────────

def test_bundle_is_append_only_across_the_year():
    standing = bl.bundle_actions([], year=2080)
    for action in fixture_year():
        bl.package_action(standing, action)
    assert [e.action_id for e in standing.entries] == [
        "a1", "a2", "a3", "a4", "a5", "a6"]

    later = bl.bundle_actions([{"id": "a8", "kind": "wage", "amount": 10.0,
                                "docs": ["statement-x.pdf"]}], year=2080)
    bl.merge_bundle(standing, later)
    assert standing.entries[-1].action_id == "a8"
    assert len(standing.receipts) == 7
    # The merged-from file is untouched, and the two no longer share objects.
    assert len(later.entries) == 1
    assert standing.entries[-1] is not later.entries[0]


def test_standing_file_persists_as_json(tmp_path):
    standing = bl.bundle_actions(fixture_year(), year=2080)
    path = os.path.join(str(tmp_path), "nested", "audit-defense-2080.json")

    assert bl.write_bundle(standing, path) is True
    with open(path) as handle:
        payload = json.load(handle)
    assert payload["year"] == 2080
    assert payload["bundle_id"] == "audit-defense-2080"
    assert len(payload["entries"]) == 6
    assert len(payload["receipts"]) == 6
    assert payload["gap_count"] == 0

    # An unwritable target is reported, not raised.
    blocker = os.path.join(str(tmp_path), "not-a-directory")
    open(blocker, "w").close()
    assert bl.write_bundle(standing, os.path.join(blocker, "x.json")) is False


def test_collect_evidence_indexes_artifacts_by_line_item():
    standing = bl.bundle_actions(fixture_year(), year=2080)
    evidence = bd.collect_evidence(standing)
    capital = evidence["by_line_item"]["capital"]
    assert len(capital) == 1
    assert sorted(capital[0]["artifacts"]) == ["confirmation-4402.pdf",
                                               "cost_basis-4402.csv"]
    assert capital[0]["action_id"] == "a3"


def test_a_year_with_holes_still_assembles_and_reports_them():
    """Completeness is a reported property, not a precondition for assembly."""
    standing = bl.bundle_actions(
        [{"id": "b1", "kind": "wage", "amount": 5000.0, "date": "2080-02-01"},
         {"id": "b2", "kind": "trade", "amount": -300.0, "date": "2080-06-01",
          "docs": ["confirmation-9.pdf"]}],
        year=2080)
    binder = bd.assemble_binder(standing, jurisdiction="CA")

    assert binder.complete is False
    assert binder.drafted_return["action_count"] == 2
    assert binder.drafted_return["totals"]["taxable"] == 4700.00
    assert [g["gap"] for g in binder.evidence["gaps"]] == [
        "GAP:statement", "GAP:cost_basis"]
    assert binder.compliance_binder.jurisdiction == "CA"
    assert binder.compliance_binder.binder_id == "binder-2080"
    assert binder.to_dict()["status"] == "draft"


def test_package_reexports_the_whole_surface():
    """`audit/__init__.py` is shipped code; nothing else here imports it.

    Loaded from its file path the way pareto/__init__.py registers the other
    subpackages, because '2080' makes `import pareto.2080.audit` a SyntaxError.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "audit", os.path.join(_AUDIT_DIR, "__init__.py"),
        submodule_search_locations=[_AUDIT_DIR])
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)

    for name in package.__all__:
        assert hasattr(package, name), name
    assert package.AuditBundle is autonomy.AuditBundle
    assert package.ComplianceBinder is autonomy.ComplianceBinder

    standing = package.bundle_actions(fixture_year(), year=2080)
    assert package.assemble_binder(standing).complete is True
