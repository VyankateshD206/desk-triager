import numpy as np
import pytest

from evals.detection import metrics, public_series, synthetic


def test_alarm_episodes_and_point_errors_are_separate():
    scores = metrics([0, 0, 1, 1, 0, 0], [1, 1, 1, 0, 0, 1], 60)
    assert scores["false_positive_points"] == 3
    assert scores["false_alarm_episodes"] == 2
    assert scores["point_precision"] == 0.25
    assert scores["point_recall"] == 0.5
    assert scores["windows_detected"] == 1
    assert scores["false_alarm_episodes_per_service_hour"] == 20


def test_no_predictions_are_not_perfect_precision():
    assert metrics([0, 1], [0, 0], 1)["point_precision"] is None
    assert metrics([0, 0], [0, 0], 1)["point_recall"] is None
    with pytest.raises(ValueError):
        metrics([], [], 1)
    with pytest.raises(ValueError):
        metrics([1], [1, 0], 1)


def test_seeded_detection_is_reproducible_and_exposes_false_alarms():
    first, second = synthetic(2), synthetic(2)
    assert first == second
    assert first["summaries"]["rules"]["service_hours"] == 6
    assert (
        first["summaries"]["combined"]["point_precision"]
        < first["summaries"]["rules"]["point_precision"]
    )
    assert {e["kind"] for row in first["rows"] for e in row["episodes"]} == {
        "tick_gap",
        "silence",
        "rate_limit",
        "latency",
        "nav_mismatch",
        "ml_degradation",
    }


def test_public_evaluation_is_past_only_and_reports_real_errors():
    report = public_series()
    assert report["train_samples"] == 3404
    assert report["results"]["forest"]["samples"] == 19291
    assert report["official_nab_score"] is None
    assert report["results"]["forest"]["false_positive_points"] > 0
    assert report["results"]["forest"]["point_recall"] < 1
    assert np.isfinite(report["seconds_per_sample"])
