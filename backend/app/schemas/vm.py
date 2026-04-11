"""
Schémas Pydantic pour VirtualMachine

Définit les schémas de validation et sérialisation pour l'API REST.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from enum import Enum


# Enums (réutilisation depuis les modèles)
class VMStatusEnum(str, Enum):
    """Statut d'une VM"""
    DISCOVERED = "discovered"
    ANALYZING = "analyzing"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    PARTIAL = "partial"
    MIGRATING = "migrating"
    MIGRATED = "migrated"
    FAILED = "failed"
    ARCHIVED = "archived"


class CompatibilityStatusEnum(str, Enum):
    """Statut de compatibilité"""
    COMPATIBLE = "compatible"
    PARTIAL = "partial"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class OSTypeEnum(str, Enum):
    """Type d'OS"""
    WINDOWS = "windows"
    LINUX = "linux"
    OTHER = "other"
    UNKNOWN = "unknown"


# Schéma de base (propriétés communes)
class VMBase(BaseModel):
    """Propriétés de base d'une VM"""
    name: str = Field(..., min_length=1, max_length=255, description="Nom de la VM")
    description: Optional[str] = Field(None, description="Description de la VM")
    cpu_cores: int = Field(..., ge=1, le=128, description="Nombre de vCPUs")
    memory_mb: int = Field(..., ge=512, description="Mémoire en MB")
    disk_gb: int = Field(..., ge=1, description="Taille du disque en GB")
    os_type: OSTypeEnum = Field(OSTypeEnum.UNKNOWN, description="Type d'OS")
    os_version: Optional[str] = Field(None, max_length=255, description="Version de l'OS")
    os_name: Optional[str] = Field(None, max_length=255, description="Nom complet de l'OS")


# Schéma pour la création (input API)
class VMCreate(VMBase):
    """Schéma pour créer une VM"""
    source_hypervisor_id: Optional[int] = Field(None, description="ID de l'hyperviseur source")
    source_uuid: Optional[str] = Field(None, max_length=255, description="UUID dans la source")
    source_name: Optional[str] = Field(None, max_length=255, description="Nom dans la source")
    ip_address: Optional[str] = Field(None, max_length=45, description="Adresse IP")
    mac_address: Optional[str] = Field(None, max_length=17, description="Adresse MAC")
    hostname: Optional[str] = Field(None, max_length=255, description="Hostname")
    tags: Optional[dict] = Field(None, description="Tags personnalisés")


# Schéma pour la mise à jour (input API)
class VMUpdate(BaseModel):
    """Schéma pour mettre à jour une VM.

    status et compatibility_status sont gérés exclusivement par le
    Discovery Service et l'Analyzer — non acceptés ici.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    cpu_cores: Optional[int] = Field(None, ge=1, le=128)
    memory_mb: Optional[int] = Field(None, ge=512)
    disk_gb: Optional[int] = Field(None, ge=1)
    os_type: Optional[OSTypeEnum] = None
    os_version: Optional[str] = Field(None, max_length=255)
    os_name: Optional[str] = Field(None, max_length=255)
    compatibility_details: Optional[dict] = None
    openshift_vm_name: Optional[str] = Field(None, max_length=255)
    openshift_namespace: Optional[str] = Field(None, max_length=255)
    tags: Optional[dict] = None


# Schéma pour la réponse (output API)
class VMResponse(VMBase):
    """Schéma de réponse avec toutes les propriétés"""
    id: int
    source_hypervisor_id: Optional[int] = None
    source_uuid: Optional[str] = None
    source_name: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    status: VMStatusEnum
    compatibility_status: CompatibilityStatusEnum
    compatibility_details: Optional[dict] = None
    openshift_vm_name: Optional[str] = None
    openshift_namespace: Optional[str] = None
    openshift_node: Optional[str] = None
    discovered_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    tags: Optional[dict] = None
    custom_metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    # Propriétés calculées
    is_compatible: bool
    is_migrated: bool
    can_migrate: bool

    model_config = ConfigDict(from_attributes=True)


# Schéma pour liste paginée
class VMListResponse(BaseModel):
    """Réponse pour liste de VMs"""
    total: int = Field(..., description="Nombre total de VMs")
    items: list[VMResponse] = Field(..., description="Liste des VMs")
    page: int = Field(..., ge=1, description="Page actuelle")
    page_size: int = Field(..., ge=1, le=100, description="Taille de la page")