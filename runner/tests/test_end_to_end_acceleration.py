import hashlib,json,os,subprocess,sys,tempfile,unittest
from unittest.mock import patch as mock_patch
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import ast_rewrite_ir,delivery_fabric,patch_protocol,pathway_arbiter,symbol_manifest
def git(repo,*args):return subprocess.run(['git',*args],cwd=repo,check=True,capture_output=True,text=True).stdout.strip()
class TestAcceleration(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.repo=self.t.name;git(self.repo,'init');git(self.repo,'config','user.email','t@e.st');git(self.repo,'config','user.name','T')
  with open(os.path.join(self.repo,'app.py'),'w') as h:h.write("def old_name():\n    return 'old_name'\n")
  git(self.repo,'add','.');git(self.repo,'commit','-m','base')
 def tearDown(self):self.t.cleanup()
 def test_billing_fail_closed(self):
  with mock_patch.dict(os.environ,{'ORCH_PREFER_COWORK_PATH':'true'}):
   self.assertEqual(pathway_arbiter.decide({},capacity={'configured':2,'healthy':1,'exhausted':False})['lane'],'cowork');d=pathway_arbiter.decide({},capacity={'configured':2,'healthy':0,'exhausted':True});self.assertEqual(d['lane'],'orchestrator_native');self.assertTrue(d['paid_api_eligible']);self.assertFalse(pathway_arbiter.decide({},capacity={'configured':0,'healthy':0,'exhausted':False})['paid_api_eligible'])
 def test_typed_rewrite_preserves_string(self):
  with open(os.path.join(self.repo,'app.py')) as h:before=h.read()
  ir={'schema':ast_rewrite_ir.SCHEMA,'operations':[{'file':'app.py','language':'python','op':'rename_symbol','old':'old_name','new':'new_name','before_sha256':hashlib.sha256(before.encode()).hexdigest(),'expected_occurrences':1}]};patch,_,_=patch_protocol.normalize(json.dumps(ir),self.repo);self.assertIn('def new_name',patch);self.assertNotIn("return 'new_name'",patch)
 def test_materialize_only_after_proof(self):
  with open(os.path.join(self.repo,'app.py')) as h:before=h.read()
  env={'schema':patch_protocol.SCHEMA,'files':[{'path':'app.py','operation':'modify','before_sha256':hashlib.sha256(before.encode()).hexdigest(),'after_text':before+'\nVALUE=1\n'}]};self.assertFalse(delivery_fabric.verify(self.repo,json.dumps(env),'fail',test_cmd='exit 7')['ok']);self.assertNotEqual(subprocess.run(['git','show-ref','--verify','refs/heads/agent/fail'],cwd=self.repo,capture_output=True).returncode,0);self.assertTrue(delivery_fabric.verify(self.repo,json.dumps(env),'pass',test_cmd='python3 -m py_compile app.py')['ok'])
 def test_delta_manifest(self):
  first=symbol_manifest.create(self.repo,'HEAD')
  with open(os.path.join(self.repo,'other.py'),'w') as h:h.write('class Added:\n pass\n')
  git(self.repo,'add','.');git(self.repo,'commit','-m','delta');second=symbol_manifest.create(self.repo,'HEAD',first);self.assertEqual(second['changed_files'],['other.py']);self.assertEqual(second['symbols']['app.py'],first['symbols']['app.py'])
if __name__=='__main__':unittest.main()
