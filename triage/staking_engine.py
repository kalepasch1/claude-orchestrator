from __future__ import annotations
import threading, uuid
from typing import Dict, List, Optional
from triage.types import (CalibrationLedgerEntry, MarketImpliedRiskScore, Proposition,
                          PropositionKind, Stake, StakeOutcome)

class _StakingEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._propositions: Dict[str, Proposition] = {}
        self._credibility: Dict[str, float] = {}
        self._ledger: List[CalibrationLedgerEntry] = []

    def create_proposition(self, kind, subject_id, statement):
        try:
            if not isinstance(kind, PropositionKind): return None
            pid = uuid.uuid4().hex[:12]
            p = Proposition(id=pid, kind=kind, subject_id=subject_id, statement=statement)
            with self._lock: self._propositions[pid] = p
            return p
        except Exception: return None

    def place_stake(self, staker_id, proposition_id, amount=1.0, direction="FOR"):
        try:
            if not staker_id or not proposition_id: return None
            with self._lock:
                p = self._propositions.get(proposition_id)
                if p is None: return None
                s = Stake(staker_id=staker_id, proposition_id=proposition_id, amount=max(0.0, amount),
                          direction=direction if direction in ("FOR","AGAINST") else "FOR")
                p.stakes.append(s)
            return s
        except Exception: return None

    def resolve(self, proposition_id, outcome):
        entries = []
        try:
            with self._lock:
                p = self._propositions.get(proposition_id)
                if p is None: return entries
                p.outcome = outcome
                for s in p.stakes:
                    cur = self._credibility.get(s.staker_id, 1.0)
                    if outcome == StakeOutcome.CONFIRMED:
                        d = s.amount*0.1 if s.direction=="FOR" else -s.amount*0.15
                    elif outcome == StakeOutcome.CONTRADICTED:
                        d = -s.amount*0.15 if s.direction=="FOR" else s.amount*0.1
                    else: d = 0.0
                    nc = max(0.0, cur+d); self._credibility[s.staker_id] = nc
                    e = CalibrationLedgerEntry(staker_id=s.staker_id, proposition_id=proposition_id,
                                              outcome=outcome, credibility_delta=d, new_credibility=nc)
                    self._ledger.append(e); entries.append(e)
            return entries
        except Exception: return entries

    def peer_prediction_score(self, proposition_id):
        try:
            with self._lock:
                p = self._propositions.get(proposition_id)
                if p is None or not p.stakes: return 0.0
                fw = sum(s.amount*self._credibility.get(s.staker_id,1.0) for s in p.stakes if s.direction=="FOR")
                aw = sum(s.amount*self._credibility.get(s.staker_id,1.0) for s in p.stakes if s.direction=="AGAINST")
                t = fw+aw; return fw/t if t else 0.0
        except Exception: return 0.0

    def market_implied_risk(self, subject_id):
        try:
            with self._lock:
                rel = [p for p in self._propositions.values() if p.subject_id==subject_id]
                if not rel: return MarketImpliedRiskScore(subject_id=subject_id)
                tf=ta=0.0
                for p in rel:
                    for s in p.stakes:
                        w=s.amount*self._credibility.get(s.staker_id,1.0)
                        if s.direction=="FOR": tf+=w
                        else: ta+=w
                t=tf+ta
                return MarketImpliedRiskScore(subject_id=subject_id, score=ta/t if t else 0.0,
                                             confidence=min(1.0,t/10.0), contributing_propositions=len(rel))
        except Exception: return MarketImpliedRiskScore(subject_id=subject_id)

    def get_credibility(self, staker_id):
        try:
            with self._lock: return self._credibility.get(staker_id, 1.0)
        except Exception: return 1.0

    def stats(self):
        with self._lock: return {"propositions":len(self._propositions),"ledger_entries":len(self._ledger),"stakers":len(self._credibility)}

    def invalidate(self):
        with self._lock: self._propositions.clear(); self._credibility.clear(); self._ledger.clear()

_engine = _StakingEngine()
create_proposition=_engine.create_proposition; place_stake=_engine.place_stake
resolve=_engine.resolve; peer_prediction_score=_engine.peer_prediction_score
market_implied_risk=_engine.market_implied_risk; get_credibility=_engine.get_credibility
stats=_engine.stats; invalidate=_engine.invalidate
