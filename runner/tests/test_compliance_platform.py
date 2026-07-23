from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_isolation_engine import AppIsolationEngine
from compliance_api_gateway import ComplianceAPIGateway
from compliance_event_stream import ComplianceEvent, ComplianceEventStream, ComplianceEventType
from compliance_knowledge_graph import ComplianceKnowledgeGraph
from anomaly_detector import CrossModuleAnomalyDetector
from auto_remediation_v2 import AutoRemediationEngineV2
from filing_optimizer_v2 import SmartFilingOptimizer
from simulation_sandbox import ComplianceSimulationSandbox
from regulation_scanner import PredictiveRegulationScanner
from dept_scorecard import DepartmentPerformanceScorecard


def test_event_delivery_and_tenant_isolation():
    received = []
    stream = ComplianceEventStream()
    stream.subscribe(ComplianceEventType.RISK_SCORE_CHANGED, received.append)
    stream.publish(ComplianceEvent(ComplianceEventType.RISK_SCORE_CHANGED, "app-a", {"new": 20}, "tenant-a"))
    engine = AppIsolationEngine()
    engine.set_risk_score("tenant-a", "app-a", 20)
    assert received[0].app_id == "app-a"
    assert engine.snapshot("tenant-a", "app-a")["risk_score"] == 20
    assert engine.snapshot("tenant-b", "app-a")["risk_score"] == 0


def test_graph_optimizer_anomaly_and_sandbox():
    graph = ComplianceKnowledgeGraph()
    graph.link("reg:ccpa", "req:notice", "requires")
    graph.link("req:notice", "filing:1", "satisfied_by")
    assert [edge.target for edge in graph.shortest_path("reg:ccpa", "filing:1")] == ["req:notice", "filing:1"]
    optimized = SmartFilingOptimizer().optimize([{"jurisdiction": "CA", "type": "privacy", "deadline": "2030-01-01"}])
    assert optimized["filings"][0]["priority"] == "standard"
    assert CrossModuleAnomalyDetector().detect("risk", [1, 1, 1, 50]) is not None
    sim = ComplianceSimulationSandbox().run({"risk_score": 10}, {"risk_delta": 20}, lambda state, scenario: {"risk": state["risk_score"] + scenario["risk_delta"]})
    assert sim["isolated"] and sim["result"]["risk"] == 30


def test_gateway_and_protected_remediation_gate():
    gateway = ComplianceAPIGateway()
    status, payload = gateway.dispatch("POST", "/compliance/v1/apps/payments/risk-score", {"tenant_id": "acme", "score": 42})
    assert status == 200 and payload["new"] == 42
    status, payload = gateway.dispatch("POST", "/compliance/v1/events", {"app_id": "payments", "tenant_id": "acme", "kind": "regulation.ingested", "payload": {"regulation_id": "ccpa", "requirements": ["notice"]}})
    assert status == 202
    result = AutoRemediationEngineV2().remediate("payments", {"id": "i1"}, lambda _: {"operation": "submit_filing"}, lambda _: True, lambda _: None)
    assert result.status == "approval_required"


def test_scanner_and_department_scorecard():
    content = {"https://regulator.example/rules": "version one"}
    scanner = PredictiveRegulationScanner(lambda source: content[source])
    assert scanner.scan(list(content))[0].changed is False
    content["https://regulator.example/rules"] = "version two"
    assert scanner.scan(list(content))[0].changed is True
    card = DepartmentPerformanceScorecard().score("Legal", approval_response_hours=[12], action_completion=[True, False], thread_resolution_hours=[24])
    assert card["department"] == "Legal" and card["score"] > 0
