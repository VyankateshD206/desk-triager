import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

FEATURES = ("fill_latency_ms", "slippage_bps", "heartbeat_jitter_ms", "reject")


class Detector:
    """Frozen synthetic healthy baseline. Replace with validated desk history before real use."""

    def __init__(self):
        rng = np.random.default_rng(42)
        baseline = np.column_stack(
            [
                rng.normal(85, 15, 2000),
                rng.normal(1.2, 0.4, 2000),
                np.abs(rng.normal(12, 4, 2000)),
                np.zeros(2000),
            ]
        )
        self.scaler = StandardScaler().fit(baseline)
        self.model = IsolationForest(n_estimators=80, contamination=0.01, random_state=42)
        self.model.fit(self.scaler.transform(baseline))

    def score(self, event):
        values = [
            [
                event.fill_latency_ms,
                event.slippage_bps,
                event.heartbeat_jitter_ms,
                float(event.reject_code != "OK"),
            ]
        ]
        # Negative margin indicates an outlier; this is not a probability.
        return float(self.model.decision_function(self.scaler.transform(values))[0])

    def detect(self, event, nav_difference=False):
        score = self.score(event)
        kinds = []
        if event.tick_age_ms > 5000:
            kinds.append("tick_gap")
        if event.reject_code == "429":
            kinds.append("rate_limit")
        if event.fill_latency_ms > 350:
            kinds.append("latency")
        if event.service == "portfolio-ledger" and nav_difference:
            kinds.append("nav_mismatch")
        if score < 0 and not kinds:
            kinds.append("ml_degradation")
        return score, kinds


RUNBOOKS = {
    "tick_gap": (
        "Market data is stale. Inspect heartbeat and transport connectivity.",
        "reconnect_feed",
    ),
    "rate_limit": (
        "Exchange returned HTTP 429. Apply cooldown and bounded retry pacing.",
        "enable_backoff",
    ),
    "nav_mismatch": (
        "Local NAV differs from simulated exchange snapshot. Review balances before resync.",
        "resync_ledger",
    ),
    "latency": (
        "Fill latency breached 350 ms. Inspect gateway backlog and resync simulated order state.",
        "resync_orders",
    ),
    "ml_degradation": (
        "Telemetry lies outside the synthetic healthy baseline. Investigate feature drift.",
        "inspect_only",
    ),
}
