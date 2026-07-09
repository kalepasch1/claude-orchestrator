import asyncio
import json
import os
import socket
import sys
import unittest
from unittest.mock import MagicMock, patch

import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control
from fleet_control import FleetWebSocketServer


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FleetControlTest(unittest.TestCase):

    def test_safe_key_rejects_credentials(self):
        self.assertTrue(fleet_control._safe_key("ORCH_AUTO_PULL"))
        self.assertTrue(fleet_control._safe_key("MAX_PARALLEL"))
        self.assertFalse(fleet_control._safe_key("OPENAI_API_KEY"))
        self.assertFalse(fleet_control._safe_key("ORCH_SECRET_TOKEN"))

    def test_all_target_done_when_expected_hosts_ack(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [{
                "id": "ctrl-1",
                "target": "all",
                "action": "reload_config",
                "handled_by": ["mac1"],
                "params": {"expected_hosts": ["mac1", "mac2"]},
            }],
            [],
        ]

        with patch.object(fleet_control, "db", fake_db), patch.object(fleet_control, "HOST", "mac2"):
            self.assertEqual(fleet_control.process_controls(), 1)

        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["mac1", "mac2"])
        self.assertTrue(update_patch["done"])

    def test_all_target_without_expected_hosts_stays_open_for_other_machines(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [{
                "id": "ctrl-1",
                "target": "all",
                "action": "reload_config",
                "handled_by": [],
                "params": {},
            }],
            [],
        ]

        with patch.object(fleet_control, "db", fake_db), patch.object(fleet_control, "HOST", "mac2"):
            self.assertEqual(fleet_control.process_controls(), 1)

        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["mac2"])
        self.assertFalse(update_patch["done"])

    def test_pause_action_sets_host_scoped_kill_switch_and_acks(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{
            "id": "ctrl-p",
            "target": "Mac-2.local",
            "action": "pause",
            "handled_by": [],
            "params": {"reason": "cost spike"},
        }]
        fake_ks = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "kill_switch", fake_ks), \
             patch.object(fleet_control, "HOST", "Mac-2.local"):
            self.assertEqual(fleet_control.process_controls(), 1)

        # soft-pauses THIS host only (not global), and does not restart/exit.
        fake_ks.pause.assert_called_once()
        kwargs = fake_ks.pause.call_args.kwargs
        self.assertEqual(kwargs.get("scope"), "host")
        self.assertEqual(kwargs.get("project"), "Mac-2.local")
        self.assertEqual(kwargs.get("reason"), "cost spike")
        # single-host target -> row closes immediately after this host acks.
        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["Mac-2.local"])
        self.assertTrue(update_patch["done"])

    def test_resume_action_lifts_host_pause(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{
            "id": "ctrl-r",
            "target": "Mac-2.local",
            "action": "resume",
            "handled_by": [],
            "params": {},
        }]
        fake_ks = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "kill_switch", fake_ks), \
             patch.object(fleet_control, "HOST", "Mac-2.local"):
            self.assertEqual(fleet_control.process_controls(), 1)

        fake_ks.resume.assert_called_once()
        self.assertEqual(fake_ks.resume.call_args.kwargs.get("scope"), "host")
        self.assertEqual(fake_ks.resume.call_args.kwargs.get("project"), "Mac-2.local")
        fake_ks.pause.assert_not_called()


async def _register(ws, hostname):
    await ws.send(json.dumps({"type": "register", "hostname": hostname}))


class TestFleetWebSocketServer(unittest.IsolatedAsyncioTestCase):

    async def test_start_and_stop(self):
        port = _free_port()
        srv = FleetWebSocketServer(port=port, heartbeat_interval=30)
        await srv.start()
        self.assertIsNotNone(srv._server)
        await srv.stop()
        self.assertEqual(srv._sessions, {})

    async def test_ten_concurrent_connections_tracked(self):
        port = _free_port()
        srv = FleetWebSocketServer(port=port, heartbeat_interval=30)
        await srv.start()
        clients = []
        try:
            for i in range(10):
                ws = await websockets.connect(f"ws://127.0.0.1:{port}")
                await _register(ws, f"runner-{i:02d}")
                clients.append(ws)
            await asyncio.sleep(0.05)
            async with srv._lock:
                names = set(srv._sessions)
            self.assertEqual(names, {f"runner-{i:02d}" for i in range(10)})
        finally:
            for ws in clients:
                await ws.close()
            await asyncio.sleep(0.05)
            await srv.stop()

    async def test_heartbeat_ping_pong(self):
        port = _free_port()
        srv = FleetWebSocketServer(port=port, heartbeat_interval=0.1)
        await srv.start()
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}")
            await _register(ws, "beat-runner")
            await asyncio.sleep(0.05)
            async with srv._lock:
                self.assertIn("beat-runner", srv._sessions)
            # the server sends pings every 0.1s; websockets client auto-responds with pong
            await asyncio.sleep(0.35)
            # connection still alive after several ping/pong cycles
            async with srv._lock:
                self.assertIn("beat-runner", srv._sessions)
            await ws.close()
        finally:
            await srv.stop()

    async def test_stale_client_dropped(self):
        port = _free_port()
        # very short heartbeat so the test completes quickly
        srv = FleetWebSocketServer(port=port, heartbeat_interval=0.1)
        await srv.start()
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}")
            await _register(ws, "stale-runner")
            await asyncio.sleep(0.05)
            async with srv._lock:
                self.assertIn("stale-runner", srv._sessions)
            # close the transport abruptly (no clean WebSocket close frame)
            ws.transport.close()
            # wait for the recv_loop / heartbeat to detect the dead connection
            await asyncio.sleep(0.5)
            async with srv._lock:
                self.assertNotIn("stale-runner", srv._sessions)
        finally:
            await srv.stop()

    async def test_reconnect_within_5s(self):
        port = _free_port()
        srv = FleetWebSocketServer(port=port, heartbeat_interval=30)
        await srv.start()
        try:
            ws1 = await websockets.connect(f"ws://127.0.0.1:{port}")
            await _register(ws1, "reconnect-runner")
            await asyncio.sleep(0.05)
            async with srv._lock:
                self.assertIn("reconnect-runner", srv._sessions)
                first_server_ws = srv._sessions["reconnect-runner"]

            await ws1.close()
            await asyncio.sleep(0.05)
            async with srv._lock:
                self.assertNotIn("reconnect-runner", srv._sessions)

            ws2 = await websockets.connect(f"ws://127.0.0.1:{port}")
            await _register(ws2, "reconnect-runner")
            await asyncio.sleep(0.05)
            async with srv._lock:
                self.assertIn("reconnect-runner", srv._sessions)
                # server-side connection is a fresh object (not the original)
                self.assertIsNot(srv._sessions["reconnect-runner"], first_server_ws)

            await ws2.close()
        finally:
            await srv.stop()

    async def test_subscribe_and_publish(self):
        port = _free_port()
        srv = FleetWebSocketServer(port=port, heartbeat_interval=30)
        await srv.start()
        received = []
        srv.subscribe("metrics", lambda ch, msg: received.append((ch, msg)))
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}")
            await _register(ws, "pub-runner")
            await asyncio.sleep(0.05)

            await srv.publish("metrics", {"cpu": 42})
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            msg = json.loads(raw)
            self.assertEqual(msg["channel"], "metrics")
            self.assertEqual(msg["data"]["cpu"], 42)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0][0], "metrics")

            await ws.close()
        finally:
            await srv.stop()


if __name__ == "__main__":
    unittest.main()
