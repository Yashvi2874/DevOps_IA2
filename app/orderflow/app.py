import os
import signal
import threading
import time
from types import SimpleNamespace

from flask import Flask, Response, g, jsonify, render_template, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)

from .chaos import Chaos
from .store import RedisStore, StoreUnavailable

# never slowed down, so a hang shows up in the black-box probe while up stays 1
UNTOUCHED = ("/metrics", "/api/chaos", "/static/")


def kill_container():
    # gunicorn is PID 1; stopping it takes the whole container down
    if os.getppid() == 1:
        os.kill(1, signal.SIGINT)
    os._exit(1)


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        self.requests = Counter(
            "http_requests", "HTTP requests handled", ["method", "route", "status"], registry=self.registry
        )
        self.duration = Histogram(
            "http_request_duration_seconds", "Time spent handling a request", ["route"],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5), registry=self.registry,
        )
        self.orders = Counter("orders_created", "Orders successfully stored", registry=self.registry)
        self.dependency_up = Gauge(
            "app_dependency_up", "1 if the dependency answers, 0 if not", ["dependency"], registry=self.registry
        )
        self.chaos = Gauge("chaos_active", "1 while a fault is being injected", ["mode"], registry=self.registry)
        self.leaked = Gauge("chaos_leaked_bytes", "Memory deliberately leaked", registry=self.registry)


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        REDIS_URL=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        CHAOS_ENABLED=os.environ.get("CHAOS_ENABLED", "true").lower() == "true",
        DEPENDENCY_CHECK_INTERVAL=float(os.environ.get("DEPENDENCY_CHECK_INTERVAL", "5")),
        STORE=None,
        CHAOS=None,
        KILL_FUNCTION=kill_container,
        START_BACKGROUND=True,
    )
    if config:
        app.config.update(config)

    store = app.config["STORE"] or RedisStore(app.config["REDIS_URL"])
    chaos = app.config["CHAOS"] or Chaos()
    metrics = Metrics()
    state = SimpleNamespace(started_at=time.time())

    def refresh_gauges():
        metrics.dependency_up.labels("redis").set(1 if store.ping() else 0)
        for mode, active in chaos.active_modes().items():
            metrics.chaos.labels(mode).set(1 if active else 0)
        metrics.leaked.set(chaos.leaked_mb * 1024 * 1024)

    def background_checks():
        while True:
            refresh_gauges()
            time.sleep(app.config["DEPENDENCY_CHECK_INTERVAL"])

    refresh_gauges()
    if app.config["START_BACKGROUND"]:
        threading.Thread(target=background_checks, name="dependency-check", daemon=True).start()

    app.extensions["orderflow"] = SimpleNamespace(store=store, chaos=chaos, metrics=metrics)

    @app.before_request
    def before():
        g.start = time.perf_counter()
        if request.path.startswith(UNTOUCHED):
            return None
        if chaos.before_request():
            return jsonify(error="injected failure (chaos: errors)"), 500
        return None

    @app.after_request
    def after(response):
        if request.path != "/metrics":
            route = request.url_rule.rule if request.url_rule else "unmatched"
            metrics.requests.labels(request.method, route, str(response.status_code)).inc()
            metrics.duration.labels(route).observe(time.perf_counter() - g.get("start", time.perf_counter()))
        return response

    @app.get("/")
    def index():
        return render_template("index.html", chaos_enabled=app.config["CHAOS_ENABLED"])

    @app.get("/health")
    def health():
        return jsonify(status="ok", uptime_seconds=round(time.time() - state.started_at, 1))

    @app.get("/ready")
    def ready():
        redis_ok = store.ping()
        metrics.dependency_up.labels("redis").set(1 if redis_ok else 0)
        body = {"status": "ready" if redis_ok else "not ready", "redis": "up" if redis_ok else "down"}
        return jsonify(body), 200 if redis_ok else 503

    @app.get("/metrics")
    def prometheus_metrics():
        refresh_gauges()
        return Response(generate_latest(metrics.registry), mimetype=CONTENT_TYPE_LATEST)

    @app.get("/api/orders")
    def list_orders():
        try:
            return jsonify(orders=store.list_orders())
        except StoreUnavailable:
            return jsonify(error="order database unavailable"), 503

    @app.post("/api/orders")
    def create_order():
        body = request.get_json(silent=True) or {}
        item = str(body.get("item", "")).strip()[:60]
        try:
            quantity = int(body.get("quantity", 1))
        except (TypeError, ValueError):
            quantity = 0
        if not item or not 1 <= quantity <= 100:
            return jsonify(error="item is required and quantity must be 1-100"), 400
        try:
            order = store.add_order(item, quantity)
        except StoreUnavailable:
            return jsonify(error="order database unavailable"), 503
        metrics.orders.inc()
        return jsonify(order=order), 201

    @app.get("/api/chaos")
    def chaos_state():
        return jsonify(enabled=app.config["CHAOS_ENABLED"], **chaos.state())

    @app.post("/api/chaos/<action>")
    def chaos_action(action):
        if not app.config["CHAOS_ENABLED"]:
            return jsonify(error="fault injection is disabled"), 403
        body = request.get_json(silent=True) or {}
        if action == "latency":
            chaos.set_latency(body.get("ms", 1500))
        elif action == "errors":
            chaos.set_error_rate(body.get("rate", 0.5))
        elif action == "leak":
            chaos.start_leak(body.get("mb_per_sec", 5), body.get("max_mb", 150))
        elif action == "oom":
            chaos.start_leak(body.get("mb_per_sec", 40), 0)
        elif action == "cpu":
            chaos.burn_cpu(body.get("seconds", 120))
        elif action == "crash":
            threading.Timer(0.5, app.config["KILL_FUNCTION"]).start()
            return jsonify(ok=True, action="crash", message="the container will exit in 0.5 s")
        elif action == "reset":
            chaos.reset()
        else:
            return jsonify(error=f"unknown action: {action}"), 400
        refresh_gauges()
        return jsonify(ok=True, action=action, state=chaos.state())

    return app
