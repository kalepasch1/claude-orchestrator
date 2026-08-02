#!/usr/bin/env python3
"""Relationship intelligence loop. It prepares recommendations only; it never sends."""
from datetime import datetime, timezone, timedelta
import db

def _iso(dt): return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')

def run(limit=250):
    now = datetime.now(timezone.utc)
    contacts = db.select('crm_contacts', {
        'select':'id,app,account_id,first_name,last_name,lifecycle_stage,relationship_health,last_contacted_at,next_contact_at,response_propensity,do_not_contact,marketing_allowed',
        'do_not_contact':'eq.false','order':'next_contact_at.asc.nullslast','limit':str(limit)
    }) or []
    created = 0
    for c in contacts:
        due = not c.get('next_contact_at') or c['next_contact_at'] <= _iso(now)
        if not due: continue
        existing = db.select('crm_recommendations', {'select':'id','contact_id':f"eq.{c['id']}",'status':'eq.open','limit':'1'}) or []
        if existing: continue
        health = int(c.get('relationship_health') or 50)
        if health < 35:
            kind,title,rationale = 'relationship_repair','Repair the relationship before making an ask','Health is below 35. Lead with acknowledgment, listening, and a no-pressure next step.'
        elif not c.get('marketing_allowed'):
            kind,title,rationale = 'permission','Resolve communication permission','Marketing permission is absent. Prepare a non-marketing, context-appropriate permission path; do not send.'
        elif c.get('last_contacted_at') and c['last_contacted_at'] < _iso(now-timedelta(days=45)):
            kind,title,rationale = 'reconnect','Prepare a value-led reconnection','The relationship is stale. Suggest a useful artifact tied to remembered context rather than a generic check-in.'
        else:
            kind,title,rationale = 'next_best_action','Prepare the next useful touch','The contact is due. Draft three tone-calibrated options and one portable value artifact for approval.'
        db.insert('crm_recommendations', {'app':c['app'],'account_id':c.get('account_id'),'contact_id':c['id'],'kind':kind,'title':title,
            'rationale':rationale,'proposed_action':{'mode':'draft_only','surface':'smarter','requires_approval':True},'confidence':0.75,'due_at':_iso(now)})
        created += 1
    print(f'relationship_crm: reviewed={len(contacts)} recommendations_created={created} sends=0')
    return {'reviewed':len(contacts),'created':created,'sent':0}

if __name__ == '__main__': run()

