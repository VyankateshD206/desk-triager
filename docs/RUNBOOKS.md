# Operational runbooks

## Stale feed or complete silence

Review the incident, heartbeat age, tick age, and service logs. A stale tick can arrive in an otherwise active service; complete silence needs the watchdog. Inspect shared ingestion/database errors before assuming the exchange disconnected. Approve `reconnect_feed` only for the simulated scenario, then wait for fresh healthy telemetry to resolve the incident.

## Exchange throttling

Inspect `429` rejects and retry-after evidence. Review the proposed retry backoff and approve it. In a real adapter, honor retry-after and use bounded backoff; never blindly replay order submissions. The simulation clears the matching simulated fault and verifies the next healthy event.

## NAV mismatch

Expand **Activity & balances** to compare local and simulated exchange NAV. Values use SQL Numeric and Python Decimal with a one-cent tolerance. Detection checks each account even if the displayed total difference cancels out. Review the source before approving `resync_ledger`. The simulation resync copies the exchange snapshot into the simulation ledger and records before-values in the audit table.

## Slow fills

Hover the latency card or chart to inspect milliseconds and compare with the 350 ms rule. Review gateway logs and the proposed simulated order resync. After approval, a fresh healthy sample verifies recovery. A last-known normal latency does not establish health when telemetry has stopped.

## Feature drift

Review slippage, heartbeat jitter, fill latency, and reject behavior against the synthetic baseline. A negative Isolation Forest margin is an outlier signal, not a probability or root cause. This incident is inspection-only and remains open for investigation. Restarting the simulator clears its temporary fault but preserves incident history.

## Database unavailable

For Neon, check project/branch state, database name, endpoint, network access, and TLS options. Run `python scripts/check_connections.py` for a credential-safe check. Startup does not silently substitute SQLite for a failed configured Neon database. Background ingestion errors are visible; direct ingestion has no durable backlog for uncommitted samples. Do not log the database URL.

## Gemini unavailable

Verify `AI_PROVIDER=gemini`, `GEMINI_API_KEY`, model access, and quota. Missing keys, permission errors, timeouts, invalid model output, and exhausted tool budgets produce offline evidence instead. Refresh the diagnosis after fixing configuration. Model output never authorizes recovery. Provider exception types are exposed without request data or secrets.
