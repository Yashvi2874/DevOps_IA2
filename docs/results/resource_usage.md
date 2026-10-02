# Resource use of the running stack

Measured with `docker stats` (average of three samples, 5 s apart) while the
traffic generator was sending requests and no faults were active.
Docker Desktop on Windows, 20 CPUs and about 8 GB of memory given to Docker.

| Container | CPU | Memory |
|---|---|---|
| ia2-prometheus | 2.2% | 77 MiB |
| ia2-shop-api | 2.8% | 46 MiB |
| ia2-alertmanager | 0.4% | 34 MiB |
| ia2-cadvisor | 3.4% | 30 MiB |
| ia2-blackbox | 1.0% | 26 MiB |
| ia2-mailpit | 0.0% | 24 MiB |
| ia2-ops-chat | 0.0% | 14 MiB |
| ia2-traffic | 1.2% | 14 MiB |
| ia2-redis-exporter | 0.8% | 13 MiB |
| ia2-redis | 0.7% | 10 MiB |

Prometheus was holding about 3,080 active time series and collecting about
3,400 samples per 5-second scrape round.
