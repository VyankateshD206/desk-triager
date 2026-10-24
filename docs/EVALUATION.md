# Evaluation and measured results

Reproduction, measured limitations and human review are collected here. Raw versioned
reports remain in [`evals/results/`](../evals/results/); no pending review counts as accuracy evidence.


## Incident benchmark

### Offline smoke regression

`python -m evals.run --output /tmp/desk-seed.json` runs the original ten synthetic
development fixtures: five recognized symptoms and five unknown or ambiguous cases.
There is no train/test split in this seed set. It checks the conservative rules baseline,
label isolation, citation membership and scorer negative controls, not root-cause accuracy.
Citation validity is null when no citations are produced; abstention cannot earn perfect
grounding. These fixtures remain useful in CI but are not the expanded benchmark below.

### Expanded corpus and reproduction

`evals/cases/incidents.json` contains 40 cases: 20 demo fault variants, ten public-postmortem
inspired reconstructions, and ten ambiguous or insufficient-evidence cases. Reconstructed
telemetry is authored for this benchmark, not quoted original production logs. Every public
case includes the original postmortem URL. Labels are agent-authored and await human review.
Development has 25 cases; test has 15. Related incident families cannot cross the split.

```bash
python -m evals.benchmark --output /tmp/rules.json
python -m evals.benchmark --provider gemini --live \
  --modes prompt,graph,graph_retrieval --request-interval 6 --output /tmp/gemini.json
python -m evals.report /tmp/gemini.json --output /tmp/comparison.json
python -m evals.review /tmp/gemini.json --count 12 --output /tmp/review.json
python -m evals.review /tmp/gemini.json --count 6 --live-judge --output /tmp/judge.json
python -m evals.injection_live --live --output /tmp/injection.json
```

`--live` and `--live-judge` explicitly opt into billable requests. Do not commit API keys.
`--split test` supports held-out scoring. Do not tune prompts against test cases. Parallel
workers have isolated databases and checkpoints, but sequential paced requests reduce API
quota pressure. Retries consume the same deadline. Latency includes pacing when enabled.

The one-prompt baseline receives all fixed tool context upfront. The graph must request that
context through scoped tools. Retrieval adds only packaged runbooks; benchmark labels and
reference answers never enter the predictor or knowledge index. Corpus hashes bind results
to the fixtures. Runbook vectors use the local lexical hash baseline unless explicitly changed;
the ablation does not establish gains from semantic embeddings.

Metrics include severity accuracy, category macro F1, answer coverage, answered-category
accuracy, abstention accuracy, Brier score on answered categories, literal evidence extract
checks, latency, usage, cost estimates and provider fallback rate. Root-cause term matching
is explicitly a regex proxy, not causal correctness. The separate optional Gemini judge is
a same-provider opinion. Deterministically sampled review JSON contains nullable human
review fields; a human must actually fill and verify them before claiming human validation.

CI runs all 40 offline cases, the ten seed regression fixtures, structural and negative-control
scorer tests, deterministic security tests and the actual Docker evidence/recovery integration.
Paid evaluations remain explicit operator actions. Do not gate CI on noisy unreviewed live
accuracy numbers. Use the versioned reports in `evals/results/` to inspect release measurements
and failure rates. The paired workflow below separates overall system performance from the
secondary matched-model sensitivity analysis.

The [human review rubric](EVALUATION.md#human-review-rubric) defines severity, symptom category and causal
support checks. The matched comparison excludes any case with a failed/fallback run in any
mode; this avoids counting offline rules as LLM success but introduces a reliability selection bias.

### Paired diagnosis evaluation

Seven successful retrieval queries measure search behavior, not diagnosis improvement. The
following workflow prepares a stronger comparison without claiming a gain in advance.
Preparation and report generation are offline; the explicitly marked live command is billable.
The existing `evals.review` spot-check and optional judge interface remains available.

First export all 40 cases for label review **before generating new predictions**:

```bash
python -m evals.review_packets labels --output /tmp/label-review.json
```

Use the [human review rubric](#human-review-rubric). Edit only each `review` object: correct its labels,
write `root_cause_reference` (including explicit uncertainty), and supply `reviewer`, a
timezone-aware `reviewed_at`, explanatory `notes`, and `status: "approved"`. The suggested
labels are agent-authored and can anchor reviewers; assess the evidence independently first.
Prefer a reviewer who did not author the prompts. Start with the 15 held-out test cases;
the 25 development cases may remain pending. Keep the full packet intact. These are operator
attestations, not authenticated proof of reviewer identity or independence. No human review
is generated automatically and no source corpus is overwritten.

Only after review and an explicit decision to incur model costs, run both modes together:

```bash
## Billable: do not run as part of offline preparation or CI.
python -m evals.benchmark --provider gemini --live \
  --modes graph,graph_retrieval --split test --request-interval 6 \
  --label-reviews /tmp/label-review.json --require-reviewed-labels \
  --output /tmp/paired-gemini.json

## Offline review export: keep the mapping key away from the reviewer.
python -m evals.review_packets diagnoses /tmp/paired-gemini.json \
  --output /tmp/diagnosis-review.json --key /tmp/diagnosis-key.json
```

Diagnosis samples are shuffled and hide case IDs, mode and provider labels in their metadata.
This is partial blinding: evidence content or prediction wording can reveal retrieval or an
offline fallback. All three judgments (`root_cause_correct`, `evidence_grounded`, and
`appropriate_abstention`) must be explicitly filled before approving a prediction review.
Judge causal support against the reviewed reference and supplied evidence, not regex overlap.
Resolve disagreements with a second reviewer and document the resolution in notes.

```bash
python -m evals.report /tmp/paired-gemini.json \
  --reviews /tmp/diagnosis-review.json --review-key /tmp/diagnosis-key.json \
  --output /tmp/paired-comparison.json
```

The new `paired_rag` report:

- Matches case IDs and rejects differing gold labels, family/split or recorded experimental
  settings. Missing pairs are listed rather than silently dropped.
- Reports development and held-out results separately. Use held-out **all attempts including
  fallback** as the primary system comparison. Matched successful calls to the same recorded
  provider/model, under verified matching settings, are a secondary sensitivity analysis;
  missing model/configuration metadata cannot qualify for it.
- Includes category accuracy/macro F1, severity and abstention accuracy, answer coverage,
  verification-issue rate on answered outputs, and category wins/regressions. A lack of
  verification issues does not prove causal correctness. Root-cause regex scores remain proxies.
- Counts human accuracy only when both predictions and their labels have approved reviews.
  Pending judgments stay unscored. Hashes bind reviews to the original corpus and exact
  prediction/evidence content; edits require regenerating packets.
- Computes paired RAG-minus-graph deltas and seeded 95% family-cluster percentile bootstrap
  intervals (1,000 draws by default). Related variants stay together. F1 uses one fixed class
  universe across both modes within each scope, including bootstrap draws. Fewer than two
  families produces no interval; even 15 held-out cases offer limited statistical power.
- Reports recorded retrieval execution and document coverage rather than assuming the
  retrieval-enabled graph used search. Any usage-selected subgroup is observational.
- Reports paired latency and known estimated-cost differences with their denominators.
  Unknown costs remain unknown, never zero. Fallbacks remain visible in overall results.

Do not select favorable seeds, subsets or configurations after seeing results. This small,
reconstructed corpus does not establish production accuracy. A null or negative RAG effect
is a valid finding. No new RAG diagnosis improvement is established by the offline tooling.

#### Retrospective check of the existing Gemini report

The paired analyzer was also run offline on the archived
`evals/results/v1.7.0/gemini-paced.json`; no model calls were repeated:

| Scope | Pairs | Graph category accuracy | Retrieval-enabled category accuracy | Paired delta (percentage points) | Family-bootstrap 95% interval |
| --- | ---: | ---: | ---: | ---: | --- |
| All cases | 40 | 77.5% | 75.0% | -2.5 | -11.1 to +6.3 |
| Test split | 15 | 53.3% | 53.3% | 0.0 | -20.0 to +20.0 |

These are provisional **all-attempt** results against agent-authored labels, not human
root-cause accuracy. Eight pairs contain at least one fallback. All 40 pairs lack the new
configuration metadata, so none qualify for the strict matched-model analysis. Actual
retrieval execution is unknown because the archived report lacks the new usage fields;
unknown is not evidence that search did not run. There are no approved label/prediction
review pairs. This archive predates the query-aware retrieval changes and cannot validate
their effect. The results show no established diagnosis benefit and motivate a new reviewed,
controlled comparison rather than a positive RAG claim.

```bash
python -m evals.report evals/results/v1.7.0/gemini-paced.json \
  --output /tmp/historical-gemini-comparison.json
```


## Historical Gemini results

Measurements were collected on 23 October 2026 with Gemini `gemini-3.5-flash-lite` and
corpus `incidents-1`. All labels are agent-authored; independent human validation is zero.
The public cases reconstruct source incidents rather than reproduce original production logs.
No OpenAI live result is claimed. The adapter is covered with mocked HTTP contract tests.

### Incident comparison

| Mode, 40 attempts each | Severity accuracy | Category macro F1 | RCA term proxy | Coverage | Error/fallback |
|---|---:|---:|---:|---:|---:|
| Offline symptom rules | 62.5% | 0.296 | 16.7% | 37.5% | 0% |
| Gemini one prompt | 72.5% | 0.448 | 76.7% | 62.5% | 15% |
| Gemini graph | 80.0% | 0.433 | 76.7% | 72.5% | 10% |
| Gemini graph + retrieval | 77.5% | 0.429 | 73.3% | 65.0% | 20% |

Model requests were paced at six seconds, one case worker, four-round/eight-tool/60-second
graph budgets, local hash-vector runbooks, critic disabled. The prompt baseline received all
fixed tool context at once. All-attempt scores include fallback. The initial unpaced run
encountered 77.5–82.5% errors/fallbacks and is retained as a separate failure experiment.
The paced rerun used the same corpus and prompts; test labels were not used to tune prompts.

Thirty case IDs succeeded in all three paced modes. On these matched cases, category macro
F1 was 0.484 (prompt), 0.478 (graph), and 0.478 (retrieval). Severity accuracy was 86.7%,
83.3%, and 86.7%. Literal extract-check pass rates among answered predictions were 90.5%,
100%, and 100%; the graph mechanically enforces extract validity. Causal term matching on
the 20 non-abstention reference cases was 19/20, 19/20 and 20/20. This is a lexical proxy,
not independently assessed causal accuracy, and the subset is selected by provider reliability.

On the 15-case held-out split, all-attempt category macro F1 was 0.354 / 0.290 / 0.278.
Neither the aggregate nor held-out results establish a broad accuracy advantage for the graph
or retrieval. The graph offers explicit tool budgets, extract validation and reviewable traces
with higher latency. These fixtures and one stochastic run do not support significance claims.

### Latency, calibration and cost

| Paced mode | Median latency | P95 latency | Answered-category Brier | Median known cost / run |
|---|---:|---:|---:|---:|
| Prompt | 6.49 s | 15.05 s | 0.123 | $0.00162, 33 known |
| Graph | 12.02 s | 25.20 s | 0.198 | $0.00238, 36 known |
| Graph + retrieval | 13.56 s | 24.62 s | 0.174 | $0.00261, 32 known |

Latency includes pacing and retries. Confidence remains uncalibrated; Brier is reported on
answered categories only and includes fallbacks in this table. Lower Brier is better. The
run reports contain answer coverage, abstention accuracy, tokens and per-run cost estimates.
Complete totals remain unknown when attempts fail or usage is missing. Median estimates
exclude unknown cost runs; they are not invoice totals. Standard text pricing provenance is
packaged in `triager/knowledge/pricing.json`.

### Retrieval and independent boundaries

Seven authored runbook queries scored recall@3 and MRR 1.00 with both keyword and local
hash-vector retrieval. The vectors are a lexical baseline, not semantic Gemini embeddings.
No vector advantage is established on those queries.

All 28 deterministic security cases passed: unsupported extract acceptance changed from
5/5 with membership-only checking to 0/5 with quote/numeric checking; neither method rejected
the two valid extracts. The typed policy/tool boundary rejected all 13 authored unsafe cases
(100% fixture recall). This is not real-world unsafe-action recall or live model susceptibility.
The live sentinel probes observed 0/6 successful attacks against the reference prompt and
0/3 against valid hardened-graph responses, with three hardened errors/fallbacks excluded.
The attack target was an exact sentinel in a hypothesis cause; no execution tools were
available. This run does not show an ASR reduction or establish general injection resistance.

### Audit artifacts and human review

The [versioned result directory](../evals/results/v1.7.0/) contains both incident runs, the
rules baseline, split/matched analysis, deterministic security and retrieval results, live
injection probes, Gemini judge opinions, and a 12-prediction manual-review export. Input
corpus hashes and report hashes bind the analysis to the relevant data. Cost accounting
conservatively marks failed/fallback runs unknown during report export.

Six Gemini judge responses were collected. The Gemini judge is a same-provider model opinion. Nullable human review fields remain
unfilled; neither judge output nor this write-up counts as human validation. Follow the
[review rubric](EVALUATION.md#human-review-rubric), resolve label disagreements, version corrected labels,
and rerun the frozen evaluation before making independent accuracy claims.


## Human review rubric

For a diagnosis-quality comparison, use the two-stage, hash-bound workflow in
[the paired diagnosis workflow](#paired-diagnosis-evaluation): review labels before predictions,
then review shuffled predictions with mode/provider metadata hidden. Keep the mapping key
away from reviewers. Evidence can still reveal retrieval, so describe this as partial blinding.
The legacy sample exporter below remains useful for exploratory spot checks.

Use `python -m evals.review REPORT --count 12 --output /tmp/review.json` to select a seeded
sample. Increase the sample or review all public cases before making research claims.
Do not count an AI-generated critique or this document as completed human review.

For each sampled prediction:

1. Read the fixture evidence and tool values before its expected labels. For a public case,
   read the linked primary postmortem and confirm which details are reconstructed.
2. Check impact and severity: critical is broad total outage or irreversible data loss; high
   is sustained impairment; medium is retriable throttling; low is informational healthy
   observation; unknown means impact cannot be established. Insufficient evidence requires
   an explicit abstention, not a confident diagnosis.
3. Check category using the published trading-symptom rubric. Slow fills are latency even
   when the cause is a deployment, database or resource problem. Use broad cause-domain
   categories when no trading-symptom category applies.
4. Check every cited evidence ID, quoted substring and numeric value against the supplied
   evidence. A correct quote can still be irrelevant to the causal assertion.
5. Assess the causal chain separately. A symptom alone is insufficient for a root cause.
   Look for a supporting mechanism, timing, metrics and corroboration. Mark unsupported
   suspicions as unsupported even if they happen to match a postmortem's final conclusion.
6. Fill reviewer identity, label-correctness, root-cause-support and notes in the exported
   JSON. Explain disagreement and any correction. Have another reviewer resolve disputed
   labels before updating the corpus and increment its version/hash.

Keep incident families in one split and keep reviewed eval answers out of the retrieval
index. Store review artifacts separately from prompts. Report sample size, disagreements,
coverage and error/fallback rates alongside accuracy. Avoid treating an answer on an empty
case as evidence of causal diagnosis skill.

In the new diagnosis packet, score each of the following independently:

- `root_cause_correct`: a specific supported mechanism matches the reviewed causal reference;
  when the reference requires abstention, an explicit evidence-limited conclusion is appropriate.
- `evidence_grounded`: material claims, including their relevance to the proposed cause, are
  supported by the supplied evidence. A matching quotation alone is insufficient.
- `appropriate_abstention`: answering or abstaining is justified by the available evidence.

Use `false` for an unsupported confident cause, even if a keyword matches. Explain ambiguity
and disagreement in notes; leave the entire review pending until resolved. Approval requires
all three boolean judgments, reviewer attribution, a timezone-aware timestamp and notes.
These fields record an operator attestation; they do not authenticate a human or independence.


## Detection evaluation

Run `python -m evals.detection --seeds 20 --output /tmp/detection.json` or `make eval`.
CI runs two seeds and the pinned external series without network access. The committed
[report](../evals/results/detection-1/results.json) retains each seed/service/mode, point errors,
window hits, normal-point false-positive rate and alarm episode counts.

### Independent synthetic regimes

The production forest remains frozen on its original seed-42 synthetic baseline. Twenty
separate test seeds start at 1000, with shifted service baselines, non-Gaussian slippage,
correlated load and varied fault durations. Each seed has three one-hour service streams,
covering stale ticks, silence, throttling, latency, NAV mismatch and feature drift. Normal
and anomalous data occur chronologically; there is no refit or threshold selection on tests.
Rules call the production rule function and the receipt-time silence threshold. Forest-only
has no prediction while telemetry is absent. This is still a synthetic stress test, not an
external validation of these fault semantics.

| Mode | Point precision | Point recall | False alarm episodes / service-hour |
|---|---:|---:|---:|
| Rules | 1.000 | 0.824 | 0.0 |
| Forest | 0.108 | 0.255 | 234.2 |
| Rules + forest | 0.315 | 0.969 | 234.2 |

Sixty service-hours per mode. Recall gains come with a severe false-alarm cost. The rules'
perfect synthetic precision reflects these chosen regimes and thresholds, not real-world
reliability. A false-alarm episode starts when a prediction outside a labeled window switches
from false to true; a single persistent alarm counts once. Point false-positive rates remain
in the report so persistent alarms cannot hide behind episode counts. Denominators use total
test clock duration, including faults; no suppression/cooldown or incident deduplication is
applied. These are raw detector episodes, not UI incident counts.

### External chronological test

Source: [Numenta Anomaly Benchmark](https://github.com/numenta/NAB), revision
`ea702d75cc2258d9d7dd35ca8e5e2539d71f3140`, realKnownCause machine-temperature series.
The CSV, combined anomaly windows, MIT license and SHA-256 provenance manifest are pinned
under `evals/data/nab/`. See Ahmad et al. (2017), Unsupervised real-time anomaly detection
for streaming data, [doi:10.1016/j.neucom.2017.04.070](https://doi.org/10.1016/j.neucom.2017.04.070).

Fit scaler/forest on the first 3,404 points (15%); test the remaining 19,291 points (85%).
The training prefix contains 567 labeled-window points and is not filtered using anomaly labels. The reference threshold uses
training median ± six scaled median absolute deviations. Neither threshold nor contamination
is tuned on test labels. This is a one-dimensional adaptation to temperature, not a mapping
of temperature into fictitious trading features. Trading rules have no meaning in these units.

| Scalar mode | Point precision | Point recall | Windows detected | False alarms / series-hour |
|---|---:|---:|---:|---:|
| Robust threshold | 1.000 | 0.005 | 1/3 | 0.0000 |
| Forest | 0.752 | 0.347 | 2/3 | 0.0373 |
| Threshold + forest | 0.752 | 0.347 | 2/3 | 0.0373 |

The held-out series spans 1,607.58 hours. Official NAB scoring uses its own time-sensitive
scheme; these point/window metrics are **not an official NAB score**. One series cannot
establish generalization. Production desk validation still requires real chronological
telemetry, independently reviewed labels, alert suppression evaluation and service-specific
thresholds. Do not use these numbers as proof the current trading forest is production-ready.
