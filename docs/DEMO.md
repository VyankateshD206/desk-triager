# Instrumented fault demo

The Compose stack runs the triager, PostgreSQL, an execution-service simulator, Prometheus,
and Loki. It is a local development environment. No exchange or live orders are connected.
All published ports bind to localhost; PostgreSQL stays on the Compose network.

## Start

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

## Inject a fault

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

## Agent tools

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

## Optional Gemini mode

Export a Gemini key in your terminal, then explicitly opt in:

```bash
docker compose -f infra/compose.yaml -f infra/compose.ai.yaml up -d --build --wait
```

This overlay requires `GEMINI_API_KEY` and enables paid model calls. The default Compose
file never forwards it. Do not commit keys or paste expanded Compose configuration into
logs. Actual Gemini accuracy, latency, and cost comparisons are still pending evaluation.

## Verify and stop

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

## Recorded console walkthrough

[Watch the local console demo](media/desk-demo.webm). The recording uses isolated SQLite,
offline reasoning and simulated telemetry. It demonstrates detection, evidence review,
approval, worker execution and recovery confirmation; it does not demonstrate live LLM
accuracy or a real exchange action.

To reproduce against an isolated local instance, install Playwright as an optional development
tool (`npm install --no-save playwright` and `npx playwright install chromium`), then run
`DEMO_URL=http://127.0.0.1:18080 node scripts/record_demo.mjs`. Output defaults to
`/tmp/desk-demo`. The script injects one rate-limit fault and approves its fixed simulator
recovery. Use an isolated local demo and a disposable database. It checks browser
errors, the approval acknowledgment and the final recovered progress state.
