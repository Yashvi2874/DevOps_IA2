"""ops-chat: a stand-in for a team chat channel such as Slack.

Alertmanager delivers notifications here through webhooks:
  POST /hooks/<channel>   alert notifications (firing and resolved)
  POST /heartbeat         the always-firing Watchdog alert, about once a minute
Pages:
  GET  /                  the channel, newest message first, plus heartbeat status
  GET  /api/messages      messages as JSON
  GET  /api/heartbeat     heartbeat status as JSON
  GET  /health            liveness

Standard library only.
"""

import html
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOOK = re.compile(r"^/hooks/([A-Za-z0-9_-]+)$")
HEARTBEAT_STALE_AFTER = int(os.environ.get("HEARTBEAT_STALE_AFTER", "180"))

_messages = deque(maxlen=300)
_heartbeat = {"last": None, "count": 0}
_lock = threading.Lock()


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S UTC")


def to_message(channel, payload, now=None):
    """Turn an Alertmanager webhook body into one chat message."""
    alerts = [
        {
            "status": a.get("status", "unknown"),
            "name": a.get("labels", {}).get("alertname", "unknown"),
            "severity": a.get("labels", {}).get("severity", "none"),
            "target": a.get("labels", {}).get("service") or a.get("labels", {}).get("name") or "",
            "summary": a.get("annotations", {}).get("summary", ""),
            "description": a.get("annotations", {}).get("description", ""),
        }
        for a in payload.get("alerts", [])
    ]
    return {
        "received_at": now if now is not None else time.time(),
        "channel": channel,
        "status": payload.get("status", "unknown"),
        "group": payload.get("groupLabels", {}),
        "alerts": alerts,
    }


def heartbeat_status(now=None):
    now = now if now is not None else time.time()
    with _lock:
        last, count = _heartbeat["last"], _heartbeat["count"]
    if last is None:
        return {"healthy": False, "seconds_ago": None, "count": 0, "text": "No heartbeat received yet"}
    age = now - last
    healthy = age <= HEARTBEAT_STALE_AFTER
    text = (f"Alerting pipeline healthy: last heartbeat {int(age)} s ago" if healthy
            else f"No heartbeat for {int(age)} s: Prometheus or Alertmanager may be broken")
    return {"healthy": healthy, "seconds_ago": round(age, 1), "count": count, "text": text}


def render(messages, beat):
    firing = sum(1 for m in messages for a in m["alerts"] if a["status"] == "firing")
    resolved = sum(1 for m in messages for a in m["alerts"] if a["status"] == "resolved")
    cards = []
    for m in messages:
        rows = []
        for a in m["alerts"]:
            state = "firing" if a["status"] == "firing" else "resolved"
            rows.append(
                f'<div class="alert {state} sev-{html.escape(a["severity"])}">'
                f'<span class="tag">{html.escape(a["status"].upper())}</span> '
                f'<b>{html.escape(a["name"])}</b>'
                f'<span class="meta"> · {html.escape(a["severity"])}'
                f'{" · " + html.escape(a["target"]) if a["target"] else ""}</span>'
                f'<div class="sum">{html.escape(a["summary"])}</div>'
                f'<div class="desc">{html.escape(a["description"])}</div></div>'
            )
        cards.append(
            f'<div class="msg"><div class="avatar">AM</div><div class="body">'
            f'<div class="who"><b>Alertmanager</b> <span>{iso(m["received_at"])} · '
            f'#{html.escape(m["channel"])}</span></div>{"".join(rows)}</div></div>'
        )
    feed = "\n".join(cards) or '<p class="empty">No alerts yet. Quiet is good.</p>'
    beat_css = "ok" if beat["healthy"] else "bad"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5"><title>#ops-chat</title>
<style>
 body {{ margin:0; font-family:"Segoe UI",system-ui,sans-serif; display:flex; min-height:100vh; background:#fff; color:#1d1c1d; }}
 nav {{ width:220px; background:#3f0e40; color:#cfc3cf; padding:18px 14px; }}
 nav h1 {{ color:#fff; font-size:1.05rem; margin:0 0 18px; }}
 nav .ch {{ background:#1164a3; color:#fff; padding:5px 10px; border-radius:6px; }}
 nav p {{ font-size:.8rem; margin-top:22px; line-height:1.4; }}
 main {{ flex:1; padding:0 0 30px; }}
 .top {{ border-bottom:1px solid #e3e3e3; padding:14px 22px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }}
 .top h2 {{ margin:0; font-size:1.1rem; }}
 .beat {{ padding:6px 12px; border-radius:999px; font-size:.82rem; font-weight:600; }}
 .beat.ok {{ background:#dcfce7; color:#166534; }} .beat.bad {{ background:#fee2e2; color:#991b1b; }}
 .counts {{ padding:10px 22px; font-size:.85rem; color:#616061; }}
 .msg {{ display:flex; gap:10px; padding:10px 22px; }} .msg:hover {{ background:#f8f8f8; }}
 .avatar {{ width:36px; height:36px; border-radius:6px; background:#e8590c; color:#fff; font-weight:700;
   display:flex; align-items:center; justify-content:center; font-size:.8rem; flex-shrink:0; }}
 .who span {{ color:#616061; font-size:.78rem; }}
 .alert {{ border-left:4px solid #d97706; background:#fffbeb; margin:6px 0; padding:6px 10px; border-radius:4px; }}
 .alert.sev-critical {{ border-color:#dc2626; background:#fef2f2; }}
 .alert.resolved {{ border-color:#16a34a; background:#f0fdf4; }}
 .tag {{ font-size:.72rem; font-weight:700; }}
 .firing .tag {{ color:#b91c1c; }} .resolved .tag {{ color:#15803d; }}
 .meta {{ color:#616061; font-size:.82rem; }} .sum {{ margin-top:2px; }} .desc {{ color:#616061; font-size:.82rem; }}
 .empty {{ padding:20px 22px; color:#616061; }}
</style></head><body>
<nav><h1>OrderFlow team</h1><div class="ch"># ops-chat</div>
<p>Warnings and critical alerts land here. Critical alerts are also emailed to the on-call engineer.</p></nav>
<main><div class="top"><h2># ops-chat</h2><span class="beat {beat_css}">{html.escape(beat["text"])}</span></div>
<div class="counts">{firing} firing · {resolved} resolved notifications in this channel · page refreshes every 5 s</div>
{feed}</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ops-chat/1.0"

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/":
            with _lock:
                messages = list(_messages)
            self._send(200, render(messages, heartbeat_status()), "text/html; charset=utf-8")
        elif self.path == "/api/messages":
            with _lock:
                self._send(200, json.dumps(list(_messages)))
        elif self.path == "/api/heartbeat":
            self._send(200, json.dumps(heartbeat_status()))
        elif self.path == "/health":
            self._send(200, '{"status": "ok"}')
        else:
            self._send(404, '{"error": "not found"}')

    def do_POST(self):
        try:
            payload = self._read_json()
        except ValueError:
            self._send(400, '{"error": "invalid JSON"}')
            return
        if self.path == "/heartbeat":
            with _lock:
                _heartbeat["last"] = time.time()
                _heartbeat["count"] += 1
            self._send(200, '{"status": "heartbeat recorded"}')
            return
        match = HOOK.match(self.path)
        if not match:
            self._send(404, '{"error": "not found"}')
            return
        message = to_message(match.group(1), payload)
        with _lock:
            _messages.appendleft(message)
        for a in message["alerts"]:
            print(f"[#{message['channel']}] {a['status'].upper():8} {a['name']} ({a['severity']}) {a['summary']}",
                  flush=True)
        self._send(200, '{"status": "posted"}')

    def log_message(self, fmt, *args):
        pass  # health checks every few seconds would drown the useful lines


def main():
    port = int(os.environ.get("PORT", "5002"))
    print(f"ops-chat listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
