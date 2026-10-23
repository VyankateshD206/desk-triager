# Implementation progress

The implementation follows the original three-tier plan. Tags identify shipped milestones;
research limitations and uncompleted human review remain explicit.

| Requested capability | Delivered |
|---|---|
| Evaluation harness | 40 labeled cases, public-source links, family-level dev/test split, label-blind predictors, single-prompt/graph/retrieval ablation, severity/category/abstention/grounding/calibration/latency/usage metrics, CI regression gates |
| Agentic tools and loop | Bounded checkpointed LangGraph loop, five scoped external tools, Docker fault app, Prometheus and Loki; v1.2–1.3 |
| Log injection defenses | Untrusted-evidence delimiters, redaction, literal quote/numeric checks, independent typed recovery policy, deterministic adversarial CI and optional live probes; v1.4 |
| Retrieval | Immutable reviewed runbooks or operator-imported past incidents, pgvector/local vectors, optional Gemini embeddings, keyword comparison and diagnosis ablation; v1.6 |
| Critic and abstention | Optional causal critic, explicit insufficient evidence, confidence/Brier reporting and coverage |
| Approval and feedback | Native interrupt/resume, durable approve/reject reasons, proposal binding, idempotent transactional outbox, leased worker, verification deadlines, approval rate and unlabeled feedback export; v1.5 |
| Models and reliability | Gemini and OpenAI REST adapters, schema repair, bounded transport retries/timeouts, configurable model fallback; live results are Gemini-only by user choice |
| Observability | Per-node timings/tokens/cost estimates, optional OTLP export, SQL audit and evidence review |
| Production polish | PostgreSQL migrations, background recovery worker, token auth, in-process rate limits, review console, tagged releases, recorded demo and published evaluation artifacts |

## Research and deployment limits

All 40 labels are agent-authored and pending independent human review. Public cases are
reconstructions, not original incident logs. Root-cause regex matches are proxies; model
judge opinions and nullable human-review exports are supplied separately. Actual human
spot checks must be completed before claiming independently validated causal accuracy.

Live provider failures are retained in reports and excluded from successful-model comparisons.
The presence of a retrieval module or critic does not establish an accuracy gain. Security
fixtures and narrow live probes do not establish universal injection resistance or real-world
unsafe-action recall. Read the release results before making CV performance claims.

The deployment remains a single-process, simulated trading desk. Exchange execution adapters,
multi-user identity/RBAC, distributed ingestion ownership and coordinated rate limiting require
separate production engineering. The Docker integration uses scripted reasoning to verify
actual evidence and recovery plumbing without charging for model calls.
