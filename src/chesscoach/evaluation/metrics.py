"""Pure evaluation metrics (no database, no I/O)."""

from collections import Counter
from collections.abc import Iterable


def prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    # F1 is undefined only with no gold and no predictions. A label that is only ever
    # predicted (or only ever missed) scores 0, so spurious labels lower macro-F1.
    if tp + fp + fn == 0:
        f1 = None
    elif tp == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": _r(precision),
        "recall": _r(recall),
        "f1": _r(f1),
    }


def multilabel_report(pairs: Iterable[tuple[set[str], set[str]]]) -> dict:
    """Per-label and macro metrics for multi-label items given (gold, predicted) sets.

    Macro-F1 averages over labels with at least one gold OR predicted instance; labels
    whose F1 is undefined (no gold and no prediction) are excluded.
    """
    tp, fp, fn = Counter(), Counter(), Counter()
    n = 0
    for gold, pred in pairs:
        n += 1
        for label in gold & pred:
            tp[label] += 1
        for label in pred - gold:
            fp[label] += 1
        for label in gold - pred:
            fn[label] += 1
    labels = sorted(set(tp) | set(fp) | set(fn))
    per_label = {label: prf(tp[label], fp[label], fn[label]) for label in labels}
    f1s = [v["f1"] for v in per_label.values() if v["f1"] is not None]
    micro = prf(sum(tp.values()), sum(fp.values()), sum(fn.values()))
    return {
        "items": n,
        "labels": per_label,
        "macro_f1": _r(sum(f1s) / len(f1s)) if f1s else None,
        "micro": micro,
    }


def binary_report(pairs: Iterable[tuple[bool, bool]]) -> dict:
    tp = fp = fn = tn = 0
    for gold, pred in pairs:
        if gold and pred:
            tp += 1
        elif pred:
            fp += 1
        elif gold:
            fn += 1
        else:
            tn += 1
    return {**prf(tp, fp, fn), "tn": tn}


def precision_at_k(predicted: list[str], relevant: set[str], k: int) -> float | None:
    """Fraction of the top-k predictions that are relevant (None if nothing predicted)."""
    top = predicted[:k]
    return _r(sum(1 for p in top if p in relevant) / len(top)) if top else None


def mean(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return _r(sum(vals) / len(vals)) if vals else None


def _r(x: float | None) -> float | None:
    return round(x, 4) if x is not None else None
