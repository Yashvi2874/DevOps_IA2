"""Where orders are kept.

The real app uses Redis. Tests use MemoryStore, which behaves the same way
but needs no server. Both raise StoreUnavailable when the backing store
can't be reached, so the app can turn that into a clear 503.
"""

import json
import time


class StoreUnavailable(Exception):
    pass


class RedisStore:
    KEY = "orders"
    MAX_ORDERS = 200

    def __init__(self, url):
        import redis  # imported here so tests don't need the package

        self._redis = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
        self._errors = (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)

    def ping(self):
        try:
            return bool(self._redis.ping())
        except self._errors:
            return False

    def add_order(self, item, quantity):
        try:
            order_id = self._redis.incr("order_id")
            order = {"id": order_id, "item": item, "quantity": quantity, "created_at": time.time()}
            pipe = self._redis.pipeline()
            pipe.lpush(self.KEY, json.dumps(order))
            pipe.ltrim(self.KEY, 0, self.MAX_ORDERS - 1)
            pipe.execute()
            return order
        except self._errors as exc:
            raise StoreUnavailable(str(exc)) from exc

    def list_orders(self, limit=20):
        try:
            return [json.loads(raw) for raw in self._redis.lrange(self.KEY, 0, limit - 1)]
        except self._errors as exc:
            raise StoreUnavailable(str(exc)) from exc


class MemoryStore:
    def __init__(self):
        self.orders = []
        self.available = True
        self._next_id = 1

    def ping(self):
        return self.available

    def add_order(self, item, quantity):
        if not self.available:
            raise StoreUnavailable("memory store switched off")
        order = {"id": self._next_id, "item": item, "quantity": quantity, "created_at": time.time()}
        self._next_id += 1
        self.orders.insert(0, order)
        return order

    def list_orders(self, limit=20):
        if not self.available:
            raise StoreUnavailable("memory store switched off")
        return self.orders[:limit]
