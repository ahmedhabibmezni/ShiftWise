"""
Modèle Hypervisor

Représente un hyperviseur source (vSphere, VMware Workstation, Hyper-V, KVM, etc.)
depuis lequel les VMs seront découvertes et migrées.
"""

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, LargeBinary,
    Enum as SQLEnum, JSON, UniqueConstraint, text, false, true, func,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
import logging

from app.models.base import BaseModel

logger = logging.getLogger(__name__)


class HypervisorType(str, enum.Enum):
    """Type d'hyperviseur"""
    VSPHERE = "vsphere"  # VMware vSphere / vCenter
    VMWARE_WORKSTATION = "vmware_workstation"  # VMware Workstation
    VMWARE_ESXi = "vmware_esxi"  # VMware ESXi standalone
    HYPER_V = "hyper_v"  # Microsoft Hyper-V
    KVM = "kvm"  # KVM (Kernel-based Virtual Machine)
    PROXMOX = "proxmox"  # Proxmox VE
    OVIRT = "ovirt"  # oVirt / Red Hat Virtualization (RHV)
    VIRTUALBOX = "virtualbox"  # Oracle VirtualBox
    XEN = "xen"  # Citrix XenServer / XCP-ng
    OTHER = "other"  # Autre type


class HypervisorStatus(str, enum.Enum):
    """Statut de connexion à l'hyperviseur"""
    ACTIVE = "active"  # Connecté et opérationnel
    INACTIVE = "inactive"  # Désactivé volontairement
    ERROR = "error"  # Erreur de connexion
    UNREACHABLE = "unreachable"  # Non accessible (réseau, firewall, etc.)
    AUTHENTICATING = "authenticating"  # Authentification en cours
    DISCOVERING = "discovering"  # Découverte en cours
    UNKNOWN = "unknown"  # Statut inconnu


class Hypervisor(BaseModel):
    """
    Modèle représentant un hyperviseur source.

    Stocke les informations de connexion et le statut des hyperviseurs
    depuis lesquels les VMs seront découvertes et migrées.
    """

    __tablename__ = "hypervisors"

    # Audit B15 — l'unicité du nom est portée par un UniqueConstraint
    # composite (tenant_id, name) : deux tenants peuvent nommer un
    # hyperviseur à l'identique sans collision ni fuite d'existence.
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_hypervisors_tenant_name"),
    )

    # Multi-tenancy isolation
    tenant_id = Column(String(100), nullable=False, index=True)

    # Identité de l'hyperviseur — pas de `unique=True` global ici
    # (l'unicité est composite, voir __table_args__ ci-dessus).
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    type = Column(SQLEnum(HypervisorType), nullable=False, index=True)

    # Connexion
    host = Column(String(255), nullable=False)  # Hostname ou IP
    port = Column(Integer, nullable=True)  # Port (défaut selon type)

    # Authentification — US4 production-readiness :
    #   * `password_ciphertext` (Fernet) est la source de vérité pour les
    #     credentials.
    #   * `password` (texte clair, nullable) est conservé pour la rétro-
    #     compatibilité pendant la fenêtre de cutover ; les writes ne le
    #     remplissent plus depuis l'introduction du vault. Une migration
    #     Alembic ultérieure dropera la colonne.
    username = Column(String(255), nullable=False)
    password = Column(Text, nullable=True)
    password_ciphertext = Column(LargeBinary, nullable=True)
    credential_key_version = Column(
        Integer, nullable=False,
        default=1, server_default="1",
    )
    credentials_updated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )

    # Configuration SSL/TLS
    verify_ssl = Column(Boolean, default=False, server_default=false())  # Vérifier certificats SSL
    ssl_cert_path = Column(String(512), nullable=True)  # Chemin vers certificat custom

    # Statut et monitoring
    # Audit D16 — `server_default` en plus du `default` Python.
    status = Column(
        SQLEnum(HypervisorStatus), nullable=False,
        default=HypervisorStatus.UNKNOWN, server_default="UNKNOWN", index=True,
    )
    is_active = Column(Boolean, default=True, server_default=true())  # Activer/Désactiver

    # Métadonnées de synchronisation
    last_sync_at = Column(DateTime(timezone=True), nullable=True)  # Dernière sync VMs
    last_successful_connection = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)  # Dernier message d'erreur

    # Statistiques
    total_vms_discovered = Column(Integer, default=0, server_default=text("0"))
    total_vms_migrated = Column(Integer, default=0, server_default=text("0"))

    # Configuration avancée (JSON)
    connection_config = Column(JSON, nullable=True)  # Config spécifique (datacenter, cluster, etc.)
    tags = Column(JSON, nullable=True)  # Tags personnalisés

    # Relations
    virtual_machines = relationship(
        "VirtualMachine",
        back_populates="source_hypervisor",
        foreign_keys="VirtualMachine.source_hypervisor_id"
    )

    def __repr__(self):
        return (
            f"<Hypervisor(id={self.id}, name='{self.name}', "
            f"type={self.type.value}, status={self.status.value})>"
        )

    @property
    def is_reachable(self) -> bool:
        """Vérifie si l'hyperviseur est accessible"""
        return self.status in [HypervisorStatus.ACTIVE, HypervisorStatus.AUTHENTICATING]

    @property
    def password_plain(self) -> str | None:
        """Decrypted credential — single accessor for connectors and CRUD.

        Behavior matrix:
        - ``password_ciphertext`` set, decrypt succeeds -> return plaintext.
        - ``password_ciphertext`` set, decrypt fails    -> log + return
          ``None``. We MUST NOT silently fall back to the legacy
          ``password`` column: the ciphertext is the source of truth and a
          decrypt failure points at a real rotation/corruption incident
          the operator must see (constitution Principle VII).
        - ``password_ciphertext`` NULL, legacy ``password`` set -> return
          legacy plaintext (pre-cutover rows; will disappear once
          c9e1d4f3b6a2 lands).
        - both NULL                                     -> ``None``.
        """
        if self.password_ciphertext:
            from cryptography.fernet import InvalidToken

            from app.services.credentials import get_vault

            try:
                return get_vault().decrypt(self.password_ciphertext)
            except InvalidToken:
                logger.error(
                    "vault.decrypt failed for hypervisor id=%s key_version=%s "
                    "- ciphertext present but no key in the rotation set decrypts it; "
                    "refusing to fall back to legacy plaintext column",
                    self.id, self.credential_key_version,
                )
                return None
        return self.password or None

    @property
    def username_masked(self) -> str:
        """
        Audit D5 — version masquée du `username` pour l'API.

        Le `username` est une moitié d'identité d'identifiant : on l'expose
        partiellement (premier caractère + ***) plutôt qu'en clair, pour ne
        pas divulguer l'identité de connexion à l'hyperviseur.
        """
        value = self.username or ""
        if len(value) <= 2:
            return "***" if value else ""
        return f"{value[0]}***{value[-1]}"

    @property
    def connection_url(self) -> str:
        """Construit l'URL de connexion (sans credentials)"""
        port_str = f":{self.port}" if self.port else ""
        return f"{self.type.value}://{self.host}{port_str}"

    @property
    def needs_sync(self) -> bool:
        """Vérifie si une synchronisation est nécessaire"""
        if not self.last_sync_at:
            return True

        # Sync nécessaire si > 24h
        from datetime import timedelta

        # S'assurer que last_sync_at est timezone-aware
        last_sync = self.last_sync_at
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)

        threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        return last_sync < threshold

    def update_status(self, new_status: HypervisorStatus, error_message: str = None):
        """Met à jour le statut de l'hyperviseur"""
        self.status = new_status

        if new_status == HypervisorStatus.ACTIVE:
            self.last_successful_connection = datetime.now(timezone.utc)
            self.last_error = None
        elif error_message:
            self.last_error = error_message

    def mark_sync_completed(self, success: bool = True, total_vms: int = 0):
        """
        Marque une synchronisation comme complétée

        Args:
            success: Si True, la sync a réussi
            total_vms: Nombre de VMs découvertes — persisté dans
                total_vms_discovered quand success=True (Audit D17 :
                l'argument était auparavant ignoré).
        """
        if success:
            now = datetime.now(timezone.utc)
            self.last_sync_at = now
            self.last_successful_connection = now
            # Audit D17 — persiste la statistique de découverte.
            self.total_vms_discovered = total_vms
        # last_sync_at non mis à jour si success=False → needs_sync reste True
