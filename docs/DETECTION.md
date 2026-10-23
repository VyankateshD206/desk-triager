# Detection evaluation

Run `python -m evals.detection --seeds 20 --output /tmp/detection.json` or `make eval`.
CI runs two seeds and the pinned external series without network access. The committed
[report](../evals/results/detection-1/results.json) retains each seed/service/mode, point errors,
window hits, normal-point false-positive rate and alarm episode counts.

## Independent synthetic regimes

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

## External chronological test

Source: [Numenta Anomaly Benchmark](https://github.com/numenta/NAB), revision
`ea702d75cc2258d9d7dd35ca8e5e2539d71f3140`, realKnownCause machine-temperature series.
The CSV, combined anomaly windows, MIT license and SHA-256 provenance manifest are pinned
under `evals/data/nab/`. See Ahmad et al. (2017), Unsupervised real-time anomaly detection
for streaming data, [doi:10.1016/j.neucom.2017.04.070](https://doi.org/10.1016/j.neucom.2017.04.070).

Fit scaler/forest on the first 3,404 points (15%); test the remaining 19,291 points (85%).
The training prefix is not filtered using anomaly labels. The reference threshold uses
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
