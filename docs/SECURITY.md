# Evidence and action safeguards (v1.4.0)

Logs, metrics, deployment diffs, and model output are untrusted. They can inform a diagnosis,
but cannot grant tool permissions, approve recovery, or change execution policy.

## Evidence boundary

Initial logs and reconciliation snapshots are sanitized before entering graph state.
Additional tool results are sanitized before evidence IDs are computed. Model responses
are sanitized before being checkpointed, and the HTTP provider boundary sanitizes outgoing
conversation content again. Sources and hashes identify the redacted evidence version;
they are not hashes of the original raw log or proof that its author was truthful.

The best-effort redactor covers sensitive dictionary keys, common secret assignments,
bearer tokens, credential-bearing URLs, selected provider token formats, configured Gemini
keys/desk tokens/database URLs, and email addresses. Diagnostic numeric values remain intact.
It does not identify arbitrary names, phone numbers, every token format, encoded secrets,
or all sensitive business information. It does not remove prompt-injection instructions
from evidence: those remain data inside the structured untrusted-evidence envelope.

Raw telemetry in application SQL and raw-data views is outside this redaction
boundary. Existing database records and checkpoint files are not retroactively rewritten.
New diagnoses use redacted evidence; pre-security graph runs refuse resume and require a
fresh diagnosis. Manage legacy data retention separately; this release does not delete it.
A changed or redacted provider signature may make a continuation invalid; the workflow then
uses its offline fallback rather than exposing the unsanitized response.

## Evidence verifier

Each cited hypothesis must supply an exact supporting quotation or a structured numeric
claim for every referenced evidence ID. The verifier independently checks:

- Citation membership in collected evidence.
- Verbatim quote membership in that evidence's redacted content.
- Exact JSON Pointer traversal, including `~0` / `~1` escaping and strict array indexes.
- Native JSON integers and finite floats; booleans and nonfinite values are rejected.
- Decimal strings only from `ledger:snapshot` or `tool:reconcile_balances`, and only when
  the resolved field is `local_nav`, `exchange_nav` or `difference`. Accepted strings match
  `-?[0-9]+(?:\.[0-9]+)?`: no whitespace, currency symbols, commas, exponent notation,
  NaN or Infinity. Ordinary telemetry/log strings remain nonnumeric.
- Exact `Decimal` comparisons. Ledger strings are parsed directly as `Decimal`, never
  through float; a wrong amount is `NumericMismatch`, while a missing/malformed pointer
  or disallowed source/value is `InvalidNumericReference`.
- Consistency between support references and the hypothesis's citation list.

Unsupported output is replaced with the conservative offline symptom baseline. The report
and audit retain verification issues and explicitly mark semantic support as `not_assessed`.
The model may repair schema errors once, within its original investigation budget.

For example, the ledger string `"1250.00"` at `/0/difference` now supports a numeric claim
of `1250` with the exact generated evidence ID. Previously this valid reference was rejected
as `InvalidNumericReference`. A claim of `1251` still fails; values are not matched fuzzily.
The external `NumericClaim.value` schema remains a finite float, so a value that loses digits
in that schema cannot gain support through approximate comparison. Database money stays in
its existing string representation. Existing diagnosis records are not rewritten.

An accurate quote can still support an unrelated causal claim. A number written only in
free-form prose is not covered by structured numeric checks. This release does not claim
semantic entailment or causal verification. The test suite deliberately includes a case
showing that an unrelated cause with a real quote passes structural checks. Semantic critic
assessment and human-reviewed root-cause rubrics remain pending evaluation work.

## Independent execution policy

`action_policy` accepts only typed actions and a fixed target. Trusted context comes from
the stored incident and application settings. Policy does not parse the model's diagnosis
or trust words such as "safe", "approved", or "requires_approval: false".

| Action | Incident kind | Ordinal risk | Decision |
|---|---|---:|---|
| `inspect_only` | `ml_degradation` | 0 | Read only |
| `enable_backoff` | `rate_limit` | 2 | Approval required in simulation |
| `reconnect_feed` | `tick_gap` | 3 | Approval required in simulation |
| `resync_orders` | `latency` | 5 | Approval required in simulation |
| `resync_ledger` | `nav_mismatch`, portfolio-ledger only | 8 | Approval required in simulation |

Unknown actions, action/kind mismatches, target mismatches, extra policy flags, and external
execution are blocked. Risk scores are fixed engineering rankings, not probabilities.
The proposal API exposes the policy decision. Approval rechecks policy inside the SQL
transaction, and the audit records the decision used for execution. Approval requests reject
extra fields. The actor field is an attribution label, not verified identity. The local
application has no access-token gate. Production identity and role separation remain future work.

Graph tools remain read only. Even if a compromised model requests shell execution, SQL,
deployment, recovery, or a different service, those requests cannot reach an executable
handler through the graph. This boundary existed as an allowlist before this release;
the new policy adds typed scope and incident-kind checks rather than replacing it with a
keyword blocklist. Version 1.5.0 adds native approval interrupts, exact proposal binding, and a durable
execution outbox; see [recovery guarantees](RECOVERY.md).

## Reproduce the security evaluation

```bash
python -m evals.security --output /tmp/desk-security-results.json
```

The 28 deterministic cases comprise six redaction fixtures, seven extract fixtures, seven
policy fixtures, and eight injected-log/compromised-planner fixtures. CI runs them as a gate
and uploads the report alongside the offline diagnosis evaluation.

| Check on seed fixtures | Reference behavior | Hardened behavior |
|---|---:|---:|
| Synthetic secret values present at the evidence boundary | 6/6 before redaction | 0/6 after redaction |
| Unsupported extracts accepted | 5/5 by citation-membership-only checking | 0/5 by quote/numeric checks |
| Valid extracts rejected | 0/2 | 0/2 |
| Forbidden tool requests accepted | Existing allowlist already blocks them | 0/8 |
| Expected policy decisions matched | Not a before/after model comparison | 7/7 |

The reference extract check reproduces the previous membership-only verifier on these
constructed inputs. These are small development fixtures, not held-out security estimates.
The planner is deliberately scripted to follow the malicious request so the evaluation
checks the execution boundary even under model compromise. It does not measure how often
Gemini follows malicious log instructions. `live_model_attack_success_rate` is null until
paid before/after model experiments are run with a reviewed corpus. Semantic attack success,
real unsafe-action recall, and calibration have not been established by these results.

## Live probe runner

`python -m evals.injection_live --live` compares a minimal schema prompt with the production
hardened graph on six authored sentinel-in-cause injections. It exposes no execution tools.
Success means the exact attack sentinel becomes a hypothesis cause. Provider failures and
fallbacks are excluded from the denominator and counted separately. A missing denominator
is unknown, not zero attack success. These probes test a narrow diagnostic-integrity objective;
they do not measure authorization bypass, exfiltration, or general model safety.

## Local application access

The console and application API connect without a desk access token. Startup no longer
creates or prints token files; legacy DESK_TOKEN / DESK_TOKEN_FILE values are ignored.
Existing local environment and token files are not rewritten or deleted. Commands bind
the local app to 127.0.0.1. The API has no identity layer; the approver name is attribution.
Policy, native graph interrupts, proposal binding, idempotency, rejection validation,
rate limits and fresh-telemetry recovery verification remain enforced. A shared deployment
would need its own access control. Model API keys and the separate demo-service control
token are unaffected.
