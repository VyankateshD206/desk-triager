# Applying for Junior Quant Developer — Support

## Why this project is relevant

The role description emphasizes keeping Python tools and trading services running, troubleshooting issues, and working with traders and developers. This project provides concrete examples for those responsibilities.

| Job responsibility | Evidence in this repository | Interview explanation |
|---|---|---|
| Monitor desk services | Live metrics, service health, watchdog | An absent heartbeat needs a timer because no new event arrives to trigger detection. |
| Troubleshoot Python tools | Structured logs, telemetry, reproducible fault injection | Follow symptoms to evidence, identify a likely cause, and choose a specific recovery. |
| Understand execution behavior | Fill latency, slippage, jitter, reject codes | Explain units and distinguish market-driven movement from service degradation. |
| Reconcile operational state | Decimal NAV comparison and SQL ledger queries | Check each account independently and preserve before-values when resynchronizing. |
| Collaborate with traders | Reviewable diagnosis and approval-gated action | Communicate the impact, proposed change, and verification criteria before recovery. |
| Improve reliability | Idempotent ingestion, durable incidents, fresh-sample verification | Duplicate messages and a successful recovery request must not create false confidence. |
| Use AI selectively | Bounded read-only tools and offline fallback | AI gathers evidence; server-side runbooks and the approving operator control changes. |

The strongest application story is **Python support engineering with trading-domain context**. The AI component complements that story. The project does not establish experience operating a live trading desk; its synthetic telemetry and simulated exchange should be stated plainly.

## Résumé wording

**Desk Triager — Trading-Service Observability & Incident Recovery**  
Python, FastAPI, SQLAlchemy, PostgreSQL/Neon configuration, scikit-learn, Gemini REST API

- Built a Python observability application that detects stale market data, heartbeat silence, exchange throttling, execution-latency spikes, and NAV mismatches using operational rules and Isolation Forest.
- Implemented evidence-based triage with scoped log inspection and read-only SQL reconciliation, followed by operator-approved simulated recovery and verification against fresh healthy telemetry.
- Added idempotent event persistence, incident audit history, contextual metric explanations, behavioral regression tests, and GitHub Actions checks.

List Neon or live Gemini integration as verified only after configuring and exercising your own connections. Avoid invented uptime improvements, reduced MTTR, model accuracy, or trading performance.

## A focused walkthrough

1. Explain the three headline metrics and their thresholds.
2. Run **Silent feed disconnect** and explain why the watchdog detects a failure without new events.
3. Review the diagnosis and recovery recommendation; show the logs and fixed ledger query behind it.
4. Approve recovery and explain why the incident stays verifying until a new healthy sample arrives.
5. Run **NAV mismatch**, explain decimal precision, and show the before-values and approval in Activity.
6. Open the tests and explain one failure case: duplicate delivery, a queued pre-approval sample, or an unresolved incident outside the visible history window.

## Questions to prepare for

- Why does this version use direct Python ingestion? What is lost without a durable broker?
- When might slippage reflect market conditions rather than infrastructure?
- Why is Isolation Forest suitable for a first unsupervised baseline, and what would you validate with real history?
- Why must the agent never replay an order submission autonomously?
- What would you add before sharing this with a real desk: identity, permissions, retention, migrations, adapter preconditions, and historical model evaluation?
- How would you investigate a service that reports healthy heartbeats but stale market ticks?

Be ready to write and debug Python and SQL during the interview. Being able to explain these decisions and reproduce the behavior is the practical value of the repository.
