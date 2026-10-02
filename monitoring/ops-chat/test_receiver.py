"""Tests for ops-chat. Standard library only: python -m unittest -v"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import receiver

PAYLOAD = {
    "status": "firing",
    "groupLabels": {"alertname": "DependencyDown"},
    "alerts": [{
        "status": "firing",
        "labels": {"alertname": "DependencyDown", "severity": "critical", "service": "redis"},
        "annotations": {"summary": "Redis (order database) is down", "description": "cannot reach Redis"},
    }],
}


class UnitTests(unittest.TestCase):
    def test_to_message(self):
        msg = receiver.to_message("ops-chat", PAYLOAD, now=100.0)
        self.assertEqual(msg["channel"], "ops-chat")
        self.assertEqual(msg["alerts"][0]["name"], "DependencyDown")
        self.assertEqual(msg["alerts"][0]["target"], "redis")

    def test_heartbeat_goes_stale(self):
        receiver._heartbeat.update(last=1000.0, count=3)
        self.assertTrue(receiver.heartbeat_status(now=1010.0)["healthy"])
        stale = receiver.heartbeat_status(now=1000.0 + receiver.HEARTBEAT_STALE_AFTER + 1)
        self.assertFalse(stale["healthy"])
        self.assertIn("may be broken", stale["text"])

    def test_render_escapes_html(self):
        bad = {"alerts": [{"status": "firing", "labels": {"alertname": "<img src=x>"}}]}
        page = receiver.render([receiver.to_message("c", bad, now=0.0)], receiver.heartbeat_status())
        self.assertNotIn("<img src=x>", page)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), receiver.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            return resp.status

    def test_webhook_and_listing(self):
        self.assertEqual(self.post("/hooks/ops-chat", PAYLOAD), 200)
        with urllib.request.urlopen(self.base + "/api/messages") as resp:
            self.assertEqual(json.load(resp)[0]["alerts"][0]["name"], "DependencyDown")

    def test_heartbeat_endpoint(self):
        self.assertEqual(self.post("/heartbeat", {"alerts": []}), 200)
        with urllib.request.urlopen(self.base + "/api/heartbeat") as resp:
            self.assertTrue(json.load(resp)["healthy"])

    def test_unknown_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
