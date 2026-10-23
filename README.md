# Desk Triager

### Trading-service observability & approval-gated incident recovery

A Python support platform that monitors execution telemetry, detects silent service failures, investigates logs and ledger differences, and proposes a recovery for trader approval.

**Python · FastAPI · LangGraph · PostgreSQL / pgvector · Prometheus · Loki · Gemini / OpenAI REST**

![Trading-service observatory](docs/desk-console.png)

## What it does

- Monitors fill latency, slippage, heartbeat jitter, stale ticks, and exchange reject codes.
- Combines explicit operational rules with a seeded Isolation Forest baseline.
- Detects complete telemetry silence with an independent receipt-time watchdog.
- Reconciles local and simulated exchange NAV using decimal-precision SQL balances.
- Automatically gathers evidence with scoped log inspection and read-only reconciliation tools.
- Requires approval for fixed recovery actions, then verifies a fresh healthy sample before closing the incident.
- Preserves events, incident history, service watermarks, and an approval audit trail in SQL.
- Uses native LangGraph approval interrupts, an idempotent SQL recovery outbox, and consecutive-sample verification.
- Retrieves versioned, reviewed runbooks and past incidents with scoped pgvector or local vectors.
- Checks quoted and numeric evidence, supports an optional causal critic, and records node usage/cost traces.
- Compares a strong one-prompt baseline with the graph and retrieval on 40 labeled incidents.

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

For the instrumented Docker demo with PostgreSQL, Prometheus, Loki, and injectable service
faults, see [the demo guide](docs/DEMO.md). Versioned [runbook retrieval](docs/RETRIEVAL.md) supports pgvector and local vectors. Track the agreed implementation phases in
[the roadmap](docs/ROADMAP.md).

The default configuration uses SQLite, synthetic telemetry, and rule-based offline triage. Use **one process / one worker** because simulator state and ingestion ownership are local to that process.

## Follow an incident

1. Choose **Stale market feed** and click **Run scenario**.
2. Watch the detector create an incident and the triage worker collect evidence.
3. Click **Review** to inspect the diagnosis and recommended recovery.
4. Approve the action as `desk-operator` or enter an attribution label of your choice.
5. Watch `Needs review → Queued → Verifying → Resolved`. Approval alone does not establish recovery; a fresh healthy telemetry sample must confirm it.
6. Enable **Show resolved** and expand **Activity & balances** to inspect the approval and verification audit records.

The selected scenario and progress survive a page refresh. All scenario execution and exchange recovery remain explicitly simulated. See [durable approval](docs/RECOVERY.md) for proposal binding, idempotency, rejection feedback, and worker recovery.

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
    DB --> T[Checkpointed LangGraph investigation]
    T <-->|read-only tools| G[Gemini REST / offline fallback]
    T --> DB
    U[Trader console] -->|approval| R[Allowlisted recovery]
    R --> S
```

Events move directly through Python background workers. SQL is authoritative for durable state and idempotency. There is no message broker, external cache, or AI provider SDK. An optional OTLP collector receives node traces.

See [architecture and tradeoffs](docs/ARCHITECTURE.md) and [operational runbooks](docs/RUNBOOKS.md).

## Evaluation and demo

[Watch the console walkthrough](docs/media/desk-demo.webm): detect a simulated incident,
inspect grounded evidence, approve the fixed recovery, and wait for verified health.
The recording uses offline reasoning. [Review screenshot](docs/media/incident-review.png).

The 40-case benchmark includes 20 demo fault variants, ten public-postmortem-inspired
reconstructions and ten ambiguous cases. It measures severity, category macro F1, literal
evidence grounding, abstention, confidence/Brier score, latency, tokens and estimated cost.
A strong single prompt receives all fixed tool context; the graph must collect it through
scoped tools. The retrieval ablation adds only packaged runbooks. Family-level splits and
corpus hashes help prevent leakage. Labels remain agent-authored pending human review.

```bash
python -m evals.benchmark --output /tmp/rules.json
python -m evals.benchmark --provider gemini --live \
  --modes prompt,graph,graph_retrieval --request-interval 6 --output /tmp/gemini.json
python -m evals.security --output /tmp/security.json
python -m evals.retrieval
```

Paid Gemini runs require explicit `--live`. OpenAI adapter behavior is mock-tested; this
release's live measurements use Gemini only. A separate Gemini judge and deterministic
manual-review export are available. Regex root-cause matches and judge opinions do not
establish independently validated causal accuracy. Provider failures and offline fallback
are reported separately. See [benchmark methodology](docs/BENCHMARK.md),
[security scope](docs/SECURITY.md) and [provider/trace configuration](docs/OBSERVABILITY.md).

CI gates the offline corpus, negative-control scorer tests, 28 security fixtures and Docker
integration. The original ten deliberately simple seed fixtures remain a smoke test.
Keyword and hashed-vector retrieval both achieved recall@3 and MRR 1.00 on seven authored
runbook queries; this establishes no advantage for vectors or improvement in diagnosis.

### Gemini live results — v1.7.0

Paced run, `gemini-3.5-flash-lite`, 40 cases per mode, 23 October 2026:

| Mode | Severity accuracy | Category macro F1 | Error/fallback rate | Median latency | Median known run cost |
|---|---:|---:|---:|---:|---:|
| One prompt | 72.5% | 0.448 | 15% | 6.49 s | $0.00162 (33 runs) |
| Graph | 80.0% | 0.433 | 10% | 12.02 s | $0.00238 (36 runs) |
| Graph + retrieval | 77.5% | 0.429 | 20% | 13.56 s | $0.00261 (32 runs) |

These all-attempt scores include failed requests and conservative fallback. Of the 40 cases,
30 succeeded in all three modes. On that matched subset, category F1 was 0.484 / 0.478 /
0.478, and literal extract checks passed for 90.5% / 100% / 100% of answered predictions.
The graph enforces extract checks; passing them does not establish causal truth. Retrieval
increased the regex root-cause proxy from 19/20 to 20/20 causal cases in this selected subset,
but held-out all-attempt category F1 decreased. **No broad accuracy or retrieval advantage is
established.** Latency includes request pacing. Costs use dated standard-text prices, exclude
unknown runs, and are estimates; complete billed totals are unknown.

[Full results and caveats](docs/RESULTS.md) · [Raw runs and matched/split analysis](evals/results/v1.7.0/) ·
[Human review rubric](docs/REVIEW_RUBRIC.md)

## Configuration

For Neon and Gemini, set these values in `.env` and restart the app:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@YOUR-ENDPOINT-pooler.REGION.aws.neon.tech/neondb?sslmode=require&channel_binding=require
AI_PROVIDER=gemini
GEMINI_API_KEY=YOUR_KEY
GEMINI_MODEL=gemini-3.5-flash-lite
TICK_GAP_SECONDS=30
```

Without cloud credentials, the app uses SQLite and offline triage. See [.env.example](.env.example) for all settings. Keep credentials private; `.env` files are excluded from Git. Gemini requests may incur API charges.

## Development commands

The app is Python with a vanilla JavaScript console. No npm wrapper is required.

```bash
make build   # Lint, optional Node syntax validation, wheel and asset verification
make run     # Serve on localhost:8000
make test    # Isolated regression suite
make eval    # Offline agent, security and detection measurements
make verify  # Explicit live service verification against the running app
```

`make verify` needs configured database/Gemini credentials and creates a synthetic incident
and recovery. Build output is under `dist/`; credentials and runtime state are excluded.
See [the next improvement cycle](docs/IMPROVEMENTS.md) and [detector evaluation](docs/DETECTION.md).

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
  agent.py        Scoped tools, Scoped tools and checkpoint lifecycle
  workflow.py     Bounded LangGraph investigation and citation validation
  contracts.py    Diagnosis and evidence schemas
  baseline.py     Conservative offline symptom classification
  db.py           SQLAlchemy engine and balance reconciliation
  models.py       Telemetry validation and SQL tables
  workers.py      Simulation, watchdog, and triage workers
  static/         Console, contextual explanations, and chart
tests/            Behavioral regression tests
scripts/          Credential-safe connection check
docs/             Architecture, runbooks, evaluation results
.github/          Continuous integration and pull request template
```

## Inspiration

The agentic incident-triage direction was inspired by
[auto-triage-agent](https://github.com/kh-arash/auto-triage-agent). This project applies that
idea to simulated trading telemetry, with an independent evaluation harness, bounded tools,
evidence checks and durable approval-gated recovery. See [implementation progress and limits](docs/ROADMAP.md).
