# Evaluation foundation

Version 1.1.0 introduces evidence and report contracts plus a reproducible offline baseline.
Version 1.2.0 migrates live diagnosis to LangGraph. The seed evaluation still runs only
the shared rules baseline; a controlled LLM comparison remains pending.

## Run

```bash
python -m evals.run --output /tmp/desk-eval-results.json
pytest -q tests/test_contracts.py tests/test_evaluation.py
```

The predictor receives only a validated `IncidentInput`. Expected labels, case IDs, and
source metadata stay in the evaluator. Do not pass the existing runtime's predefined
`diagnosis`, `kind`, or `action` into future diagnosis benchmarks as answer hints.

Each report records predictions, labels, per-case latency, and invalid reference counts.
Aggregate metrics include severity accuracy, category macro F1 over the union of observed
and predicted labels, abstention accuracy, answer coverage, and citation validity. Citation
validity is null when no citations are produced; abstaining cannot earn perfect grounding.
The seed scorer still measures citation membership. The live workflow additionally checks
quotes and structured numeric values; neither establishes causal support.

Version 1.4.0 adds `python -m evals.security` for deterministic boundary, redaction, extract,
and policy cases. Its before/after comparison targets the old membership-only verifier,
not model susceptibility. Live-model attack success remains unmeasured. See
[security evaluation](SECURITY.md).

## Seed limitations

The ten fixtures are hand-authored synthetic development examples. They include five
recognized symptoms and five unknown or ambiguous cases. They have no train/test split
and are not adapted from public postmortems. The phrase-based rules baseline deliberately
does not diagnose root causes, execute actions, call providers, or incur API charges.
Its fixed confidence is not calibrated. Perfect seed scores are only a smoke check.

CI regression tests also inject incorrect labels and nonexistent citations to check that
the scorer detects failures. The workflow uploads the baseline report for inspection.

## Next milestones

1. Add a label-blind single-prompt provider baseline and adapt the existing agent.
2. Evaluate the bounded LangGraph loop (implemented in v1.2.0) against the prompt baseline.
3. Expand to 40 reviewed cases and split by source incident or fault family.
4. Add root-cause rubrics, semantic support checks, and manual judge audits.
5. Add injection cases, unsafe-action recall, false-block rates, and hard policy gates.
6. Compare retrieval and tool-use variants under comparable model budgets.
7. Track tokens, versioned pricing, cost, latency distributions, and calibration.

Keep held-out labels and answer-bearing incident documents out of retrieval. Version case
sets, prompts, models, and policy alongside results. Establish paid-evaluation regression
thresholds only after collecting representative baseline measurements.

## Expanded release benchmark

The original ten fixtures remain a smoke regression. The new 40-case benchmark, strong
single-prompt baseline, graph/retrieval ablation, optional Gemini judge, manual review export
and measurement caveats are documented in [BENCHMARK.md](BENCHMARK.md). See the README
results section for measured release outcomes. Provider failures and offline fallback are
reported explicitly; they must not be credited as live-model success.

For the reviewed-label, mode-blinded paired RAG comparison, follow
[the paired diagnosis workflow](BENCHMARK.md#paired-diagnosis-evaluation). Offline packet
generation makes no provider calls. Pending reviews are not counted as human accuracy,
and retrieval-query relevance alone is not evidence of better incident diagnosis.
