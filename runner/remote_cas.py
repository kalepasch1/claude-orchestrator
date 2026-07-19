#!/usr/bin/env python3
import hashlib,json,socket
def key(repo,commit,dependency,command,image=''):return hashlib.sha256(json.dumps([repo,commit,dependency,command,image],separators=(',',':')).encode()).hexdigest()
def get(cache_key):
 try:
  import db;rows=db.select('verification_cache_entries',{'select':'*','cache_key':'eq.'+cache_key,'success':'eq.true','limit':'1'}) or [];return rows[0].get('result') if rows else None
 except Exception:return None
def put(cache_key,result,success):
 try:
  import db;return db.insert('verification_cache_entries',{'cache_key':cache_key,'result':result,'success':bool(success),'host':socket.gethostname(),'completed_at':'now()'},upsert=True)
 except Exception:return None
