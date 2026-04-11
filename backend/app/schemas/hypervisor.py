"""
Schémas Pydantic pour Hypervisor

Définit les schémas de validation et sérialisation pour l'API REST.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from enum import Enum


# Enums
class HypervisorTypeEnum(str, Enum):
    """Type d'hyperviseur"""
    VSPHERE = "vsphere"
    VMWARE_WORKSTATION = "vmware_workstation"
    VMWARE_ESXI = "vmware_esxi"
    HYPER_V = "hyper_v"
    KVM = "kvm"
    PROXMOX = "proxmox"
    VIRTUALBOX = "virtualbox"
    XEN = "xen"
    OTHER = "other"


class HypervisorStatusEnum(str, Enum):
    """Statut de connexion"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    UNREACHABLE = "unreachable"
    AUTHENTICATING = "authenticating"
    DISCOVERING = "discovering"
    UNKNOWN = "unknown"


# Schéma de base
class HypervisorBase(BaseModel):
    """Propriétés de base d'un hyperviseur"""
    name: str = Field(..., min_length=1, max_length=255, description="Nom de l'hyperviseur")
    description: Optional[str] = Field(None, description="Description")
    type: HypervisorTypeEnum = Field(..., description="Type d'hyperviseur")
    host: str = Field(..., min_length=1, max_length=255, description="Hostname ou IP")
    port: Optional[int] = Field(None, ge=1, le=65535, description="Port de connexion")


# Schéma pour la création (avec credentials)
class HypervisorCreate(HypervisorBase):
    """Schéma pour créer un hyperviseur"""
    username: str = Field(..., min_length=1, max_length=255, description="Nom d'utilisateur")
    password: str = Field(..., min_length=1, description="Mot de passe")
    verify_ssl: bool = Field(False, description="Vérifier les certificats SSL")
    ssl_cert_path: Optional[str] = Field(None, max_length=512, description="Chemin certificat SSL")
    connection_config: Optional[dict] = Field(None, description="Configuration avancée")
    tags: Optional[dict] = Field(None, description="Tags personnalisés")


# Schéma pour la mise à jour
class HypervisorUpdate(BaseModel):
    """Schéma pour mettre à jour un hyperviseur"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    host: Optional[str] = Field(None, min_length=1, max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = Field(None, min_length=1, max_length=255)
    password: Optional[str] = Field(None, min_length=1)  # Mettre à jour le password
    verify_ssl: Optional[bool] = None
    ssl_cert_path: Optional[str] = Field(None, max_length=512)
    is_active: Optional[bool] = None
    connection_config: Optional[dict] = None
    tags: Optional[dict] = None


# Schéma pour la réponse (SANS password par défaut)
class HypervisorResponse(HypervisorBase):
    """Schéma de réponse (sans credentials sensibles)"""
    id: int
    username: str  # On garde le username mais PAS le password
    verify_ssl: bool
    status: HypervisorStatusEnum
    is_active: bool
    last_sync_at: Optional[datetime] = None
    last_successful_connection: Optional[datetime] = None
    last_error: Optional[str] = None
    total_vms_discovered: int
    total_vms_migrated: int
    connection_config: Optional[dict] = None
    tags: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    # Propriétés calculées
    is_reachable: bool
    connection_url: str
    needs_sync: bool

    model_config = ConfigDict(from_attributes=True)


# Schéma pour liste paginée
class HypervisorListResponse(BaseModel):
    """Réponse pour liste d'hyperviseurs"""
    total: int = Field(..., description="Nombre total d'hyperviseurs")
    items: list[HypervisorResponse] = Field(..., description="Liste des hyperviseurs")
    page: int = Field(..., ge=1, description="Page actuelle")
    page_size: int = Field(..., ge=1, le=100, description="Taille de la page")


# Schéma pour tester la connexion
class HypervisorTestConnection(BaseModel):
    """Schéma pour tester une connexion hyperviseur"""
    type: HypervisorTypeEnum
    host: str = Field(..., min_length=1, max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)
    verify_ssl: bool = False


# Schéma de réponse du test de connexion
class HypervisorTestConnectionResponse(BaseModel):
    """Résultat du test de connexion"""
    success: bool = Field(..., description="Connexion réussie")
    message: str = Field(..., description="Message de résultat")
    vms_count: Optional[int] = Field(None, description="Nombre de VMs découvertes")
    error: Optional[str] = Field(None, description="Message d'erreur si échec")