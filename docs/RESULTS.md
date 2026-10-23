# v1.7.0 measured results

Measurements were collected on 23 October 2026 with Gemini `gemini-3.5-flash-lite` and
corpus `incidents-1`. All labels are agent-authored; independent human validation is zero.
The public cases reconstruct source incidents rather than reproduce original production logs.
No OpenAI live result is claimed. The adapter is covered with mocked HTTP contract tests.

## Incident comparison

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

## Latency, calibration and cost

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

## Retrieval and independent boundaries

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

## Audit artifacts and human review

The [versioned result directory](../evals/results/v1.7.0/) contains both incident runs, the
rules baseline, split/matched analysis, deterministic security and retrieval results, live
injection probes, Gemini judge opinions, and a 12-prediction manual-review export. Input
corpus hashes and report hashes bind the analysis to the relevant data. Cost accounting
conservatively marks failed/fallback runs unknown during report export.

Six Gemini judge responses were collected. The Gemini judge is a same-provider model opinion. Nullable human review fields remain
unfilled; neither judge output nor this write-up counts as human validation. Follow the
[review rubric](REVIEW_RUBRIC.md), resolve label disagreements, version corrected labels,
and rerun the frozen evaluation before making independent accuracy claims.
