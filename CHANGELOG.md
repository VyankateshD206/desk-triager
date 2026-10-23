# Changelog

## 1.2.0 — 2026-10-23

- Replace the manual tool loop with a checkpointed LangGraph investigation.
- Add service metric queries, total tool budgets, round limits, and deadlines.
- Validate structured diagnoses and citation IDs; repair malformed output once.
- Exclude predefined detector answers from model input.
- Resume read-only investigations from persisted node boundaries.
- Abstain on exhausted budgets; retain deterministic recovery approval controls.
- Record workflow IDs and structured diagnoses in the audit trail.

## 1.1.0 — 2026-10-23

- Add validated diagnosis, hypothesis, and evidence contracts.
- Bind stable evidence IDs to source, service, timestamp, and content.
- Add ten synthetic evaluation cases and a label-isolated offline rules baseline.
- Measure severity, category F1, abstention, citation validity, and per-case latency.
- Run the evaluation in CI and upload its report.
- Isolate watchdog regression tests from local timeout settings.

## 1.0.0

Initial trading telemetry console, anomaly detection, Gemini tool calling, SQL audit
history, and approval-gated simulated recovery with fresh-telemetry verification.
