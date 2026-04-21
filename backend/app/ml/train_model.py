"""
Train the compatibility classifier on the synthetic dataset.

Usage
-----
Dry run (cross-validation + confusion matrix, no artifact written):
    python -m app.ml.train_model

Serialize to backend/app/ml/artifacts/compatibility_model.joblib:
    python -m app.ml.train_model --save

Notes
-----
- joblib pickles are NOT portable across sklearn minor versions. Retrain
  whenever ``requirements.txt`` bumps scikit-learn.
- Features come from :func:`app.services.feature_extractor.rules_features`
  (single source of truth).  Changing FEATURE_NAMES requires retraining.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Tuple

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split

from app.ml.synthetic_data import generate_dataset
from app.services.feature_extractor import FEATURE_NAMES, rules_features, to_vector

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "compatibility_model.joblib"

LABELS = ("COMPATIBLE", "PARTIAL", "INCOMPATIBLE")


def _vectorise(dataset: List[Tuple[dict, str]]) -> Tuple[np.ndarray, np.ndarray]:
    X = np.asarray([to_vector(rules_features(vm)) for vm, _ in dataset], dtype=float)
    y = np.asarray([grade for _, grade in dataset])
    return X, y


def _evaluate(model, X: np.ndarray, y: np.ndarray, label: str) -> float:
    """Run 5-fold stratified CV and return mean accuracy."""
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(model, X, y, cv=cv, scoring="accuracy", n_jobs=-1)
    print(f"\n[{label}] 5-fold CV accuracy: "
          f"{scores.mean():.4f} ± {scores.std():.4f}")
    print(f"[{label}] fold scores: {[f'{s:.4f}' for s in scores]}")
    return float(scores.mean())


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true",
                        help="Serialize the winning model to artifacts/compatibility_model.joblib")
    parser.add_argument("--n-samples", type=int, default=1800)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    print(f"scikit-learn {sklearn.__version__} | joblib {joblib.__version__}")
    print(f"Feature space: {len(FEATURE_NAMES)} columns")

    dataset = generate_dataset(n_samples=args.n_samples, seed=args.seed)
    print(f"Dataset: {len(dataset)} samples")

    X, y = _vectorise(dataset)

    # Hold out 20 % for the final confusion matrix.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=args.seed, stratify=y
    )

    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        random_state=args.seed,
        n_jobs=-1,
    )
    gb = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=3,
        random_state=args.seed,
    )

    rf_cv = _evaluate(rf, X_train, y_train, "RandomForest")
    gb_cv = _evaluate(gb, X_train, y_train, "GradientBoosting")

    # Tie-breaker: prefer RandomForest (faster predict, same quality on 6 cats).
    if rf_cv >= gb_cv:
        winner_name, winner = "RandomForest", rf
    else:
        winner_name, winner = "GradientBoosting", gb

    print(f"\n>>> Winner: {winner_name} (CV acc = "
          f"{max(rf_cv, gb_cv):.4f})")

    winner.fit(X_train, y_train)

    # Held-out evaluation
    y_pred = winner.predict(X_test)
    print("\n=== Held-out classification report ===")
    print(classification_report(y_test, y_pred, labels=list(LABELS), digits=4))

    print("=== Confusion matrix (rows = true, cols = predicted) ===")
    cm = confusion_matrix(y_test, y_pred, labels=list(LABELS))
    header = "           " + "  ".join(f"{lab:>12}" for lab in LABELS)
    print(header)
    for i, lab in enumerate(LABELS):
        row = "  ".join(f"{cm[i, j]:>12d}" for j in range(len(LABELS)))
        print(f"{lab:>11}  {row}")

    if args.save:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        # Refit on the full dataset before serialising — the held-out split
        # was only used to report honest metrics.
        winner.fit(X, y)
        payload = {
            "model": winner,
            "feature_names": list(FEATURE_NAMES),
            "labels": list(LABELS),
            "sklearn_version": sklearn.__version__,
            "model_kind": winner_name,
        }
        joblib.dump(payload, ARTIFACT_PATH)
        size_kb = os.path.getsize(ARTIFACT_PATH) / 1024
        print(f"\nArtifact written: {ARTIFACT_PATH} ({size_kb:.1f} KB)")
    else:
        print("\n(dry run — pass --save to serialize the artifact)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
