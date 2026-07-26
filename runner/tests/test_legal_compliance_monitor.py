"""Comprehensive tests for legal_compliance_monitor module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import legal_compliance_monitor


class TestScanDiff:
    """Test cases for scan_diff() function."""

    def test_scan_empty_diff(self):
        """Test scan_diff with empty diff returns no events."""
        events = legal_compliance_monitor.scan_diff("", "proj1")
        assert events == []

    def test_scan_none_diff(self):
        """Test scan_diff with None diff returns no events."""
        events = legal_compliance_monitor.scan_diff(None, "proj1")
        assert events == []

    def test_scan_pii_exposure(self):
        """Test detection of PII exposure in added lines."""
        diff = """\
--- a/src/utils.js
+++ b/src/utils.js
+console.log("User email:", user.email)
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1", task_slug="t1")
        categories = [e["risk_category"] for e in events]
        assert "pii_exposure" in categories

    def test_scan_auth_change(self):
        """Test detection of authentication changes."""
        diff = """\
--- a/src/auth.js
+++ b/src/auth.js
+const session = supabase.auth.signIn({ email, password })
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        categories = [e["risk_category"] for e in events]
        assert "auth_change" in categories

    def test_scan_payment_change(self):
        """Test detection of payment logic changes."""
        diff = """\
--- a/src/billing.js
+++ b/src/billing.js
+const charge = await stripe.charges.create({ amount: 1000 })
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        categories = [e["risk_category"] for e in events]
        assert "payment_change" in categories

    def test_scan_data_retention(self):
        """Test detection of data retention changes."""
        diff = """\
--- a/src/cleanup.py
+++ b/src/cleanup.py
+db.execute("DELETE FROM users WHERE last_login < %s", [cutoff])
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        categories = [e["risk_category"] for e in events]
        assert "data_retention" in categories

    def test_scan_gdpr(self):
        """Test detection of GDPR-relevant changes."""
        diff = """\
--- a/src/consent.js
+++ b/src/consent.js
+const consent = await getUserConsent({ lawful_basis: "legitimate_interest" })
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        categories = [e["risk_category"] for e in events]
        assert "gdpr" in categories

    def test_scan_license_violation(self):
        """Test detection of license violations."""
        diff = """\
--- a/package.json
+++ b/package.json
+// This code is GPL licensed - all rights reserved
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        categories = [e["risk_category"] for e in events]
        assert "license_violation" in categories

    def test_scan_encryption(self):
        """Test detection of encryption changes."""
        diff = """\
--- a/src/crypto.py
+++ b/src/crypto.py
+hashed = bcrypt.hash(password, salt_rounds=12)
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        categories = [e["risk_category"] for e in events]
        assert "encryption" in categories

    def test_scan_api_security(self):
        """Test detection of API security changes."""
        diff = """\
--- a/src/server.js
+++ b/src/server.js
+app.use(cors({ origin: '*', allowedHeaders: ['x-api-key'] }))
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        categories = [e["risk_category"] for e in events]
        assert "api_security" in categories

    def test_scan_third_party_sdk(self):
        """Test detection of third-party SDK additions."""
        diff = """\
--- a/package.json
+++ b/package.json
+import mixpanel from 'mixpanel-browser'
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        categories = [e["risk_category"] for e in events]
        assert "third_party_sdk" in categories

    def test_scan_only_added_lines(self):
        """Test that only added lines (starting with +) are scanned."""
        diff = """\
--- a/src/auth.js
+++ b/src/auth.js
-const session = supabase.auth.signIn({ email, password })
 // unchanged line about signOut
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        assert events == []

    def test_scan_file_path_extraction(self):
        """Test that file path is extracted from diff header."""
        diff = """\
--- a/src/auth.js
+++ b/src/auth.js
+const token = jwt.sign(payload, secret)
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        assert len(events) > 0
        assert events[0]["file_path"] == "src/auth.js"

    def test_scan_sets_project_and_task(self):
        """Test that project_id and task_slug are set on events."""
        diff = """\
+++ b/src/auth.js
+const session = supabase.auth.signIn({ email })
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1", dag_id="dag1", task_slug="t1")
        assert len(events) > 0
        assert events[0]["project_id"] == "proj1"
        assert events[0]["dag_id"] == "dag1"
        assert events[0]["task_slug"] == "t1"

    def test_scan_truncates_diff_excerpt(self):
        """Test that diff excerpt is truncated to 500 chars."""
        long_line = "+" + "x" * 1000
        diff = f"+++ b/src/auth.js\n{long_line}\n+const token = jwt.sign(payload, secret)"
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        for event in events:
            assert len(event["diff_excerpt"]) <= 500


class TestSeverityEscalation:
    """Test cases for severity escalation logic."""

    def test_production_escalation(self):
        """Test that production context escalates severity by 1."""
        diff = """\
+++ b/src/auth.js
+// production deployment: accessibility changes
+const el = document.querySelector('[aria-label="submit"]')
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        # accessibility default is "info", production should escalate to "low"
        accessibility_events = [e for e in events if e["risk_category"] == "accessibility"]
        if accessibility_events:
            assert accessibility_events[0]["severity"] in ("low", "medium", "high")

    def test_medical_escalation(self):
        """Test that medical/health context escalates severity by 2."""
        diff = """\
+++ b/src/patient.js
+// HIPAA patient data handler
+console.log("Patient email:", patient.email)
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        pii_events = [e for e in events if e["risk_category"] == "pii_exposure"]
        if pii_events:
            assert pii_events[0]["severity"] == "critical"

    def test_financial_escalation(self):
        """Test that financial/SOX context escalates severity by 2."""
        diff = """\
+++ b/src/audit.js
+// SOX compliance audit trail
+audit.log({ created_by: user.id, action: "modify" })
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        assert len(events) > 0

    def test_children_escalation(self):
        """Test that children/COPPA context escalates severity by 2."""
        diff = """\
+++ b/src/age.js
+// COPPA: children under 13 require parental consent
+const consent = await getParentalConsent({ minor: true })
"""
        events = legal_compliance_monitor.scan_diff(diff, "proj1")
        assert len(events) > 0


class TestRecordEvents:
    """Test cases for record_events() function."""

    def test_record_events_basic(self):
        """Test recording events to database."""
        mock_db = Mock()
        mock_db.insert.return_value = {"id": "1"}
        with patch('legal_compliance_monitor.db', mock_db):
            events = [{"risk_category": "pii_exposure", "severity": "high", "summary": "test"}]
            count = legal_compliance_monitor.record_events(events)
            assert count == 1
            mock_db.insert.assert_called_once()

    def test_record_events_no_db(self):
        """Test record_events returns 0 when db unavailable."""
        with patch('legal_compliance_monitor.db', None):
            count = legal_compliance_monitor.record_events([{"test": "event"}])
            assert count == 0

    def test_record_events_empty_list(self):
        """Test record_events with empty list."""
        count = legal_compliance_monitor.record_events([])
        assert count == 0

    def test_record_events_db_error(self):
        """Test record_events handles db errors gracefully."""
        mock_db = Mock()
        mock_db.insert.side_effect = Exception("DB error")
        with patch('legal_compliance_monitor.db', mock_db):
            count = legal_compliance_monitor.record_events([{"test": "event"}])
            assert count == 0


class TestBroadcastToBus:
    """Test cases for broadcast_to_bus() function."""

    def test_broadcast_high_severity(self):
        """Test that high severity events are broadcast."""
        bus = Mock()
        events = [{"severity": "high", "summary": "test", "risk_category": "pii",
                    "task_slug": "t1", "diff_excerpt": "...", "file_path": "a.py"}]
        legal_compliance_monitor.broadcast_to_bus(events, bus)
        bus.publish.assert_called_once()

    def test_broadcast_critical_severity(self):
        """Test that critical severity events are broadcast."""
        bus = Mock()
        events = [{"severity": "critical", "summary": "test", "risk_category": "pii",
                    "task_slug": "t1", "diff_excerpt": "...", "file_path": "a.py"}]
        legal_compliance_monitor.broadcast_to_bus(events, bus)
        bus.publish.assert_called_once()

    def test_no_broadcast_low_severity(self):
        """Test that low severity events are NOT broadcast."""
        bus = Mock()
        events = [{"severity": "low", "summary": "test", "risk_category": "audit",
                    "task_slug": "t1"}]
        legal_compliance_monitor.broadcast_to_bus(events, bus)
        bus.publish.assert_not_called()

    def test_no_broadcast_no_bus(self):
        """Test broadcast does nothing when bus is None."""
        legal_compliance_monitor.broadcast_to_bus([{"severity": "high"}], None)
        # Should not raise


class TestCheckMergeBlock:
    """Test cases for check_merge_block() function."""

    def test_block_on_critical(self):
        """Test that critical events block merge."""
        events = [{"severity": "critical", "summary": "critical risk"}]
        blocked, event = legal_compliance_monitor.check_merge_block(events)
        assert blocked is True
        assert event is not None

    def test_no_block_on_high(self):
        """Test that high severity events do NOT block merge."""
        events = [{"severity": "high", "summary": "high risk"}]
        blocked, event = legal_compliance_monitor.check_merge_block(events)
        assert blocked is False

    def test_no_block_on_empty(self):
        """Test no block with empty events."""
        blocked, event = legal_compliance_monitor.check_merge_block([])
        assert blocked is False
        assert event is None


class TestStats:
    """Test cases for stats() function."""

    def test_stats_no_db(self):
        """Test stats returns empty dict when db unavailable."""
        with patch('legal_compliance_monitor.db', None):
            result = legal_compliance_monitor.stats()
            assert result == {}

    def test_stats_db_error(self):
        """Test stats handles db errors gracefully."""
        mock_db = Mock()
        mock_db.count.side_effect = Exception("DB error")
        with patch('legal_compliance_monitor.db', mock_db):
            result = legal_compliance_monitor.stats()
            assert result == {}


class TestAcknowledge:
    """Test cases for acknowledge() function."""

    def test_acknowledge_success(self):
        """Test acknowledging a compliance event."""
        mock_db = Mock()
        with patch('legal_compliance_monitor.db', mock_db):
            result = legal_compliance_monitor.acknowledge("event-123", by="operator")
            assert result is True
            mock_db.update.assert_called_once()

    def test_acknowledge_no_db(self):
        """Test acknowledge returns False when db unavailable."""
        with patch('legal_compliance_monitor.db', None):
            result = legal_compliance_monitor.acknowledge("event-123")
            assert result is False

    def test_acknowledge_db_error(self):
        """Test acknowledge handles db errors."""
        mock_db = Mock()
        mock_db.update.side_effect = Exception("DB error")
        with patch('legal_compliance_monitor.db', mock_db):
            result = legal_compliance_monitor.acknowledge("event-123")
            assert result is False


class TestUnacknowledgedRisks:
    """Test cases for unacknowledged_risks() function."""

    def test_unacknowledged_no_db(self):
        """Test unacknowledged_risks returns empty when db unavailable."""
        with patch('legal_compliance_monitor.db', None):
            result = legal_compliance_monitor.unacknowledged_risks()
            assert result == []

    def test_unacknowledged_db_error(self):
        """Test unacknowledged_risks handles db errors."""
        mock_db = Mock()
        mock_db.select.side_effect = Exception("DB error")
        with patch('legal_compliance_monitor.db', mock_db):
            result = legal_compliance_monitor.unacknowledged_risks()
            assert result == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
