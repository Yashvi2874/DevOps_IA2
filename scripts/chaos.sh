#!/bin/sh
# Inject (and clear) failures during a demo, from bash. Same faults as chaos.ps1:
#   errors | slow | hang | leak | oom | cpu | crash | reset | status
#   db-down | db-up | app-down | app-up
set -eu
URL="${URL:-http://localhost:8100}"
post() { curl -s -X POST "$URL/api/chaos/$1" -H 'Content-Type: application/json' -d "$2"; echo; }

case "${1:?usage: chaos.sh <fault>}" in
  errors)   post errors '{"rate": 0.5}' ;;
  slow)     post latency '{"ms": 1500}' ;;
  hang)     post latency '{"ms": 3000}' ;;
  leak)     post leak '{"mb_per_sec": 5, "max_mb": 170}' ;;
  oom)      post oom '{"mb_per_sec": 40}' ;;
  cpu)      post cpu '{"seconds": 120}' ;;
  crash)    post crash '{}' ;;
  reset)    post reset '{}' ;;
  status)   curl -s "$URL/api/chaos"; echo ;;
  db-down)  docker stop ia2-redis ;;
  db-up)    docker start ia2-redis ;;
  app-down) docker stop ia2-shop-api ;;
  app-up)   docker start ia2-shop-api ;;
  *)        echo "unknown fault: $1" >&2; exit 1 ;;
esac
