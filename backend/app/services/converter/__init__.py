"""
ShiftWise Converter Service

Pipeline disque : pull source (hyperviseur) -> stage (NFS) -> convert
(qemu-img / virt-v2v in-cluster) -> verify -> READY pour CDI.

Sous-modules :
- errors    : codes d'erreur structurés (transient/configurable/permanent)
- protocol  : DiskPuller Protocol + PullResult dataclass
- plan      : sélection tool + format cible à partir des métadonnées VM
- paths     : layout NFS par tenant
- connectors: implémentations par hyperviseur (one file each)
- service   : ConverterService orchestrateur (phase suivante)
"""

from app.services.converter.errors import (
    ConversionError,
    ErrorBucket,
    ERROR_CATALOG,
)
from app.services.converter.protocol import DiskPuller, PullResult
from app.services.converter.plan import ConversionPlan, plan_conversion

__all__ = [
    "ConversionError",
    "ErrorBucket",
    "ERROR_CATALOG",
    "DiskPuller",
    "PullResult",
    "ConversionPlan",
    "plan_conversion",
]
