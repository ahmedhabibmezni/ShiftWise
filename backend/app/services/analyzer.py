"""
Analyzer service — compatibility classification orchestration.

Hybrid engine: ML model + rules fallback. Single source of truth for
feature extraction (:mod:`app.services.feature_extractor`).
"""

from __future__ import annotations

import json
import logging
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


class AnalyzerService:
    """Orchestrate VM compatibility analysis."""

    def __init__(self):
        self.model = None
        self.feature_names = list(FEATURE_NAMES)
        self.labels = ("COMPATIBLE", "PARTIAL", "INCOMPATIBLE")
        self.threshold = settings.ANALYZER_CONFIDENCE_THRESHOLD

        self._load_model()

    def _load_model(self) -> None:
        """Load the joblib artifact. Fallback to rules on any error."""
        if not _ARTIFACT_PATH.exists():
            logger.warning(f"Model artifact not found: {_ARTIFACT_PATH} — will use rules fallback")
            return

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("error", category=UserWarning)
                payload = joblib.load(_ARTIFACT_PATH)
            self.model = payload.get("model")
            logger.info(f"Model loaded: {payload.get('model_kind', 'unknown')} "
                        f"(sklearn {payload.get('sklearn_version', 'unknown')})")
        except UserWarning as e:
            logger.warning(f"sklearn InconsistentVersionWarning: {e} — using rules fallback")
        except Exception as e:
            logger.warning(f"Failed to load model: {e} — using rules fallback")

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

            # Decide: model or rules?
            engine = "rules"
            confidence = 0.0

            if self.model:
                features = to_vector(rules_features(vm_dict))
                proba = self.model.predict_proba([features])[0]
                pred_idx = np.argmax(proba)
                confidence = float(proba[pred_idx])

                if confidence >= self.threshold:
                    engine = "model"

            if engine == "model":
                pred_idx = np.argmax(self.model.predict_proba([to_vector(rules_features(vm_dict))])[0])
                grade = self.labels[pred_idx]
            else:
                grade = rules_agg["grade"]

            grade_map = {
                "COMPATIBLE": CompatibilityStatus.COMPATIBLE,
                "PARTIAL": CompatibilityStatus.PARTIAL,
                "INCOMPATIBLE": CompatibilityStatus.INCOMPATIBLE,
            }

            details: Dict[str, Any] = {
                "score": rules_agg["score"],
                "grade": grade,
                "engine": engine,
                "confidence": confidence if engine == "model" else None,
                "rules": rules,
                "blockers": rules_agg["blockers"],
                "warnings": rules_agg["warnings"],
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }

            vm.compatibility_status = grade_map[grade]
            vm.compatibility_details = details
            vm.status = VMStatus.DISCOVERED

            db.commit()

            logger.info(
                f"VM {vm_id} analyzed: {grade} (engine={engine}, score={details['score']})"
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
