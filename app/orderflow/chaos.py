"""Fault injection, so the monitoring has real failures to catch.

Every fault is switched on through the API and cleared by reset(). Nothing
here runs unless someone asks for it.
"""

import random
import threading
import time

MB = 1024 * 1024


class Chaos:
    def __init__(self, sleep=time.sleep, rng=None):
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self.latency_ms = 0
        self.error_rate = 0.0
        self.leak_mb_per_sec = 0
        self.leak_max_mb = 0
        self.cpu_until = 0.0
        self._leaked = []
        self._leak_thread = None
        self._cpu_threads = []

    # --- request-level faults -------------------------------------------------

    def before_request(self):
        """Called before each API request: add delay, maybe fail."""
        if self.latency_ms:
            self._sleep(self.latency_ms / 1000)
        return self.error_rate > 0 and self._rng.random() < self.error_rate

    def set_latency(self, ms):
        self.latency_ms = max(0, int(ms))

    def set_error_rate(self, rate):
        self.error_rate = min(1.0, max(0.0, float(rate)))

    # --- resource faults ------------------------------------------------------

    @property
    def leaked_mb(self):
        return len(self._leaked)

    def start_leak(self, mb_per_sec, max_mb=0):
        """Allocate memory every second and never free it (until reset)."""
        self.leak_mb_per_sec = max(1, int(mb_per_sec))
        self.leak_max_mb = max(0, int(max_mb))
        if self._leak_thread is None or not self._leak_thread.is_alive():
            self._leak_thread = threading.Thread(target=self._leak_loop, name="chaos-leak", daemon=True)
            self._leak_thread.start()

    def _leak_loop(self):
        while self.leak_mb_per_sec:
            with self._lock:
                for _ in range(self.leak_mb_per_sec):
                    if self.leak_max_mb and len(self._leaked) >= self.leak_max_mb:
                        break
                    # bytes filled with a non-zero value so the pages are really used
                    self._leaked.append(b"\x01" * MB)
            time.sleep(1)

    def burn_cpu(self, seconds, threads=2):
        """Keep the CPU busy for a while."""
        self.cpu_until = time.time() + max(1, int(seconds))
        for _ in range(threads):
            t = threading.Thread(target=self._burn_loop, name="chaos-cpu", daemon=True)
            t.start()
            self._cpu_threads.append(t)

    def _burn_loop(self):
        x = 0
        while time.time() < self.cpu_until:
            x = (x * 31 + 7) % 1_000_003

    # --- state ----------------------------------------------------------------

    def reset(self):
        self.latency_ms = 0
        self.error_rate = 0.0
        self.leak_mb_per_sec = 0
        self.leak_max_mb = 0
        self.cpu_until = 0.0
        with self._lock:
            self._leaked.clear()

    def state(self):
        return {
            "latency_ms": self.latency_ms,
            "error_rate": self.error_rate,
            "leak_mb_per_sec": self.leak_mb_per_sec,
            "leaked_mb": self.leaked_mb,
            "cpu_burning": time.time() < self.cpu_until,
        }

    def active_modes(self):
        s = self.state()
        return {
            "latency": s["latency_ms"] > 0,
            "errors": s["error_rate"] > 0,
            "memory_leak": s["leak_mb_per_sec"] > 0,
            "cpu_burn": s["cpu_burning"],
        }
