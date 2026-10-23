# Connection and release verification

Verified on **19 October 2026**, with the application running locally and its database hosted on Neon.

## Live service checks

Command:

```bash
npm run verify:services
```

Observed output (successful exit):

```text
PASS Neon PostgreSQL: SELECT 1; TLS=true
PASS Incident detection: persisted rate-limit incident
PASS Gemini: live REST diagnosis persisted
PASS Recovery: open -> verifying -> resolved
PASS Neon persistence: independent SQL read confirms resolved incident + approval audit
```

The script checks encryption on the Python client's PostgreSQL connection, creates a synthetic incident through the running API, waits for automatic Gemini diagnosis, approves a fixed simulated recovery, and checks the resolved incident and audit history through an independent SQL connection.

## Regression and package checks

```text
npm test
25 passed
```

```text
npm run build
Successfully built desk_triager-1.0.0-py3-none-any.whl
Package verified: desk_triager-1.0.0-py3-none-any.whl; application + console assets present; no local configuration/state
Build complete: Python wheel and console assets verified.
```

These are local command results, not an assertion that a GitHub Actions run or a hosted web application has been deployed.

## Issues resolved during setup

- The global Neon CLI install failed because `/usr/local/lib/node_modules` was not writable. Its latest release also required a newer Node runtime than the system's Node 18.
- The requested `npx neon init` invocation was declined at the approval step and did not run. The existing Neon database was subsequently connected using the manually supplied connection string. No CLI provisioning or `neon deploy` success is claimed.
- Gemini model discovery authenticated the supplied key. Generation with the initial `gemini-2.5-flash` setting returned HTTP 404. The locally configured model was changed to an available `gemini-3.5-flash-lite`, and live diagnosis succeeded.
- A first verification script incorrectly inspected PostgreSQL server-side TLS state behind the Neon proxy. It was corrected to inspect psycopg's actual client connection (`pgconn.ssl_in_use`); encryption was confirmed.
- Read-only dashboard queries no longer block ingestion while waiting for remote SQL round trips. The local Neon configuration uses a 30-second silence threshold to tolerate network and startup jitter. This threshold is configurable; the local SQLite default remains eight seconds.

No credentials, connection strings, provider response bodies, or real trading records are included in these notes. The retained verification incident uses synthetic execution telemetry and simulated recovery.


## v1.3.0 demo milestone

Local checks passed 62 tests, lint/format, wheel/asset validation, and Compose configuration
validation. No Docker daemon was reachable in the implementation environment, so the live
stack was verified on a fresh GitHub Actions runner instead.

[Integration run 39929972100](https://github.com/VyankateshD206/desk-triager/actions/runs/39929972100)
passed both the test and demo jobs. The demo job built containers, started all five services,
injected four faults, matched current event IDs in Loki, checked Prometheus gauges, verified
PostgreSQL incident ingestion, and exercised all four external tools through LangGraph with
a scripted planner. It also called the authenticated triage API in offline mode. No paid
model calls or LLM accuracy claims are included in that result.


## v1.4.0 security milestone

[Integration run 39936854394](https://github.com/VyankateshD206/desk-triager/actions/runs/39936854394)
passed the unit/build/evaluation job and the Docker demo job. The unit suite has 96 tests.
The security benchmark passes 28 deterministic fixtures, including deliberately compromised
planner requests. All five constructed unsupported extracts that passed membership-only
checking are rejected by the new extract verifier; two valid extracts remain accepted.
These are seed fixture results, not a live-model attack success measurement. The demo
planner now supplies verified quotations, and the external tool integration still passes.


## v1.5.0 durable recovery

[CI run 39939131125](https://github.com/VyankateshD206/desk-triager/actions/runs/39939131125)
passed unit/build/security checks, the full fault demo, and the isolated PostgreSQL
recovery test. The latter verified interrupt resume, idempotency, competing worker claims,
ledger execution, and fresh-telemetry resolution. Local regression coverage also includes
stale proposals, rejected decisions, expired leases, and verification timeouts.


## v1.6.0 retrieval milestone

[CI run 39940687269](https://github.com/VyankateshD206/desk-triager/actions/runs/39940687269)
passed unit checks, the fault demo, and isolated PostgreSQL vector search/recovery. A prior
integration run caught an unqualified vector operator; the fixed query qualifies the type
and operator in public. Both lexical keyword and hash-vector methods score recall@3/MRR
1.00 on seven development queries; no root-cause improvement is implied.
