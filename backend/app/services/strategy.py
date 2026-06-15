"""
Automatic migration-strategy selection from the analyzer compatibility score.

Pure mapping — no DB, no I/O. The score (0-100) is produced by the rules engine
(``compatibility_rules.aggregate``) as ``100 − Σ intervention penalties``; the
band a score falls into names the pipeline work the migration implies. Thresholds
are module constants so they can be tuned in one place.
"""

from __future__ import annotations

from typing import Optional

from app.models.migration import MigrationStrategy

_DIRECT_MIN = 90      # native disk + virtio-ready guest → direct import
_CONVERSION_MIN = 70  # disk conversion only
_HYBRID_MIN = 50      # guest adaptation (± conversion) — common VMware/physical


def recommend_strategy(*, score: int, has_blocker: bool) -> Optional[MigrationStrategy]:
    """Return the auto-selected strategy, or None when the VM is INCOMPATIBLE."""
    if has_blocker:
        return None
    if score >= _DIRECT_MIN:
        return MigrationStrategy.DIRECT
    if score >= _CONVERSION_MIN:
        return MigrationStrategy.CONVERSION
    if score >= _HYBRID_MIN:
        return MigrationStrategy.HYBRID
    return MigrationStrategy.COLD
