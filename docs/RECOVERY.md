# Durable approval and recovery

Recovery uses a dedicated deterministic LangGraph workflow linked to the diagnosis run.
It pauses at `interrupt()` with a persisted, fingerprinted proposal. The explicit human
approval or rejection endpoint resumes that interrupt with `Command(resume=...)`.
No model can call these endpoints through the investigation graph.

The proposal binds incident ID, service, action, policy, report hash, diagnosis run ID,
simulator fault generation, and ledger preconditions. Updated diagnosis runs, faults,
balances, or policy require another review. Evidence continues to arrive while review is
pending; the proposal describes a frozen recovery intent rather than every later log line.

Approval requests require `proposal_id`, `action`, `actor`, and an `Idempotency-Key` header
of 8–80 characters. Reusing a key with an identical request returns its existing execution;
reusing it with another request is rejected. A second key cannot approve the same proposal.
Keys are hashed in SQL. Rejection requires a reason and is persisted but never executed.
Refreshing diagnosis creates a new proposal even when report text remains the same.

Approval and a queued outbox job commit together in application SQL. Graph checkpoint and
SQL writes are separate; replay consults SQL uniqueness and request hashes to avoid a second
job. A pending SQL proposal whose interrupt was not written is reconstructed on demand.
A background worker discovers queued jobs on startup, atomically claims one with a lease,
rechecks policy and preconditions, and executes a fixed simulation handler. Expired leases
can be reclaimed; transient failures retry at most three times, while changed preconditions
fail immediately. No external exchange execution adapter is installed.

Ledger changes, durable fault removal, job completion, and action audit commit in the same
SQL transaction. Simulator faults are now persisted; a newly injected generation cannot be
cleared by an older approval. The running simulator refreshes its fault state from SQL.
This provides transactional execution for these SQL-backed simulation handlers, not an
exactly-once guarantee for arbitrary external side effects.

Incidents move `open → queued → verifying → resolved`. Execution failures or verification
timeouts move to `failed` for operator attention. Two consecutive fresh healthy samples are
required by default; an unhealthy accepted sample resets progress. The default deadline is
30 seconds. Legacy verifying rows without a durable job retain compatibility behavior.
Original receipt-time, watermark, and late-sample protections remain in force.

The console shows queued/failed states, supports rejection feedback, and retains an
idempotency key per proposal in session storage for request retries. The actor is an
attribution label, not verified identity. No desk access token is required. Application ingestion and
simulation remain single-process even though SQL jobs use atomic claims.

Regression tests cover native interrupts, restart/resume, concurrent identical requests,
key misuse, stale proposals, rejection, worker leases, SQL commit replay, verification
windows, and timeouts. CI additionally exercises PostgreSQL ledger execution and competing
worker claims in an isolated temporary schema. Feedback counts and approval rate are
available in `/api/snapshot`; rejected examples are not automatically trusted as knowledge.

## Reusing feedback

`python -m evals.feedback --output /tmp/feedback-candidates.json` exports rejected diagnoses
and their redacted evidence as unlabeled candidates. Actor names are excluded. A rejection
is not a root-cause label: review the evidence, supply a corrected answer, and assign the
incident family to one split before adding it to the benchmark. Knowledge imports still
require a separate reviewed knowledge document; feedback is never indexed automatically.
The console reports approvals, rejections and approval rate from durable decision records.
