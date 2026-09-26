"""Train+evaluate a small urgency classifier from the synthetic fixtures.

TF-IDF over the description, plus days_until_due as a numeric feature, into
logistic regression. See hub/models.classify_urgency for the rule-based
version this is meant to eventually replace once there's real (non-synthetic)
labeled data - see the Agent board discussion (#15).

Usage: uv run python scripts/train_urgency_classifier.py
"""
import json
from pathlib import Path

import joblib
from scipy.sparse import hstack, csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report

FIXTURES = Path(__file__).parent.parent / "fixtures"
# Title-only: what's actually available at inference time (a bare Canvas/
# PrairieLearn/syllabus title, no description or stated weight). See the
# Agent board (#15): the rich-description set below overstates accuracy.
TRAIN_PATH = FIXTURES / "synthetic_urgency_titles_train.jsonl"
TEST_PATH = FIXTURES / "synthetic_urgency_titles_test.jsonl"
MODEL_PATH = FIXTURES / "urgency_classifier.joblib"


def load(path: Path) -> tuple[list[str], list[float], list[str]]:
    texts, days, labels = [], [], []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        texts.append(row.get("description") or row["title"])
        days.append(row["days_until_due"])
        labels.append(row["urgency"])
    return texts, days, labels


def features(vectorizer: TfidfVectorizer, descriptions: list[str], days: list[float], fit: bool):
    text_matrix = vectorizer.fit_transform(descriptions) if fit else vectorizer.transform(descriptions)
    day_matrix = csr_matrix([[d] for d in days])
    return hstack([text_matrix, day_matrix])


def main():
    train_desc, train_days, train_labels = load(TRAIN_PATH)

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2)
    X_train = features(vectorizer, train_desc, train_days, fit=True)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, train_labels)

    joblib.dump({"vectorizer": vectorizer, "model": model}, MODEL_PATH)
    print(f"Trained on {len(train_labels)} rows, saved to {MODEL_PATH}")

    if TEST_PATH.exists():
        test_desc, test_days, test_labels = load(TEST_PATH)
        X_test = features(vectorizer, test_desc, test_days, fit=False)
        predictions = model.predict(X_test)
        print(f"\nHeld-out test set ({len(test_labels)} rows):")
        print(classification_report(test_labels, predictions, zero_division=0))
    else:
        print(f"\nNo test set at {TEST_PATH} yet - skipping evaluation.")


if __name__ == "__main__":
    main()
