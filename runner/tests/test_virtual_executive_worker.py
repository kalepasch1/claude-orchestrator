import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch

RUNNER_DIR=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RUNNER_DIR))
SPEC=importlib.util.spec_from_file_location('virtual_executive_worker',RUNNER_DIR/'virtual_executive_worker.py')
worker=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(worker)

class VirtualExecutiveWorkerTests(unittest.TestCase):
 def test_worker_is_registered_on_fast_control_loop(self):
  registry=(RUNNER_DIR/'runner.py').read_text()
  self.assertIn('("virtualexec-30", "virtual_executive_worker.py", "interval", 30)',registry)

 def test_internal_step_executes_and_finishes_saga(self):
  step={'id':'s1','saga_id':'g1','operation':'reconcile','external_effect':False,'state':'claimed','evidence':{},'attempt_count':1}
  with patch.object(worker.db,'rpc',return_value=[step]) as claim,patch.object(worker.db,'select',side_effect=[[{'id':'g1','agent_id':'a1'}],[{'id':'a1','agent_key':'accounting_controller'}],[]]),patch.object(worker.db,'update') as update:
   result=worker.execute_once('worker')
  claim.assert_called_once_with('claim_agentic_business_saga_step',{'p_worker':'worker'})
  self.assertEqual(result['status'],'completed')
  self.assertTrue(any(c.args[2].get('state')=='completed' for c in update.call_args_list))

 def test_external_step_fails_closed_without_adapter(self):
  step={'id':'s2','saga_id':'g2','operation':'send_payment','connector_provider':'banking','external_effect':True,'state':'claimed','evidence':{},'attempt_count':5,'approval_id':'p1'}
  with patch.dict(worker.os.environ,{},clear=True),patch.object(worker.db,'rpc',return_value=[step]),patch.object(worker.db,'select',side_effect=[[{'id':'g2','agent_id':'a2'}],[{'id':'a2','agent_key':'treasury_chief'}]]),patch.object(worker.db,'update') as update:
   result=worker.execute_once('worker')
  self.assertEqual(result['status'],'blocked')
  self.assertTrue(any(c.args[2].get('state')=='blocked' for c in update.call_args_list))

 def test_prediction_is_idempotently_upserted(self):
  obligation={'id':'o1','organization_id':'org','contract_id':'c1','obligation':'Pay invoice','due_at':'2026-08-01T00:00:00Z','status':'open'}
  with patch.object(worker.db,'select',side_effect=[[obligation],[]]),patch.object(worker.db,'insert') as insert:
   result=worker.predict_work()
  self.assertEqual(result['predictions'],1)
  self.assertTrue(insert.call_args.kwargs['upsert'])
  self.assertIn('prediction_digest',insert.call_args.args[1])

if __name__=='__main__':unittest.main()
