"""Chronological detection measurements; NAB adaptation is not an official NAB score."""

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from triager.detector import Detector

DATA = Path(__file__).parent / "data/nab"


def metrics(labels, predictions, seconds_per_sample):
    labels, predictions = np.asarray(labels, bool), np.asarray(predictions, bool)
    if len(labels) != len(predictions) or not len(labels) or seconds_per_sample <= 0:
        raise ValueError("Aligned, nonempty samples and positive cadence required")
    tp = int(np.sum(labels & predictions))
    fp = int(np.sum(~labels & predictions))
    fn = int(np.sum(labels & ~predictions))
    false = predictions & ~labels
    episodes = int(np.sum(false & ~np.r_[False, false[:-1]]))
    starts = np.flatnonzero(labels & ~np.r_[False, labels[:-1]])
    ends = np.flatnonzero(labels & ~np.r_[labels[1:], False]) + 1
    return {
        "samples": len(labels),
        "true_positive_points": tp,
        "false_positive_points": fp,
        "false_negative_points": fn,
        "point_precision": tp / (tp + fp) if tp + fp else None,
        "point_recall": tp / (tp + fn) if tp + fn else None,
        "normal_point_false_positive_rate": fp / int(np.sum(~labels)) if np.any(~labels) else None,
        "anomaly_windows": len(starts),
        "windows_detected": sum(bool(predictions[a:b].any()) for a, b in zip(starts, ends)),
        "false_alarm_episodes": episodes,
        "service_hours": len(labels) * seconds_per_sample / 3600,
        "false_alarm_episodes_per_service_hour": episodes
        / (len(labels) * seconds_per_sample / 3600),
    }


def synthetic(seeds=20):
    detector, rows = Detector(), []
    for seed in range(seeds):
        rng = np.random.default_rng(1000 + seed)  # Disjoint from production training seed 42.
        for service in ("market-feed", "execution-gateway", "portfolio-ledger"):
            n = 3600
            # Independent service regimes; deliberately not sampled from Detector's fit distribution.
            load = np.sin(np.arange(n) / 210) + rng.normal(0, 0.3, n)
            values = np.column_stack(
                (
                    90 + rng.uniform(-12, 25) + load * 8 + rng.normal(0, 12, n),
                    rng.lognormal(0.1, 0.35, n),
                    np.maximum(0, 15 + load * 3 + rng.normal(0, 5, n)),
                    np.zeros(n),
                )
            )
            labels, rules, missing = np.zeros(n, bool), np.zeros(n, bool), np.zeros(n, bool)
            tick_age, nav_difference = np.zeros(n), np.zeros(n, bool)
            episodes = []
            kinds = {
                "market-feed": ("tick_gap", "silence"),
                "execution-gateway": ("rate_limit", "latency", "ml_degradation"),
                "portfolio-ledger": ("nav_mismatch",),
            }[service]
            for index, kind in enumerate(kinds):
                start = 800 + index * 800 + int(rng.integers(-80, 80))
                end = start + int(rng.integers(30, 100))
                labels[start:end] = True
                episodes.append({"kind": kind, "start": start, "end": end})
                if kind == "ml_degradation":
                    values[start:end, 1:3] += [1.4, 14]
                if kind == "latency":
                    values[start:end, 0] = rng.uniform(400, 900)
                if kind == "rate_limit":
                    values[start:end, 3] = 1
                if kind == "tick_gap":
                    tick_age[start:end] = 9000
                if kind == "nav_mismatch":
                    nav_difference[start:end] = True
                if kind == "silence":
                    missing[start:end] = True
            absent_for = 0
            for index in range(n):
                absent_for = absent_for + 1 if missing[index] else 0
                if missing[index]:
                    rules[index] = absent_for > 8  # Receipt-time watchdog, not an oracle label.
                else:
                    event = SimpleNamespace(
                        service=service,
                        tick_age_ms=tick_age[index],
                        reject_code="429" if values[index, 3] else "OK",
                        fill_latency_ms=values[index, 0],
                    )
                    rules[index] = bool(detector.rule_kinds(event, nav_difference[index]))
            forest = detector.model.decision_function(detector.scaler.transform(values)) < 0
            forest[missing] = False  # A sample-only model cannot score absent telemetry.
            for mode, predicted in (
                ("rules", rules),
                ("forest", forest),
                ("combined", rules | forest),
            ):
                rows.append(
                    {
                        "seed": seed,
                        "service": service,
                        "mode": mode,
                        "episodes": episodes,
                        **metrics(labels, predicted, 1),
                    }
                )
    summaries = {}
    for mode in ("rules", "forest", "combined"):
        group = [r for r in rows if r["mode"] == mode]
        tp, fp, fn = (
            sum(r[key] for r in group)
            for key in ("true_positive_points", "false_positive_points", "false_negative_points")
        )
        hours = sum(r["service_hours"] for r in group)
        summaries[mode] = {
            "point_precision": tp / (tp + fp) if tp + fp else None,
            "point_recall": tp / (tp + fn),
            "service_hours": hours,
            "false_alarm_episodes_per_service_hour": sum(r["false_alarm_episodes"] for r in group)
            / hours,
        }
    return {
        "training": "Frozen production forest; synthetic baseline seed 42",
        "test": "Independent shifted service regimes; synthetic evidence only",
        "seeds": seeds,
        "summaries": summaries,
        "rows": rows,
    }


def public_series():
    manifest = json.loads((DATA / "manifest.json").read_text())
    for name, source in manifest["files"].items():
        if hashlib.sha256((DATA / name).read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("NAB input checksum mismatch")
    with (DATA / "machine_temperature_system_failure.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    timestamps = [datetime.fromisoformat(row["timestamp"]) for row in rows]
    values = np.array([float(row["value"]) for row in rows])[:, None]
    windows = json.loads((DATA / "combined_windows.json").read_text())[
        "realKnownCause/machine_temperature_system_failure.csv"
    ]
    labels = np.array(
        [
            any(datetime.fromisoformat(a) <= t <= datetime.fromisoformat(b) for a, b in windows)
            for t in timestamps
        ]
    )
    split = int(0.15 * len(values))
    scaler = StandardScaler().fit(values[:split])
    model = IsolationForest(n_estimators=80, contamination=0.01, random_state=42)
    model.fit(scaler.transform(values[:split]))
    median = np.median(values[:split])
    mad = max(float(np.median(np.abs(values[:split] - median))) * 1.4826, 1e-9)
    forest = model.decision_function(scaler.transform(values[split:])) < 0
    threshold = np.abs(values[split:, 0] - median) > 6 * mad
    cadence = float(np.median(np.diff(np.array(timestamps, dtype="datetime64[s]")).astype(float)))
    return {
        "dataset": manifest,
        "adaptation": "Scalar temperature forest, not the four-feature trading model",
        "protocol": "First 15% train, final 85% test; no label filtering or threshold tuning",
        "train_samples": split,
        "train_anomaly_points": int(labels[:split].sum()),
        "test_start": timestamps[split].isoformat(),
        "seconds_per_sample": cadence,
        "official_nab_score": None,
        "results": {
            mode: metrics(labels[split:], predicted, cadence)
            for mode, predicted in (
                ("robust_threshold", threshold),
                ("forest", forest),
                ("combined", threshold | forest),
            )
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("/tmp/detection.json"))
    args = parser.parse_args()
    if not 1 <= args.seeds <= 100:
        parser.error("Seeds must be 1..100")
    result = {"version": "detection-1", "synthetic": synthetic(args.seeds), "nab": public_series()}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {"synthetic": result["synthetic"]["summaries"], "nab": result["nab"]["results"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
