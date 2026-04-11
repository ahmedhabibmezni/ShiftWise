"""
Discovery Service - Découverte des VMs depuis les hyperviseurs sources

Supporte :
- VMware vSphere (via pyvmomi)
- VMware Workstation (via vmrun)
- Hyper-V (via PowerShell)
- KVM/QEMU (via libvirt)
"""

import traceback
from typing import List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import logging

from app.models.hypervisor import Hypervisor, HypervisorType, HypervisorStatus
from app.models.virtual_machine import VirtualMachine, VMStatus, CompatibilityStatus, OSType

logger = logging.getLogger(__name__)


class DiscoveryError(Exception):
    """Erreur lors de la découverte de VMs"""
    pass


class DiscoveryService:
    """Service de découverte des VMs depuis les hyperviseurs"""

    def __init__(self, db: Session):
        self.db = db

    # ========================================================================
    # MÉTHODES PRINCIPALES
    # ========================================================================

    def discover_hypervisor(self, hypervisor_id: int) -> Dict[str, Any]:
        """
        Découvre toutes les VMs d'un hypervisor

        Args:
            hypervisor_id: ID de l'hypervisor à scanner

        Returns:
            Statistiques de découverte

        Raises:
            DiscoveryError: Si la découverte échoue
        """
        # Récupérer l'hypervisor
        hypervisor = self.db.query(Hypervisor).filter(
            Hypervisor.id == hypervisor_id
        ).first()

        if not hypervisor:
            raise DiscoveryError(f"Hypervisor {hypervisor_id} introuvable")

        logger.info(f"Début découverte hypervisor {hypervisor.name} (type: {hypervisor.type})")

        # Marquer le début de la synchronisation — last_sync_at n'est PAS mis à jour ici.
        # Il sera mis à jour par mark_sync_completed(success=True) uniquement.
        hypervisor.status = HypervisorStatus.DISCOVERING
        self.db.commit()

        try:
            # Découvrir selon le type
            if hypervisor.type == HypervisorType.VSPHERE:
                vms_data = self._discover_vsphere(hypervisor)
            elif hypervisor.type == HypervisorType.VMWARE_WORKSTATION:
                vms_data = self._discover_vmware_workstation(hypervisor)
            elif hypervisor.type == HypervisorType.HYPER_V:
                vms_data = self._discover_hyperv(hypervisor)
            elif hypervisor.type == HypervisorType.KVM:
                vms_data = self._discover_kvm(hypervisor)
            else:
                raise DiscoveryError(f"Type d'hypervisor non supporté: {hypervisor.type}")

            # Sauvegarder les VMs découvertes
            stats = self._save_discovered_vms(hypervisor, vms_data)

            # Mettre à jour l'hypervisor
            hypervisor.update_status(HypervisorStatus.ACTIVE)
            hypervisor.mark_sync_completed(success=True, total_vms=stats['total_discovered'])
            self.db.commit()

            logger.info(f"Découverte terminée: {stats['total_discovered']} VMs trouvées")

            return stats

        except (DiscoveryError, ConnectionError, TimeoutError) as e:
            logger.error(f"Erreur découverte hypervisor {hypervisor.name}: {str(e)}")
            hypervisor.update_status(HypervisorStatus.ERROR, error_message=str(e))
            hypervisor.mark_sync_completed(success=False)
            self.db.commit()
            raise DiscoveryError(f"Échec de la découverte: {str(e)}")

    # ========================================================================
    # DÉCOUVERTE PAR TYPE D'HYPERVISOR
    # ========================================================================

    def _discover_vsphere(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """
        Découvre les VMs depuis vSphere

        Args:
            hypervisor: Instance de l'hypervisor vSphere

        Returns:
            Liste des VMs découvertes
        """
        logger.info(f"Connexion à vSphere: {hypervisor.host}")

        try:
            # TODO: Implémenter avec pyvmomi
            # from pyVim.connect import SmartConnect, Disconnect
            # from pyVmomi import vim

            # Pour l'instant, retourner des données de test
            logger.warning("⚠️  Mode SIMULATION - pyvmomi non encore implémenté")

            # Simuler la découverte de 3 VMs
            mock_vms = [
                {
                    "source_uuid": "vm-001-vsphere",
                    "source_name": "web-server-prod",
                    "name": "web-server-prod",
                    "cpu_cores": 4,
                    "memory_mb": 8192,
                    "disk_gb": 100,
                    "os_type": OSType.LINUX,
                    "os_version": "Ubuntu 22.04",
                    "os_name": "Ubuntu Server 22.04 LTS",
                    "ip_address": "192.168.1.10",
                    "mac_address": "00:50:56:00:00:01",
                    "hostname": "web-prod-01",
                    "power_state": "poweredOn"
                },
                {
                    "source_uuid": "vm-002-vsphere",
                    "source_name": "db-server-prod",
                    "name": "db-server-prod",
                    "cpu_cores": 8,
                    "memory_mb": 16384,
                    "disk_gb": 500,
                    "os_type": OSType.LINUX,
                    "os_version": "CentOS 8",
                    "os_name": "CentOS 8 Stream",
                    "ip_address": "192.168.1.11",
                    "mac_address": "00:50:56:00:00:02",
                    "hostname": "db-prod-01",
                    "power_state": "poweredOn"
                },
                {
                    "source_uuid": "vm-003-vsphere",
                    "source_name": "win-app-server",
                    "name": "win-app-server",
                    "cpu_cores": 2,
                    "memory_mb": 4096,
                    "disk_gb": 80,
                    "os_type": OSType.WINDOWS,
                    "os_version": "Windows Server 2019",
                    "os_name": "Windows Server 2019 Standard",
                    "ip_address": "192.168.1.12",
                    "mac_address": "00:50:56:00:00:03",
                    "hostname": "win-app-01",
                    "power_state": "poweredOn"
                }
            ]

            return mock_vms

        except Exception as e:
            raise DiscoveryError(f"Erreur connexion vSphere: {str(e)}")

    def _discover_vmware_workstation(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """
        Découvre les VMs depuis VMware Workstation

        Args:
            hypervisor: Instance de l'hypervisor VMware Workstation

        Returns:
            Liste des VMs découvertes
        """
        logger.info(f"Scan VMware Workstation: {hypervisor.host}")

        try:
            # TODO: Implémenter avec vmrun
            # import subprocess
            # result = subprocess.run(['vmrun', 'list'], capture_output=True)

            logger.warning("⚠️  Mode SIMULATION - vmrun non encore implémenté")

            mock_vms = [
                {
                    "source_uuid": "vm-001-vmware",
                    "source_name": "dev-ubuntu",
                    "name": "dev-ubuntu",
                    "cpu_cores": 2,
                    "memory_mb": 4096,
                    "disk_gb": 40,
                    "os_type": OSType.LINUX,
                    "os_version": "Ubuntu 22.04",
                    "os_name": "Ubuntu Desktop 22.04",
                    "ip_address": "192.168.100.10",
                    "power_state": "running"
                }
            ]

            return mock_vms

        except Exception as e:
            raise DiscoveryError(f"Erreur scan VMware Workstation: {str(e)}")

    def _discover_hyperv(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """
        Découvre les VMs depuis Hyper-V

        Args:
            hypervisor: Instance de l'hypervisor Hyper-V

        Returns:
            Liste des VMs découvertes
        """
        logger.info(f"Connexion à Hyper-V: {hypervisor.host}")

        try:
            # TODO: Implémenter avec PowerShell via subprocess
            # import subprocess
            # ps_script = "Get-VM | ConvertTo-Json"

            logger.warning("⚠️  Mode SIMULATION - PowerShell Hyper-V non encore implémenté")

            mock_vms = [
                {
                    "source_uuid": "vm-001-hyperv",
                    "source_name": "exchange-server",
                    "name": "exchange-server",
                    "cpu_cores": 4,
                    "memory_mb": 8192,
                    "disk_gb": 200,
                    "os_type": OSType.WINDOWS,
                    "os_version": "Windows Server 2022",
                    "os_name": "Windows Server 2022 Datacenter",
                    "ip_address": "192.168.2.10",
                    "power_state": "Running"
                }
            ]

            return mock_vms

        except Exception as e:
            raise DiscoveryError(f"Erreur connexion Hyper-V: {str(e)}")

    def _discover_kvm(self, hypervisor: Hypervisor) -> List[Dict[str, Any]]:
        """
        Découvre les VMs depuis KVM/QEMU

        Args:
            hypervisor: Instance de l'hypervisor KVM

        Returns:
            Liste des VMs découvertes
        """
        logger.info(f"Connexion à KVM: {hypervisor.host}")

        try:
            # TODO: Implémenter avec libvirt
            # import libvirt
            # conn = libvirt.open(f'qemu+ssh://{hypervisor.username}@{hypervisor.host}/system')

            logger.warning("⚠️  Mode SIMULATION - libvirt non encore implémenté")

            mock_vms = [
                {
                    "source_uuid": "vm-001-kvm",
                    "source_name": "test-fedora",
                    "name": "test-fedora",
                    "cpu_cores": 2,
                    "memory_mb": 2048,
                    "disk_gb": 30,
                    "os_type": OSType.LINUX,
                    "os_version": "Fedora 38",
                    "os_name": "Fedora 38 Server",
                    "ip_address": "192.168.122.10",
                    "power_state": "running"
                }
            ]

            return mock_vms

        except Exception as e:
            raise DiscoveryError(f"Erreur connexion KVM: {str(e)}")

    # ========================================================================
    # SAUVEGARDE DES VMs DÉCOUVERTES
    # ========================================================================

    def _save_discovered_vms(
            self,
            hypervisor: Hypervisor,
            vms_data: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Sauvegarde les VMs découvertes dans la base de données

        Args:
            hypervisor: Hypervisor source
            vms_data: Liste des VMs découvertes

        Returns:
            Statistiques (total, nouvelles, mises à jour)
        """
        stats = {
            "total_discovered": len(vms_data),
            "new_vms": 0,
            "updated_vms": 0,
            "errors": 0
        }

        for vm_data in vms_data:
            try:
                # Chercher si la VM existe déjà POUR CET HYPERVISOR
                # D'abord par UUID
                existing_vm = self.db.query(VirtualMachine).filter(
                    VirtualMachine.source_hypervisor_id == hypervisor.id,
                    VirtualMachine.source_uuid == vm_data["source_uuid"]
                ).first()

                # Si pas trouvé par UUID, chercher par nom POUR CET HYPERVISOR
                if not existing_vm:
                    existing_vm = self.db.query(VirtualMachine).filter(
                        VirtualMachine.source_hypervisor_id == hypervisor.id,
                        VirtualMachine.name == vm_data["name"]
                    ).first()

                if existing_vm:
                    # Mettre à jour la VM existante
                    self._update_vm_from_discovery(existing_vm, vm_data)
                    stats["updated_vms"] += 1
                    logger.info(f"✅ VM mise à jour: {vm_data['name']}")
                else:
                    # Créer une nouvelle VM
                    new_vm = self._create_vm_from_discovery(hypervisor, vm_data)
                    self.db.add(new_vm)
                    self.db.flush()  # Forcer l'insertion immédiate
                    stats["new_vms"] += 1
                    logger.info(f"✅ Nouvelle VM créée: {vm_data['name']} (ID: {new_vm.id})")

            except (ValueError, KeyError, AttributeError, TypeError) as e:
                logger.error(f"❌ Erreur sauvegarde VM {vm_data.get('name', 'unknown')}: {str(e)}")
                logger.error(traceback.format_exc())
                stats["errors"] += 1

        self.db.commit()

        return stats

    def _create_vm_from_discovery(
            self,
            hypervisor: Hypervisor,
            vm_data: Dict[str, Any]
    ) -> VirtualMachine:
        """
        Crée une nouvelle VM depuis les données de découverte

        Args:
            hypervisor: Hypervisor source
            vm_data: Données de la VM découverte

        Returns:
            Instance VirtualMachine
        """
        vm = VirtualMachine(
            name=vm_data["name"],
            tenant_id=hypervisor.tenant_id,
            source_hypervisor_id=hypervisor.id,
            source_uuid=vm_data["source_uuid"],
            source_name=vm_data["source_name"],
            cpu_cores=vm_data.get("cpu_cores", 1),
            memory_mb=vm_data.get("memory_mb", 1024),
            disk_gb=vm_data.get("disk_gb", 10),
            os_type=vm_data.get("os_type"),
            os_version=vm_data.get("os_version"),
            os_name=vm_data.get("os_name"),
            ip_address=vm_data.get("ip_address"),
            mac_address=vm_data.get("mac_address"),
            hostname=vm_data.get("hostname"),
            status=VMStatus.DISCOVERED,
            compatibility_status=CompatibilityStatus.UNKNOWN,
            discovered_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc)
        )

        return vm

    def _update_vm_from_discovery(
            self,
            vm: VirtualMachine,
            vm_data: Dict[str, Any]
    ) -> None:
        """
        Met à jour une VM existante avec les nouvelles données

        Args:
            vm: VM existante à mettre à jour
            vm_data: Nouvelles données de découverte
        """
        # Mettre à jour les champs qui peuvent changer
        vm.cpu_cores = vm_data.get("cpu_cores", vm.cpu_cores)
        vm.memory_mb = vm_data.get("memory_mb", vm.memory_mb)
        vm.disk_gb = vm_data.get("disk_gb", vm.disk_gb)
        vm.ip_address = vm_data.get("ip_address", vm.ip_address)
        vm.mac_address = vm_data.get("mac_address", vm.mac_address)
        vm.hostname = vm_data.get("hostname", vm.hostname)
        vm.os_version = vm_data.get("os_version", vm.os_version)
        vm.last_seen_at = datetime.now(timezone.utc)

        # Mettre à jour le statut à discovered si ce n'est pas déjà le cas
        # (sauf si la VM est en migration ou migrée)
        if vm.status not in [VMStatus.MIGRATING, VMStatus.MIGRATED]:
            vm.status = VMStatus.DISCOVERED


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def create_discovery_service(db: Session) -> DiscoveryService:
    """Factory pour créer une instance du service de découverte"""
    return DiscoveryService(db)
