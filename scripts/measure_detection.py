"""Inject each failure into the running stack and time the alerts: until the
ops chat (and, for critical alerts, the email inbox) gets them, and until
they resolve after the fix. Writes docs/results/. Takes about 25 minutes.

    python scripts/measure_detection.py
    python scripts/measure_detection.py --only "cpu burn"    # re-run some
"""

import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP = "http://localhost:8100"
PROM = "http://localhost:9091"
AM = "http://localhost:9094"
CHAT = "http://localhost:5002"
MAIL = "http://localhost:8025"
OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "results"


def http(method, url, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode()
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code}
    except OSError as exc:
        return {"error": str(exc)}


def chaos(action, **body):
    return http("POST", f"{APP}/api/chaos/{action}", body)


def docker(*args):
    subprocess.run(["docker", *args], check=True, capture_output=True)


def chat_events(since):
    msgs = http("GET", f"{CHAT}/api/messages")
    if not isinstance(msgs, list):
        return []
    return [(a["name"], a["status"], m["received_at"]) for m in msgs if m["received_at"] >= since
            for a in m["alerts"]]


def email_subjects(since):
    res = http("GET", f"{MAIL}/api/v1/messages?limit=200")
    if not isinstance(res, dict):
        return []
    out = []
    for m in res.get("messages", []):
        created = m.get("Created", "")
        # Mailpit timestamps are RFC 3339; compare as epoch seconds
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if ts >= since:
            out.append((m.get("Subject", ""), ts))
    return out


def wait_for(check, timeout, poll=1.0):
    start = time.time()
    while time.time() - start < timeout:
        result = check()
        if result:
            return result
        time.sleep(poll)
    return None


def active_alerts():
    res = http("GET", f"{AM}/api/v2/alerts?active=true&silenced=false&inhibited=false")
    return sorted({a["labels"]["alertname"] for a in res}) if isinstance(res, list) else []


def inhibited_alerts():
    res = http("GET", f"{AM}/api/v2/alerts?active=false&silenced=false&inhibited=true")
    return sorted({a["labels"]["alertname"] for a in res}) if isinstance(res, list) else []


def prometheus_firing():
    res = http("GET", f"{PROM}/api/v1/alerts")
    alerts = res.get("data", {}).get("alerts", []) if isinstance(res, dict) else []
    return sorted({a["labels"]["alertname"] for a in alerts if a["state"] == "firing"} - {"Watchdog"})


def settle(ignore=("Watchdog", "ContainerRestarted"), timeout=240):
    wait_for(lambda: not (set(active_alerts()) - set(ignore)), timeout, poll=3)
    time.sleep(35)  # let Alertmanager's group_interval pass so the next scenario starts clean


SCENARIOS = [
    # name, expected alert, severity, break, fix
    ("API error spike (50% of requests fail)", "HighErrorRate", "critical",
     lambda: chaos("errors", rate=0.5), lambda: chaos("reset")),
    ("Slow responses (1.5 s per request)", "HighLatencyP95", "warning",
     lambda: chaos("latency", ms=1500), lambda: chaos("reset")),
    ("App hangs (3 s, health probe times out)", "EndpointDown", "critical",
     lambda: chaos("latency", ms=3000), lambda: chaos("reset")),
    ("Memory leak up to ~85% of the limit", "ContainerMemoryNearLimit", "warning",
     lambda: chaos("leak", mb_per_sec=5, max_mb=170), lambda: chaos("reset")),
    ("CPU burn (container at its CPU limit)", "ContainerCPUThrottled", "warning",
     lambda: chaos("cpu", seconds=150), lambda: chaos("reset")),
    ("Database outage (docker stop ia2-redis)", "DependencyDown", "critical",
     lambda: docker("stop", "ia2-redis"), lambda: docker("start", "ia2-redis")),
    ("Out of memory (fast leak, kernel OOM kill)", "ContainerOOMKilled", "critical",
     lambda: chaos("oom", mb_per_sec=40), lambda: chaos("reset")),
    ("Container crash (process exits)", "ContainerRestarted", "warning",
     lambda: chaos("crash"), lambda: None),
    ("Whole service down (docker stop ia2-shop-api)", "ServiceDown", "critical",
     lambda: docker("stop", "ia2-shop-api"), lambda: docker("start", "ia2-shop-api")),
]


def run_scenario(name, alert, severity, breaker, fixer):
    print(f"\n=== {name}  (expecting {alert})", flush=True)
    t0 = time.time()
    breaker()
    hit = wait_for(lambda: next((t for n, s, t in chat_events(t0) if n == alert and s == "firing"), None), 240)
    chat_s = round(hit - t0, 1) if hit else None
    mail_s = None
    if severity == "critical":
        mail = wait_for(lambda: next((ts for subj, ts in email_subjects(t0 - 2)
                                      if alert in subj and "FIRING" in subj), None), 60)
        mail_s = round(mail - t0, 1) if mail else None
    time.sleep(3)
    raw = prometheus_firing()
    suppressed = inhibited_alerts()
    print(f"    chat after {chat_s}s, email after {mail_s}s; Prometheus firing {raw}; inhibited {suppressed}",
          flush=True)

    t1 = time.time()
    fixer()
    resolved = wait_for(lambda: next((t for n, s, t in chat_events(t1) if n == alert and s == "resolved"), None),
                        300) if alert != "ContainerRestarted" else None
    resolved_s = round(resolved - t1, 1) if resolved else None
    print(f"    resolved after {resolved_s}s", flush=True)
    return {"scenario": name, "alert": alert, "severity": severity, "chat_seconds": chat_s,
            "email_seconds": mail_s, "resolved_seconds": resolved_s,
            "prometheus_firing": raw, "inhibited": suppressed}


def blip_test():
    # a 10 s outage must not page anyone
    print("\n=== 10 s blip (docker stop, wait 10 s, docker start)", flush=True)
    t0 = time.time()
    docker("stop", "ia2-shop-api")
    time.sleep(10)
    docker("start", "ia2-shop-api")
    time.sleep(75)
    paged = [n for n, s, _ in chat_events(t0) if n in ("ServiceDown", "EndpointDown") and s == "firing"]
    print(f"    critical pages during blip: {paged or 'none'}", flush=True)
    return {"scenario": "10 s outage (false-positive check)", "paged": paged}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    only = [w.lower() for w in sys.argv[sys.argv.index("--only") + 1:]] if "--only" in sys.argv else []
    saved = OUT / "detection_results.json"
    previous = json.loads(saved.read_text()) if only and saved.exists() else {}
    chaos("reset")
    settle()
    results = []
    for scenario in SCENARIOS:
        if only and not any(w in scenario[0].lower() for w in only):
            old = next((r for r in previous.get("scenarios", []) if r["scenario"] == scenario[0]), None)
            if old:
                results.append(old)
            continue
        results.append(run_scenario(*scenario))
        settle()
    blip = previous.get("blip") if only and previous.get("blip") else blip_test()

    (OUT / "detection_results.json").write_text(json.dumps({"scenarios": results, "blip": blip}, indent=2))
    lines = ["| Scenario | Expected alert | Severity | Ops chat | On-call email | Resolved after fix | "
             "Firing in Prometheus | Suppressed by inhibition |",
             "|---|---|---|---|---|---|---|---|"]
    fmt = lambda v: f"{v:.0f} s" if isinstance(v, (int, float)) else "–"  # noqa: E731
    for r in results:
        lines.append(f"| {r['scenario']} | `{r['alert']}` | {r['severity']} | {fmt(r['chat_seconds'])} | "
                     f"{fmt(r['email_seconds'])} | {fmt(r['resolved_seconds'])} | "
                     f"{', '.join(r['prometheus_firing']) or '–'} | {', '.join(r['inhibited']) or '–'} |")
    lines.append("")
    lines.append(f"False-positive check, 10 s outage: critical pages sent = {len(blip['paged'])}")
    (OUT / "detection_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    return 0 if all(r["chat_seconds"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
