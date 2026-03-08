"""
ShiftWise KubeVirt Client

Interface Python pour interagir avec l'API KubeVirt d'OpenShift Virtualization.
Gère la création, lecture, mise à jour et suppression des VirtualMachines.

Supporte 3 modes de connexion :
- kubeconfig : Fichier kubeconfig local (développement)
- incluster  : ServiceAccount du pod (production dans OpenShift)
- custom     : URL et token personnalisés (production externe)

Usage:
    from app.core.kubevirt_client import KubeVirtClient

    client = KubeVirtClient()
    vms = client.list_vms()
    vm = client.get_vm("test-vm")
    client.create_vm("new-vm", cpu=2, memory="4Gi")
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from app.core.config import settings

# Configuration du logger
logger = logging.getLogger(__name__)


class KubeVirtClientError(Exception):
    """Exception de base pour les erreurs du KubeVirt Client"""
    pass


class KubeVirtClient:
    """
    Client pour interagir avec l'API KubeVirt d'OpenShift Virtualization.

    Gère automatiquement la connexion selon le mode configuré dans .env :
    - Mode kubeconfig : Utilise le fichier kubeconfig local
    - Mode incluster  : Utilise le ServiceAccount du pod
    - Mode custom     : Utilise URL et token personnalisés
    """

    # Constantes API KubeVirt
    GROUP = "kubevirt.io"
    VERSION = "v1"
    VM_PLURAL = "virtualmachines"
    VMI_PLURAL = "virtualmachineinstances"

    def __init__(self):
        """
        Initialise le client KubeVirt.

        La méthode de connexion est déterminée automatiquement selon :
        1. Si KUBERNETES_SERVICE_HOST existe → Mode incluster
        2. Sinon, utilise le mode configuré dans settings.KUBERNETES_MODE

        Raises:
            KubeVirtClientError: Si la connexion échoue
        """
        try:
            # Détecter automatiquement si on est dans un cluster
            if settings.is_kubernetes_incluster and settings.USE_IN_CLUSTER:
                self._load_incluster_config()

            elif settings.KUBERNETES_MODE == "custom":
                self._load_custom_config()

            else:  # Mode kubeconfig (par défaut)
                self._load_kubeconfig()

            # Initialiser les clients API
            self.api = client.CustomObjectsApi()
            self.core_api = client.CoreV1Api()
            self.storage_api = client.StorageV1Api()

            logger.info("✅ KubeVirt client initialized successfully")

        except Exception as e:
            logger.error(f"❌ Failed to initialize KubeVirt client: {e}")
            raise KubeVirtClientError(f"Initialization failed: {e}") from e

    def _load_incluster_config(self):
        """Charge la configuration in-cluster (ServiceAccount du pod)"""
        config.load_incluster_config()
        logger.info("🔧 Loaded IN-CLUSTER config (Production mode)")

    def _load_custom_config(self):
        """Charge une configuration personnalisée (URL + Token)"""
        if not settings.KUBERNETES_API_URL or not settings.KUBERNETES_TOKEN:
            raise KubeVirtClientError(
                "KUBERNETES_API_URL and KUBERNETES_TOKEN must be set for custom mode"
            )

        configuration = client.Configuration()
        configuration.host = settings.KUBERNETES_API_URL
        configuration.api_key["authorization"] = settings.KUBERNETES_TOKEN
        configuration.api_key_prefix["authorization"] = "Bearer"
        configuration.verify_ssl = settings.KUBERNETES_VERIFY_SSL

        client.Configuration.set_default(configuration)
        logger.info(f"🔧 Loaded CUSTOM config (API: {settings.KUBERNETES_API_URL})")

    def _load_kubeconfig(self):
        """Charge la configuration depuis un fichier kubeconfig"""
        kube_path = settings.KUBECONFIG_PATH

        if not kube_path:
            # Fallback: ~/.kube/config
            config.load_kube_config()
            logger.info("🔧 Loaded kubeconfig from default location (~/.kube/config)")
            return

        # Convertir chemin relatif en absolu
        if not Path(kube_path).is_absolute():
            base_path = Path(__file__).parent.parent.parent  # backend/
            kube_path = str(base_path / kube_path)

        if not os.path.exists(kube_path):
            raise KubeVirtClientError(f"Kubeconfig not found: {kube_path}")

        config.load_kube_config(config_file=kube_path)
        logger.info(f"🔧 Loaded kubeconfig from: {kube_path}")

    # ========================================
    # GESTION DES VIRTUALMACHINES
    # ========================================

    def list_vms(
        self,
        namespace: str | None = None,
        label_selector: str | None = None
    ) -> List[Dict[str, Any]]:
        """
        Liste toutes les VirtualMachines dans un namespace.

        Args:
            namespace: Namespace Kubernetes (défaut: settings.KUBERNETES_DEFAULT_NAMESPACE)
            label_selector: Filtre par labels (ex: "app=myapp,env=prod")

        Returns:
            Liste des VMs avec leurs métadonnées et statuts

        Raises:
            KubeVirtClientError: Si l'API retourne une erreur
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE

        try:
            kwargs = {"label_selector": label_selector} if label_selector else {}

            response = self.api.list_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=namespace,
                plural=self.VM_PLURAL,
                **kwargs
            )

            vms = response.get("items", [])
            logger.info(f"📋 Found {len(vms)} VMs in namespace '{namespace}'")
            return vms

        except ApiException as e:
            logger.error(f"❌ Error listing VMs: {e}")
            raise KubeVirtClientError(f"Failed to list VMs: {e}") from e

    def get_vm(
        self,
        name: str,
        namespace: str | None = None
    ) -> Dict[str, Any] | None:
        """
        Récupère une VirtualMachine spécifique.

        Args:
            name: Nom de la VM
            namespace: Namespace Kubernetes

        Returns:
            Dictionnaire contenant les détails de la VM ou None si non trouvée
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE

        try:
            vm = self.api.get_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=namespace,
                plural=self.VM_PLURAL,
                name=name
            )
            logger.info(f"📄 Retrieved VM '{name}' from namespace '{namespace}'")
            return vm

        except ApiException as e:
            if e.status == 404:
                logger.warning(f"⚠️ VM '{name}' not found in namespace '{namespace}'")
                return None
            logger.error(f"❌ Error getting VM '{name}': {e}")
            raise KubeVirtClientError(f"Failed to get VM: {e}") from e

    def create_vm(
        self,
        name: str,
        namespace: str | None = None,
        cpu: int = 1,
        memory: str = "2Gi",
        image: str = "quay.io/containerdisks/fedora:latest",
        disk_size: str | None = None,
        storage_class: str | None = "nfs-client",
        run_strategy: str = "Always",
        labels: Dict[str, str] | None = None,
        annotations: Dict[str, str] | None = None
    ) -> Dict[str, Any]:
        """
        Crée une nouvelle VirtualMachine.

        Args:
            name: Nom de la VM
            namespace: Namespace Kubernetes
            cpu: Nombre de vCPUs
            memory: Mémoire (ex: "2Gi", "4Gi")
            image: Image container ou DataVolume
            disk_size: Taille du disque persistant (ex: "10Gi")
            storage_class: StorageClass pour les PVCs
            run_strategy: "Always", "Manual", "Halted"
            labels: Labels Kubernetes additionnels
            annotations: Annotations Kubernetes additionnelles

        Returns:
            VM créée avec son état initial

        Raises:
            KubeVirtClientError: Si la création échoue
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE

        # Construction du manifeste VM
        vm_manifest = self._build_vm_manifest(
            name=name,
            namespace=namespace,
            cpu=cpu,
            memory=memory,
            image=image,
            disk_size=disk_size,
            storage_class=storage_class,
            run_strategy=run_strategy,
            labels=labels or {},
            annotations=annotations or {}
        )

        try:
            vm = self.api.create_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=namespace,
                plural=self.VM_PLURAL,
                body=vm_manifest
            )
            logger.info(f"✅ Created VM '{name}' in namespace '{namespace}'")
            return vm

        except ApiException as e:
            logger.error(f"❌ Error creating VM '{name}': {e}")
            raise KubeVirtClientError(f"Failed to create VM: {e}") from e

    def delete_vm(
        self,
        name: str,
        namespace: str | None = None
    ) -> bool:
        """
        Supprime une VirtualMachine.

        Args:
            name: Nom de la VM
            namespace: Namespace Kubernetes

        Returns:
            True si suppression réussie, False sinon
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE

        try:
            self.api.delete_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=namespace,
                plural=self.VM_PLURAL,
                name=name
            )
            logger.info(f"🗑️ Deleted VM '{name}' from namespace '{namespace}'")
            return True

        except ApiException as e:
            if e.status == 404:
                logger.warning(f"⚠️ VM '{name}' not found, cannot delete")
                return False
            logger.error(f"❌ Error deleting VM '{name}': {e}")
            raise KubeVirtClientError(f"Failed to delete VM: {e}") from e

    # ========================================
    # GESTION DES VIRTUALMACHINEINSTANCES
    # ========================================

    def list_vmis(
        self,
        namespace: str | None = None,
        label_selector: str | None = None
    ) -> List[Dict[str, Any]]:
        """
        Liste toutes les VirtualMachineInstances (VMs en cours d'exécution).

        Args:
            namespace: Namespace Kubernetes
            label_selector: Filtre par labels

        Returns:
            Liste des VMIs avec leurs statuts
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE

        try:
            kwargs = {"label_selector": label_selector} if label_selector else {}

            response = self.api.list_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=namespace,
                plural=self.VMI_PLURAL,
                **kwargs
            )

            vmis = response.get("items", [])
            logger.info(f"📋 Found {len(vmis)} VMIs in namespace '{namespace}'")
            return vmis

        except ApiException as e:
            logger.error(f"❌ Error listing VMIs: {e}")
            raise KubeVirtClientError(f"Failed to list VMIs: {e}") from e

    def get_vmi(
        self,
        name: str,
        namespace: str | None = None
    ) -> Dict[str, Any] | None:
        """
        Récupère une VirtualMachineInstance spécifique.

        Args:
            name: Nom de la VMI
            namespace: Namespace

        Returns:
            VMI details ou None si non trouvée
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE

        try:
            vmi = self.api.get_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=namespace,
                plural=self.VMI_PLURAL,
                name=name
            )
            return vmi

        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(f"❌ Error getting VMI '{name}': {e}")
            raise KubeVirtClientError(f"Failed to get VMI: {e}") from e

    # ========================================
    # CONTRÔLE D'ÉTAT DES VMS
    # ========================================

    def start_vm(
        self,
        name: str,
        namespace: str | None = None
    ) -> bool:
        """
        Démarre une VM (équivalent à virtctl start).

        Args:
            name: Nom de la VM
            namespace: Namespace

        Returns:
            True si démarrage réussi
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE
        vm = self.get_vm(name, namespace)

        if not vm:
            raise KubeVirtClientError(f"VM '{name}' not found")

        vm["spec"]["runStrategy"] = "Always"

        try:
            self.api.replace_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=namespace,
                plural=self.VM_PLURAL,
                name=name,
                body=vm
            )
            logger.info(f"▶️ Started VM '{name}'")
            return True

        except ApiException as e:
            logger.error(f"❌ Error starting VM '{name}': {e}")
            raise KubeVirtClientError(f"Failed to start VM: {e}") from e

    def stop_vm(
        self,
        name: str,
        namespace: str | None = None
    ) -> bool:
        """
        Arrête une VM (équivalent à virtctl stop).

        Args:
            name: Nom de la VM
            namespace: Namespace

        Returns:
            True si arrêt réussi
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE
        vm = self.get_vm(name, namespace)

        if not vm:
            raise KubeVirtClientError(f"VM '{name}' not found")

        vm["spec"]["runStrategy"] = "Halted"

        try:
            self.api.replace_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=namespace,
                plural=self.VM_PLURAL,
                name=name,
                body=vm
            )
            logger.info(f"⏹️ Stopped VM '{name}'")
            return True

        except ApiException as e:
            logger.error(f"❌ Error stopping VM '{name}': {e}")
            raise KubeVirtClientError(f"Failed to stop VM: {e}") from e

    # ========================================
    # UTILITAIRES
    # ========================================

    def get_vm_status(
        self,
        name: str,
        namespace: str | None = None
    ) -> Dict[str, Any]:
        """
        Récupère le statut détaillé d'une VM.

        Returns:
            Dictionnaire avec: status, ready, phase, ip, node, etc.
        """
        namespace = namespace or settings.KUBERNETES_DEFAULT_NAMESPACE
        vm = self.get_vm(name, namespace)
        vmi = self.get_vmi(name, namespace)

        if not vm:
            return {"error": "VM not found"}

        status = {
            "name": name,
            "namespace": namespace,
            "status": vm.get("status", {}).get("printableStatus", "Unknown"),
            "ready": vm.get("status", {}).get("ready", False),
            "created": vm.get("status", {}).get("created", False),
        }

        if vmi:
            status.update({
                "phase": vmi.get("status", {}).get("phase", "Unknown"),
                "node": vmi.get("status", {}).get("nodeName", "N/A"),
                "ip": self._get_vmi_ip(vmi),
                "live_migratable": self._is_live_migratable(vmi)
            })

        return status

    def list_storage_classes(self) -> List[str]:
        """
        Liste les StorageClasses disponibles pour les VMs.

        Returns:
            Liste des noms de StorageClasses
        """
        try:
            scs = self.storage_api.list_storage_class()
            return [sc.metadata.name for sc in scs.items]
        except ApiException as e:
            logger.error(f"❌ Error listing storage classes: {e}")
            return []

    # ========================================
    # MÉTHODES PRIVÉES
    # ========================================

    def _build_vm_manifest(
            self,
            name: str,
            namespace: str,
            cpu: int,
            memory: str,
            image: str,
            disk_size: str | None,
            storage_class: str | None,
            run_strategy: str,
            labels: Dict[str, str],
            annotations: Dict[str, str]
    ) -> Dict[str, Any]:
        """Construit le manifeste YAML d'une VirtualMachine."""

        base_labels = {
            "kubevirt.io/vm": name,
            "app.shiftwise.io/managed": "true"
        }
        base_labels.update(labels)

        manifest = {
            "apiVersion": f"{self.GROUP}/{self.VERSION}",
            "kind": "VirtualMachine",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "labels": base_labels,
                "annotations": annotations
            },
            "spec": {
                "runStrategy": run_strategy,
                "template": {
                    "metadata": {
                        "labels": base_labels
                    },
                    "spec": {
                        "domain": {
                            "devices": {
                                "disks": []
                            },
                            "resources": {
                                "requests": {
                                    "cpu": str(cpu),
                                    "memory": memory
                                }
                            }
                        },
                        "volumes": []
                    }
                }
            }
        }

        # ========================================
        # GESTION DES DISQUES (NOUVEAU)
        # ========================================

        if disk_size and storage_class:
            # Disque persistant avec PVC
            manifest["spec"]["template"]["spec"]["domain"]["devices"]["disks"].append({
                "name": "datavolumedisk",
                "disk": {"bus": "virtio"}
            })
            manifest["spec"]["template"]["spec"]["volumes"].append({
                "name": "datavolumedisk",
                "persistentVolumeClaim": {
                    "claimName": f"{name}-pvc"
                }
            })

            # Note: Le PVC doit être créé séparément
            # TODO: Implémenter create_pvc() pour créer automatiquement le PVC
            logger.warning(
                f"⚠️ Persistent disk requested ({disk_size}) but PVC must be created manually"
            )
        else:
            # ContainerDisk (éphémère) par défaut
            manifest["spec"]["template"]["spec"]["domain"]["devices"]["disks"].append({
                "name": "containerdisk",
                "disk": {"bus": "virtio"}
            })
            manifest["spec"]["template"]["spec"]["volumes"].append({
                "name": "containerdisk",
                "containerDisk": {"image": image}
            })

        return manifest

    def _get_vmi_ip(self, vmi: Dict[str, Any]) -> str:
        """Extrait l'IP d'une VMI."""
        interfaces = vmi.get("status", {}).get("interfaces", [])
        if interfaces:
            return interfaces[0].get("ipAddress", "N/A")
        return "N/A"

    def _is_live_migratable(self, vmi: Dict[str, Any]) -> bool:
        """Vérifie si la VMI est Live Migratable."""
        conditions = vmi.get("status", {}).get("conditions", [])
        for condition in conditions:
            if condition.get("type") == "LiveMigratable":
                return condition.get("status") == "True"
        return False