import time

from orderflow.chaos import Chaos


def test_error_rate_is_clamped():
    chaos = Chaos()
    chaos.set_error_rate(5)
    assert chaos.error_rate == 1.0
    chaos.set_error_rate(-1)
    assert chaos.error_rate == 0.0


def test_leak_grows_until_its_cap_and_reset_frees_it():
    chaos = Chaos()
    chaos.start_leak(mb_per_sec=4, max_mb=6)
    deadline = time.time() + 5
    while chaos.leaked_mb < 6 and time.time() < deadline:
        time.sleep(0.1)
    time.sleep(1.2)
    assert chaos.leaked_mb == 6          # stopped at the cap
    chaos.reset()
    assert chaos.leaked_mb == 0
    assert chaos.active_modes()["memory_leak"] is False


def test_cpu_burn_reports_active_then_stops():
    chaos = Chaos()
    chaos.burn_cpu(seconds=1, threads=1)
    assert chaos.state()["cpu_burning"] is True
    time.sleep(1.3)
    assert chaos.state()["cpu_burning"] is False
