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
  if (state && state.mode !== "simulated desk") {
    $("#scenario-hint").textContent = "Simulation controls are disabled for external telemetry.";
    return;
  }
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
  const spec = metricSpec[$("#chart-metric").value];
  return (state?.events || []).filter(e => e.service === spec.service &&
    Number.isFinite(e[$("#chart-metric").value]) && Number.isFinite(Date.parse(e.timestamp)))
    .sort((a,b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
}
let chartLayout = null;
function renderChart() {
  const metric = $("#chart-metric").value, spec = metricSpec[metric], events = chartSamples();
  const svg = $("#chart"), width = Math.max(240, svg.clientWidth), height = 224;
  const left = 58, right = width - 16, top = 30, bottom = height - 40;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  $("#chart-state").hidden = events.length > 0;
  $("#chart-state").textContent = state ? "No samples for this service yet" : "Connecting to telemetry…";
  $("#chart-context").textContent = `${spec.service} · ${events.length} accepted sample${events.length === 1 ? "" : "s"}`;
  svg.setAttribute("aria-label", `${spec.label} in ${spec.unit}; ${events.length} samples`);
  svg.dataset.help = events.length ? `${spec.label} in ${spec.unit}. Hover or tap for exact values. Use Left and Right arrow keys to inspect samples.` : "No telemetry samples available for the selected service.";
  $("#chart-start").textContent = events.length ? `From ${new Date(events[0].timestamp).toLocaleString()}` : "Waiting for telemetry";
  if (!events.length) {
    svg.innerHTML = ""; chartLayout = null;
    $("#chart-threshold").textContent = spec.threshold ? `Alert above ${spec.threshold} ${spec.unit}` : "No fixed alert threshold";
    return;
  }
  const values = events.map(e => e[metric]);
  const rawMax = Math.max(spec.unit === "bps" ? 1 : 10, ...values) * 1.15;
  const rawMin = Math.min(0, ...values) * 1.15;
  const roughStep = (rawMax - rawMin) / 4;
  const power = 10 ** Math.floor(Math.log10(roughStep));
  const step = [1, 2, 2.5, 5, 10].map(n => n * power).find(n => n >= roughStep);
  const min = Math.floor(rawMin / step) * step, max = Math.ceil(rawMax / step) * step;
  const first = Date.parse(events[0].timestamp), last = Date.parse(events.at(-1).timestamp);
  const x = at => first === last ? (left+right)/2 : left + (Date.parse(at)-first)/(last-first)*(right-left);
  const y = value => bottom - (value-min)/(max-min)*(bottom-top);
  const fmt = value => Number(value.toPrecision(5)).toLocaleString(undefined,{maximumFractionDigits:4, notation: Math.abs(value)>=10000 ? "compact" : "standard"});
  const ticks = [];
  for (let value = min; value <= max + step/100; value += step) {
    ticks.push(`<line x1="${left}" y1="${y(value)}" x2="${right}" y2="${y(value)}" class="chart-grid"/><text x="${left-10}" y="${y(value)+4}" text-anchor="end" class="chart-label">${fmt(value)}</text>`);
  }
  const timeTicks = first === last ? [first] : width < 420 ? [first,last] : [first,(first+last)/2,last];
  const times = timeTicks.map((at,i) => `<text x="${first === last ? (left+right)/2 : left+(at-first)/(last-first)*(right-left)}" y="${bottom+25}" text-anchor="${first === last ? "middle" : i===0 ? "start" : i===timeTicks.length-1 ? "end" : "middle"}" class="chart-label">${clock(at)}</text>`).join("");
  const thresholdVisible = spec.threshold != null && spec.threshold >= min && spec.threshold <= max;
  const threshold = thresholdVisible ? `<line x1="${left}" y1="${y(spec.threshold)}" x2="${right}" y2="${y(spec.threshold)}" class="chart-limit"/>` : "";
  $("#chart-threshold").textContent = spec.threshold ? `Alert > ${spec.threshold} ${spec.unit}${thresholdVisible ? " · dashed line" : " · above visible range"}` : "No fixed alert threshold";
  const points = events.map(e => `${x(e.timestamp)},${y(e[metric])}`).join(" ");
  svg.innerHTML = `<text x="${left}" y="17" class="chart-label">${spec.unit}</text>${ticks.join("")}${times}${threshold}<polyline points="${points}" class="chart-series"/>${events.length===1 ? `<circle cx="${x(events[0].timestamp)}" cy="${y(events[0][metric])}" r="3" class="chart-dot"/>` : ""}<g id="chart-cursor" hidden><line y1="${top}" y2="${bottom}" class="chart-crosshair"/><circle r="4" class="chart-dot"/></g>`;
  chartLayout = {events, left, right, first, last, x, y, metric, spec, index: events.length-1};
  // A live refresh must never leave a tooltip describing a point that has moved.
  if (helpAnchor === svg) hideHelp();
}
function inspectChart(index, pointer) {
  if (!chartLayout) return;
  const c = chartLayout, sample = c.events[index]; c.index = index;
  const cursor = $("#chart-cursor"), x = c.x(sample.timestamp);
  cursor.removeAttribute("hidden");
  cursor.querySelector("line").setAttribute("x1",x);
  cursor.querySelector("line").setAttribute("x2",x);
  cursor.querySelector("circle").setAttribute("cx",x);
  cursor.querySelector("circle").setAttribute("cy",c.y(sample[c.metric]));
  const time = new Date(sample.timestamp).toISOString();
  showHelp($("#chart"), `${c.spec.service}\n${time}\n${c.spec.label}: ${sample[c.metric]} ${c.spec.unit}`, pointer?.clientX, pointer?.clientY);
}
function inspectChartPointer(event) {
  if (!chartLayout) return;
  const c = chartLayout, rect = $("#chart").getBoundingClientRect();
  const at = c.first + Math.max(0,Math.min(1,(event.clientX-rect.left-c.left)/(c.right-c.left)))*(c.last-c.first);
  const index = c.events.reduce((best,e,i) => Math.abs(Date.parse(e.timestamp)-at) < Math.abs(Date.parse(c.events[best].timestamp)-at) ? i : best,0);
  inspectChart(index,event);
}

function setMetricState(name, label, status) {
  const badge = $("#"+name+"-state");
  badge.textContent = label; badge.className = "metric-state " + status;
}
function render(s) {
  state = s;

  $("#open").textContent = s.open_incident_count;
  $("#open").style.color = s.open_incident_count
    ? "var(--orange)"
    : "var(--text)";
  $("#queue-status").textContent = s.open_incident_count
    ? "Unresolved across all services"
    : "No unresolved incidents";
  setMetricState("open", s.open_incident_count ? "Needs review" : "Clear", s.open_incident_count ? "warning" : "success");
  const gateway = s.events.filter((e) => e.service === "execution-gateway"),
    latest = gateway.at(-1);
  $("#latency").innerHTML = latest
    ? `${Math.round(latest.fill_latency_ms)} <small>ms</small>`
    : "—";
  $("#latency-note").textContent = !latest
    ? "No gateway samples"
    : s.service_age_seconds["execution-gateway"] > s.tick_gap_seconds
      ? "Last known sample · feed stale"
      : "Latest gateway sample · alert above 350 ms";
  const gatewayStale = s.service_age_seconds["execution-gateway"] == null || s.service_age_seconds["execution-gateway"] > s.tick_gap_seconds;
  setMetricState("latency", !latest ? "No samples" : gatewayStale ? "Stale sample" : latest.fill_latency_ms > 350 ? "Above threshold" : "Within threshold", !latest ? "waiting" : gatewayStale || latest.fill_latency_ms > 350 ? "warning" : "success");
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
      : "Local ledger minus exchange · USD";
  setMetricState("nav", !s.balances.length ? "No accounts" : mismatch ? "Reconcile" : "Aligned", !s.balances.length ? "waiting" : mismatch ? "warning" : "success");
  const degraded = Object.keys(s.errors).length || ["market-feed", "execution-gateway", "portfolio-ledger"].some(service => s.service_age_seconds[service] == null || s.service_age_seconds[service] > s.tick_gap_seconds);
  $("#session").textContent = degraded
    ? "Needs attention"
    : s.last_ingest ? "Monitoring" : "Waiting for telemetry";
  $("#global-mode").textContent = s.mode === "simulated desk" ? "SIMULATED" : "EXTERNAL TELEMETRY";
  $("#sample-age").textContent = s.last_ingest ? "Last sample " + ageText(s.last_ingest) : "No samples yet";
  $("#session").style.color = degraded ? "var(--orange)" : s.last_ingest ? "var(--green)" : "var(--muted)";
  $("#updated").textContent = s.last_ingest
    ? "Updated " + clock(s.last_ingest)
    : "Waiting for telemetry";
  $("#infrastructure").textContent =
    `${s.database === "postgresql" ? "PostgreSQL" : "Local SQLite"} · ${s.ai_provider === "gemini" ? "Gemini REST" : "Offline triage"} · Direct Python ingestion`;
  if (Object.keys(s.errors).length)
    showError(
      Error("A background worker needs attention: " + JSON.stringify(s.errors)),
    );
  for (const service of ["market-feed", "execution-gateway", "portfolio-ledger"]) {
    const age = s.service_age_seconds[service];
    const node = $("#service-" + service),
      count = s.open_incidents_by_service[service] || 0,
      stale = age > s.tick_gap_seconds,
      hasSample = s.events.some(e => e.service === service);
    const status = count ? "Review" : !hasSample || age == null ? "Waiting" : stale ? "Stale" : "Healthy";
    node.className = "service" + (count || stale ? " attention" : !hasSample || age == null ? " waiting" : "");
    node.innerHTML = `<span class="service-name">${escape(service)}</span><span class="service-status">${status === "Review" ? "Needs review" : status}</span><span class="service-meta">${hasSample && age != null ? `Last sample ${age.toFixed(1)}s ago` : "No recent samples"} · ${count} open</span>`;
    node.setAttribute("aria-label", `${service}: ${status}`);
    node.dataset.help = `${service}: ${status.toLowerCase()}. ${hasSample && age != null ? `Last accepted sample arrived ${age.toFixed(1)} seconds ago.` : "No recent telemetry samples available."} Silence beyond ${s.tick_gap_seconds} seconds triggers a feed-gap incident. ${count} unresolved incident(s). A service can receive telemetry while its values are anomalous.`;
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
function filterIncidents(incidents, filters, sort) {
  const severity = {critical:0, high:1, medium:2, low:3, unknown:4};
  return incidents.filter(i =>
    (filters.status === "all" || (filters.status === "resolved" ? i.status === "resolved" : i.status !== "resolved")) &&
    (filters.severity === "all" || (i.severity || "unknown") === filters.severity) &&
    (filters.service === "all" || i.service === filters.service)
  ).sort((a,b) => {
    if (sort.key !== "severity") return sort.direction * a.opened_at.localeCompare(b.opened_at);
    const left = severity[a.severity] ?? 4, right = severity[b.severity] ?? 4;
    if (left === 4 || right === 4) return left === right ? 0 : left === 4 ? 1 : -1;
    return sort.direction * (left-right);
  });
}
function incidentAction(incident) {
  return ["open", "failed"].includes(incident.status) ? "Review" : "View details";
}
function incidentRow(i) {
  const source = i.analysis_source ? (i.analysis_source === "offline" ? "Offline analysis" : i.analysis_source === "gemini" ? "Gemini" : i.analysis_source) : "Analysis pending";
  const signal = i.signal || names[i.kind] || i.kind;
  const exactTime = new Date(i.opened_at).toLocaleString();
  const action = incidentAction(i);
  const statusHints = {open:"Awaiting incident review", queued:"Recovery queued; not executed yet", verifying:"Handler ran; healthy telemetry must confirm recovery", resolved:"Recovery confirmed by fresh telemetry", failed:"Recovery failed or needs further attention"};
  return `<tr role="row" class="incident-row" tabindex="0" data-id="${escape(i.id)}" aria-label="${action} ${escape(signal)} on ${escape(i.service)}">
  <td role="cell" class="severity-cell"><span class="severity ${escape(i.severity || "unknown")}">${escape(i.severity || "unknown")}</span></td>
  <td role="cell" class="signal-cell"><strong class="incident-name">${escape(signal)}</strong><div class="analysis-summary" title="${escape(i.summary || "Awaiting diagnosis")}">${escape(i.summary || "Awaiting diagnosis")}</div><span class="source-badge">${escape(source)}</span> ${i.abstained ? '<span class="source-badge">Insufficient evidence</span>' : ""}${i.fallback_reason ? ' <span class="source-badge">Fallback</span>' : ""}</td>
  <td role="cell" class="service-cell"><span class="mobile-cell-label">Service · </span><span>${escape(i.service)}</span></td>
  <td role="cell" class="detected-cell"><span class="mobile-cell-label">Detected </span><time tabindex="0" datetime="${escape(i.opened_at)}" data-help="${escape(exactTime + " (browser local time) · " + i.opened_at)}" aria-describedby="help-tooltip" title="${escape(exactTime)}">${ageText(i.opened_at)}</time><small>${escape(new Date(i.opened_at).toLocaleDateString(undefined,{month:"short",day:"numeric"}))} · ${clock(i.opened_at)}</small></td>
  <td role="cell" class="status-cell"><span class="badge ${escape(i.status)}" tabindex="0" data-help="${escape(statusHints[i.status] || i.status)}" aria-describedby="help-tooltip">${escape(statusLabels[i.status] || i.status)}</span></td>
  <td role="cell" class="incident-action"><button class="inspect ${action === "Review" ? "review-action" : ""}" data-id="${escape(i.id)}" aria-label="${action} ${escape(signal)} on ${escape(i.service)}">${action}</button></td></tr>`;
}
function incidentEmptyState(filters, loadedCount, openCount) {
  const narrowed = filters.severity !== "all" || filters.service !== "all";
  if (narrowed) return ["No incidents match these filters", "Choose another severity or service, or reset the filters to see open incidents."];
  if (filters.status === "resolved") return ["No resolved incidents in loaded history", "Resolved incidents will appear here after recovery has been verified."];
  if (filters.status === "all") return ["No incidents in loaded history", "Detected signals will appear here with their service, status and review action."];
  if (openCount > 0) return ["No open incidents in loaded history", `${openCount} unresolved incident(s) reported across the desk. Filters apply only to the ${loadedCount} incidents in this snapshot.`];
  return ["No incidents require attention", "There are no unresolved incidents across the desk. New signals will appear here for review."];
}
function resetIncidentFilters() {
  $("#show-history").value = "open";
  $("#severity-filter").value = "all";
  $("#service-filter").value = "all";
  renderIncidents();
}
function renderIncidents() {
  if (!state) return;
  const serviceSelect = $("#service-filter");
  const services = [...new Set([...Object.keys(state.service_age_seconds || {}), ...state.incidents.map(i=>i.service), ...(serviceSelect.value !== "all" ? [serviceSelect.value] : [])])].sort();
  const options = '<option value="all">All services</option>' + services.map(service=>`<option value="${escape(service)}">${escape(service)}</option>`).join("");
  if (serviceSelect.dataset.options !== options) {
    const value = serviceSelect.value;
    serviceSelect.innerHTML = options; serviceSelect.value = value || "all";
    serviceSelect.dataset.options = options;
  }
  $("#incident-sort").value = incidentSort.key + ":" + incidentSort.direction;
  const filters = {status: $("#show-history").value, severity: $("#severity-filter").value, service: serviceSelect.value};
  const rows = filterIncidents(state.incidents, filters, incidentSort);
  $("#incident-count").textContent = `${rows.length} of ${state.incidents.length} loaded incidents`;
  $("#reset-incidents").disabled = filters.status === "open" && filters.severity === "all" && filters.service === "all";
  const earlier = rows.filter(i => i.opened_at < state.started_at).length;
  $("#history-note").textContent = earlier ? `${earlier} shown incident(s) retained from earlier sessions.` : "";
  const focused = document.activeElement;
  const focusId = focused?.closest("[data-id]")?.dataset.id;
  const focusWasButton = focused?.tagName === "BUTTON";
  const focusWasTime = focused?.tagName === "TIME";
  const focusWasBadge = focused?.classList?.contains("badge");
  const shown = new Set();
  $("#incident-rows").innerHTML = rows.map(i => {
    let context = "";
    if (i.correlation && !shown.has(i.correlation.id)) {
      const group = i.correlation;
      shown.add(group.id);
      context = `<tr class="correlation"><td colspan="6"><details data-correlation="${escape(group.id)}" ${openCorrelations.has(group.id) ? "open" : ""}><summary>Related telemetry interruption · ${group.impacted_services.length} impacted services</summary><p>${escape(group.basis)}. Common cause is unconfirmed; review and approval remain per service. Filters may show only part of this group.</p><small>${group.impacted_services.map(escape).join(" · ")}</small></details></td></tr>`;
    }
    return context + incidentRow(i);
  }).join("") || (() => {
    const [title, description] = incidentEmptyState(filters, state.incidents.length, state.open_incident_count);
    return `<tr class="empty-row" role="row"><td role="cell" class="empty" colspan="6"><strong>${escape(title)}</strong><p>${escape(description)}</p><small>Last checked ${clock(new Date().toISOString())} · Browser local time</small></td></tr>`;
  })();
  if (focusId) {
    const row=[...$("#incident-rows").querySelectorAll("tr[data-id]")].find(r=>r.dataset.id===focusId);
    (focusWasButton ? row?.querySelector("button") : focusWasTime ? row?.querySelector("time") : focusWasBadge ? row?.querySelector(".badge") : row)?.focus({preventScroll:true});
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
    $("#session").style.color = "var(--error)";
    $("#inject").disabled = true;
    if (!state) $("#global-mode").textContent = "ENV UNKNOWN";
    $("#chart-context").textContent = state ? "Connection lost · showing last received telemetry" : "Telemetry unavailable · check Settings";
    if (!state) $("#chart-state").textContent = "Connect in Settings to load telemetry";
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
  if (e.target.closest("[data-help]")) return;
  const button = e.target.closest("[data-id]");
  if (button) inspect(button.dataset.id);
});
["#show-history", "#severity-filter", "#service-filter"].forEach(selector => $(selector).onchange = renderIncidents);
$("#reset-incidents").onclick = resetIncidentFilters;
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
  $("#inject").textContent = "Starting…";
  $("#scenario-hint").textContent = "Sending fault to the simulator…";
  try {
    await api("/api/faults", { kind, service });
    activeScenario = { kind, service, since: Date.now() };
    sessionStorage.setItem("desk-scenario", JSON.stringify(activeScenario));
    sessionStorage.setItem("desk-scenario-selection", $("#fault").value);
    await refresh();
  } catch (e) {
    showError(e);
    $("#scenario-hint").textContent = "Scenario could not start. Check the error above and retry.";
  } finally {
    starting = false;
    $("#inject").textContent = "Run scenario";
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
  $("#chart-cursor")?.setAttribute("hidden", "");
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
$("#chart").addEventListener("pointermove", inspectChartPointer);
$("#chart").addEventListener("click", inspectChartPointer);
$("#chart").addEventListener("keydown", event => {
  if (!chartLayout || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const c = chartLayout;
  inspectChart(event.key === "Home" ? 0 : event.key === "End" ? c.events.length-1 : Math.max(0,Math.min(c.events.length-1,c.index + (event.key === "ArrowLeft" ? -1 : 1))));
});
$("#chart-metric").onchange = renderChart;
window.addEventListener("resize", renderChart);
function setIncidentSort(key, direction) {
  incidentSort = {key, direction};
  document.querySelectorAll("[data-sort]").forEach(button => {
    const th = button.closest("th");
    th.removeAttribute("aria-sort");
    if (button.dataset.sort === key) th.setAttribute("aria-sort", direction === 1 ? "ascending" : "descending");
  });
  renderIncidents();
}
document.querySelectorAll("[data-sort]").forEach(button => button.onclick = () => {
  const key = button.dataset.sort;
  setIncidentSort(key, incidentSort.key === key ? -incidentSort.direction : key === "severity" ? 1 : -1);
});
$("#incident-sort").onchange = () => {
  const [key,direction] = $("#incident-sort").value.split(":");
  setIncidentSort(key,Number(direction));
};
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
