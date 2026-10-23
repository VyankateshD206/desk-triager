# Incident console

The compact header keeps the connection state, most recent sample age and simulation scope
visible. The dark cards, monospace metrics and guided scenario flow remain intact. The
incident queue shows actual diagnosis severity, source, abstention, summary, detected time
and age. Unknown severity remains unknown until assessed. Column buttons sort severity/time;
rows open by pointer or keyboard, and table headings remain sticky in the scrolling region.

## Retained silence incidents

Read-only inspection of the configured database found unresolved watchdog incidents from
19 October on market-feed, execution-gateway and portfolio-ledger. They were historical
records, not three new faults created by the current scenario. The universal "Stale market
feed" display name was wrong for gateway/ledger receipt gaps; watchdog incidents now show
"Telemetry silence". Historical records are not deleted or silently resolved on startup.

The console identifies earlier-session incidents and reports active simulator faults even
when browser scenario state is absent. Watchdog gaps detected within one silence-threshold
window across multiple services receive a temporal correlation group with impacted services.
The group explicitly says its common cause is unconfirmed. Time proximity does not prove a
market-feed dependency failure. Underlying incident IDs, counts, approvals and verification
remain independent; each service requires its own bound approval. A causal incident merger
requires dependency/topology evidence that this simulator does not currently provide.

## Review and charts

Review shows actual audit timestamps for detected, triaged, approved, verifying and resolved;
stages without events say Pending. It retains the inspectable agent trace, arguments, result
previews, per-tool latency, model usage and step budgets. Evidence links open the relevant
sanitized source record. Unsupported extract checks and provider fallbacks are explicit.
The approval panel names the target service and fixed simulated action; NAV resync also shows
the reviewed local/exchange amounts when present. Fresh telemetry still verifies recovery.

Chart selection covers fill latency, jitter, slippage and tick age. Y-axes use metric units and
five ticks, with automatic scaling from zero. A threshold outside the visible data range is
explicitly labeled with an upward arrow; it is not plotted as if the data reached that value.
Only latency/tick-age have fixed numeric rules. Slippage/jitter do not get invented thresholds.

## Validation

138 regression tests passed; the wheel and JavaScript syntax checks passed. Browser checks
covered sorting, metric selection, explicit token connection, evidence navigation, the full
approval/recovery timeline and the empty queue. At the narrow breakpoint, document width
matched viewport width and secondary text was at least 12px. The scrolling incident table
retains all columns. Shared secondary-text contrast was checked against its dark backgrounds:
6.82:1 for muted panel text, 7.49:1 on the page, 8.60:1 for scenario step text and 8.71:1 for
source badges. Disabled controls are visibly disabled.

Screenshots use an isolated SQLite database, offline reasoning and synthetic telemetry:
[dashboard](media/operations-dashboard.jpg), [Review](media/operations-review.jpg),
[completed timeline](media/operations-resolved.jpg), [narrow layout](media/operations-mobile.jpg).
No existing incident history was changed for this verification.
