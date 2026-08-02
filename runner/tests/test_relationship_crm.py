import os,sys,unittest
from unittest.mock import patch
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import relationship_crm

class RelationshipCrmTest(unittest.TestCase):
    @patch('relationship_crm.db.insert')
    @patch('relationship_crm.db.select')
    def test_tick_only_prepares_and_never_sends(self,select,insert):
        select.side_effect=[[{'id':'c1','app':'pareto','account_id':None,'relationship_health':20,'do_not_contact':False,'marketing_allowed':True}],[]]
        result=relationship_crm.run()
        self.assertEqual(result['sent'],0)
        self.assertEqual(insert.call_args.args[0],'crm_recommendations')
        self.assertTrue(insert.call_args.args[1]['proposed_action']['requires_approval'])

if __name__=='__main__':unittest.main()
