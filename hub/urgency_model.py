"""Loads the trained urgency classifier (scripts/train_urgency_classifier.py)
so the app can call it like classify_urgency() - same input, same Urgency
labels. Kept separate from hub/models.py: the rule-based classify_urgency()
has no dependency beyond stdlib, and this one needs scikit-learn/joblib at
import time.

Stays on `jacky` for now per the Agent board (#15)/#27 decision: MVP ranking
is due-date, classify_urgency() is what's wired into the live demo. This
module exists so the trained model is actually runnable, not just sitting in
fixtures/ - flip demo.py's toggle to compare it live.
"""
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import joblib
from scipy.sparse import hstack, csr_matrix

from hub.models import Urgency

MODEL_PATH = Path(__file__).parent.parent / "fixtures" / "urgency_classifier.joblib"


@lru_cache(maxsize=1)
def _load():
    bundle = joblib.load(MODEL_PATH)
    return bundle["vectorizer"], bundle["model"]


def predict_urgency(title: str, due: datetime | None, now: datetime | None = None) -> Urgency:
    """Same signature/labels as hub.models.classify_urgency, but from the
    trained model instead of the keyword heuristic. due=None -> "low",
    matching classify_urgency's behavior (the model was never trained on
    a missing due date)."""
    if due is None:
        return "low"
    now = now or datetime.now(due.tzinfo)
    days_until_due = (due - now).total_seconds() / 86400
    vectorizer, model = _load()
    X = hstack([vectorizer.transform([title]), csr_matrix([[days_until_due]])])
    return model.predict(X)[0]
