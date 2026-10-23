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
and failure rates; compare matched successful runs before attributing a difference to retrieval.
