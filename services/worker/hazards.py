"""
Stage 9 (production wiring): predict hazard categories from a narrative
using the model classifier.py trained and saved to
services/worker/model/hazard_model.joblib.

parser.py already fills `hazards` with source='nasa' rows straight from
NASA's own Anomaly.* coding - that part needs no model. This file adds the
source='model' rows: what our own classifier thinks, given only the
narrative text, exactly the way it would have to guess on a brand-new
report with no NASA codes at all.

Kept separate from parser.py on purpose: parsing a PDF should never depend
on whether a trained model file happens to exist on disk. If the model file
is missing (e.g. classifier.py hasn't been run yet on a fresh checkout),
predict_hazards() returns an empty list rather than raising - a document
still gets its 'nasa' hazards and its narrative either way.
"""

from __future__ import annotations

import joblib

from services.worker.classifier import MODEL_PATH

CONFIDENCE_THRESHOLD = 0.5

_model_cache: dict | None = None


def _load_model() -> dict | None:
    global _model_cache
    if _model_cache is None:
        try:
            _model_cache = joblib.load(MODEL_PATH)
        except FileNotFoundError:
            _model_cache = {}
    return _model_cache or None


def predict_hazards(narrative: str) -> list[dict]:
    """Returns [{"code", "confidence", "source": "model"}, ...] for every
    label the model is at least CONFIDENCE_THRESHOLD sure of. Empty list if
    no model has been trained yet, or the narrative is empty."""
    model = _load_model()
    if model is None or not narrative.strip():
        return []

    from services.worker.parser import hazard_code  # local import: avoid a cycle at module load

    X = model["vectorizer"].transform([narrative])
    proba = model["classifier"].predict_proba(X)[0]  # one row, len == len(labels)

    hazards = []
    for label, confidence in zip(model["labels"], proba, strict=False):
        if confidence >= CONFIDENCE_THRESHOLD:
            hazards.append(
                {
                    "code": hazard_code(label),
                    "confidence": round(float(confidence), 3),
                    "source": "model",
                }
            )
    return hazards
