"""Read the centered 0..15 word, never the nearby Tuarim percentage."""

import cv2
import numpy as np
from zipfile import BadZipFile

from .. import paths

SHAPE = (23, 28)
MIN_SCORE = 0.88
MIN_MARGIN = 0.10


def prepare(region):
    if (not isinstance(region, np.ndarray) or region.dtype != np.uint8
            or region.ndim != 3 or region.shape[2] != 3
            or region.shape[0] < 16 or region.shape[1] < 19
            or not 1.1 <= region.shape[1] / region.shape[0] <= 1.35):
        return None
    normalized = cv2.resize(region, SHAPE[::-1], interpolation=cv2.INTER_AREA)
    ink = (normalized[4:19, 3:25].min(axis=2) >= 150).astype(np.float32)
    if (not ink.any() or ink[0].any() or ink[-1].any()
            or ink[:, 0].any() or ink[:, -1].any()):
        return None
    return ink


def _normalize(ink):
    vector = ink.ravel() - ink.mean()
    return vector / max(float(vector.std()), 1e-6)


def _load():
    try:
        with np.load(paths.detect_templates_dir() / "dorcha" / "refs.npz", allow_pickle=False) as data:
            refs, labels = data["refs"], data["labels"]
            if (refs.ndim != 2 or labels.ndim != 1 or labels.dtype.kind not in "iu"
                    or refs.dtype.kind not in "fiu" or refs.shape[1] != 330 or len(refs) != len(labels)
                    or set(labels.tolist()) != set(range(16)) or not np.isfinite(refs).all()):
                return None
            return refs.astype(np.float32), labels.astype(np.int64)
    except (OSError, ValueError, KeyError, EOFError, BadZipFile):
        return None


_REFS = _load()


def read_dorcha(region, diagnostics=None):
    trace = diagnostics if diagnostics is not None else {}
    ink = prepare(region)
    if ink is None or _REFS is None:
        trace["rejection"] = "invalid_input" if ink is None else "missing_references"
        return None
    refs, labels = _REFS
    scores = refs @ _normalize(ink) / ink.size
    by_value = sorted(((float(scores[labels == value].max()), value) for value in range(16)), reverse=True)
    score, value = by_value[0]
    margin = score - by_value[1][0]
    trace.update(score=score, margin=margin, candidate=value, min_score=MIN_SCORE, min_margin=MIN_MARGIN)
    if score < MIN_SCORE or margin < MIN_MARGIN:
        trace["rejection"] = "uncertain_word"
        return None
    return value
