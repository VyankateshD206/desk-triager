const $ = (selector) => document.querySelector(selector);
const names = {
  tick_gap: "Stale market feed",
  rate_limit: "Exchange throttling",
  nav_mismatch: "NAV mismatch",
  latency: "Slow order fills",
  ml_degradation: "Telemetry feature drift",
};
const statusLabels = {open: "Needs review", queued: "Queued", verifying: "Verifying recovery",
  failed: "Needs attention", resolved: "Resolved"};
const actions = {
  reconnect_feed: "Reconnect the simulated market feed.",
  enable_backoff: "Apply retry backoff to the simulated gateway.",
  resync_ledger:
    "Synchronize the simulation ledger with the simulated exchange balance.",
  resync_orders: "Resynchronize simulated order state.",
  inspect_only:
    "Review feature drift. No automated recovery is available for this signal.",
};
const scenarios = {
  tick_gap:
    "Market ticks stop updating. The detector flags stale data while the service still appears to be running.",
  silence:
    "The feed stops sending telemetry entirely. A watchdog detects the missing heartbeat.",
  rate_limit:
    "The simulated exchange rejects requests with HTTP 429. Review the evidence and approve retry backoff.",
  latency:
    "Simulated order fills slow to 650 ms, breaching the 350 ms alert threshold.",
  nav_mismatch:
    "A $1,250 gap appears between the local ledger and simulated exchange. Reconcile it before approving a resync.",
  ml_degradation:
    "Slippage and heartbeat jitter drift outside the synthetic baseline. The ML detector flags this for inspection only.",
};
let state,
  selected,
  busy = false,
  starting = false,
  activeScenario = null;
try {
  activeScenario = JSON.parse(
    sessionStorage.getItem("desk-scenario") || "null",
  );
} catch {
  sessionStorage.removeItem("desk-scenario");
}
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const clock = (value) =>
  new Date(value).toLocaleTimeString([], { hour12: false });
const money = (value) =>
  Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const help = (value, text) =>
  `<span tabindex="0" data-help="${escape(text)}" aria-describedby="help-tooltip">${escape(value)}</span>`;
async function api(path, body, extraHeaders = {}) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Desk-Token": $("#token").value,
      ...extraHeaders,
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const value = await response.json();
  if (!response.ok)
    throw Error(
      typeof value.detail === "string"
        ? value.detail
        : JSON.stringify(value.detail),
    );
  return value;
}
function showError(error) {
  $("#error").textContent = error.message;
  $("#error").classList.remove("hidden");
}
function updateGuide() {
  ["detect", "review", "recover"].forEach((step) =>
    $("#step-" + step).classList.remove("active"),
  );
  if (!activeScenario) {
    $("#scenario-hint").textContent =
      "Choose a failure to see how the desk responds.";
    return;
  }
  $("#step-detect").classList.add("active");
  const kind =
    activeScenario.kind === "silence" ? "tick_gap" : activeScenario.kind;
  const incident = state?.incidents.find(
    (i) =>
      i.service === activeScenario.service &&
      i.kind === kind &&
      (i.status !== "resolved" ||
        Date.parse(i.opened_at) >= activeScenario.since - 1000),
  );
  if (!incident) {
    $("#scenario-hint").textContent =
      activeScenario.kind === "silence"
        ? `Waiting for the ${state?.tick_gap_seconds ?? 8}-second silence threshold…`
        : "Failure injected. Waiting for the detector…";
    return;
  }
  $("#step-review").classList.add("active");
  if (incident.status === "resolved") {
    $("#step-recover").classList.add("active");
    $("#scenario-hint").textContent =
      "Recovered. A fresh healthy sample confirmed success.";
  } else if (incident.status === "verifying") {
    $("#step-recover").classList.add("active");
    $("#scenario-hint").textContent =
      "Recovery approved. Checking fresh telemetry…";
  } else {
    $("#scenario-hint").textContent =
      incident.action === "inspect_only"
        ? "Drift detected. Open the incident to inspect the evidence."
        : "Incident detected. Open Review below to approve recovery.";
  }
}
function renderChart(events) {
  const width = 760,
    left = 40,
    max = Math.max(400, ...events.map((e) => e.fill_latency_ms));
  const y = (value) => 145 - (value / max) * 128;
  const points = events
    .map(
      (e, i) =>
        `${left + (i * width) / Math.max(1, events.length - 1)},${y(e.fill_latency_ms)}`,
    )
    .join(" ");
  const svg = $("#chart");
  svg.innerHTML = `${[0, max].map((value) => `<line x1="${left}" y1="${y(value)}" x2="800" y2="${y(value)}" stroke="#30383b"/><text x="0" y="${y(value) + 4}" fill="#98a6a9" font-size="11">${Math.round(value)}</text>`).join("")}<line x1="${left}" y1="${y(350)}" x2="800" y2="${y(350)}" stroke="#ad8863" stroke-dasharray="4 5"/><polyline points="${points}" fill="none" stroke="#b9dfc4" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
  $("#chart-start").textContent = events.length
    ? clock(events[0].timestamp)
    : "Waiting for samples";
}
function render(s) {
  state = s;
  const unresolved = s.incidents.filter((i) => i.status !== "resolved");
  $("#open").textContent = s.open_incident_count;
  $("#open").style.color = s.open_incident_count
    ? "var(--orange)"
    : "var(--text)";
  $("#queue-status").textContent = s.open_incident_count
    ? "Review needed"
    : "No unresolved incidents";
  const gateway = s.events.filter((e) => e.service === "execution-gateway"),
    latest = gateway.at(-1);
  $("#latency").innerHTML = latest
    ? `${Math.round(latest.fill_latency_ms)} <small>ms</small>`
    : "—";
  $("#latency-note").textContent = !latest
    ? "No gateway samples"
    : s.service_age_seconds["execution-gateway"] > s.tick_gap_seconds
      ? "Last known sample · feed stale"
      : "Latest gateway sample";
  const difference = s.balances.reduce(
    (sum, b) => sum + Number(b.difference),
    0,
  );
  const mismatch = s.balances.some(
    (b) => Math.abs(Number(b.difference)) > 0.01,
  );
  $("#difference").textContent = s.balances.length
    ? "$" + money(difference)
    : "—";
  $("#difference").style.color = mismatch ? "var(--orange)" : "var(--text)";
  $("#balance-note").textContent = !s.balances.length
    ? "No ledger accounts"
    : mismatch
      ? "Reconciliation needed"
      : "Ledger matches exchange";
  const degraded = Object.keys(s.errors).length;
  $("#session").textContent = degraded
    ? "Needs attention"
    : s.mode === "simulated desk"
      ? "Monitoring services"
      : "Monitoring";
  $("#session").style.color = degraded ? "var(--orange)" : "var(--green)";
  $("#updated").textContent = s.last_ingest
    ? "Updated " + clock(s.last_ingest)
    : "Waiting for telemetry";
  $("#infrastructure").textContent =
    `${s.database === "postgresql" ? "PostgreSQL" : "Local SQLite"} · ${s.ai_provider === "gemini" ? "Gemini REST" : "Offline triage"} · Direct Python ingestion`;
  if (degraded)
    showError(
      Error("A background worker needs attention: " + JSON.stringify(s.errors)),
    );
  for (const [service, age] of Object.entries(s.service_age_seconds)) {
    const node = $("#service-" + service),
      count = s.open_incidents_by_service[service] || 0,
      stale = age > s.tick_gap_seconds;
    const status = count ? "Review" : stale ? "Stale" : "Healthy";
    node.className = "service" + (count || stale ? " attention" : "");
    node.innerHTML = `${escape(service)}<small>${status}</small>`;
    node.dataset.help = `${service}: ${status.toLowerCase()}. Last accepted sample arrived ${age.toFixed(1)} seconds ago. Silence beyond ${s.tick_gap_seconds} seconds triggers a feed-gap incident. ${count} unresolved incident(s). A service can receive telemetry while its values are anomalous.`;
  }
  renderIncidents();
  renderChart(gateway);
  renderSupporting(s);
  $("#inject").disabled = starting || s.mode !== "simulated desk";
  updateGuide();
  if (selected && $("#detail").open) {
    const current = s.incidents.find((i) => i.id === selected.id);
    if (current) {
      selected.status = current.status;
      if (current.report && !busy && current.report !== selected.report) {
        $("#report").textContent = current.report;
        if (selected.approval) selected.approval.status = "superseded";
        $("#modal-message").textContent = "Diagnosis changed. Reopen this incident to review the updated proposal.";
      }
      updateApproval();
    }
  }
}
function renderIncidents() {
  if (!state) return;
  const rows = state.incidents.filter(
    (i) => $("#show-history").checked || i.status !== "resolved",
  );
  $("#incident-rows").innerHTML =
    rows
      .map(
        (i) =>
          `<tr><td>${escape(names[i.kind] || i.kind)}</td><td>${escape(i.service)}</td><td><span class="badge ${escape(i.status)}">${escape(statusLabels[i.status] || i.status)}</span></td><td><button class="inspect" data-id="${escape(i.id)}">${i.status === "open" ? "Review" : "View"}</button></td></tr>`,
      )
      .join("") ||
    '<tr><td class="empty" colspan="4"><strong>No open incidents</strong>Start a scenario to follow detection, diagnosis, and recovery.</td></tr>';
}
function renderSupporting(s) {
  $("#events").textContent = s.event_count.toLocaleString();
  $("#balances").innerHTML =
    s.balances
      .map(
        (b) =>
          `<div class="balance"><div class="account">${escape(b.account)}</div><div class="balance-grid"><div><small>Local NAV</small><strong>${help(money(b.local_nav), "Net asset value held in the local ledger, in US dollars.")}</strong></div><div><small>Exchange NAV</small><strong>${help(money(b.exchange_nav), "Net asset value reported by the simulated exchange, in US dollars. This is the reference for simulated reconciliation.")}</strong></div><div><small>Difference</small><strong>${help(money(b.difference), "Local NAV minus simulated exchange NAV. A difference above one cent in absolute value triggers reconciliation review.")}</strong></div></div></div>`,
      )
      .join("") || '<p class="subtle">No ledger accounts configured.</p>';
  $("#journal").innerHTML =
    s.audit
      .slice(0, 15)
      .map(
        (a) =>
          `<div class="journal-row"><time data-help="${escape("Audit event recorded at " + new Date(a.at).toLocaleString() + ". Times use your browser timezone.")}" tabindex="0" aria-describedby="help-tooltip">${clock(a.at)}</time><span>${escape(a.action.replaceAll("_", " "))}<small>${escape(a.actor)}</small></span></div>`,
      )
      .join("") ||
    '<p class="subtle">Detection and recovery activity will appear here.</p>';
}
function updateApproval() {
  $("#detail-status").textContent = statusLabels[selected.status] || selected.status;
  $("#detail-status").className = "badge " + selected.status;
  $("#approve").disabled =
    busy ||
    selected.status !== "open" ||
    selected.action === "inspect_only" ||
    state?.mode !== "simulated desk" || selected.approval?.status !== "pending";
  $("#reject").disabled = busy || selected.status !== "open" || selected.approval?.status !== "pending";
  $("#approve").textContent =
    selected.action === "inspect_only"
      ? "Inspection only"
      : selected.status === "resolved"
        ? "Recovery verified"
        : selected.status === "verifying"
          ? "Verifying recovery…"
          : selected.status === "queued" ? "Recovery queued…"
          : selected.status === "failed" ? "Escalation required"
          : "Approve recovery";
}
async function refresh() {
  try {
    const s = await api("/api/snapshot");
    $("#error").classList.add("hidden");
    render(s);
  } catch (e) {
    showError(e);
    $("#session").textContent = "Disconnected";
  }
}
async function inspect(id) {
  try {
    selected = await api("/api/incidents/" + id);
    $("#detail-title").textContent = names[selected.kind] || selected.kind;
    $("#detail-service").textContent = selected.service;
    $("#diagnosis").textContent = selected.diagnosis;
    $("#action").textContent = actions[selected.action] || selected.action;
    $("#script").textContent = selected.script;
    $("#evidence").textContent = JSON.stringify(selected.evidence, null, 2);
    $("#report").textContent =
      selected.report ||
      "The triage worker is collecting logs and checking ledger balances. You can also refresh the diagnosis.";
    $("#modal-message").textContent = "";
    updateApproval();
    $("#detail").showModal();
  } catch (e) {
    showError(e);
  }
}
$("#incident-rows").addEventListener("click", (e) => {
  const button = e.target.closest("[data-id]");
  if (button) inspect(button.dataset.id);
});
$("#show-history").onchange = renderIncidents;
$("#close").onclick = () => {
  $("#detail").close();
  hideHelp();
};
const savedToken = sessionStorage.getItem("desk-token");
$("#token").value =
  savedToken && savedToken !== "local-demo-token"
    ? savedToken
    : "local-access-token";
$("#token").onchange = () => {
  sessionStorage.setItem("desk-token", $("#token").value);
  refresh();
};
$("#fault").onchange = () => {
  $("#scenario-description").textContent =
    scenarios[$("#fault").value.split("|")[0]];
  activeScenario = null;
  sessionStorage.removeItem("desk-scenario");
  sessionStorage.setItem("desk-scenario-selection", $("#fault").value);
  updateGuide();
};
$("#inject").onclick = async () => {
  const [kind, service] = $("#fault").value.split("|");
  starting = true;
  $("#inject").disabled = true;
  try {
    await api("/api/faults", { kind, service });
    activeScenario = { kind, service, since: Date.now() };
    sessionStorage.setItem("desk-scenario", JSON.stringify(activeScenario));
    sessionStorage.setItem("desk-scenario-selection", $("#fault").value);
    await refresh();
  } catch (e) {
    showError(e);
  } finally {
    starting = false;
    $("#inject").disabled = state?.mode !== "simulated desk";
  }
};
$("#triage").onclick = async () => {
  $("#triage").disabled = true;
  busy = true;
  $("#report").textContent =
    "Inspecting service logs and reconciling balances…";
  updateApproval();
  try {
    const result = await api("/api/incidents/" + selected.id + "/triage", {});
    selected = await api("/api/incidents/" + selected.id);
    $("#script").textContent = selected.script;
    $("#report").textContent =
      `${result.provider === "gemini" ? "Gemini diagnosis" : "Offline diagnosis"}${result.fallback_reason ? " (Gemini unavailable)" : ""}\n\n${result.report}`;
  } catch (e) {
    $("#report").textContent = e.message;
  } finally {
    busy = false;
    $("#triage").disabled = false;
    updateApproval();
  }
};
async function submitDecision(approved) {
  busy = true;
  updateApproval();
  try {
    if (!selected.approval) throw Error("Reopen the incident to review its proposal.");
    const keyName = "desk-decision:" + selected.approval.id;
    let key = sessionStorage.getItem(keyName);
    if (!key) { key = crypto.randomUUID(); sessionStorage.setItem(keyName, key); }
    const body = {action: selected.action, actor: $("#actor").value,
      proposal_id: selected.approval.id};
    if (!approved) body.reason = $("#feedback-reason").value;
    await api("/api/incidents/" + selected.id + (approved ? "/approve" : "/reject"), body,
      {"Idempotency-Key": key});
    selected = await api("/api/incidents/" + selected.id);
    $("#modal-message").textContent = approved
      ? "Recovery queued. The worker will apply it, then check consecutive fresh healthy samples."
      : "Rejection recorded. Refresh the diagnosis before proposing another recovery.";
    await refresh();
  } catch (e) {
    $("#modal-message").textContent = e.message;
  } finally {
    busy = false;
    updateApproval();
  }
}
$("#approve").onclick = () => submitDecision(true);
$("#reject").onclick = () => submitDecision(false);
// Shared tooltip supports pointer hover, keyboard focus, and tap without covering nearby metrics.
let helpAnchor = null;
function hideHelp() {
  helpAnchor = null;
  $("#help-tooltip").hidden = true;
}
function showHelp(anchor, text, x, y) {
  const tooltip = $("#help-tooltip"),
    host = anchor.closest("dialog") || document.body;
  if (tooltip.parentNode !== host) host.appendChild(tooltip);
  tooltip.textContent = text;
  tooltip.hidden = false;
  helpAnchor = anchor;
  const rect = anchor.getBoundingClientRect(),
    width = tooltip.offsetWidth,
    height = tooltip.offsetHeight;
  const preferredX = x ?? rect.left,
    preferredY = y ?? rect.bottom;
  tooltip.style.left =
    Math.max(12, Math.min(preferredX, window.innerWidth - width - 12)) + "px";
  tooltip.style.top =
    (preferredY + 12 + height < window.innerHeight
      ? preferredY + 12
      : Math.max(12, (y ?? rect.top) - height - 12)) + "px";
}
document.addEventListener("pointerover", (event) => {
  const anchor = event.target.closest?.("[data-help]");
  if (anchor && anchor !== helpAnchor) showHelp(anchor, anchor.dataset.help);
});
document.addEventListener("pointerout", (event) => {
  if (
    helpAnchor &&
    event.target.closest?.("[data-help]") === helpAnchor &&
    !helpAnchor.contains(event.relatedTarget) &&
    !helpAnchor.contains(document.activeElement)
  )
    hideHelp();
});
document.addEventListener("focusin", (event) => {
  const anchor = event.target.closest?.("[data-help]");
  if (anchor) showHelp(anchor, anchor.dataset.help);
  else hideHelp();
});
document.addEventListener("focusout", hideHelp);
document.addEventListener("click", (event) => {
  const anchor = event.target.closest?.("[data-help]");
  if (anchor) showHelp(anchor, anchor.dataset.help);
  else hideHelp();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideHelp();
});
window.addEventListener("scroll", hideHelp, true);
$("#chart").addEventListener("pointermove", (event) => {
  const events = state?.events.filter((e) => e.service === "execution-gateway");
  if (!events?.length) return;
  const rect = $("#chart").getBoundingClientRect(),
    fraction = (((event.clientX - rect.left) / rect.width) * 800 - 40) / 760;
  const index = Math.max(
      0,
      Math.min(events.length - 1, Math.round(fraction * (events.length - 1))),
    ),
    sample = events[index];
  showHelp(
    $("#chart"),
    `${clock(sample.timestamp)} · ${sample.fill_latency_ms.toFixed(1)} ms\nTime from simulated order submission to fill. ${sample.fill_latency_ms > 350 ? "Above" : "Below"} the 350 ms latency alert threshold.`,
    event.clientX,
    event.clientY,
  );
});
const savedScenario = sessionStorage.getItem("desk-scenario-selection");
if ([...$("#fault").options].some((option) => option.value === savedScenario))
  $("#fault").value = savedScenario;
$("#scenario-description").textContent =
  scenarios[$("#fault").value.split("|")[0]];
async function poll() {
  await refresh();
  setTimeout(poll, 1500);
}
poll();
