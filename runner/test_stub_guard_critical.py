"""Regression tests for stub_guard's CRITICAL fabricated-return classifier.

The incident (tomorrow, commits 114a6c081 and 0ef37d685; apparently, commit dec963c4):
206 constant-return stubs were appended to barrels to make builds pass. Two consequences
made this worse than a crash:

  * assertEcpCounterparty() -- a REGULATORY eligibility gate -- stopped throwing, so every
    ineligible counterparty passed the check silently;
  * computeWarrantyEconomics() returned all zeros and compileReplication() returned the
    literal string 'replicated' for every policy, so downstream financial output was
    plausible and WRONG rather than absent.

Fabricated compliance and financial output is believable, so nobody investigates. Before
this change stub_guard reported these as advisory warnings that merged anyway; they are now
BLOCKING (fabricated_critical_return).

Those repos are not on this machine, so the SHAPES are reproduced as fixtures. The false-
positive controls matter as much as the detections: a UI helper returning {} is ordinary and
must not block the train.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("db", type(sys)("db"))
import stub_guard  # noqa: E402


def _scan(tmp_path, filename, source):
    target = tmp_path / filename
    target.write_text(source)
    return stub_guard.scan_fabricated(str(tmp_path), [str(target)])


def _codes(findings):
    return {f["code"] for f in findings}


# --------------------------------------------------------------------- name classifier

def test_regulatory_and_financial_names_are_critical():
    for name in ("assertEcpCounterparty", "computeWarrantyEconomics", "priceSwapLeg",
                 "validateKycStatus", "verifySignature", "checkCollateral",
                 "isTradeEnforceable", "isCounterpartyEligible", "reconcileLedger",
                 "settleTrade", "enforceLimit", "swapPricing", "clientCompliance",
                 "positionExposure", "portfolioValuation"):
        assert stub_guard.is_critical_name(name), name


def test_ordinary_names_are_not_critical():
    """These must stay advisory — blocking them would make the gate unusable."""
    for name in ("renderHeader", "getUserName", "formatDate", "toSlug", "useModal",
                 "buildClassName", "mapRows", "onClick", "parseArgs", "emptyState"):
        assert not stub_guard.is_critical_name(name), name


# --------------------------------------------------------------------- the real shapes

def test_assert_ecp_counterparty_stub_is_blocking(tmp_path):
    """A regulatory gate that stopped throwing."""
    findings = _scan(tmp_path, "ecp.ts",
                     "export function assertEcpCounterparty(id: string): void { return; }\n")
    assert "fabricated_critical_return" in _codes(findings)
    f = [x for x in findings if x["code"] == "fabricated_critical_return"][0]
    assert f["severity"] == "block"
    assert f["symbol"] == "assertEcpCounterparty"
    assert "MUST throw" in f["fix"]


def test_compute_warranty_economics_zeros_are_blocking(tmp_path):
    findings = _scan(
        tmp_path, "econ.ts",
        "export function computeWarrantyEconomics(p: Policy): Econ "
        "{ return { premium: 0, reserve: 0, margin: 0 }; }\n")
    assert "fabricated_critical_return" in _codes(findings)
    assert [f for f in findings if f["severity"] == "block"]


def test_compile_replication_literal_string_is_caught(tmp_path):
    """compileReplication() handed back 'replicated' for every policy."""
    findings = _scan(tmp_path, "repl.ts",
                     "export function checkReplication(p: Policy): string "
                     "{ return 'replicated'; }\n")
    assert "fabricated_critical_return" in _codes(findings)


def test_scalar_shapes_all_caught(tmp_path):
    """{} / 0 / [] / 'x' / true — the object-literal-only rule missed four of these."""
    for i, body in enumerate(("{}", "0", "[]", "'replicated'", "true", "null")):
        findings = _scan(tmp_path, "s%d.ts" % i,
                         "export function priceLeg(x: number): any { return %s; }\n" % body)
        assert "fabricated_critical_return" in _codes(findings), body


def test_non_exported_critical_function_is_still_caught(tmp_path):
    findings = _scan(tmp_path, "internal.ts",
                     "function validateKycStatus(u: User): boolean { return true; }\n")
    assert "fabricated_critical_return" in _codes(findings)


def test_critical_violation_blocks_check_repo(tmp_path):
    """End-to-end: the code must be in BLOCKING so gate()/merge_train refuse."""
    assert "fabricated_critical_return" in stub_guard.BLOCKING
    (tmp_path / "ecp.ts").write_text(
        "export function assertEcpCounterparty(id: string): void { return; }\n")
    result = stub_guard.check_repo(str(tmp_path), None, "fixture")
    assert result["ok"] is False


# --------------------------------------------------------------- clean controls (no FPs)

def test_real_implementation_does_not_fire(tmp_path):
    findings = _scan(
        tmp_path, "econ.ts",
        "export function computeWarrantyEconomics(p: Policy): Econ {\n"
        "  const premium = p.base * p.rate;\n"
        "  const reserve = premium * 0.4;\n"
        "  return { premium, reserve, margin: premium - reserve };\n"
        "}\n")
    assert findings == []


def test_function_that_throws_does_not_fire(tmp_path):
    """The prescribed remedy for genuinely unimplemented work must be accepted."""
    findings = _scan(
        tmp_path, "econ.ts",
        "export function computeWarrantyEconomics(p: Policy): Econ "
        "{ throw new Error('not implemented'); }\n")
    assert findings == []


def test_ordinary_ui_helper_returning_empty_is_not_blocking(tmp_path):
    """A UI helper returning {} is ordinary; blocking it would get the gate disabled."""
    findings = _scan(tmp_path, "ui.ts",
                     "export function renderHeader(): any { return {}; }\n")
    assert "fabricated_critical_return" not in _codes(findings)
    assert not [f for f in findings if f["severity"] == "block"]


def test_computed_return_from_critical_name_does_not_fire(tmp_path):
    findings = _scan(tmp_path, "p.ts",
                     "export function priceLeg(n: number): number { return n * 1.5; }\n")
    assert findings == []


def test_critical_name_returning_a_call_does_not_fire(tmp_path):
    findings = _scan(tmp_path, "p.ts",
                     "export function validateKyc(u: User): boolean { return check(u); }\n")
    assert findings == []


def test_clean_repo_passes_check_repo(tmp_path):
    (tmp_path / "ok.ts").write_text(
        "export function priceLeg(n: number): number {\n"
        "  const spread = n * 0.02;\n  return n + spread;\n}\n")
    result = stub_guard.check_repo(str(tmp_path), None, "fixture")
    assert result["ok"] is True, result["violations"]


# ------------------------------------------------------- shadowed re-export (merge gate)

def test_shadowed_reexport_still_detected(tmp_path):
    """Class 2's detector, now enforced at merge time by merge_train._stub_gate."""
    (tmp_path / "real.ts").write_text(
        "export function assertEcpCounterparty(id: string): void {\n"
        "  if (!id) { throw new Error('ineligible'); }\n}\n")
    (tmp_path / "index.ts").write_text(
        "export * from './real';\n"
        "export const assertEcpCounterparty = () => ({});\n")
    findings = stub_guard.scan_shadowed(str(tmp_path), [str(tmp_path / "index.ts")])
    assert findings, "a local stub shadowing an export * must be detected"
    assert findings[0]["code"] == "stub_shadows_reexport"
    assert findings[0]["severity"] == "block"
    assert findings[0]["symbol"] == "assertEcpCounterparty"


def test_all_arrow_stub_shapes_shadow_detected(tmp_path):
    """`export const x = () => ({})` is the form the 206 real stubs actually used.

    _STUB_CONST only matched a bare literal after `=`, so before this fix the arrow form --
    the one named in the incident report -- was invisible to the shadowed-re-export scan.
    """
    shapes = [
        "export const assertEcpCounterparty = () => ({});",
        "export const assertEcpCounterparty = () => ({})",
        "export const assertEcpCounterparty = (...args: any[]) => ({});",
        "export const assertEcpCounterparty = async () => ({});",
        "export const assertEcpCounterparty: Fn = () => ({});",
        "export const assertEcpCounterparty = () => 0;",
        "export const assertEcpCounterparty = () => [];",
        "export const assertEcpCounterparty = () => null;",
        "export const assertEcpCounterparty = () => {};",
        "export const assertEcpCounterparty = {};",
    ]
    for shape in shapes:
        assert stub_guard._stub_symbol(shape) == "assertEcpCounterparty", shape


def test_real_arrow_implementation_is_not_a_stub():
    """Controls: an arrow with a real body must never be classified as a stub."""
    for line in (
            "export const assertEcpCounterparty = (id: string) => validate(id);",
            "export const priceLeg = (n: number) => n * 1.5;",
            "export const useModal = () => ({ open, close });",
            "export const config = { retries: 3 };",
            "export const handler = () => { doWork(); };"):
        assert stub_guard._stub_symbol(line) is None, line


def test_barrel_without_local_stub_is_clean(tmp_path):
    (tmp_path / "real.ts").write_text(
        "export function assertEcpCounterparty(id: string): void {\n"
        "  if (!id) { throw new Error('ineligible'); }\n}\n")
    (tmp_path / "index.ts").write_text("export * from './real';\n")
    assert stub_guard.scan_shadowed(str(tmp_path), [str(tmp_path / "index.ts")]) == []
