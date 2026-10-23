# Implementation progress

Follow the agreed evidence-first plan. Version tags describe shipped milestones, not
claims that the entire research evaluation or production hardening is complete.

| Phase | Status | Evidence / remaining work |
|---|---|---|
| 1. Contracts and evaluation foundation | Foundation shipped in v1.1.0 | Ten synthetic cases, isolated labels, offline scorer. Still expand to 40 reviewed cases, add single-prompt and existing-agent comparisons, and create a held-out split. |
| 2. LangGraph investigation | Shipped in v1.2.0 | Bounded tools, checkpoints, restart/resume, schema repair, citation membership, budget abstention. Confidence calibration and semantic support checks remain. |
| 3. Realistic evidence sources | v1.3.0 milestone | Docker demo, controlled faults, Loki, Prometheus, deployment registry, scoped read tools, integration CI. |
| 4. Verification and injection defenses | Guardrails shipped in v1.4.0 | Redaction, quote/numeric checks, independent typed policy, and 28 deterministic adversarial cases. Semantic verification and live-model before/after attack measurements remain pending. |
| 5. Durable approval and execution | v1.5.0 milestone | Native approval interrupts, bound proposals, idempotency keys, transactional outbox, lease claims, rejection feedback, consecutive-sample verification and deadlines. See RECOVERY.md. |
| 6. Retrieval and ablation | Planned | Versioned runbooks and reviewed incidents, pgvector, retrieval metrics, leakage controls. |
| 7. Complete evaluation and presentation | Planned | Root-cause rubrics, calibration, multi-provider comparisons, node usage/cost traces, UI timeline, video and release results. |

The demo integration uses scripted reasoning to verify real tool plumbing without paid
model calls. It must not be reported as LLM accuracy. The public-postmortem corpus, unsafe
action recall, attack success comparisons, and retrieval gains have not yet been measured.

Keep changes in small functional commits, run appropriate checks, and tag only verified
milestones. Close the outstanding evaluation work as security and retrieval are introduced;
those comparisons depend on the real sources and policy under test.
