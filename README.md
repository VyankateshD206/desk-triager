# Desk Triager

### Trading-service observability & approval-gated incident recovery

A Python support platform that monitors execution telemetry, detects silent service failures, investigates logs and ledger differences, and proposes a recovery for trader approval.

Built around the daily responsibilities of a **Junior Quant Developer — Support**: keep desk tools running, troubleshoot failures, communicate clearly with traders, and improve reliability.

**Python · FastAPI · PostgreSQL / Neon · scikit-learn · Gemini REST API**

![Trading-service observatory](docs/desk-console.png)

## What it does

- Monitors fill latency, slippage, heartbeat jitter, stale ticks, and exchange reject codes.
- Combines explicit operational rules with a seeded Isolation Forest baseline.
- Detects complete telemetry silence with an independent receipt-time watchdog.
- Reconciles local and simulated exchange NAV using decimal-precision SQL balances.
- Automatically gathers evidence with scoped log inspection and read-only reconciliation tools.
- Requires approval for fixed recovery actions, then verifies a fresh healthy sample before closing the incident.
- Preserves events, incident history, service watermarks, and an approval audit trail in SQL.

The interface stays focused on three metrics and the incident queue. Hover, focus, or tap a number for its definition, units, and threshold. Technical evidence, scripts, balances, and audit history are available on demand.

## Quick start

Requires Python 3.11+. No cloud credentials or additional infrastructure are needed for the local configuration.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp -n .env.example .env
uvicorn triager.app:app --host 127.0.0.1 --port 8000
```

Open [the observatory](http://127.0.0.1:8000/). The local access token is `local-access-token`. If you change `DESK_TOKEN`, enter the same value under **Settings**. Restart after changing `.env`.

The default configuration uses SQLite, synthetic telemetry, and rule-based offline triage. Use **one process / one worker** because simulator state and ingestion ownership are local to that process.

## Follow an incident

1. Choose **Stale market feed** and click **Run scenario**.
2. Watch the detector create an incident and the triage worker collect evidence.
3. Click **Review** to inspect the diagnosis and recommended recovery.
4. Approve the action as `desk-operator` or enter an attribution label of your choice.
5. Watch `Needs review → Verifying → Resolved`. Approval alone does not establish recovery; a fresh healthy telemetry sample must confirm it.
6. Enable **Show resolved** and expand **Activity & balances** to inspect the approval and verification audit records.

The selected scenario and progress survive a page refresh. All scenario execution and exchange recovery remain explicitly simulated.

| Scenario | Signal | Recovery |
|---|---|---|
| Stale market feed | Tick age above 5,000 ms | Reconnect simulated feed |
| Silent feed disconnect | No accepted samples beyond 8 seconds by default | Reconnect simulated feed |
| Exchange rate limit | HTTP `429` reject code | Apply simulated retry backoff |
| Slow order fills | Fill latency above 350 ms | Resynchronize simulated order state |
| NAV mismatch | Absolute per-account difference above USD 0.01 | Synchronize simulation ledger |
| Subtle feature drift | Isolation Forest decision margin below zero | Investigation only |

## Architecture

```mermaid
flowchart LR
    S[Synthetic service telemetry] --> I[Python ingestion]
    H[Authenticated telemetry API] --> I
    I --> D[Rules + Isolation Forest]
    D --> DB[(PostgreSQL / SQLite)]
    W[Silence watchdog] --> DB
    DB --> T[Automatic triage]
    T <-->|read-only tools| G[Gemini REST / offline fallback]
    T --> DB
    U[Trader console] -->|approval| R[Allowlisted recovery]
    R --> S
```

Events move directly through Python background workers. SQL is authoritative for durable state and idempotency. There is no message broker, external cache, or AI provider SDK.

See [architecture and tradeoffs](docs/ARCHITECTURE.md) and [operational runbooks](docs/RUNBOOKS.md).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | Empty → local SQLite | Neon/PostgreSQL connection string |
| `DESK_TOKEN` | `local-access-token` | Shared localhost API access token |
| `SIMULATOR_ENABLED` | `true` | Generate synthetic telemetry and enable simulated recovery |
| `AI_PROVIDER` | `offline` | `offline` or `gemini` |
| `GEMINI_API_KEY` | Empty | Backend-only Gemini API credential |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model available to your Gemini account |
| `TICK_GAP_SECONDS` | `8` | Receipt-time silence threshold |

The backend reads process environment variables first, then `.env.local`, then `.env`. Keep credentials in `.env`; configuration files containing secrets and local database files are excluded from Git.

### Neon PostgreSQL

Create a dedicated development database/branch in Neon and paste its connection string into `.env`:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@YOUR-ENDPOINT-pooler.REGION.aws.neon.tech/neondb?sslmode=require&channel_binding=require
```

For a remote database, set `TICK_GAP_SECONDS=30` to tolerate network and cold-start jitter; retain a tighter threshold when measuring a local service. Restart the service. SQLAlchemy uses psycopg, connection pre-ping, and the connection string's TLS settings. Startup initializes missing tables and seeds a `desk-primary` account for simulation. SQLite history is not copied automatically. Tables: `telemetry`, `incidents`, `balances`, `service_watermarks`, and `audit`.

[Neon SQLAlchemy documentation](https://neon.com/docs/guides/sqlalchemy).

### Gemini REST API

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=YOUR_KEY
GEMINI_MODEL=gemini-3.5-flash-lite
```

The backend calls Gemini's HTTPS `generateContent` endpoint using `httpx` and an `x-goog-api-key` header. The browser never receives this key. Automatic incident diagnosis and explicit diagnosis refreshes can make billable API requests when Gemini is enabled.

The model can request only `inspect_service_logs` and `reconcile_balances`. Service scope and queries are fixed by the server. Execution is bounded to four request rounds and four tool calls per round. Provider errors, missing keys, timeouts, and invalid responses return offline evidence. The agent cannot execute arbitrary Python, SQL, or shell commands.

[Gemini REST documentation](https://ai.google.dev/api/generate-content).

## Build and run with npm

The application remains Python. These npm commands delegate to the local `.venv` interpreter and require no Node runtime service dependencies:

```bash
npm ci --ignore-scripts
npm run build          # Lint, validate JavaScript, build wheel, verify packaged assets
npm start              # Start the Python service on localhost:8000
npm test               # Run isolated regression tests
npm run verify:services # Exercise live Neon + Gemini through the running service
```

`npm run verify:services` requires configured credentials and a running application. It creates one synthetic rate-limit incident, uses the automatic triage report, approves recovery, and independently verifies the retained SQL audit history. Build output is under `dist/` and excludes local credentials and database files.

## Validation

```bash
pytest -q
ruff check triager tests scripts
ruff format --check triager tests scripts
node --check triager/static/app.js
python scripts/check_connections.py
```

Tests exercise fault detection, silence, duplicate IDs, out-of-order samples, persistence, API authorization, decimal reconciliation, repeated approvals, post-approval verification, queue totals beyond visible history, legacy account migration, and Gemini tool calls with mocked HTTP responses. GitHub Actions runs the automated checks on pushes and pull requests without requiring cloud credentials.

The local configuration is tested against SQLite and offline triage. Live verification also confirmed Neon PostgreSQL over TLS, Gemini REST diagnosis, approval-gated recovery, and persisted audit records. See [verification results](docs/VERIFICATION.md).

## Repository map

```text
triager/
  app.py          Authenticated FastAPI routes and worker lifecycle
  runtime.py      Ingestion, incidents, approvals, and verification
  detector.py     Rule thresholds and Isolation Forest baseline
  agent.py        Bounded, read-only Gemini REST tool calling
  db.py           SQLAlchemy engine and balance reconciliation
  models.py       Telemetry validation and SQL tables
  workers.py      Simulation, watchdog, and triage workers
  static/         Console, contextual explanations, and chart
tests/            Behavioral regression tests
scripts/          Credential-safe connection check
docs/             Architecture, runbooks, interview notes, publishing
.github/          Continuous integration and pull request template
```

## Scope and engineering tradeoffs

This release is a portfolio application with a simulated exchange. It does not place trades, connect to a live exchange, or demonstrate production uptime. The Isolation Forest uses a frozen synthetic baseline; its margin is not a probability or a validated production accuracy measure. Simulated reconnect/backoff/resync handlers clear matching injected faults; ledger recovery copies the simulated exchange snapshot.

SQL commits are durable and event IDs are idempotent, but direct ingestion has no durable buffer for samples that fail before commit. A shared deployment would need verified identity/role checks, schema migrations, retention, and real adapter preconditions. The current approver label is audit attribution, not authenticated trader identity. Keep the application bound to localhost.

## Job application and GitHub

See [interview talking points and résumé wording](docs/INTERVIEW.md), [publishing instructions](docs/PUBLISHING.md), and [contribution instructions](CONTRIBUTING.md).
