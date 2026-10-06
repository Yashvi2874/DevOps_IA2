import json
import sys
from unittest import mock

import pytest

from orderflow import create_app
from orderflow.chaos import Chaos
from orderflow.store import MemoryStore


class NoRandom:
    """rng stand-in: random() returns a fixed value."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def chaos():
    return Chaos(sleep=lambda s: None, rng=NoRandom(0.0))


@pytest.fixture
def kill():
    return mock.Mock()


@pytest.fixture
def client(store, chaos, kill):
    app = create_app({"STORE": store, "CHAOS": chaos, "KILL_FUNCTION": kill,
                      "START_BACKGROUND": False, "TESTING": True})
    return app.test_client()


def post(client, path, **body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


def test_health_is_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_ready_depends_on_redis(client, store):
    assert client.get("/ready").status_code == 200
    store.available = False
    res = client.get("/ready")
    assert res.status_code == 503
    assert res.get_json()["redis"] == "down"


def test_create_and_list_orders(client):
    res = post(client, "/api/orders", item="Margherita Pizza", quantity=2)
    assert res.status_code == 201
    orders = client.get("/api/orders").get_json()["orders"]
    assert orders[0]["item"] == "Margherita Pizza"
    assert orders[0]["quantity"] == 2


@pytest.mark.parametrize("body", [{"item": "", "quantity": 1}, {"item": "Pen", "quantity": 0},
                                  {"item": "Pen", "quantity": "lots"}, {"item": "Pen", "quantity": 101}])
def test_invalid_orders_are_rejected(client, body):
    assert post(client, "/api/orders", **body).status_code == 400


def test_orders_api_returns_503_when_database_is_down(client, store):
    store.available = False
    assert client.get("/api/orders").status_code == 503
    assert post(client, "/api/orders", item="Pen", quantity=1).status_code == 503


def test_metrics_expose_request_and_dependency_metrics(client, store):
    client.get("/api/orders")
    store.available = False
    text = client.get("/metrics").get_data(as_text=True)
    assert 'http_requests_total{method="GET",route="/api/orders",status="200"} 1.0' in text
    assert "http_request_duration_seconds_bucket" in text
    assert 'app_dependency_up{dependency="redis"} 0.0' in text
    if sys.platform.startswith("linux"):  # process metrics come from /proc
        assert "process_start_time_seconds" in text


def test_metrics_endpoint_is_not_counted_as_traffic(client):
    client.get("/metrics")
    text = client.get("/metrics").get_data(as_text=True)
    assert 'route="/metrics"' not in text


def test_error_injection_fails_api_requests_but_not_metrics(client, chaos):
    assert post(client, "/api/chaos/errors", rate=1.0).status_code == 200
    assert client.get("/api/orders").status_code == 500
    assert client.get("/metrics").status_code == 200
    assert 'chaos_active{mode="errors"} 1.0' in client.get("/metrics").get_data(as_text=True)


def test_latency_injection_sleeps_before_requests(store, kill):
    sleeps = []
    chaos = Chaos(sleep=sleeps.append, rng=NoRandom(0.99))
    app = create_app({"STORE": store, "CHAOS": chaos, "KILL_FUNCTION": kill, "START_BACKGROUND": False})
    client = app.test_client()
    post(client, "/api/chaos/latency", ms=1500)
    client.get("/health")
    assert sleeps == [1.5]
    client.get("/metrics")
    assert sleeps == [1.5]  # /metrics is never slowed down


def test_reset_clears_faults(client, chaos):
    post(client, "/api/chaos/errors", rate=1.0)
    post(client, "/api/chaos/latency", ms=900)
    post(client, "/api/chaos/reset")
    assert chaos.state()["error_rate"] == 0
    assert chaos.state()["latency_ms"] == 0
    assert client.get("/api/orders").status_code == 200


def test_crash_answers_first_then_kills(client, kill):
    with mock.patch("orderflow.app.threading.Timer") as timer:
        res = post(client, "/api/chaos/crash")
    assert res.status_code == 200
    timer.assert_called_once_with(0.5, kill)


def test_unknown_fault_is_rejected(client):
    assert post(client, "/api/chaos/meteor").status_code == 400


def test_fault_injection_can_be_disabled(store, kill):
    app = create_app({"STORE": store, "KILL_FUNCTION": kill, "START_BACKGROUND": False, "CHAOS_ENABLED": False})
    assert app.test_client().post("/api/chaos/errors").status_code == 403


def test_index_page_renders(client):
    page = client.get("/").get_data(as_text=True)
    assert "OrderFlow" in page
    assert "Fault injection" in page
