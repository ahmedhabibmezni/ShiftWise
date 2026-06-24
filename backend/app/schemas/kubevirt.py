"""
Schémas Pydantic pour KubeVirt / OpenShift Virtualization

Définit les schémas de validation pour les opérations directes sur le cluster.
"""

from pydantic import BaseModel, Field
from typing import Optional


class KubeVirtVMCreate(BaseModel):
    """Schéma pour créer une VirtualMachine dans OpenShift via KubeVirt."""

    name: str = Field(..., min_length=1, max_length=253, description="Nom de la VM (RFC 1123)")
    cpu: int = Field(1, ge=1, le=64, description="Nombre de vCPUs")
    memory: str = Field("2Gi", description="Mémoire allouée (ex: 2Gi, 4Gi)")
    image: str = Field(
        "quay.io/containerdisks/fedora:latest",
        description="Image container ou DataVolume"
    )
    disk_size: Optional[str] = Field(None, description="Taille du disque persistant (ex: 10Gi)")
    storage_class: Optional[str] = Field("nfs-client", description="StorageClass OpenShift")
    run_strategy: str = Field("Always", description="RunStrategy KubeVirt (Always, Manual, Halted)")
