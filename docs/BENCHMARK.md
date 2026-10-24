# Reproducing the expanded benchmark

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

The [human review rubric](REVIEW_RUBRIC.md) defines severity, symptom category and causal
support checks. The matched comparison excludes any case with a failed/fallback run in any
mode; this avoids counting offline rules as LLM success but introduces a reliability selection bias.

## Paired diagnosis evaluation

Seven successful retrieval queries measure search behavior, not diagnosis improvement. The
following workflow prepares a stronger comparison without claiming a gain in advance.
Preparation and report generation are offline; the explicitly marked live command is billable.
The existing `evals.review` spot-check and optional judge interface remains available.

First export all 40 cases for label review **before generating new predictions**:

```bash
python -m evals.review_packets labels --output /tmp/label-review.json
```

Use [REVIEW_RUBRIC.md](REVIEW_RUBRIC.md). Edit only each `review` object: correct its labels,
write `root_cause_reference` (including explicit uncertainty), and supply `reviewer`, a
timezone-aware `reviewed_at`, explanatory `notes`, and `status: "approved"`. The suggested
labels are agent-authored and can anchor reviewers; assess the evidence independently first.
Prefer a reviewer who did not author the prompts. Start with the 15 held-out test cases;
the 25 development cases may remain pending. Keep the full packet intact. These are operator
attestations, not authenticated proof of reviewer identity or independence. No human review
is generated automatically and no source corpus is overwritten.

Only after review and an explicit decision to incur model costs, run both modes together:

```bash
# Billable: do not run as part of offline preparation or CI.
python -m evals.benchmark --provider gemini --live \
  --modes graph,graph_retrieval --split test --request-interval 6 \
  --label-reviews /tmp/label-review.json --require-reviewed-labels \
  --output /tmp/paired-gemini.json

# Offline review export: keep the mapping key away from the reviewer.
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

### Retrospective check of the existing Gemini report

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
