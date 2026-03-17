"""
Modèle Hypervisor

Représente un hyperviseur source (vSphere, VMware Workstation, Hyper-V, KVM, etc.)
depuis lequel les VMs seront découvertes et migrées.
"""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from app.models.base import BaseModel


class HypervisorType(str, enum.Enum):
    """Type d'hyperviseur"""
    VSPHERE = "vsphere"  # VMware vSphere / vCenter
    VMWARE_WORKSTATION = "vmware_workstation"  # VMware Workstation
    VMWARE_ESXi = "vmware_esxi"  # VMware ESXi standalone
    HYPER_V = "hyper_v"  # Microsoft Hyper-V
    KVM = "kvm"  # KVM (Kernel-based Virtual Machine)
    PROXMOX = "proxmox"  # Proxmox VE
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

    # Identité de l'hyperviseur
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    type = Column(SQLEnum(HypervisorType), nullable=False, index=True)

    # Connexion
    host = Column(String(255), nullable=False)  # Hostname ou IP
    port = Column(Integer, nullable=True)  # Port (défaut selon type)

    # Authentification (À CHIFFRER EN PRODUCTION)
    # TODO: Implémenter le chiffrement des credentials avec Fernet ou Vault
    username = Column(String(255), nullable=False)
    password = Column(Text, nullable=False)  # ATTENTION: Stocker chiffré en production

    # Configuration SSL/TLS
    verify_ssl = Column(Boolean, default=False)  # Vérifier certificats SSL
    ssl_cert_path = Column(String(512), nullable=True)  # Chemin vers certificat custom

    # Statut et monitoring
    status = Column(SQLEnum(HypervisorStatus), nullable=False, default=HypervisorStatus.UNKNOWN, index=True)
    is_active = Column(Boolean, default=True)  # Activer/Désactiver l'hyperviseur

    # Métadonnées de synchronisation
    last_sync_at = Column(DateTime, nullable=True)  # Dernière sync VMs
    last_successful_connection = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)  # Dernier message d'erreur

    # Statistiques
    total_vms_discovered = Column(Integer, default=0)
    total_vms_migrated = Column(Integer, default=0)

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

    def to_dict(self, include_credentials: bool = False) -> dict:
        """
        Conversion en dictionnaire pour API.

        Args:
            include_credentials: Si True, inclut username/password (ATTENTION: usage admin uniquement)
        """
        data = {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
            "host": self.host,
            "port": self.port,
            "verify_ssl": self.verify_ssl,
            "status": self.status.value,
            "is_active": self.is_active,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "last_successful_connection": self.last_successful_connection.isoformat() if self.last_successful_connection else None,
            "last_error": self.last_error,
            "total_vms_discovered": self.total_vms_discovered,
            "total_vms_migrated": self.total_vms_migrated,
            "connection_config": self.connection_config,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_reachable": self.is_reachable,
            "connection_url": self.connection_url,
            "needs_sync": self.needs_sync
        }

        # Inclure credentials uniquement si explicitement demandé (usage admin)
        if include_credentials:
            data["username"] = self.username
            data["password"] = self.password  # ATTENTION: Sensible !
        else:
            data["username"] = self.username
            # Ne jamais exposer le password dans l'API par défaut

        return data

    def update_status(self, new_status: HypervisorStatus, error_message: str = None):
        """Met à jour le statut de l'hyperviseur"""
        self.status = new_status

        if new_status == HypervisorStatus.ACTIVE:
            self.last_successful_connection = datetime.now(timezone.utc)
            self.last_error = None
        elif error_message:
            self.last_error = error_message

        self.updated_at = datetime.now(timezone.utc)

    def mark_sync_completed(self, success: bool = True, total_vms: int = 0):
        """
        Marque une synchronisation comme complétée

        Args:
            success: Si True, la sync a réussi
            total_vms: Nombre de VMs découvertes
        """
        self.last_sync_at = datetime.now(timezone.utc)

        if success:
            self.total_vms_discovered = total_vms
            self.last_successful_connection = datetime.now(timezone.utc)

        self.updated_at = datetime.now(timezone.utc)