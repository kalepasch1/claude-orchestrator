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

    @patch('relationship_crm.db.insert')
    @patch('relationship_crm.db.select')
    def test_defensively_skips_opted_out_contacts(self,select,insert):
        select.return_value=[{'id':'c1','app':'pareto','do_not_contact':True}]

        result=relationship_crm.run()

        self.assertEqual(result,{'reviewed':1,'created':0,'sent':0})
        insert.assert_not_called()
        select.assert_called_once()

    @patch('relationship_crm.db.insert')
    @patch('relationship_crm.db.select')
    def test_zero_health_creates_relationship_repair(self,select,insert):
        select.side_effect=[[{'id':'c1','app':'pareto','relationship_health':0,'do_not_contact':False,'marketing_allowed':True}],[]]

        result=relationship_crm.run()

        self.assertEqual(result['created'],1)
        self.assertEqual(insert.call_args.args[1]['kind'],'relationship_repair')

if __name__=='__main__':unittest.main()
