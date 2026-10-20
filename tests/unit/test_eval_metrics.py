import pytest

from chesscoach.evaluation.metrics import (
    binary_report,
    mean,
    multilabel_report,
    precision_at_k,
    prf,
)


def test_prf_handles_empty_denominators():
    assert prf(0, 0, 0) == {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "precision": None,
        "recall": None,
        "f1": None,
    }
    assert prf(0, 2, 0)["precision"] == 0.0 and prf(0, 2, 0)["recall"] is None
    assert prf(3, 1, 1)["f1"] == pytest.approx(0.75)


def test_multilabel_report_per_label_and_macro():
    pairs = [
        ({"forks"}, {"forks"}),  # TP forks
        ({"forks"}, set()),  # FN forks
        (set(), {"hanging"}),  # FP hanging
        ({"mate", "forks"}, {"mate"}),  # TP mate, FN forks
        (set(), set()),  # correct "no label"
    ]
    r = multilabel_report(pairs)
    assert r["items"] == 5
    assert r["labels"]["forks"] == {
        "tp": 1,
        "fp": 0,
        "fn": 2,
        "precision": 1.0,
        "recall": 0.3333,
        "f1": 0.5,
    }
    assert r["labels"]["hanging"]["precision"] == 0.0
    assert r["labels"]["mate"]["f1"] == 1.0
    assert r["macro_f1"] == pytest.approx((0.5 + 0.0 + 1.0) / 3, abs=1e-4)


def test_binary_report():
    r = binary_report([(True, True), (True, False), (False, True), (False, False)])
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 1, 1, 1)
    assert r["precision"] == 0.5 and r["recall"] == 0.5


def test_precision_at_k_and_mean():
    assert precision_at_k(["a", "b", "c"], {"a", "c"}, 2) == 0.5
    assert precision_at_k([], {"a"}, 3) is None
    assert precision_at_k(["a"], {"a"}, 3) == 1.0  # fewer than k predictions
    assert mean([1.0, None, 0.0]) == 0.5 and mean([None]) is None
