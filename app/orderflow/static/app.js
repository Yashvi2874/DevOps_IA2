const host = window.location.hostname;
const links = { "l-prom": 9091, "l-am": 9094, "l-chat": 5002, "l-mail": 8025, "l-cad": 8089 };
for (const [id, port] of Object.entries(links)) {
  document.getElementById(id).href = `http://${host}:${port}`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function pill(id, ok, text) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = "pill " + (ok ? "good" : "bad");
}

async function refresh() {
  try {
    const res = await fetch("/ready", { cache: "no-store" });
    const body = await res.json();
    pill("api-status", true, "API up");
    pill("db-status", body.redis === "up", body.redis === "up" ? "Redis up" : "Redis down");
  } catch (err) {
    pill("api-status", false, "API unreachable");
    pill("db-status", false, "Redis unknown");
  }

  try {
    const res = await fetch("/api/orders", { cache: "no-store" });
    const body = await res.json();
    const rows = (body.orders || []).slice(0, 8).map((o) =>
      `<tr><td>${o.id}</td><td>${esc(o.item)}</td><td>${o.quantity}</td>` +
      `<td>${new Date(o.created_at * 1000).toLocaleTimeString()}</td></tr>`);
    document.getElementById("orders").innerHTML = res.ok
      ? rows.join("") || '<tr><td colspan="4">No orders yet</td></tr>'
      : `<tr><td colspan="4" class="err">${esc(body.error)} (HTTP ${res.status})</td></tr>`;
  } catch (err) {
    document.getElementById("orders").innerHTML = '<tr><td colspan="4" class="err">Could not load orders</td></tr>';
  }

  const stateEl = document.getElementById("chaos-state");
  if (stateEl) {
    try {
      const s = await (await fetch("/api/chaos", { cache: "no-store" })).json();
      stateEl.textContent = `latency ${s.latency_ms} ms · error rate ${Math.round(s.error_rate * 100)}% · ` +
        `leaked ${s.leaked_mb} MB · CPU burn ${s.cpu_burning ? "on" : "off"}`;
    } catch (err) {
      stateEl.textContent = "fault state unavailable";
    }
  }
}

document.getElementById("order-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("order-msg");
  const res = await fetch("/api/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item: document.getElementById("item").value, quantity: Number(document.getElementById("qty").value) }),
  });
  const body = await res.json();
  msg.textContent = res.ok ? `Order #${body.order.id} placed` : `Failed: ${body.error}`;
  refresh();
});

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const res = await fetch(`/api/chaos/${btn.dataset.action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: btn.dataset.body,
  });
  const body = await res.json().catch(() => ({}));
  document.getElementById("chaos-state").textContent = res.ok ? `Done: ${btn.textContent}` : `Failed: ${body.error}`;
});

refresh();
setInterval(refresh, 3000);
