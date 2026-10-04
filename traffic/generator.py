"""Fake users: a steady mix of browsing and ordering, so error rate and
latency have something to measure."""

import json
import os
import random
import time
import urllib.error
import urllib.request

TARGET = os.environ.get("TARGET", "http://shop-api:8000")
RATE = float(os.environ.get("REQUESTS_PER_SECOND", "4"))
ITEMS = ["Notebook", "Pen", "Backpack", "Water bottle", "Desk lamp", "Headphones", "Stapler"]


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(TARGET + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return 0


def main():
    print(f"sending ~{RATE} requests/s to {TARGET}", flush=True)
    sent, last_report = 0, time.time()
    while True:
        roll = random.random()
        if roll < 0.7:
            request("GET", "/api/orders")
        elif roll < 0.9:
            request("POST", "/api/orders", {"item": random.choice(ITEMS), "quantity": random.randint(1, 5)})
        else:
            request("GET", "/")
        sent += 1
        if time.time() - last_report > 60:
            print(f"{sent} requests sent in the last minute", flush=True)
            sent, last_report = 0, time.time()
        time.sleep(1 / RATE)


if __name__ == "__main__":
    main()
