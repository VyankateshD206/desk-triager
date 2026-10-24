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


## Docker laboratory

The Compose stack runs the triager, PostgreSQL, an execution-service simulator, Prometheus,
and Loki. It is a local development environment. No exchange or live orders are connected.
All published ports bind to localhost; PostgreSQL stays on the Compose network.

### Start

From the repository root, with Docker Engine running and Docker Compose installed:

```bash
docker compose -f infra/compose.yaml up -d --build --wait
```

Open the console at [localhost:18000](http://localhost:18000); it connects automatically. The demo control service is on port 18001, Prometheus on 19090,
and Loki on 13100. The default stack uses offline triage and needs no cloud credentials.
It does not read your host `.env` into the containers. The Docker build context allowlist
excludes local configuration, database files, and Git history.

The demo sends telemetry for all three monitored services; only execution-gateway is
faulted. Prometheus scrapes its gauges every two seconds. The app pushes structured logs
directly to Loki and also writes them to stdout. Delivery failures appear in the demo
service's `/health` response.

### Inject a fault

```bash
curl -fsS http://localhost:18001/faults \
  -H 'X-Demo-Token: local-demo-token' \
  -H 'Content-Type: application/json' \
  -d '{"kind":"slow_query"}'
```

| Kind | Workload and evidence |
|---|---|
| `slow_query` | An in-memory SQLite SELECT invokes a controlled 600 ms delay; SQL duration and fill latency rise. |
| `memory_pressure` | Retains 1 MiB buffers per sample up to 16 MiB; a controlled queue-latency penalty accompanies pressure. |
| `bad_deploy` | Records a simulated version and diff, adds 650 ms of routing delay, and emits deployment-correlated logs. |
| `rate_limit` | Emits simulated HTTP 429 rejects and retry-after guidance. |
| `healthy` | Clears retained buffers and fault behavior; records a rollback when leaving the bad deployment. |

Memory gauges report retained demo buffer bytes, not process RSS. Error ratio is a
controlled scenario gauge, not a statistical error-rate estimate. A capped resource-pressure
scenario substitutes for an unbounded memory leak. Deployment history and fault switches
are in memory and reset when the demo restarts; they are not real Git deployments.

Reset with the same curl command and `{"kind":"healthy"}`. In this stack the triager's
internal simulator is disabled so telemetry comes from the external demo service. Existing
recovery handlers cannot manipulate that external process: approval returns a conflict.
Fault injection/reset is a separate authenticated demo control. Healthy telemetry alone
does not close incidents. This milestone demonstrates investigation, not autonomous repair.

### Agent tools

With the configured source URLs, Gemini can request these additional argument-free tools:

- `query_logs`: fixed service selector, last five minutes, maximum 50 Loki log lines.
- `get_metrics`: fixed Prometheus gauges for the incident service.
- `list_deployments`: bounded demo deployment history.
- `get_deploy_diff`: latest demo deployment's controlled configuration diff.

Each tool uses only GET, rejects redirects, times out after five seconds, and caps response
content at 256 KiB. Models cannot provide a URL, service override, LogQL, PromQL, or shell
command. Tool errors consume the investigation budget and are exposed as exception types.
These sources remain untrusted evidence. Version 1.4.0 adds best-effort evidence redaction
and deterministic adversarial evaluation; see [the security scope](SECURITY.md). The log window is relative to query time, not a historical incident
replay; historical time-window querying remains follow-up work.

For an existing non-Docker installation, configure `LOKI_URL`, `PROMETHEUS_URL`, and
`DEMO_SERVICE_URL` in its environment and restart. Empty URLs keep external tools disabled.

### Optional Gemini mode

Export a Gemini key in your terminal, then explicitly opt in:

```bash
docker compose -f infra/compose.yaml -f infra/compose.ai.yaml up -d --build --wait
```

This overlay requires `GEMINI_API_KEY` and enables paid model calls. The default Compose
file never forwards it. Do not commit keys or paste expanded Compose configuration into
logs. Historical Gemini accuracy, latency and cost measurements are documented in
[results](EVALUATION.md#historical-gemini-results); they do not validate diagnosis accuracy on this external demo stack.

### Verify and stop

```bash
docker compose -f infra/compose.yaml exec -T triager python scripts/verify_demo.py
docker compose -f infra/compose.yaml down
```

The integration script injects all four faults, waits for matching real Loki log event IDs
and Prometheus gauges, checks incident ingestion, and runs the real graph with a scripted
planner through all four external tools. It also checks API triage uses LangGraph. This
proves wiring and tool execution, not LLM diagnosis accuracy. It restores healthy mode even
when verification fails. Run it against the default offline stack to avoid model charges.

Named volumes preserve database history, graph checkpoints, logs, and metrics when stopping.
The verification script adds test incidents and checkpoints to that demo history. For a
separate clean experiment, use a different Compose project name with `-p`.
