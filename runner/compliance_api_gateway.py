"""Local REST dispatcher joining the compliance modules behind one safe API surface.

The gateway never submits filings or alters protected policies; it queues/proposes those
operations for the existing approval workflow.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Any

from app_isolation_engine import AppIsolationEngine
from compliance_event_stream import ComplianceEvent, ComplianceEventStream, ComplianceEventType
from compliance_knowledge_graph import ComplianceKnowledgeGraph
from evidence_collector import EvidenceCollector
from filing_optimizer_v2 import SmartFilingOptimizer
from anomaly_detector import CrossModuleAnomalyDetector
from dept_scorecard import DepartmentPerformanceScorecard
from simulation_sandbox import ComplianceSimulationSandbox
from auto_remediation_v2 import AutoRemediationEngineV2


class ComplianceAPIGateway:
    def __init__(self) -> None:
        self.isolation = AppIsolationEngine()
        self.events = ComplianceEventStream()
        self.graph = ComplianceKnowledgeGraph()
        self.evidence = EvidenceCollector()
        self.filings = SmartFilingOptimizer()
        self.anomalies = CrossModuleAnomalyDetector()
        self.scorecards = DepartmentPerformanceScorecard()
        self.simulations = ComplianceSimulationSandbox()
        self.remediation = AutoRemediationEngineV2()
        self.events.subscribe(ComplianceEventType.REGULATION_INGESTED, self._index_regulation)

    def _index_regulation(self, event: ComplianceEvent) -> None:
        regulation = str(event.payload.get("regulation_id", event.event_id))
        for requirement in event.payload.get("requirements", []):
            self.graph.link(regulation, str(requirement), "requires")
            self.graph.link(str(requirement), f"app:{event.app_id}", "applies_to")

    def dispatch(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        body = body or {}; method = method.upper(); pieces = [x for x in path.split("?")[0].split("/") if x]
        if pieces[:2] != ["compliance", "v1"]:
            return 404, {"error": "unknown endpoint"}
        try:
            endpoint = pieces[2:]
            if method == "GET" and endpoint == ["health"]:
                return 200, {"status": "ok", "service": "compliance-api-gateway"}
            if method == "GET" and len(endpoint) == 2 and endpoint[0] == "apps":
                return 200, self.isolation.snapshot(body.get("tenant_id", "default"), endpoint[1])
            if method == "POST" and len(endpoint) == 3 and endpoint[0] == "apps" and endpoint[2] == "risk-score":
                old, new = self.isolation.set_risk_score(body.get("tenant_id", "default"), endpoint[1], body["score"])
                self.events.publish(ComplianceEvent(ComplianceEventType.RISK_SCORE_CHANGED, endpoint[1], {"old": old, "new": new}, body.get("tenant_id", "default")))
                return 200, {"old": old, "new": new}
            if method == "POST" and endpoint == ["events"]:
                event = ComplianceEvent(ComplianceEventType(body["kind"]), body["app_id"], body.get("payload", {}), body.get("tenant_id", "default"))
                return 202, asdict(self.events.publish(event))
            if method == "GET" and endpoint == ["events"]:
                return 200, {"events": [asdict(e) for e in self.events.recent(int(body.get("limit", 100)), body.get("app_id"))]}
            if method == "POST" and endpoint == ["filings", "optimize"]:
                return 200, self.filings.optimize(body.get("filings", []))
            if method == "POST" and endpoint == ["graph", "link"]:
                return 201, asdict(self.graph.link(body["source"], body["target"], body["relation"], **body.get("metadata", {})))
            if method == "POST" and endpoint == ["graph", "path"]:
                return 200, {"path": [asdict(e) for e in self.graph.shortest_path(body["source"], body["target"])]}
            if method == "POST" and endpoint == ["evidence", "collect"]:
                return 201, self.evidence.collect(body["app_id"], body["kind"], body["subject"], file_path=body.get("file_path"), metadata=body.get("metadata"))
            if method == "POST" and endpoint == ["anomalies", "detect"]:
                value = self.anomalies.detect(body["metric"], body["values"], float(body.get("threshold", 3)))
                return 200, {"anomaly": asdict(value) if value else None}
            if method == "POST" and endpoint == ["departments", "scorecard"]:
                return 200, self.scorecards.score(**body)
            if method == "POST" and endpoint == ["simulations"]:
                snapshot, scenario = body.get("snapshot", {}), body.get("scenario", {})
                def pipeline(state, changes):
                    state.update(changes.get("state_patch", {}))
                    return {"projected_risk_score": max(0, min(100, float(state.get("risk_score", 0)) + float(changes.get("risk_delta", 0)))),
                            "projected_filing_count": len(state.get("filing_queue", [])) + int(changes.get("filing_delta", 0))}
                return 200, self.simulations.run(snapshot, scenario, pipeline)
            if method == "POST" and endpoint == ["remediations", "propose"]:
                issue = body.get("issue", {})
                plan = body.get("plan", {"operation": "review"})
                result = self.remediation.remediate(body.get("app_id", "unknown"), issue,
                    generate=lambda _: plan, validate=lambda candidate: bool(candidate.get("validated", False)),
                    apply=lambda _: None)
                return 200, asdict(result)
            return 404, {"error": "unknown endpoint"}
        except (KeyError, TypeError, ValueError) as exc:
            return 400, {"error": str(exc)}


gateway = ComplianceAPIGateway()
