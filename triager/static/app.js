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
  ["detect", "review", "recover"].forEach((step) => {$("#step-" + step).classList.remove("active"); $("#step-"+step).removeAttribute("aria-current");});
  if (!activeScenario) {
    $("#scenario-hint").textContent =
      state && Object.keys(state.faults || {}).length ? "Active simulated faults: " + Object.entries(state.faults).map(([service,kind])=>`${service}: ${names[kind] || kind}`).join(" · ") : "No active scenario. Incident history is retained across sessions.";
    return;
  }
  $("#step-detect").classList.add("active");
  $("#step-detect").setAttribute("aria-current", "step");
  const kind =
    activeScenario.kind === "silence" ? "tick_gap" : activeScenario.kind;
  const incident = state?.incidents.find(
    (i) =>
      i.service === activeScenario.service &&
      i.kind === kind &&
      (i.id === activeScenario.incidentId || i.status !== "resolved" ||
        Date.parse(i.opened_at) >= activeScenario.since - 1000),
  );
  if (!incident) {
    $("#scenario-hint").textContent =
      activeScenario.kind === "silence"
        ? `Waiting for the ${state?.tick_gap_seconds ?? 8}-second silence threshold…`
        : "Failure injected. Waiting for the detector…";
    return;
  }
  if (!activeScenario.incidentId) {
    activeScenario.incidentId = incident.id;
    sessionStorage.setItem("desk-scenario", JSON.stringify(activeScenario));
  }
  $("#step-review").classList.add("active");
  $("#step-detect").removeAttribute("aria-current");
  $("#step-review").setAttribute("aria-current", "step");
  if (incident.status === "resolved") {
    $("#step-recover").classList.add("active");
    $("#step-review").removeAttribute("aria-current");
    $("#step-recover").setAttribute("aria-current", "step");
    $("#scenario-hint").textContent =
      "Recovered. A fresh healthy sample confirmed success.";
  } else if (incident.status === "queued" || incident.status === "verifying") {
    $("#step-recover").classList.add("active");
    $("#step-review").removeAttribute("aria-current");
    $("#step-recover").setAttribute("aria-current", "step");
    $("#scenario-hint").textContent =
      incident.status === "queued" ? "Recovery queued for the worker…" : "Recovery approved. Checking fresh telemetry…";
  } else if (incident.status === "failed") {
    $("#scenario-hint").textContent = "Recovery needs attention. Review the incident and worker result.";
  } else {
    $("#scenario-hint").textContent =
      incident.action === "inspect_only"
        ? "Drift detected. Open the incident to inspect the evidence."
        : "Incident detected. Open Review below to approve recovery.";
  }
}
const metricSpec = {
  fill_latency_ms: {label: "Fill latency", unit: "ms", threshold: 350, service: "execution-gateway"},
  heartbeat_jitter_ms: {label: "Heartbeat jitter", unit: "ms", service: "execution-gateway"},
  slippage_bps: {label: "Slippage", unit: "bps", service: "execution-gateway"},
  tick_age_ms: {label: "Tick age", unit: "ms", threshold: 5000, service: "market-feed"},
};
const ageText = (at) => {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(at)) / 1000));
  return seconds < 60 ? `${seconds}s ago` : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h ago` : `${Math.floor(seconds / 86400)}d ago`;
};
function chartSamples() {
  return (state?.events || []).filter(e => e.service === metricSpec[$("#chart-metric").value].service);
}
function renderChart() {
  const metric = $("#chart-metric").value, spec = metricSpec[metric], events = chartSamples();
  const svg = $("#chart"), width = Math.max(240, svg.clientWidth), left = 44, right = width - 12;
  const rawMax = Math.max(spec.unit === "bps" ? 2 : 20, ...events.map(e => e[metric])) * 1.2;
  const step = spec.unit === "bps" ? 2 : rawMax < 200 ? 40 : rawMax < 1000 ? 200 : 2000;
  const max = Math.ceil(rawMax/step)*step;
  const y = v => 160 - (v / max) * 125;
  svg.setAttribute("viewBox", `0 0 ${width} 190`);
  svg.setAttribute("aria-label", `${spec.label} in ${spec.unit}; ${events.length} samples; auto-scaled from zero`);
  svg.dataset.help = `${spec.label} in ${spec.unit}. Auto-scaled from zero. ${spec.threshold ? `Alert threshold ${spec.threshold} ${spec.unit}; an upward arrow means the threshold is outside the visible range.` : "No fixed numeric alert rule for this metric."}`;
  const points = events.map((e,i) => `${left + i * (right-left) / Math.max(1,events.length-1)},${y(e[metric])}`).join(" ");
  const ticks = [0,.25,.5,.75,1].map(f => `<line x1="${left}" y1="${y(max*f)}" x2="${right}" y2="${y(max*f)}" stroke="var(--line)"/><text x="0" y="${y(max*f)+4}" fill="var(--muted)" font-size="13">${max < 10 ? (max*f).toFixed(1) : Math.round(max*f)}</text>`).join("");
  const thresholdY = spec.threshold ? Math.max(25, y(spec.threshold)) : 0;
  const threshold = spec.threshold ? `<line x1="${left}" y1="${thresholdY}" x2="${right}" y2="${thresholdY}" stroke="var(--orange)" stroke-dasharray="4 5"/><text x="${right}" y="${thresholdY-8}" text-anchor="end" fill="var(--orange)" font-size="13">${spec.threshold} ${spec.unit} alert${spec.threshold > max ? " ↑ off scale" : ""}</text>` : "";
  svg.innerHTML = `<text x="0" y="16" fill="var(--muted)" font-size="13">${spec.unit}</text>${ticks}${threshold}<polyline points="${points}" fill="none" stroke="var(--green)" stroke-width="2"/>`;
  $("#chart-start").textContent = events.length ? clock(events[0].timestamp) : "Waiting for samples";
}

function render(s) {
  state = s;

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
      ? "Monitoring"
      : "Monitoring";
  $("#global-mode").textContent = s.mode === "simulated desk" ? "SIMULATED" : "EXTERNAL TELEMETRY";
  $("#sample-age").textContent = s.last_ingest ? "Last sample " + ageText(s.last_ingest) : "No samples yet";
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
    node.textContent = service;
    node.setAttribute("aria-label", `${service}: ${status}`);
    node.dataset.help = `${service}: ${status.toLowerCase()}. Last accepted sample arrived ${age.toFixed(1)} seconds ago. Silence beyond ${s.tick_gap_seconds} seconds triggers a feed-gap incident. ${count} unresolved incident(s). A service can receive telemetry while its values are anomalous.`;
  }
  renderIncidents();
  renderChart();
  renderSupporting(s);
  $("#inject").disabled = starting || s.mode !== "simulated desk";
  updateGuide();
  if (selected && $("#detail").open) {
    const current = s.incidents.find((i) => i.id === selected.id);
    if (current) {
      const statusChanged = selected.status !== current.status;
      selected.status = current.status;
      if (statusChanged) {
        const id = selected.id;
        api("/api/incidents/"+id).then(fresh => {
          if (selected?.id === id && $("#detail").open) {
            selected.execution=fresh.execution; renderTimeline(fresh); updateApproval();
          }
        }).catch(showError);
      }
      if (current.report && !busy && current.report !== selected.report) {
        $("#report").textContent = current.report;
        if (selected.approval) selected.approval.status = "superseded";
        $("#modal-message").textContent = "Diagnosis changed. Reopen this incident to review the updated proposal.";
      }
      updateApproval();
    }
  }
}
let incidentSort = {key: "opened_at", direction: -1};
const openCorrelations = new Set();
function incidentRow(i) {
  const source = i.analysis_source ? (i.analysis_source === "offline" ? "Offline analysis" : i.analysis_source === "gemini" ? "Gemini" : i.analysis_source) : "Pending";
  return `<tr class="incident-row" tabindex="0" data-id="${escape(i.id)}" aria-label="Review ${escape(i.signal || names[i.kind] || i.kind)} on ${escape(i.service)}">
  <td><span class="severity ${escape(i.severity || "unknown")}">${escape(i.severity || "unknown")}</span></td>
  <td>${escape(i.signal || names[i.kind] || i.kind)}<small>${escape(i.service)}</small></td>
  <td><time datetime="${escape(i.opened_at)}" title="${escape(new Date(i.opened_at).toLocaleString())}">${clock(i.opened_at)}</time><small>${ageText(i.opened_at)}</small></td>
  <td><div class="analysis-summary" title="${escape(i.summary)}">${escape(i.summary)}</div><span class="source-badge">${escape(source)}</span> ${i.abstained ? '<span class="source-badge">Insufficient evidence</span>' : ""}${i.fallback_reason ? ' <span class="source-badge">Fallback</span>' : ""}</td>
  <td><span class="badge ${escape(i.status)}">${escape(statusLabels[i.status] || i.status)}</span></td>
  <td><button class="inspect" data-id="${escape(i.id)}">${i.status === "open" ? "Review" : "View"}</button></td></tr>`;
}
function renderIncidents() {
  if (!state) return;
  const severity = {critical:0, high:1, medium:2, low:3, unknown:4};
  const rows = state.incidents.filter(i => $("#show-history").checked || i.status !== "resolved").sort((a,b) => incidentSort.direction * (incidentSort.key === "severity" ? (severity[a.severity] ?? 4) - (severity[b.severity] ?? 4) : a.opened_at.localeCompare(b.opened_at)));
  const earlier = rows.filter(i => i.opened_at < state.started_at).length;
  $("#history-note").textContent = earlier ? `${earlier} shown incident(s) retained from earlier sessions. No history is deleted when the server restarts.` : "";
  const focused = document.activeElement;
  const focusId = focused?.closest("[data-id]")?.dataset.id;
  const focusWasButton = focused?.tagName === "BUTTON";
  const shown = new Set();
  $("#incident-rows").innerHTML = rows.map(i => {
    if (!i.correlation) return incidentRow(i);
    const group = i.correlation;
    if (shown.has(group.id)) return "";
    shown.add(group.id);
    return `<tr class="correlation"><td colspan="6"><details data-correlation="${escape(group.id)}" ${openCorrelations.has(group.id) ? "open" : ""}><summary>Telemetry interruption · ${group.impacted_services.length} impacted services</summary><p>${escape(group.basis)}. Historical incidents remain until reviewed; approval is per service.</p><ul>${rows.filter(r=>r.correlation?.id===group.id).map(r=>`<li>${escape(r.service)} · ${escape(statusLabels[r.status])} <button class="inspect" data-id="${escape(r.id)}">Review service</button></li>`).join("")}</ul></details><small>${group.impacted_services.map(escape).join(" · ")} · Detected ${ageText(i.opened_at)}</small></td></tr>`;
  }).join("") || `<tr><td class="empty" colspan="6"><strong>No open incidents ✓</strong>Last checked ${clock(new Date().toISOString())}</td></tr>`;
  if (focusId) {
    const row=[...$("#incident-rows").querySelectorAll("tr[data-id]")].find(r=>r.dataset.id===focusId);
    (focusWasButton ? row?.querySelector("button") : row)?.focus({preventScroll:true});
  }
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
  const feedback = s.approval_feedback || {};
  $("#feedback-stats").textContent = `Approvals ${feedback.approved || 0} · Rejections ${feedback.rejected || 0} · Approval rate ${feedback.approval_rate == null ? "no decisions" : Math.round(feedback.approval_rate * 100) + "%"}`;
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
  if (selected.status === "resolved") $("#modal-message").textContent = "Recovery verified by fresh healthy telemetry. The incident is resolved.";
  else if (selected.status === "verifying") $("#modal-message").textContent = "The fixed handler ran. Checking consecutive fresh healthy samples…";
  else if (selected.status === "failed") $("#modal-message").textContent = "Recovery needs attention. Check the worker result and verification history.";
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
          : "Approve simulated recovery";
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
function renderTimeline(incident) {
  const stages = [["Detected",["opened"]],["Triaged",["diagnosed"]],["Approved",["approval_queued"]],["Verifying",["reconnect_feed","enable_backoff","resync_orders","resync_ledger"]],["Resolved",["resolved"]]];
  $("#incident-timeline").innerHTML = stages.map(([label,actions]) => {
    const entry=(incident.timeline || []).filter(e=>actions.includes(e.action)).at(-1);
    return `<li class="${entry?"done":""}">${label}<time ${entry?`datetime="${escape(entry.at)}"`:""}>${entry?clock(entry.at):"Pending"}</time></li>`;
  }).join("");
}

function renderInvestigation(data) {
  const host = $("#investigation-trace");
  host.replaceChildren();
  const line = (text) => {
    const p = document.createElement("p");
    p.textContent = text;
    host.append(p);
  };
  if (!data) { line("No completed investigation yet."); return; }
  const diagnosis = data.diagnosis || {};
  line(`${data.provider || "unknown"} · ${diagnosis.abstained ? "Insufficient evidence" : `Confidence ${Math.round((diagnosis.confidence || 0) * 100)}% (uncalibrated)`}`);
  line(`Causal support: ${data.verification?.semantic_support || "not independently assessed"}`);
  for (const hypothesis of diagnosis.hypotheses || []) {
    const claim=document.createElement("p");
    claim.append(document.createTextNode(hypothesis.cause + " "));
    for (const id of hypothesis.evidence_ids || []) {
      const link=document.createElement("a"); link.className="evidence-link";
      link.href="#evidence-"+id; link.textContent="[source "+id.slice(0,8)+"…] "; claim.append(link);
    }
    host.append(claim);
  }
  if (data.fallback_reason) line(`Provider fallback: ${data.fallback_reason}`);
  line(`Budget: ${data.rounds ?? "—"}/${data.budget?.rounds ?? "—"} reasoning rounds · ${data.tool_calls ?? "—"}/${data.budget?.tools ?? "—"} tool calls`);
  for (const issue of data.verification?.issues || []) line(`Unsupported claim flagged: ${issue}`);
  for (const tool of data.tool_events || []) {
    const details=document.createElement("details"); details.className="tool-record";
    const summary=document.createElement("summary");
    summary.textContent=`${tool.tool} ${JSON.stringify(tool.arguments)} · ${tool.status} · ${Math.round(tool.latency_ms)} ms`;
    const pre=document.createElement("pre"); pre.textContent=tool.result_summary + (tool.summary_truncated?" … (truncated)":"");
    details.append(summary,pre);
    const links = document.createElement("p");
    for (const id of tool.evidence_ids || []) {
      const link = document.createElement("a"); link.className="evidence-link";
      link.href="#evidence-"+id; link.textContent="Evidence "+id.slice(0,8)+"… "; links.append(link);
    }
    details.append(links); host.append(details);
  }
  const calls = data.model_calls || [];
  line(`Tokens: ${calls.reduce((n, c) => n + (c.input_tokens || 0), 0)} input / ${calls.reduce((n, c) => n + (c.output_tokens || 0), 0)} output. Estimated cost: ${data.estimated_cost_usd == null ? "unavailable" : "$" + data.estimated_cost_usd.toFixed(5)}`);
  for (const node of data.node_trace || []) line(`${node.node}: ${Math.round(node.latency_ms)} ms`);
  const library=document.createElement("details");
  const libraryTitle=document.createElement("summary"); libraryTitle.textContent=`Evidence library · ${(data.evidence_items || []).length} sources`;
  library.append(libraryTitle); host.append(library);
  for (const item of data.evidence_items || []) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `${item.source} · ${item.evidence_id.slice(0, 12)}…`;
    details.id = "evidence-" + item.evidence_id;
    summary.title = item.evidence_id;
    const pre = document.createElement("pre");
    pre.textContent = item.content;
    details.append(summary, pre);
    library.append(details);
  }
}
async function inspect(id) {
  try {
    selected = await api("/api/incidents/" + id);
    renderInvestigation(selected.investigation);
    $("#detail-title").textContent = names[selected.kind] || selected.kind;
    $("#detail-service").textContent = selected.service;
    $("#diagnosis").textContent = selected.diagnosis;
    $("#action").textContent = actions[selected.action] || selected.action;
    const balance = selected.approval?.payload?.balance;
    const balanceChange = balance ? ` Local NAV $${money(balance.local)} → simulated exchange NAV $${money(balance.exchange)}.` : "";
    $("#approval-scope").textContent = `SIMULATED ONLY · ${selected.service}: ${actions[selected.action] || selected.action} This queues the fixed handler for this service; consecutive fresh healthy samples must confirm recovery. No real exchange action is sent.${balanceChange}`;
    renderTimeline(selected);
    $("#script").textContent = selected.script;
    $("#evidence").textContent = JSON.stringify(selected.evidence, null, 2);
    $("#report").textContent =
      selected.report ||
      "The triage worker is collecting logs and checking ledger balances. You can also refresh the diagnosis.";
    $("#modal-message").textContent = "";
    $("#feedback-reason").value = "";
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
$("#token").value = savedToken || "";
if (!savedToken) document.querySelector(".settings").open = true;
const connect = () => {
  sessionStorage.setItem("desk-token", $("#token").value);
  refresh();
};
$("#token").onchange = connect;
$("#connect").onclick = connect;
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
      `${result.provider} diagnosis${result.fallback_reason ? " (provider fallback)" : ""}\n\n${result.report}`;
    renderInvestigation(selected.investigation);
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
    body.reason = $("#feedback-reason").value;
    await api("/api/incidents/" + selected.id + (approved ? "/approve" : "/reject"), body,
      {"Idempotency-Key": key});
    selected = await api("/api/incidents/" + selected.id);
    renderTimeline(selected);
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
  const events = chartSamples(); if (!events.length) return;
  const rect = $("#chart").getBoundingClientRect();
  const fraction = (event.clientX - rect.left - 44) / Math.max(1,rect.width-56);
  const sample = events[Math.max(0, Math.min(events.length-1, Math.round(fraction*(events.length-1))))];
  const metric = $("#chart-metric").value, spec = metricSpec[metric];
  showHelp($("#chart"), `${clock(sample.timestamp)} · ${spec.label} ${sample[metric].toFixed(1)} ${spec.unit}`, event.clientX,event.clientY);
});
$("#chart-metric").onchange = renderChart;
window.addEventListener("resize", renderChart);
document.querySelectorAll("[data-sort]").forEach(button => button.onclick = () => {
  incidentSort = {key:button.dataset.sort, direction:incidentSort.key === button.dataset.sort ? -incidentSort.direction : button.dataset.sort === "severity" ? 1 : -1};
  document.querySelectorAll("[data-sort]").forEach(b=>b.closest("th").removeAttribute("aria-sort"));
  button.closest("th").setAttribute("aria-sort",incidentSort.direction===1?"ascending":"descending"); renderIncidents();
});
$("#incident-rows").addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr[data-id]")) {e.preventDefault(); inspect(e.target.dataset.id);} });
$("#incident-rows").addEventListener("toggle", e => { const id=e.target.dataset.correlation; if(id) {if(e.target.open) openCorrelations.add(id); else openCorrelations.delete(id);} }, true);
$("#investigation-trace").addEventListener("click", e => {
  const link=e.target.closest(".evidence-link"); if(!link) return;
  e.preventDefault(); const target=document.getElementById(link.hash.slice(1));
  if(target) {target.open=true; const library=target.parentElement; if(library.tagName==="DETAILS") library.open=true; target.scrollIntoView({block:"nearest"});}
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
