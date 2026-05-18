"""
Analyzer service — compatibility classification orchestration.

Hybrid engine: ML model + rules fallback. Single source of truth for
feature extraction (:mod:`app.services.feature_extractor`).
"""

from __future__ import annotations

import json
import logging
import threading
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import joblib
import numpy as np
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.virtual_machine import VirtualMachine, VMStatus, CompatibilityStatus
from app.services.compatibility_rules import aggregate, evaluate_all
from app.services.feature_extractor import FEATURE_NAMES, rules_features, to_vector

logger = logging.getLogger(__name__)

_ARTIFACT_PATH = Path(__file__).parent.parent / "ml" / "artifacts" / "compatibility_model.joblib"

_GRADE_MAP = {
    "COMPATIBLE": CompatibilityStatus.COMPATIBLE,
    "PARTIAL": CompatibilityStatus.PARTIAL,
    "INCOMPATIBLE": CompatibilityStatus.INCOMPATIBLE,
}
# Audit C-06 : promouvoir le statut de cycle de vie de la VM à partir du
# grade. Sans ça `can_migrate` reste toujours False (statut figé à
# DISCOVERED) et POST /migrations rejette toute VM.
_STATUS_MAP = {
    "COMPATIBLE": VMStatus.COMPATIBLE,
    "PARTIAL": VMStatus.PARTIAL,
    "INCOMPATIBLE": VMStatus.INCOMPATIBLE,
}


# ---------------------------------------------------------------------------
# Process-level model cache (Audit E14)
#
# The joblib artifact is ~10 MB; deserialising it on every AnalyzerService()
# instantiation wasted CPU and RAM (every request handler builds one). The
# model is immutable at runtime, so it is loaded once per process and shared.
# A sentinel distinguishes "not yet attempted" from "attempted, no model"
# (degraded mode) — the latter must not retrigger a disk load on every call.
# ---------------------------------------------------------------------------
_MODEL_NOT_LOADED = object()
_model_cache: Any = _MODEL_NOT_LOADED
_model_lock = threading.Lock()


def _load_model_artifact() -> Optional[Any]:
    """Load + validate the joblib artifact. Returns the estimator or None.

    Returns ``None`` on any failure (missing file, sklearn version skew,
    feature-space mismatch) — the caller then runs the rules fallback.
    """
    if not _ARTIFACT_PATH.exists():
        logger.warning(
            f"Model artifact not found: {_ARTIFACT_PATH} — will use rules fallback"
        )
        return None

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("error", category=UserWarning)
            payload = joblib.load(_ARTIFACT_PATH)
        stored_features = payload.get("feature_names") or []
        if list(stored_features) != list(FEATURE_NAMES):
            logger.warning(
                "Model feature space mismatch (artifact=%d cols, runtime=%d cols) — "
                "retrain via `python -m app.ml.train_model --save`; falling back to rules",
                len(stored_features), len(FEATURE_NAMES),
            )
            return None
        model = payload.get("model")
        logger.info(f"Model loaded: {payload.get('model_kind', 'unknown')} "
                    f"(sklearn {payload.get('sklearn_version', 'unknown')})")
        return model
    except UserWarning as e:
        logger.warning(f"sklearn InconsistentVersionWarning: {e} — using rules fallback")
        return None
    except Exception as e:  # NOSONAR — any load failure must degrade to rules
        logger.warning(f"Failed to load model: {e} — using rules fallback")
        return None


def _get_cached_model() -> Optional[Any]:
    """Return the process-wide model, loading it once (Audit E14)."""
    global _model_cache
    if _model_cache is not _MODEL_NOT_LOADED:
        return _model_cache
    with _model_lock:
        if _model_cache is _MODEL_NOT_LOADED:
            _model_cache = _load_model_artifact()
        return _model_cache


def reset_model_cache() -> None:
    """Reset the process-level model cache. Used by tests."""
    global _model_cache
    with _model_lock:
        _model_cache = _MODEL_NOT_LOADED


class AnalyzerService:
    """Orchestrate VM compatibility analysis."""

    def __init__(self):
        self.feature_names = list(FEATURE_NAMES)
        self.threshold = settings.ANALYZER_CONFIDENCE_THRESHOLD
        # Audit E14 — share the process-wide model instead of a per-instance
        # joblib load. Stays a normal attribute so tests / callers can still
        # override it (e.g. force degraded mode with svc.model = None).
        self.model = _get_cached_model()

    def ml_status(self) -> Dict[str, Any]:
        """Report whether the analyzer runs on the ML model or the rules
        fallback (Audit E15 — degraded mode must be observable, surfaced by
        ``GET /health``).

        Returns a dict with:
          - ``degraded``  (bool): True when no ML model is loaded.
          - ``engine``    (str):  "rules" (degraded) or "model".
          - ``model_loaded`` (bool): convenience inverse of ``degraded``.
        """
        loaded = self.model is not None
        return {
            "degraded": not loaded,
            "engine": "model" if loaded else "rules",
            "model_loaded": loaded,
        }

    def _decide_grade(
        self,
        vm_id: int,
        vm_dict: Dict[str, Any],
        rules_agg: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Decide the compatibility grade — ML model or rules fallback.

        Extracted from ``analyze_vm`` — Audit S3776. Behaviour is unchanged.

        Returns a dict: ``grade``, ``engine`` ("model"/"rules"),
        ``confidence`` (float), ``model_grade`` (str|None),
        ``override_reason`` (str|None).
        """
        engine = "rules"
        confidence = 0.0
        model_grade: Optional[str] = None
        override_reason: Optional[str] = None

        if self.model:
            features = to_vector(rules_features(vm_dict))
            proba = self.model.predict_proba([features])[0]
            pred_idx = int(np.argmax(proba))
            confidence = float(proba[pred_idx])
            # Audit C-11 : l'ordre des classes vient du modèle lui-même
            # (scikit-learn trie les labels alphabétiquement) — surtout
            # pas d'un tuple codé en dur, qui inverserait PARTIAL et
            # INCOMPATIBLE.
            model_grade = str(self.model.classes_[pred_idx])
            if confidence >= self.threshold:
                engine = "model"

        if engine == "model":
            # Sanity guard (Fix B1): blockers are deterministic, hard
            # requirements (unsupported OS, ISO disk, <512MB RAM). The model
            # may refine grades but must not contradict the blocker truth —
            # in either direction. Defer to rules whenever the model and
            # rules disagree on the presence of a blocker.
            rules_has_blockers = bool(rules_agg["blockers"])
            model_says_incompatible = model_grade == "INCOMPATIBLE"
            if model_says_incompatible != rules_has_blockers:
                override_reason = (
                    f"model predicted {model_grade} (conf={confidence:.2f}) but "
                    f"rules report {len(rules_agg['blockers'])} blocker(s) — "
                    "deferring to rules"
                )
                logger.info(f"VM {vm_id}: {override_reason}")
                engine = "rules"
                grade = rules_agg["grade"]
            else:
                grade = model_grade
        else:
            grade = rules_agg["grade"]

        return {
            "grade": grade,
            "engine": engine,
            "confidence": confidence,
            "model_grade": model_grade,
            "override_reason": override_reason,
        }

    def analyze_vm(self, db: Session, vm_id: int, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        Analyze a VM's compatibility. Lock the row for update to prevent
        concurrent clobbering.

        Args:
            db: Database session.
            vm_id: VM id to analyze.
            force: Re-analyze even if already classified (not UNKNOWN).

        Returns:
            Updated VirtualMachine row dict, or None if VM not found.

        Raises:
            Logs errors but does not raise.
        """
        try:
            # Row lock: SELECT ... FOR UPDATE (pessimistic lock)
            vm = (
                db.query(VirtualMachine)
                .filter(VirtualMachine.id == vm_id)
                .with_for_update()
                .first()
            )

            if not vm:
                logger.warning(f"VM {vm_id} not found")
                return None

            # Skip if already classified (unless force=true)
            if not force and vm.compatibility_status != CompatibilityStatus.UNKNOWN:
                logger.debug(
                    f"VM {vm_id} already classified as {vm.compatibility_status.value} — skipping"
                )
                return vm.to_dict()

            vm.status = VMStatus.ANALYZING
            db.commit()

            logger.info(f"Analyzing VM {vm_id} ({vm.name})")

            vm_dict = {
                "id": vm.id,
                "cpu_cores": vm.cpu_cores,
                "memory_mb": vm.memory_mb,
                "disk_gb": vm.disk_gb,
                "os_type": vm.os_type.value if vm.os_type else "unknown",
                "os_name": vm.os_name,
                "os_version": vm.os_version,
                "hypervisor_type": vm.source_hypervisor.type.value if vm.source_hypervisor else "unknown",
                "custom_metadata": vm.custom_metadata,
            }

            rules = evaluate_all(vm_dict)
            rules_agg = aggregate(rules)

            # Decide: model or rules? Extracted to a helper (Audit S3776).
            decision = self._decide_grade(vm_id, vm_dict, rules_agg)
            grade = decision["grade"]

            details: Dict[str, Any] = {
                "score": rules_agg["score"],
                "grade": grade,
                "engine": decision["engine"],
                "confidence": decision["confidence"] if self.model else None,
                "model_grade": decision["model_grade"],
                "override_reason": decision["override_reason"],
                "rules": rules,
                "blockers": rules_agg["blockers"],
                "warnings": rules_agg["warnings"],
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }

            vm.compatibility_status = _GRADE_MAP[grade]
            vm.compatibility_details = details
            vm.status = _STATUS_MAP[grade]

            db.commit()

            logger.info(
                f"VM {vm_id} analyzed: {grade} "
                f"(engine={decision['engine']}, score={details['score']})"
            )

            return vm.to_dict()

        except Exception as e:
            logger.error(f"Error analyzing VM {vm_id}: {e}", exc_info=True)
            try:
                vm = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id).first()
                if vm and vm.status == VMStatus.ANALYZING:
                    vm.status = VMStatus.DISCOVERED
                    db.commit()
            except Exception as rollback_err:
                logger.error(f"Failed to rollback status: {rollback_err}")
            return None

    def analyze_batch(
        self, db: Session, vm_ids: list[int], force: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze multiple VMs synchronously. Cap at 20 to prevent long-running
        requests.

        Returns:
            Dict with keys: total, analyzed, failed, results (list of VM dicts).
        """
        if len(vm_ids) > 20:
            logger.warning(f"Batch cap exceeded: {len(vm_ids)} > 20")

        results = []
        failed = 0

        for vm_id in vm_ids[:20]:
            try:
                result = self.analyze_vm(db, vm_id, force=force)
                if result:
                    results.append(result)
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Batch error analyzing {vm_id}: {e}")
                failed += 1

        return {
            "total": len(vm_ids),
            "analyzed": len(results),
            "failed": failed,
            "results": results,
        }

    def get_stats(self, db: Session, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate compatibility stats."""
        query = db.query(
            VirtualMachine.compatibility_status,
            func.count(VirtualMachine.id),
        ).group_by(VirtualMachine.compatibility_status)

        if tenant_id:
            query = query.filter(VirtualMachine.tenant_id == tenant_id)

        stats = {}
        for status, count in query.all():
            stats[status.value] = count

        return {
            "compatible": stats.get("compatible", 0),
            "partial": stats.get("partial", 0),
            "incompatible": stats.get("incompatible", 0),
            "unknown": stats.get("unknown", 0),
        }


def create_analyzer_service() -> AnalyzerService:
    """Factory for AnalyzerService."""
    return AnalyzerService()
