# Providers, traces and reliability

Set `AI_PROVIDER=gemini` to use the configured Gemini REST model. The OpenAI Responses
adapter accepts `AI_PROVIDER=openai`, `OPENAI_MODEL` and `OPENAI_API_KEY`; its tool history
and fallback behavior are mock-tested. This release publishes Gemini live measurements
only. `FALLBACK_PROVIDER=offline` is the default; opting into another provider can transmit
the same redacted incident context to that provider and incur additional charges.

A provider call has a maximum 20-second timeout and at most one retry for transport errors,
429, or selected 5xx responses. Both attempts share the investigation deadline. Invalid
schema output gets one graph repair attempt; tool/round/deadline budgets remain enforced.
A failed provider falls back to a conservative symptom report. The console and evaluation
report retain that fact; a fallback result must not count as successful model reasoning.

`CRITIC_ENABLED=true` enables a second model pass after extract validation. Set
`CRITIC_PROVIDER=gemini` or `openai` to choose the critic; empty uses the primary provider.
The critic assesses every hypothesis exactly once, drops unsupported hypotheses and
abstains when no supported hypothesis remains. An unavailable requested critic causes
abstention. Its opinion is fallible and does not authorize recovery. The default remains
o critic so the retrieval ablation does not change two variables simultaneously.

Every completed investigation retains node durations, input/output token usage where
reported by the provider, and dated standard text cost estimates. Pricing provenance lives
in `triager/knowledge/pricing.json`. Missing usage, failed request attempts, unavailable
critics or semantic embedding charges make total cost unknown; unknown is not zero.
Estimates exclude discounts, taxes and provider billing adjustments. Model thought tokens
are included in Gemini output usage when reported. Node traces are available in the incident
review and persisted SQL audit.

Set `OTEL_EXPORTER_OTLP_ENDPOINT` for an optional OTLP HTTP collector. Spans contain the
service, run ID, node timings and usage estimates. Evidence and exception text are excluded
from span attributes. SQL audit/checkpoint data still contains redacted diagnostic evidence;
restrict access and define retention for your deployment. The collector is operator-provided.

The authenticated API has per-client-IP in-process limits: 600 requests/minute generally
and six manual triage requests/minute. HTTP 429 includes Retry-After. Forwarded headers
are not trusted. These limits, simulator ownership and worker lifecycle assume one process;
scale-out needs coordinated limits and ingestion ownership. Approval is an authenticated
operator attribution label, not a multi-user identity system.
