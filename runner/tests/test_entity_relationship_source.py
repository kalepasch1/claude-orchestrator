"""Tests for relationship_crm.run — validates entity-relationship recommendation generation."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import relationship_crm


class TestSourceBasics(unittest.TestCase):
    """Validates active relationships, opted-out filtering, and structured data return."""

    @patch('relationship_crm.db.select', return_value=[])
    @patch('relationship_crm.db.insert')
    def test_no_contacts_returns_zero(self, mock_insert, mock_select):
        """No contacts to review should return reviewed=0."""
        result = relationship_crm.run()
        self.assertEqual(result['reviewed'], 0)
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['sent'], 0)

    @patch('relationship_crm.db.select', return_value=None)
    @patch('relationship_crm.db.insert')
    def test_none_contacts_returns_zero(self, mock_insert, mock_select):
        """None contacts should be treated as empty list."""
        result = relationship_crm.run()
        self.assertEqual(result['reviewed'], 0)
        self.assertEqual(result['created'], 0)

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_respects_limit_parameter(self, mock_insert, mock_select):
        """run(limit=100) should pass limit parameter to select."""
        mock_select.return_value = []
        relationship_crm.run(limit=100)
        call_args = mock_select.call_args
        self.assertEqual(call_args[0][1]['limit'], '100')

    @patch('relationship_crm.db.select', return_value=[
        {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'John',
            'last_name': 'Doe', 'lifecycle_stage': 'customer', 'relationship_health': '50',
            'last_contacted_at': '2026-07-01T00:00:00Z', 'next_contact_at': '2026-07-25T00:00:00Z',
            'response_propensity': '0.8', 'do_not_contact': False, 'marketing_allowed': True
        }
    ])
    @patch('relationship_crm.db.insert')
    def test_reviewed_count_matches_contact_list(self, mock_insert, mock_select):
        """Reviewed count should match number of contacts after opt-out filtering."""
        result = relationship_crm.run()
        self.assertEqual(result['reviewed'], 1)

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_queries_with_do_not_contact_false(self, mock_insert, mock_select):
        """select should filter for do_not_contact=false."""
        mock_select.return_value = []
        relationship_crm.run()
        call_args = mock_select.call_args
        self.assertEqual(call_args[0][1]['do_not_contact'], 'eq.false')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_queries_ordered_by_next_contact_at(self, mock_insert, mock_select):
        """select should order by next_contact_at ascending."""
        mock_select.return_value = []
        relationship_crm.run()
        call_args = mock_select.call_args
        self.assertEqual(call_args[0][1]['order'], 'next_contact_at.asc.nullslast')


class TestRecommendationGeneration(unittest.TestCase):
    """Validates health-based, permission-based, stale-contact, and active-contact recommendations."""

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_relationship_repair_health_below_35(self, mock_insert, mock_select):
        """health < 35 should generate relationship_repair recommendation."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        mock_insert.assert_called_once()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['kind'], 'relationship_repair')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_permission_no_marketing_allowed(self, mock_insert, mock_select):
        """marketing_allowed=false should generate permission recommendation."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '50', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': False,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['kind'], 'permission')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_reconnect_stale_contact_45_days(self, mock_insert, mock_select):
        """last_contacted_at > 45 days ago should generate reconnect recommendation."""
        now = datetime.now(timezone.utc)
        stale_date = (now - timedelta(days=46)).isoformat().replace('+00:00', 'Z')
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '50', 'last_contacted_at': stale_date,
            'next_contact_at': now.isoformat().replace('+00:00', 'Z'),
            'marketing_allowed': True, 'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['kind'], 'reconnect')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_next_best_action_active_contact(self, mock_insert, mock_select):
        """Active contact without other triggers should generate next_best_action."""
        now = datetime.now(timezone.utc)
        recent_date = (now - timedelta(days=30)).isoformat().replace('+00:00', 'Z')
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '50', 'last_contacted_at': recent_date,
            'next_contact_at': now.isoformat().replace('+00:00', 'Z'),
            'marketing_allowed': True, 'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['kind'], 'next_best_action')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_health_35_uses_default_action(self, mock_insert, mock_select):
        """health = 35 (at boundary) should use next_best_action, not relationship_repair."""
        now = datetime.now(timezone.utc)
        recent_date = (now - timedelta(days=30)).isoformat().replace('+00:00', 'Z')
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '35', 'last_contacted_at': recent_date,
            'next_contact_at': now.isoformat().replace('+00:00', 'Z'),
            'marketing_allowed': True, 'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['kind'], 'next_best_action')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_health_none_defaults_to_50(self, mock_insert, mock_select):
        """None health should default to 50."""
        now = datetime.now(timezone.utc)
        recent_date = (now - timedelta(days=30)).isoformat().replace('+00:00', 'Z')
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': None, 'last_contacted_at': recent_date,
            'next_contact_at': now.isoformat().replace('+00:00', 'Z'),
            'marketing_allowed': True, 'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['kind'], 'next_best_action')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    @patch('relationship_crm.datetime')
    def test_last_contacted_at_45_days_exact_boundary(self, mock_dt, mock_insert, mock_select):
        """last_contacted_at exactly 45 days ago should not trigger reconnect."""
        now = datetime.now(timezone.utc)
        mock_dt.now.return_value = now
        mock_dt.datetime = datetime
        mock_dt.timezone = timezone
        mock_dt.timedelta = timedelta

        boundary_date = (now - timedelta(days=45)).isoformat().replace('+00:00', 'Z')
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '50', 'last_contacted_at': boundary_date,
            'next_contact_at': (now - timedelta(hours=1)).isoformat().replace('+00:00', 'Z'),
            'marketing_allowed': True, 'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['kind'], 'next_best_action')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_no_last_contacted_at_field(self, mock_insert, mock_select):
        """Missing last_contacted_at should not trigger reconnect."""
        now = datetime.now(timezone.utc)
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '50', 'last_contacted_at': None,
            'next_contact_at': now.isoformat().replace('+00:00', 'Z'),
            'marketing_allowed': True, 'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['kind'], 'next_best_action')


class TestDuplicatePrevention(unittest.TestCase):
    """Validates duplicate prevention by checking for existing open recommendations."""

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_skips_contact_with_existing_open_recommendation(self, mock_insert, mock_select):
        """Contact with existing open recommendation should be skipped."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }

        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return [{'id': 'rec1', 'status': 'open'}]
            return []

        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        mock_insert.assert_not_called()

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_checks_existing_by_contact_id(self, mock_insert, mock_select):
        """Duplicate check should query by contact_id."""
        contact = {
            'id': 'c999', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }

        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                # Verify the contact_id parameter
                if params.get('contact_id') == 'eq.c999':
                    return [{'id': 'rec1'}]
                return []
            return []

        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        mock_insert.assert_not_called()

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_creates_when_no_existing_recommendation(self, mock_insert, mock_select):
        """Should create recommendation when no existing open recommendation exists."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }

        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []

        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        mock_insert.assert_called_once()

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_duplicate_check_limits_to_one(self, mock_insert, mock_select):
        """Duplicate check should limit query to 1 result."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }

        call_count = [0]
        def select_side_effect(table, params):
            call_count[0] += 1
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                # Verify limit is 1
                self.assertEqual(params.get('limit'), '1')
                return []
            return []

        mock_select.side_effect = select_side_effect
        relationship_crm.run()


class TestReturnStructure(unittest.TestCase):
    """Validates all required fields in return value and recommendations."""

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_return_structure_has_reviewed_created_sent(self, mock_insert, mock_select):
        """Return value should have reviewed, created, sent keys."""
        mock_select.return_value = []
        result = relationship_crm.run()
        self.assertIn('reviewed', result)
        self.assertIn('created', result)
        self.assertIn('sent', result)

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_sent_always_zero(self, mock_insert, mock_select):
        """sent should always be 0 (no auto-send)."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        result = relationship_crm.run()
        self.assertEqual(result['sent'], 0)

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_created_equals_insert_calls(self, mock_insert, mock_select):
        """created count should equal number of insert calls."""
        contacts = [
            {
                'id': f'c{i}', 'app': 'app1', 'account_id': f'acc{i}', 'first_name': f'Name{i}',
                'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
                'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
                'do_not_contact': False
            }
            for i in range(3)
        ]

        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return contacts
            elif table == 'crm_recommendations':
                return []
            return []

        mock_select.side_effect = select_side_effect
        result = relationship_crm.run()
        self.assertEqual(result['created'], 3)
        self.assertEqual(mock_insert.call_count, 3)

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_recommendation_has_kind_title_rationale(self, mock_insert, mock_select):
        """Inserted recommendation should have kind, title, rationale."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertIn('kind', call_args)
        self.assertIn('title', call_args)
        self.assertIn('rationale', call_args)

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_recommendation_has_app_contact_id_account_id(self, mock_insert, mock_select):
        """Inserted recommendation should preserve app, contact_id, account_id."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['app'], 'app1')
        self.assertEqual(call_args['contact_id'], 'c1')
        self.assertEqual(call_args['account_id'], 'acc1')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_recommendation_has_confidence_and_due_at(self, mock_insert, mock_select):
        """Inserted recommendation should have confidence and due_at."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertIn('confidence', call_args)
        self.assertIn('due_at', call_args)

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_proposed_action_mode_is_draft_only(self, mock_insert, mock_select):
        """proposed_action.mode should always be 'draft_only'."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['proposed_action']['mode'], 'draft_only')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_confidence_is_0_75(self, mock_insert, mock_select):
        """confidence should be 0.75."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['confidence'], 0.75)


class TestBehaviorPreservation(unittest.TestCase):
    """Validates existing behavior, DB patterns, and graceful error handling."""

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_skips_contact_when_not_due(self, mock_insert, mock_select):
        """Contact with future next_contact_at should be skipped."""
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace('+00:00', 'Z')
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': future, 'marketing_allowed': True,
            'do_not_contact': False
        }
        mock_select.return_value = [contact]
        relationship_crm.run()
        mock_insert.assert_not_called()

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_processes_contact_when_no_next_contact_at(self, mock_insert, mock_select):
        """Contact with None next_contact_at should be processed (always due)."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': None, 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        mock_insert.assert_called_once()

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_queries_crm_contacts_table(self, mock_insert, mock_select):
        """Should query crm_contacts table."""
        mock_select.return_value = []
        relationship_crm.run()
        first_call = mock_select.call_args_list[0]
        self.assertEqual(first_call[0][0], 'crm_contacts')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_inserts_to_crm_recommendations_table(self, mock_insert, mock_select):
        """Should insert to crm_recommendations table."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0]
        self.assertEqual(call_args[0], 'crm_recommendations')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_handles_empty_recommendations_list(self, mock_insert, mock_select):
        """Should handle None returned from recommendations query."""
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [{'id': 'c1', 'app': 'app1', 'account_id': 'acc1',
                         'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
                         'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
                         'do_not_contact': False}]
            elif table == 'crm_recommendations':
                return None
            return []

        mock_select.side_effect = select_side_effect
        result = relationship_crm.run()
        self.assertEqual(result['created'], 1)


class TestIntegration(unittest.TestCase):
    """Validates multi-app bulk processing and account_id preservation."""

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_processes_multiple_apps(self, mock_insert, mock_select):
        """Should handle contacts from multiple apps."""
        contacts = [
            {
                'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
                'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
                'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
                'do_not_contact': False
            },
            {
                'id': 'c2', 'app': 'app2', 'account_id': 'acc2', 'first_name': 'John',
                'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
                'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
                'do_not_contact': False
            }
        ]

        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return contacts
            elif table == 'crm_recommendations':
                return []
            return []

        mock_select.side_effect = select_side_effect
        result = relationship_crm.run()
        self.assertEqual(result['created'], 2)
        self.assertEqual(mock_insert.call_count, 2)

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_preserves_account_id_through_recommendation(self, mock_insert, mock_select):
        """account_id from contact should be preserved in recommendation."""
        contact = {
            'id': 'c1', 'app': 'app1', 'account_id': 'account_xyz', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['account_id'], 'account_xyz')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_preserves_app_through_recommendation(self, mock_insert, mock_select):
        """app from contact should be preserved in recommendation."""
        contact = {
            'id': 'c1', 'app': 'special_app', 'account_id': 'acc1', 'first_name': 'Jane',
            'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
            'next_contact_at': '2026-07-25T00:00:00Z', 'marketing_allowed': True,
            'do_not_contact': False
        }
        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return [contact]
            elif table == 'crm_recommendations':
                return []
            return []
        mock_select.side_effect = select_side_effect
        relationship_crm.run()
        call_args = mock_insert.call_args[0][1]
        self.assertEqual(call_args['app'], 'special_app')

    @patch('relationship_crm.db.select')
    @patch('relationship_crm.db.insert')
    def test_bulk_processing_with_mixed_outcomes(self, mock_insert, mock_select):
        """Should handle mix of contacts that create and skip recommendations."""
        now = datetime.now(timezone.utc)
        contacts = [
            {
                'id': 'c1', 'app': 'app1', 'account_id': 'acc1', 'first_name': 'Jane',
                'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
                'next_contact_at': (now - timedelta(hours=1)).isoformat().replace('+00:00', 'Z'),
                'marketing_allowed': True, 'do_not_contact': False
            },
            {
                'id': 'c2', 'app': 'app2', 'account_id': 'acc2', 'first_name': 'John',
                'relationship_health': '30', 'last_contacted_at': '2026-07-20T00:00:00Z',
                'next_contact_at': (now + timedelta(days=1)).isoformat().replace('+00:00', 'Z'),
                'marketing_allowed': True, 'do_not_contact': False
            }
        ]

        def select_side_effect(table, params):
            if table == 'crm_contacts':
                return contacts
            elif table == 'crm_recommendations':
                return []
            return []

        mock_select.side_effect = select_side_effect
        result = relationship_crm.run()
        self.assertEqual(result['reviewed'], 2)
        self.assertEqual(result['created'], 1)


if __name__ == '__main__':
    unittest.main()
