from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Thread
import unittest

from hermes_plugin import TavrelClient
from tavrel.engine import Engine
from tavrel.runtime import operator_key
from tavrel.server import Gateway
from tavrel.services import Receipt
from tests.fixtures import SERVICES


class RecordingService:
    """A controllable local service that records actual execution attempts."""

    def __init__(self, price=24, cost=None, error=None, started=None, finish=None):
        self.id = "search_brief"
        self.name = "Test search"
        self.price_cents = price
        self.cost = price if cost is None else cost
        self.error = error
        self.started = started
        self.finish = finish
        self.calls = []
        self.lock = Lock()

    def public(self):
        return {**SERVICES[self.id].public(), "price_cents": self.price_cents}

    def execute(self, payload, request_id):
        with self.lock:
            self.calls.append((request_id, payload))
        if self.started:
            self.started.set()
        if self.finish and not self.finish.wait(10):
            raise TimeoutError("Test service was not released")
        if self.error:
            raise self.error
        return Receipt(self.cost, {"query": payload["query"]}, {"kind": "simulated", "reference": "test_" + request_id})


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="tavrel-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.service = RecordingService()
        self.engine = Engine(self.directory / "ledger.sqlite3", {self.service.id: self.service})

    def create(self, budget=100, threshold=100):
        return self.engine.create_task("Test task", budget, threshold, [self.service.id])

    def purchase(self, task_id, key="operation", query="Test query"):
        return self.engine.purchase(task_id, self.service.id, {"query": query}, key)

    def assert_accounting(self, task_id, spent, reserved):
        snapshot = self.engine.snapshot()
        task = self.engine.task(task_id)
        self.assertEqual((task["spent_cents"], task["reserved_cents"]), (spent, reserved))
        self.assertEqual(task["available_cents"], task["limit_cents"] - spent - reserved)
        self.assertEqual(snapshot["account"]["spent_cents"], sum(item["spent_cents"] for item in snapshot["tasks"]))
        self.assertEqual(snapshot["account"]["reserved_cents"], sum(item["reserved_cents"] for item in snapshot["tasks"]))
        self.assertGreaterEqual(snapshot["account"]["available_cents"], 0)


class GatewayCase(EngineCase):
    def setUp(self):
        super().setUp()
        self.operator_token = operator_key(self.directory, create=True)
        self.gateway = Gateway(("127.0.0.1", 0), self.engine, self.operator_token, quiet=True)
        self.url = f"http://127.0.0.1:{self.gateway.server_address[1]}"
        self.thread = Thread(target=self.gateway.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_gateway)
        self.operator = TavrelClient(self.url, self.operator_token)
        created = self.create()
        self.task_id = created["task"]["id"]
        self.task_token = created["task_token"]
        self.agent = TavrelClient(self.url, self.task_token)

    def stop_gateway(self):
        self.gateway.shutdown()
        self.gateway.server_close()
        self.thread.join(timeout=5)
