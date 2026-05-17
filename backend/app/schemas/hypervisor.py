"""
Schémas Pydantic pour Hypervisor

Définit les schémas de validation et sérialisation pour l'API REST.
"""

import ipaddress
import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.hypervisor import HypervisorType as HypervisorTypeEnum
from app.models.hypervisor import HypervisorStatus as HypervisorStatusEnum


# Audit H-03 — plages réseau interdites comme cible d'hyperviseur (SSRF).
# Un hôte link-local pointe typiquement vers le endpoint de métadonnées
# cloud (169.254.169.254) ; aucun hyperviseur légitime n'y réside.
_SSRF_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),  # link-local IPv4 (métadonnées cloud)
    ipaddress.ip_network("fe80::/10"),       # link-local IPv6
)


def _check_host_not_ssrf(host: str) -> str:
    """
    Rejette un host dont le littéral IP cible une plage interdite.

    Le champ `host` est polymorphe (IP, hostname, URI ``qemu+ssh://``, ou
    chemin local pour VMware Workstation) : on n'inspecte un littéral IP que
    s'il y en a un. La validation réseau complète (allowlist d'opérateur,
    résolution DNS anti-rebinding) relève d'un durcissement ultérieur.
    """
    candidate = host.strip()
    uri_match = re.search(r"@([^/:?]+)", candidate) or re.search(r"://([^/:?@]+)", candidate)
    if uri_match:
        candidate = uri_match.group(1)
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return host  # pas un littéral IP — laissé tel quel
    if ip.is_unspecified:
        raise ValueError(f"hôte interdit : {host!r} (adresse non spécifiée)")
    for net in _SSRF_BLOCKED_NETWORKS:
        if ip in net:
            raise ValueError(
                f"hôte interdit : {host!r} cible la plage link-local {net} "
                f"(risque de SSRF vers les métadonnées cloud)"
            )
    return host


# Schéma de base
class HypervisorBase(BaseModel):
    """Propriétés de base d'un hyperviseur"""
    name: str = Field(..., min_length=1, max_length=255, description="Nom de l'hyperviseur")
    description: Optional[str] = Field(None, description="Description")
    type: HypervisorTypeEnum = Field(..., description="Type d'hyperviseur")
    host: str = Field(..., min_length=1, max_length=255, description="Hostname ou IP")
    port: Optional[int] = Field(None, ge=1, le=65535, description="Port de connexion")

    @field_validator("host")
    @classmethod
    def _validate_host_ssrf(cls, v: Optional[str]) -> Optional[str]:
        """Audit H-03 — refuse un hôte link-local (SSRF métadonnées cloud)."""
        return v if v is None else _check_host_not_ssrf(v)


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

    @field_validator("host")
    @classmethod
    def _validate_host_ssrf(cls, v: Optional[str]) -> Optional[str]:
        """Audit H-03 — refuse un hôte link-local (SSRF métadonnées cloud)."""
        return v if v is None else _check_host_not_ssrf(v)


# Schéma pour la réponse (SANS password par défaut)
class HypervisorResponse(HypervisorBase):
    """Schéma de réponse (sans credentials sensibles).

    Audit D5 — le `username` en clair n'est PAS exposé : seule la forme
    masquée `username_masked` (propriété du modèle) est servie.
    Audit D8 — `tenant_id` exposé en lecture seule (traçabilité multi-tenant).
    Audit D9 — `ssl_cert_path` exposé (champ jusque-là write-only).
    """
    id: int
    tenant_id: str  # Audit D8 — lecture seule
    username_masked: str  # Audit D5 — username masqué, jamais en clair
    verify_ssl: bool
    ssl_cert_path: Optional[str] = None  # Audit D9
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

    # Audit D10 — `from_attributes` pour une construction homogène depuis l'ORM.
    model_config = ConfigDict(from_attributes=True)


# Schéma pour tester la connexion
class HypervisorTestConnection(BaseModel):
    """Schéma pour tester une connexion hyperviseur"""
    type: HypervisorTypeEnum
    host: str = Field(..., min_length=1, max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)
    verify_ssl: bool = False

    # Audit D18 — `model_config` pour la cohérence de convention.
    model_config = ConfigDict(from_attributes=True)

    @field_validator("host")
    @classmethod
    def _validate_host_ssrf(cls, v: Optional[str]) -> Optional[str]:
        """Audit H-03 — refuse un hôte link-local (SSRF métadonnées cloud)."""
        return v if v is None else _check_host_not_ssrf(v)


# Schéma de réponse du test de connexion
class HypervisorTestConnectionResponse(BaseModel):
    """Résultat du test de connexion"""
    success: bool = Field(..., description="Connexion réussie")
    message: str = Field(..., description="Message de résultat")
    vms_count: Optional[int] = Field(None, description="Nombre de VMs découvertes")
    error: Optional[str] = Field(None, description="Message d'erreur si échec")

    # Audit D18 — `model_config` pour la cohérence de convention.
    model_config = ConfigDict(from_attributes=True)