# Evaluation foundation

Version 1.1.0 introduces evidence and report contracts plus a reproducible offline baseline.
It does not yet migrate the live diagnosis flow to LangGraph.

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
Citation membership verifies provenance, not whether the cited text supports a claim.

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
2. Introduce a bounded LangGraph investigation loop with persisted checkpoints.
3. Expand to 40 reviewed cases and split by source incident or fault family.
4. Add root-cause rubrics, semantic support checks, and manual judge audits.
5. Add injection cases, unsafe-action recall, false-block rates, and hard policy gates.
6. Compare retrieval and tool-use variants under comparable model budgets.
7. Track tokens, versioned pricing, cost, latency distributions, and calibration.

Keep held-out labels and answer-bearing incident documents out of retrieval. Version case
sets, prompts, models, and policy alongside results. Establish paid-evaluation regression
thresholds only after collecting representative baseline measurements.
