# Human review rubric

For a diagnosis-quality comparison, use the two-stage, hash-bound workflow in
[BENCHMARK.md](BENCHMARK.md#paired-diagnosis-evaluation): review labels before predictions,
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
