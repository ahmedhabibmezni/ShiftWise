"""
Modèle VirtualMachine

Représente une machine virtuelle découverte depuis une source (vSphere, VMware, etc.)
et son état dans le processus de migration vers OpenShift Virtualization.
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, Enum as SQLEnum, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.models.base import BaseModel


class VMStatus(str, enum.Enum):
    """Statut d'une VM dans le processus de migration"""
    DISCOVERED = "discovered"          # VM découverte depuis la source
    ANALYZING = "analyzing"            # Analyse de compatibilité en cours
    COMPATIBLE = "compatible"          # Compatible avec OpenShift
    INCOMPATIBLE = "incompatible"      # Non compatible
    PARTIAL = "partial"                # Partiellement compatible (nécessite conversion)
    MIGRATING = "migrating"            # Migration en cours
    MIGRATED = "migrated"              # Migration terminée avec succès
    FAILED = "failed"                  # Échec de migration
    ARCHIVED = "archived"              # VM archivée


class CompatibilityStatus(str, enum.Enum):
    """Statut de compatibilité avec OpenShift Virtualization"""
    COMPATIBLE = "compatible"          # 100% compatible, migration directe possible
    PARTIAL = "partial"                # Compatible avec conversions (VMDK→QCOW2, drivers, etc.)
    INCOMPATIBLE = "incompatible"      # Non compatible (OS non supporté, etc.)
    UNKNOWN = "unknown"                # Pas encore analysée


class OSType(str, enum.Enum):
    """Type de système d'exploitation"""
    WINDOWS = "windows"
    LINUX = "linux"
    OTHER = "other"
    UNKNOWN = "unknown"


class VirtualMachine(BaseModel):
    """
    Modèle représentant une machine virtuelle.

    Stocke les informations sur les VMs découvertes depuis les hyperviseurs sources
    et leur état dans le processus de migration vers OpenShift Virtualization.
    """

    __tablename__ = "virtual_machines"

    # Multi-tenancy isolation
    tenant_id = Column(String(100), nullable=False, index=True)

    # Identité de la VM
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # Source (Hypervisor d'origine)
    source_hypervisor_id = Column(
        Integer,
        ForeignKey("hypervisors.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    source_uuid = Column(String(255), nullable=True, index=True)  # UUID dans vSphere/VMware
    source_name = Column(String(255), nullable=True)  # Nom original dans la source

    # Spécifications matérielles
    cpu_cores = Column(Integer, nullable=False)
    memory_mb = Column(Integer, nullable=False)
    disk_gb = Column(Integer, nullable=False)

    # Système d'exploitation
    os_type = Column(SQLEnum(OSType), nullable=False, default=OSType.UNKNOWN)
    os_version = Column(String(255), nullable=True)
    os_name = Column(String(255), nullable=True)  # Ex: "Ubuntu 22.04 LTS", "Windows Server 2022"

    # Réseau
    ip_address = Column(String(45), nullable=True)  # IPv4 ou IPv6
    mac_address = Column(String(17), nullable=True)
    hostname = Column(String(255), nullable=True)

    # Statut et compatibilité
    status = Column(SQLEnum(VMStatus), nullable=False, default=VMStatus.DISCOVERED, index=True)
    compatibility_status = Column(
        SQLEnum(CompatibilityStatus),
        nullable=False,
        default=CompatibilityStatus.UNKNOWN,
        index=True
    )
    compatibility_details = Column(JSON, nullable=True)  # Détails de l'analyse de compatibilité

    # OpenShift Virtualization (après migration)
    openshift_vm_name = Column(String(255), nullable=True, index=True)
    openshift_namespace = Column(String(255), nullable=True, default="default")
    openshift_node = Column(String(255), nullable=True)  # Node où tourne la VM

    # Métadonnées de découverte
    discovered_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)

    # Métadonnées supplémentaires
    tags = Column(JSON, nullable=True)  # Tags personnalisés
    custom_metadata = Column(JSON, nullable=True)  # Métadonnées additionnelles

    # Relations
    source_hypervisor = relationship(
        "Hypervisor",
        back_populates="virtual_machines",
        foreign_keys=[source_hypervisor_id]
    )

    migrations = relationship(
        "Migration",
        back_populates="virtual_machine",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<VirtualMachine(id={self.id}, name='{self.name}', "
            f"status={self.status.value}, compatibility={self.compatibility_status.value})>"
        )

    @property
    def is_compatible(self) -> bool:
        """Vérifie si la VM est compatible (directement ou partiellement)"""
        return self.compatibility_status in [
            CompatibilityStatus.COMPATIBLE,
            CompatibilityStatus.PARTIAL
        ]

    @property
    def is_migrated(self) -> bool:
        """Vérifie si la VM a été migrée avec succès"""
        return self.status == VMStatus.MIGRATED

    @property
    def can_migrate(self) -> bool:
        """Vérifie si la VM peut être migrée"""
        return (
            self.is_compatible and
            self.status in [VMStatus.COMPATIBLE, VMStatus.PARTIAL, VMStatus.FAILED]
        )

    def to_dict(self) -> dict:
        """Conversion en dictionnaire pour API"""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "source_hypervisor_id": str(self.source_hypervisor_id) if self.source_hypervisor_id else None,
            "source_uuid": self.source_uuid,
            "source_name": self.source_name,
            "cpu_cores": self.cpu_cores,
            "memory_mb": self.memory_mb,
            "disk_gb": self.disk_gb,
            "os_type": self.os_type.value,
            "os_version": self.os_version,
            "os_name": self.os_name,
            "ip_address": self.ip_address,
            "mac_address": self.mac_address,
            "hostname": self.hostname,
            "status": self.status.value,
            "compatibility_status": self.compatibility_status.value,
            "compatibility_details": self.compatibility_details,
            "openshift_vm_name": self.openshift_vm_name,
            "openshift_namespace": self.openshift_namespace,
            "openshift_node": self.openshift_node,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "tags": self.tags,
            "custom_metadata": self.custom_metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_compatible": self.is_compatible,
            "is_migrated": self.is_migrated,
            "can_migrate": self.can_migrate
        }