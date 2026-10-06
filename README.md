# Automated Failure Detection & Alert Notification for Containerized Applications

**DevOps IA-2 Case Study · Prometheus & Alertmanager**

| Name | Roll No. |
|---|---|
| Yashasvi Gupta | 16010123341 |
| Shweta Karandikar | 16010123329 |
| Aditi Agrawal | 16010123018 |

**Department of Computer Engineering · Academic Year 2026–27**

---

### Project Links & Submission Artifacts

- **GitHub Repository:** [https://github.com/Yashvi2874/DevOps_IA2](https://github.com/Yashvi2874/DevOps_IA2)
- **Demonstration Video & Presentation (Google Drive):** [https://drive.google.com/drive/folders/11pqw2HeYxWI5QLId-3zkHv1x-a_rm6BP?usp=sharing](https://drive.google.com/drive/folders/11pqw2HeYxWI5QLId-3zkHv1x-a_rm6BP?usp=sharing)
- **Case Study Report (PDF):** [`docs/Case_Study_Report.pdf`](docs/Case_Study_Report.pdf)
- **Case Study Report (Word):** [`docs/Case_Study_Report.docx`](docs/Case_Study_Report.docx)
- **Presentation Slides (PDF):** [`docs/DevOps IA2.pdf`](docs/DevOps%20IA2.pdf)
- **Presentation Slides (PPTX):** [`docs/DevOps IA2.pptx`](docs/DevOps%20IA2.pptx)

---

## Overview

**OrderFlow** is a containerized food ordering service backed by a Redis database. Customers place meal orders day and night, so a silent failure at 2:00 AM that goes unnoticed means customers keep placing orders that never arrive, and the engineering team only discovers the outage the following morning.

Containers make these failures especially easy to miss: Docker can still report a container as `Up` while the application inside has hung, the database crashed, memory leaked until the kernel kills the process, or the CPU hit its quota and throttled everything.

This case study implements automated failure detection and noise-controlled alert notification using **Prometheus** and **Alertmanager** across a ten-container stack. We inject nine real failure scenarios (error spikes, high latency, hangs, memory leaks, OOM kills, CPU exhaustion, container crashes, database outages, and full service outages) and demonstrate:
- Every failure detected automatically between 16 and 90 seconds (median 60 s).
- Critical alerts routed to on-call email and chat within ~1 minute.
- Intelligent noise suppression: Alertmanager inhibits downstream symptoms so a database crash yields exactly one root-cause notification instead of an alert flood.
- Zero false alarms on a 10-second transient blip due to evaluation wait windows (`for: 30s`).
- Continuous alerting health verification via an automated `Watchdog` heartbeat.

![Architecture](docs/screenshots/architecture.png)

## What runs

The complete stack starts with a single command: `docker compose up -d --build`:

| Container | Port | Role |
|---|---|---|
| `ia2-shop-api` | 8100 | OrderFlow web service (Flask + Gunicorn, limited to 256 MB RAM and 0.5 CPU) |
| `ia2-redis` | internal | Redis database storing orders |
| `ia2-traffic` | internal | Simulated customer traffic generating continuous read and order activity |
| `ia2-prometheus` | 9091 | Scrapes all 7 targets every 5 s, evaluates recording and alerting rules |
| `ia2-alertmanager` | 9094 | Routes, groups, inhibits, silences, and dispatches alert notifications |
| `ia2-blackbox` | 9115 | External prober calling `/health` and `/ready` with a 2-second timeout |
| `ia2-cadvisor` | 8089 | Container Advisor collecting kernel cgroup metrics (CPU, RAM, OOMs, restarts) |
| `ia2-redis-exporter` | internal | Bridges Redis internal telemetry into Prometheus metrics |
| `ia2-mailpit` | 8025 | Local SMTP server with responsive web inbox receiving on-call pages |
| `ia2-ops-chat` | 5002 | Team operations chat channel receiving webhook alerts and watchdog heartbeat |

### Service URLs
- **OrderFlow App & Chaos Panel:** [http://localhost:8100](http://localhost:8100)
- **Prometheus Dashboard & Alerts:** [http://localhost:9091/alerts](http://localhost:9091/alerts)
- **Alertmanager Dashboard:** [http://localhost:9094](http://localhost:9094)
- **Mailpit On-Call Webmail:** [http://localhost:8025](http://localhost:8025)
- **Ops Chat & Heartbeat:** [http://localhost:5002](http://localhost:5002)

## Three Angles of Monitoring

1. **White-box.** OrderFlow exposes `/metrics` via the `prometheus_client` SDK: request counts by route and status, request latency histogram, orders created, and Redis connectivity.
2. **Black-box.** The Prometheus Blackbox Exporter calls `/health` and `/ready` from outside the container. This catches hangs where the process still runs and `/metrics` answers (`up == 1`), but user requests time out.
3. **Container-level.** cAdvisor reads Linux cgroup counters directly from the kernel: memory working set vs limit, throttled CPU periods vs total periods, OOM kill events, and container start times.

## Alert Rules

| Alert | Condition | Wait (`for`) | Severity | Delivery Route |
|---|---|---|---|---|
| `ServiceDown` | `up == 0` | 30 s | critical | email + chat |
| `EndpointDown` | black-box probe of `/health` fails | 40 s | critical | email + chat |
| `DependencyDown` | `redis_up == 0 or up{job="redis"} == 0` | 15 s | critical | email + chat |
| `HighErrorRate` | HTTP 5xx error ratio > 10% | 30 s | critical | email + chat |
| `ContainerOOMKilled` | `increase(container_oom_events_total[5m]) > 0` | 0 s | critical | email + chat |
| `ServiceNotReady` | `/ready` probe fails | 45 s | warning | chat only |
| `HighLatencyP95` | p95 latency > 500 ms | 1 m | warning | chat only |
| `ContainerMemoryNearLimit` | memory > 80% of limit | 15 s | warning | chat only |
| `ContainerCPUThrottled` | throttled in > 50% of CPU periods | 30 s | warning | chat only |
| `ContainerRestarted` | container start timestamp changed in last 5m | 0 s | warning | chat only |
| `Watchdog` | always firing `vector(1)` (dead man's snitch) | 0 s | none | heartbeat receiver |

Precomputed **recording rules** calculate request rates, error ratios, 95th percentile latency, CPU throttling ratios, and memory percentages relative to limits.

## Alertmanager Pipeline & Noise Control

- **Routing:** Critical alerts email on-call immediately (`group_wait: 5s`) *and* dispatch to ops chat (`continue: true`). Warnings route to ops chat only.
- **Grouping:** Alerts are bundled by `[alertname, service]` so related occurrences arrive as a single notification.
- **Inhibition:** When a root cause is firing, secondary symptoms are held back:
  - `DependencyDown` (Redis down) inhibits `HighErrorRate`, `HighLatencyP95`, and `ServiceNotReady`.
  - `ServiceDown` inhibits `EndpointDown` and derivative warnings.
  - `EndpointDown` inhibits latency and readiness alerts.
- **Heartbeat:** The `Watchdog` alert continuously pings the ops chat receiver (~every minute). If the alerting pipeline breaks, the heartbeat badge turns red.
- **HTML Templates:** Custom email templates format clear incident subjects (`[FIRING x1] HighErrorRate on shop-api`) with runbook links and remediation guidance.

## Failure Scenarios & Benchmark Results

Faults can be triggered via the web UI at http://localhost:8100 or using the automated chaos scripts:

```powershell
.\scripts\chaos.ps1 errors     # Options: slow, hang, leak, oom, cpu, crash, db-down, app-down, reset
```

Detection and recovery latency benchmarked via `python scripts/measure_detection.py`:

| Failure Injected | Triggered Alert | Severity | Ops Chat | On-Call Email | Resolved After Fix |
|---|---|---|---|---|---|
| API error spike (50% requests fail) | `HighErrorRate` | critical | 64 s | 59 s | 57 s |
| Slow responses (+1.5 s latency) | `HighLatencyP95` | warning | 90 s | n/a | 56 s |
| Web service hang (+3.0 s delay) | `EndpointDown` | critical | 60 s | 55 s | 26 s |
| Memory leak (~85% of RAM limit) | `ContainerMemoryNearLimit` | warning | 72 s | n/a | 26 s |
| CPU burn (saturated quota) | `ContainerCPUThrottled` | warning | 76 s | n/a | 56 s |
| Database outage (`docker stop ia2-redis`) | `DependencyDown` | critical | 32 s | 27 s | 26 s |
| Fast memory leak (kernel OOM kill) | `ContainerOOMKilled` | critical | 31 s | 26 s | 296 s ¹ |
| Container crash (process exits) | `ContainerRestarted` | warning | 16 s | n/a | n/a ² |
| Full service outage (`docker stop ia2-shop-api`) | `ServiceDown` | critical | 52 s | 47 s | 27 s |

¹ `ContainerOOMKilled` evaluates events over a 5-minute sliding window; it naturally clears 5 minutes after the kill.  
² Container restarts are discrete point-in-time events; the warning clears automatically after 5 minutes.

- **Transient Blip Resilience:** Stopping OrderFlow for 10 seconds dispatched **zero** critical pages because the 30-second `for` wait window absorbed the temporary blip.
- Raw measurement logs are preserved in [`docs/results/`](docs/results).

## Automated Testing & CI/CD Pipeline

Our GitHub Actions workflow (`.github/workflows/ci.yml`) treats alerting as code and validates every commit across three stages:
1. **Unit Tests:** Runs 20 `pytest` tests on OrderFlow, 6 tests on the chat receiver, and `flake8` linting.
2. **Prometheus & Alertmanager Validation:** Validates rule syntax with `promtool check rules`, verifies alert math with `promtool test rules` (8 test suites, including transient blip suppression), and tests routing trees with `amtool config routes test`.
3. **End-to-End Smoke Test:** Starts all 10 containers via Docker Compose, waits for target health and the Watchdog heartbeat, injects a 50% error rate, and asserts alert delivery in both Mailpit and Ops Chat.

![CI/CD Pipeline](docs/screenshots/github-actions.png)

## Repository Layout

```
.github/workflows/       GitHub Actions automated CI/CD pipeline
app/                     OrderFlow Flask application, Dockerfile, and pytest suite
monitoring/
  prometheus/            Scrape config, recording rules, alert rules, promtool tests
  alertmanager/          Routing tree, inhibition rules, HTML email templates
  blackbox/              HTTP 2xx synthetic probe configuration
  ops-chat/              Chat webhook receiver with live watchdog heartbeat badge
traffic/                 Simulated customer ordering traffic generator
scripts/                 Chaos fault injection (chaos.ps1, chaos.sh) and detection benchmark
docs/                    Case study report (PDF, DOCX, MD), presentation slides, screenshots
```

## Useful PromQL Queries

```promql
service:http_requests:rate1m                     # Requests per second
service:http_errors:ratio_rate1m                 # Error ratio (0% to 100%)
service:http_request_duration_seconds:p95_1m     # 95th percentile latency
container:memory_working_set:ratio_limit         # Memory utilization relative to limit
container_cpu_cfs_throttled_periods_total        # CPU throttling events from kernel
probe_success                                    # External blackbox probe availability (0 or 1)
ALERTS{alertstate="firing"}                      # Active firing alerts in Prometheus
```

## Troubleshooting

- **Port Conflict:** If port 8100, 9091, 9094, 8025, or 5002 is in use, modify the host port binding in `docker-compose.yml`.
- **Alert Status:** Inspect `http://localhost:9091/alerts`. Alerts show as *Pending* while the `for` duration timer evaluates.
- **Hot Reloading:** Config changes can be reloaded without container restarts via `curl -X POST localhost:9091/-/reload` (Prometheus) and `curl -X POST localhost:9094/-/reload` (Alertmanager).
- **cAdvisor Permissions:** Requires privileged mode and host root filesystem mounts in `docker-compose.yml` to query cgroup metrics.
