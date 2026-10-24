# Console design system — Phase 1

The existing vanilla HTML/CSS/JavaScript console uses a neutral dark palette and shared
semantic tokens in `triager/static/style.css`. No remote font requests are required.
Keep later design phases on the dashboard design PR; this phase changes presentation only.

| Foundation | Tokens / convention |
| --- | --- |
| Surfaces | `--bg`, `--panel`, `--surface-raised`, `--surface-inset`, `--surface-hover` |
| Borders | `--line`, `--border-strong` |
| Text | `--text`, `--text-secondary`, `--muted` |
| Status | `--green` (success), `--orange` (warning), `--error` (failure), each with a background and border token |
| Source labels | `--info`, `--info-bg` |
| Focus | `--focus`, a two-pixel outline with three-pixel offset |
| Spacing | 4, 8, 12, 16, 20, 24, 32, 36px via `--space-*` |
| Radius | 6px controls, 10px cards, 12px dialogs; pill radius for statuses |
| Elevation | `--shadow-card`, `--shadow-popover`, `--shadow-dialog` |
| Type | 15px body, 14px content/controls, 13px secondary labels, 16px section headings, 24px titles, 32px metrics |

Use `--sans` for interface text and `--mono` for metric numbers, code and timestamps.
Numbers use tabular figures; body line height is 1.6. Reserve 12px for exceptional compact
annotations rather than normal content. Metrics stay 32px on narrow screens.
Chart labels use the same muted, warning, border and success tokens as the rest of the UI.

Buttons, inputs and selects share a minimum 36px height. Secondary and text buttons retain
their hierarchy on hover, disabled buttons stay disabled visually, and interactive elements
have visible keyboard focus. Tooltips use an elevated dark surface with readable text;
status meanings remain written out rather than conveyed through color alone. Existing
keyboard, tooltip, modal, sorting, simulation and approval behavior is preserved.

## Validation

- JavaScript syntax check and `make build` (lint, formatting, wheel and packaged assets).
- CSS parsed without errors; all 47 referenced custom properties resolve.
- Shared text/background contrast: primary 14.84:1, muted 7.64:1, success 7.56:1,
  warning 7.93:1, failure 6.90:1, source badge 7.95:1. These are token-pair checks,
  not a claim of a complete accessibility audit.
- Browser review of dashboard and incident dialog at desktop and 375px viewport:
  no document overflow, 15px body, 32px metrics; existing table scrolls horizontally
  within its container. Review retains its timeline, evidence, trace and approval controls.

No backend, endpoint, dependency, application version or release tag changes are included.

## Phase 2 — main dashboard

The operations overview uses the same tokens with a branded monitoring header, explicit
metric states, a balanced chart/scenario grid and three labeled service health cards.
Statuses describe observed telemetry and unresolved incidents separately; no received
samples never becomes a healthy reading merely because the process just started.
Simulation is disabled for external telemetry and the environment remains unknown until
a snapshot succeeds. Metrics show current values only, with no invented trends.

Execution pulse is 224px high. Its x-axis uses real sample timestamps rather than uniform
sample spacing; the y-axis includes negative slippage and uses metric units. Only finite
samples with valid timestamps from the selected service are drawn. Single points remain
visible. Thresholds within the visible range have a dashed line; thresholds outside it are
annotated in the footer without drawing a misleading line. Hover/tap and keyboard arrows
inspect the exact stored value and UTC timestamp. Axis labels use local browser time.
Loading, connection failure, no samples and stale telemetry have explicit states.

Validation includes `scripts/test_dashboard.cjs` through the existing frontend build check:
empty, zero, single, negative, invalid, uneven-time samples and visible/off-scale thresholds.
Browser checks cover desktop/375px layouts, metric switching, exact-value inspection,
scenario triggering, no-telemetry/unauthenticated states and the existing Review dialog.
All 138 existing regression tests and `make build` pass.
The review markup, backend and APIs are unchanged. Fixture telemetry is used only by the
renderer tests; browser validation uses the real local simulator and an isolated empty DB.

## Phase 3 — incident management

The queue presents severity, signal/diagnosis/source, affected service, detection time,
status and action in six readable columns. Relative times expose the exact local and
original ISO timestamp through pointer and keyboard tooltips. Queued is explicitly waiting
for execution; verifying is waiting for healthy telemetry; only resolved means confirmed
recovery. Failed incidents retain a Review action and their existing backend restrictions.
Unknown severity is displayed as unknown and sorts after known severities in both directions.

Client-side filters provide All/Open/Resolved, severity and service. Open means every
unresolved status, including queued, verifying and failed. Counts explicitly refer to the
loaded snapshot, not the entire database; this preserves the backend's existing history
limit. Filters and sort survive polling. No-match, no-resolved-history, and no-attention
states have different explanations. If the desk reports unresolved incidents outside loaded
history, the empty state reports that limit rather than claiming the desk is clear.

Temporal correlation context is retained, with every individual incident row and action
still visible. This grouping does not infer a shared root cause or merge approvals.
On intermediate widths, the action column stays visible while the table scrolls. At 680px
and below the same rows become labeled cards, retaining status/action and an equivalent
sort selector. The Review dialog and all other dashboard sections are unchanged.

Validation: renderer checks cover all five statuses, filter combinations, sorting, unknown
severity, escaping, exact timestamps, action labels, empty states and correlation rows.
Browser checks cover pending Review, resolved View details (approval disabled), keyboard
Enter selection, timestamp tooltip without opening Review, service/severity filters, reset,
and desktop/375px layouts with no page overflow. Test fixtures stay inside the Node checks;
UI validation reads actual isolated demo history. No recovery decision was submitted.

## Phase 4 — incident review

The native dialog is a responsive investigation workspace, up to 1180px wide. Its header
names the service, actual severity/status and detection time. The main column shows the
observed symptom, verbatim structured findings, cited source links/quotes and uncertainty.
Abstention, missing information, unsupported claims and provider fallback remain visible.
The complete original report is retained in its own expandable panel, alongside source
records/full evidence IDs, tool calls/arguments/results, workflow timings, model usage,
stored incident telemetry/logs and the fixed recovery script.

The decision panel names the fixed simulated handler and target, displays the server's
policy disposition/reason, collects an approver and decision reason, and separates the
submission acknowledgement from current recovery status. Queued is not successful
recovery; only the backend's verified state is presented as resolved. Rejection still
requires a nonempty reason and approval remains bound to the existing proposal and
idempotency key. Frontend validation does not replace server authorization. No backend,
LangGraph interrupt, execution, verification or API changes are included.

The dialog has a single main scroll area; reports and code blocks have no nested scrolling.
On narrow screens, the investigation comes first, then the decision, followed by recovery
progress and optional technical panels. Native modal focus containment and Escape are
preserved; opening focuses the title and closing restores the invoking row/action (or the
status filter if that row has disappeared). Evidence links open the appropriate source
and focus its summary. Field/API errors use alert regions, preserve drafts, and are not
overwritten by polling. Recovery status is announced only when its presentation changes.

Validation:
- Node review checks exercise the real decision handler with mocked HTTP: rejection reason,
  approver, original proposal/action payload, retry key reuse, duplicate in-flight clicks,
  draft/error preservation, recovery states and late responses after another incident opens.
- In an isolated SQLite/offline simulator, browser rejection without a reason focused the
  textarea without submitting. Rejection with a reason was recorded; refreshing created
  a new reviewable proposal. Approval then displayed queued before actual verification.
- Read-only SQL inspection confirmed one rejected decision (zero attempts) and one approved
  recovery (one worker attempt, two healthy verification samples, succeeded). The incident
  resolved only after those samples. Existing desk history was not used for decisions.
- Browser checks covered source navigation, native Escape/focus return, initially closed
  technical panels, and desktop/375px layouts. At 375px the dialog's scroll width equaled
  its client width; primary report text was 14px and the decision preceded technical panels.

## Phase 5 — observable investigation visualization

The review adds Summary/Workflow/Evidence/Tools navigation and an expandable, numbered
view of the existing `node_trace`, preserving recorded order and repeated reasoning/tool
passes. Every card names the operation, recorded status, available duration and explanation.
Missing traces do not produce inferred stages. Node records have no wall-clock timestamps
or tool-parent IDs, so the UI keeps tool records/timestamps separate rather than inventing
an exact combined timeline. The six-stage process guide is explicitly labeled as a guide,
not a run trace; human authorization and recovery remain separate from investigation.

The critic wrapper is always visited by the current graph, even if the critic model is
not requested. A record of that gate is labeled "No assessment recorded" unless the final
verification metadata records a critic assessment or unavailability. Node completion is
not presented as causal correctness or as proof that every tool succeeded.

Tool entries retain actual name, scope, timestamp, arguments, status, result summary,
truncation marker and evidence links. Blocked/duplicate/error outcomes do not imply a
source was accessed. Legacy name-only traces explicitly lack detailed outcomes/timings.
The evidence explorer filters collected data, runbook searches and other sources, and
cited/uncited records. It shows exact source, observed time, evidence ID, excerpt and
related final findings. Only the recorded `tool:search_runbooks` source can be classified
as knowledge retrieval, with structured returned documents; ordinary logs/metrics are not
RAG. Empty/malformed retrieval results are distinguished. Returned document/version/source,
embedding metadata and similarity are inspectable; similarity is not diagnosis accuracy.
Following a citation resets filters and opens/focuses its source record.

The final provider, predicted severity/category, hypotheses, uncertainty, missing information
and fallback reason remain visible. Offline output is labeled rule-based, and uncalibrated
confidence remains explicitly uncalibrated. Model usage stays secondary. Only allowlisted
public call metadata and node metrics are rendered; model messages, response parts and
private reasoning fields are never serialized by the visualization. No model architecture,
backend/API, model execution permissions or recovery behavior is changed.

Validation on 24 October 2026:
- UI/adapter checks used actual offline history: five node records, no model calls and two
  context tool records. Offline rules and the unassessed critic gate were labeled correctly.
- One isolated live Gemini smoke run recorded seven nodes, two model calls, three tool
  records and fourteen evidence records. The model made a read-only service-metrics request
  between reasoning passes. The explorer correctly found three cited records and zero
  runbook searches. This was UI smoke validation, not an accuracy benchmark.
- Positive, empty and malformed runbook retrieval, fallback, critic outcomes, blocked tools,
  missing timings, legacy records and private-field exclusion have labeled Node fixtures;
  fixtures are never injected into the live UI.
- Browser checks covered stage expansion, tool/source inspection, citation/filter reset,
  secondary token/cost records, keyboard focus and desktop/mobile layout. At 375px the
  offline trace stacked in one column and dialog scroll width matched client width.
- No recovery decisions were submitted during this phase.


## Phase 6A: review refinement

Recorded graph operations now follow a single connected, numbered timeline, including
repeated operations in their stored order. Stage, recorded status and duration remain
visible; technical metrics and explanations expand on demand. An unassessed critic gate
uses a dashed marker and explicit status, never an implied model assessment. Verification
check names use plain English, and confidence is explicitly uncalibrated rather than an
accuracy measure. Run references are shortened visually; Copy run ID copies the full
reference and reports success or provides selectable text when clipboard access fails.

The existing section links now remain available while the dialog scrolls, with a direct
Recovery decision destination. Anchor offsets follow the actual navigation height using
ResizeObserver, including wrapped mobile links. The recovery panel remains visually
separate. No inner scroll containers were added. Advanced panels use consistent borders,
spacing and readable summaries. Approval authorization, decision handlers, API contracts,
backend state and execution behavior are unchanged.

Validation: frontend fixture suites include full-ID copying, clipboard failure, missing run
IDs and the unassessed critic marker. Browser checks cover timeline expansion, copy feedback,
section focus, mobile navigation at 375px, no horizontal dialog overflow and native Escape /
focus return. Existing offline and Gemini record exports are checked without new model calls.
The existing build and Python regression suite pass (138 tests).

Limitations: expanded raw sources can still make the dialog long. On small screens recovery
buttons remain in the stacked decision section, reachable through the persistent link;
they are not permanently pinned over the content. Exact node-to-tool correlation and
per-stage timestamps remain unavailable where the backend did not record them.

## Phase 6B: first-visit clarity and final QA

The overview explains the monitored domains (market data, execution, ledger balances) and
what an incident means. Review instructions connect diagnosis, tool calls, cited sources,
human policy approval and telemetry verification without requiring a README. No tour,
extra navigation, canned investigations or fabricated telemetry is added.

The header shows configured analysis separately from each investigation's recorded provider.
Offline configuration explicitly says no LLM. OpenAI configuration is no longer mislabeled
as offline in Settings. The fault summary uses the snapshot's active fault map; changing the
scenario selection does not imply a fault has started or stopped. Historical incidents stay
visible independently. Fallback wording describes the recorded fallback without inventing a
network failure (validation failures can also cause fallback).

A missing investigation now renders an empty state instead of dereferencing a null record.
Missing tool arguments/results say Not recorded. Authentication errors provide a Settings
instruction. Failed snapshot loads replace indefinite loading labels, identify last received
history/health/configuration, and explain why scenario execution is disabled.

Recorded-data audit:

| Display | Source and interpretation |
| --- | --- |
| Environment / configured analysis / active faults | Snapshot mode, ai_provider and faults; configuration is not a claim of successful model execution |
| Incident title, severity, status and detection time | Incident record / diagnosis; missing values remain unknown |
| Investigation order and duration | node_trace in stored order; absent timing is not estimated |
| Critic assessment | verification.semantic_support; visiting the gate does not imply assessment |
| Evidence and findings | evidence_items and explicit hypothesis evidence_ids; retrieval requires structured search_runbooks records |
| Tool calls, outcomes and budgets | tool_events and recorded counters; unrecorded details remain unavailable |
| Model usage and cost | Allowlisted recorded model_calls metadata; no hidden reasoning or invented usage |
| Recovery | Incident state and audit entries; queued and verifying remain distinct from resolved |

QA on 24 October 2026:
- 138 Python tests passed. Frontend suites cover filtering/statuses, chart edge cases,
  decision binding/idempotency/rejection validation, providers/fallback/critic semantics,
  source provenance and private-field exclusion. New checks cover null investigation,
  missing run ID, authentication instructions and configured-provider/active-fault labels.
- Previously recorded offline (5 nodes, no model calls) and live Gemini (7 nodes, 2 model
  calls) exports pass the adapter checks. No new provider calls were made in this phase.
- Browser checks at desktop 1280px, tablet 768px and mobile 375px found no page or dialog
  horizontal overflow. Review navigation destinations remain below the sticky links.
- Verified token-free first visit, reconnect, stale authenticated snapshot failure, filter
  empty state, no retrieved documents, completed-incident details and disabled decisions.
  Required rejection feedback was checked without submitting a decision. Keyboard Tab,
  Escape/focus return and chart Home inspection were checked in the browser.
- Lint, frontend validation, CSS parsing, wheel build and packaged-asset verification pass.

Assessment: the existing interface communicates monitoring, investigation and controlled
recovery with factual labels and visible primary actions. This is UI QA, not a diagnosis
accuracy benchmark or a full assistive-technology audit. Remaining limitations include long
expanded source payloads, stored-history limits, missing per-node/tool correlation and a
stacked mobile decision area. No backend or recovery behavior changed.


## Automatic local access

The desk access token and its UI field are removed. The console polls the API on first
load without credentials; Settings offers Refresh connection and infrastructure details.
Prior phase notes about token entry describe the old behavior. Legacy environment/token
files are left untouched, and database/model configuration is unchanged. API rate limits,
explicit human decisions, required rejection feedback, native approval interrupts, bound
proposals, idempotent requests and fresh-telemetry verification remain in place.

Validation includes token-free startup with legacy token variables, API schema without a
desk-token parameter, malformed approval rejection, existing recovery regression checks
and a browser simulator/review smoke test on an isolated offline database.

Token-removal validation: 135 Python tests pass (the four retired token-bootstrap tests
were replaced by token-free API access/schema/validation coverage). Frontend suites, lint,
wheel/package checks and recorder syntax validation pass. An isolated browser run connected
without credentials, injected an HTTP 429 fault, rejected an empty decision reason, accepted
an explicit simulated approval and reached resolved after fresh telemetry. Refresh connection
works without a token field. Local .env/database/provider configuration was not modified.
