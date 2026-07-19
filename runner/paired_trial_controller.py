#!/usr/bin/env python3
"""Matched frozen-input trials; shadow tasks are forbidden from integration."""
import hashlib,json,os,uuid,db
def value(result):return 0.0 if not result.get('verified') else float(result.get('value',1))/max(float(result.get('wall_ms',0))/3600000,1/3600)
def record(task,result):
 trial=task.get('paired_trial_id')
 if not trial:return
 lane='cowork' if task.get('execution_lane')=='cowork' else 'native';rows=db.select('native_paired_shadow_trials',{'select':'cowork_result,native_result','id':'eq.'+str(trial),'limit':'1'}) or [];other='native_result' if lane=='cowork' else 'cowork_result';patch={lane+'_result':result,lane+'_value_per_hour':value(result)}
 if rows and rows[0].get(other):patch.update(status='completed',completed_at='now()')
 return db.update('native_paired_shadow_trials',{'id':trial},patch)
def sample_once(limit=1):
 if os.environ.get('ORCH_PAIRED_SHADOW_TRIALS','true').lower() not in ('1','true','yes','on'):return {'created':0}
 rate=float(os.environ.get('ORCH_PAIRED_SHADOW_RATE','0.02'));tasks=db.select('tasks',{'select':'*','state':'eq.QUEUED','shadow_only':'eq.false','order':'created_at.asc','limit':str(max(10,limit*20))}) or [];created=0
 for source in tasks:
  key=hashlib.sha256((str(source['id'])+str(source.get('prompt'))).encode()).hexdigest()
  if int(key[:8],16)/0xffffffff>rate:continue
  if db.select('native_paired_shadow_trials',{'select':'id','source_task_id':'eq.'+source['id'],'limit':'1'}):continue
  tid=str(uuid.uuid4());ids={}
  for lane in ('cowork','orchestrator_native'):
   row={k:source.get(k) for k in ('project_id','kind','prompt','material','base_branch') if source.get(k) is not None};row.update(slug=f"shadow-{tid[:8]}-{lane}",state='QUEUED',shadow_only=True,paired_trial_id=tid,execution_lane=lane,_allow_dup=True,note='paired shadow; never integrate/deploy');ins=db.insert('tasks',row) or [];ids[lane]=ins[0].get('id') if isinstance(ins,list) and ins else None
  db.insert('native_paired_shadow_trials',{'id':tid,'source_task_id':source['id'],'project_id':source.get('project_id'),'base_sha':source.get('base_branch') or 'HEAD','prompt_hash':hashlib.sha256(str(source.get('prompt') or '').encode()).hexdigest(),'frozen_prompt':source.get('prompt'),'cowork_task_id':ids['cowork'],'native_task_id':ids['orchestrator_native'],'status':'running'});created+=1
  if created>=limit:break
 return {'created':created}
if __name__=='__main__':print(json.dumps(sample_once()))
