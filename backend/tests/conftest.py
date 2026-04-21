"""
Pytest configuration and shared fixtures for all tests.
"""

import sys
from pathlib import Path

import pytest

# Ensure app module is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ml.synthetic_data import generate_dataset
from app.services.feature_extractor import FEATURE_NAMES, to_vector, rules_features

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier


@pytest.fixture(scope="session")
def test_model_path(tmp_path_factory):
    """
    Train a tiny model on 200 synthetic samples for fast testing.

    Session-scoped so it's created once per test session.
    """
    tmp_dir = tmp_path_factory.mktemp("models")
    model_path = tmp_dir / "test_model.joblib"

    dataset = generate_dataset(n_samples=200, seed=42)
    X = np.asarray(
        [to_vector(rules_features(vm)) for vm, _ in dataset],
        dtype=float
    )
    y = np.asarray([grade for _, grade in dataset])

    model = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42)
    model.fit(X, y)

    payload = {
        "model": model,
        "feature_names": list(FEATURE_NAMES),
        "labels": ("COMPATIBLE", "PARTIAL", "INCOMPATIBLE"),
        "sklearn_version": "1.5.2",
        "model_kind": "RandomForest",
    }
    joblib.dump(payload, model_path)
    return model_path
