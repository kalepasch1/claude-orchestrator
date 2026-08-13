"""Tests for the interface layer (REST controllers + external adapters)."""
import os
import sys
import unittest

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from interfaces.gateways import inbox_gateway  # noqa: E402
from interfaces.http import inbox_controller  # noqa: E402


class InboxControllerTest(unittest.TestCase):
    def setUp(self):
        inbox_controller.reset()

    def test_valid_payload_returns_200(self):
        response = inbox_controller.handle_request({"id": "doc-1", "kind": "contract"})
        self.assertEqual(response["status"], 200)
        self.assertEqual(response["body"]["status"], "processed")
        self.assertEqual(response["body"]["item"]["id"], "doc-1")

    def test_missing_payload_returns_400(self):
        self.assertEqual(inbox_controller.handle_request(None)["status"], 400)

    def test_empty_payload_returns_400(self):
        self.assertEqual(inbox_controller.handle_request({})["status"], 400)

    def test_non_mapping_payload_returns_400(self):
        for bad in ("string", 42, ["a"], object()):
            self.assertEqual(inbox_controller.handle_request(bad)["status"], 400)

    def test_missing_required_field_returns_400(self):
        response = inbox_controller.handle_request({"kind": "contract"})
        self.assertEqual(response["status"], 400)
        self.assertIn("id", response["error"])

    def test_oversized_payload_returns_400(self):
        payload = {"id": "x"}
        payload.update({"k%d" % i: i for i in range(inbox_controller.ORCH_INBOX_MAX_FIELDS + 1)})
        self.assertEqual(inbox_controller.handle_request(payload)["status"], 400)

    def test_domain_error_returns_500_not_raise(self):
        original = inbox_controller.process_inbox_item

        def boom(_item):
            raise RuntimeError("domain exploded")

        inbox_controller.process_inbox_item = boom
        try:
            response = inbox_controller.handle_request({"id": "doc-1"})
            self.assertEqual(response["status"], 500)
            self.assertIn("domain exploded", response["error"])
        finally:
            inbox_controller.process_inbox_item = original

    def test_stats_track_handled_and_rejected(self):
        inbox_controller.handle_request({"id": "a"})
        inbox_controller.handle_request(None)
        stats = inbox_controller.stats()
        self.assertEqual(stats["handled"], 1)
        self.assertEqual(stats["rejected"], 1)

    def test_validate_is_pure_and_reports_reason(self):
        self.assertIsNone(inbox_controller.InboxController.validate({"id": "x"}))
        self.assertIn("object", inbox_controller.InboxController.validate("nope"))


class InboxGatewayTest(unittest.TestCase):
    def setUp(self):
        inbox_gateway.clear()

    def test_no_sinks_is_a_noop_not_an_error(self):
        outcome = inbox_gateway.dispatch({"status": "processed"})
        self.assertEqual(outcome["dispatched"], 0)
        self.assertEqual(outcome["failed"], 0)

    def test_registered_sink_receives_result(self):
        received = []
        inbox_gateway.register("collector", received.append)
        outcome = inbox_gateway.dispatch({"status": "processed", "item": {"id": "1"}})
        self.assertEqual(outcome["dispatched"], 1)
        self.assertEqual(received[0]["item"]["id"], "1")

    def test_failing_sink_does_not_block_others(self):
        received = []

        def bad(_result):
            raise ValueError("sink down")

        inbox_gateway.register("bad", bad)
        inbox_gateway.register("good", received.append)
        outcome = inbox_gateway.dispatch({"status": "processed"})
        self.assertEqual(outcome["dispatched"], 1)
        self.assertEqual(outcome["failed"], 1)
        self.assertIn("sink down", outcome["outcomes"]["bad"])
        self.assertEqual(len(received), 1)

    def test_failing_sink_is_retried(self):
        attempts = []

        def flaky(_result):
            attempts.append(1)
            if len(attempts) < 2:
                raise ValueError("transient")

        inbox_gateway.register("flaky", flaky)
        outcome = inbox_gateway.dispatch({"status": "processed"})
        self.assertEqual(outcome["dispatched"], 1)
        self.assertGreaterEqual(len(attempts), 2)

    def test_register_rejects_bad_input(self):
        self.assertFalse(inbox_gateway.register("", print))
        self.assertFalse(inbox_gateway.register("x", "not-callable"))

    def test_register_replaces_same_name(self):
        inbox_gateway.register("only", lambda _r: None)
        inbox_gateway.register("only", lambda _r: None)
        self.assertEqual(inbox_gateway.stats()["sinks"], 1)

    def test_unregister(self):
        inbox_gateway.register("temp", lambda _r: None)
        self.assertTrue(inbox_gateway.unregister("temp"))
        self.assertFalse(inbox_gateway.unregister("temp"))

    def test_non_dict_result_is_fail_soft(self):
        inbox_gateway.register("collector", lambda _r: None)
        self.assertEqual(inbox_gateway.dispatch("nope")["dispatched"], 0)
        self.assertEqual(inbox_gateway.dispatch(None)["dispatched"], 0)


class EndToEndTest(unittest.TestCase):
    def test_controller_result_flows_through_gateway(self):
        inbox_controller.reset()
        inbox_gateway.clear()
        delivered = []
        inbox_gateway.register("sink", delivered.append)
        response = inbox_controller.handle_request({"id": "doc-9"})
        self.assertEqual(response["status"], 200)
        inbox_gateway.dispatch(response["body"])
        self.assertEqual(delivered[0]["item"]["id"], "doc-9")


if __name__ == "__main__":
    unittest.main()
