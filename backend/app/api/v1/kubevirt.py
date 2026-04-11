"""
Routes API pour l'intégration KubeVirt / OpenShift Virtualization

Endpoints pour interagir directement avec le cluster OpenShift.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Annotated, Optional, List

from app.core.config import settings
from app.core.database import get_db
from app.core.kubevirt_client import KubeVirtClient, KubeVirtClientError
from app.api.deps import get_current_user, check_permission, validate_kubevirt_namespace
from app.models.user import User

router = APIRouter()


@router.get("/vms")
def list_kubevirt_vms(
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        label_selector: Annotated[Optional[str], Query(description="Sélecteur de labels")] = None,
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Liste les VirtualMachines dans OpenShift.

    **Permissions requises :** vms:read

    Utilise le KubeVirtClient pour interroger directement le cluster OpenShift.
    """
    try:
        client = KubeVirtClient()
        vms = client.list_vms(namespace=namespace, label_selector=label_selector)

        return {
            "namespace": namespace,
            "total": len(vms),
            "vms": vms
        }
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        )


@router.get("/vms/{vm_name}")
def get_kubevirt_vm(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Récupère les détails d'une VM dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        client = KubeVirtClient()
        vm = client.get_vm(name=vm_name, namespace=namespace)

        if not vm:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"VM '{vm_name}' introuvable dans le namespace '{namespace}'"
            )

        return vm
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        )


@router.get("/vms/{vm_name}/status")
def get_kubevirt_vm_status(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Récupère le statut détaillé d'une VM dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        client = KubeVirtClient()
        status_info = client.get_vm_status(name=vm_name, namespace=namespace)

        return status_info
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        )


@router.post("/vms")
def create_kubevirt_vm(
        name: Annotated[str, Query(description="Nom de la VM")],
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        cpu: Annotated[int, Query(ge=1, le=64, description="Nombre de vCPUs")] = 1,
        memory: Annotated[str, Query(description="Mémoire (ex: 2Gi, 4Gi)")] = "2Gi",
        image: Annotated[str, Query(description="Image container")] = "quay.io/containerdisks/fedora:latest",
        disk_size: Annotated[Optional[str], Query(description="Taille disque persistant")] = None,
        storage_class: Annotated[str, Query(description="StorageClass")] = "nfs-client",
        run_strategy: Annotated[str, Query(description="RunStrategy")] = "Always",
        current_user: Annotated[User, Depends(check_permission("vms", "create"))] = None
):
    """
    Crée une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:create

    **Exemples d'images :**
    - `quay.io/containerdisks/fedora:latest`
    - `quay.io/containerdisks/centos-stream:9`
    - `quay.io/containerdisks/ubuntu:22.04`
    """
    try:
        client = KubeVirtClient()

        vm = client.create_vm(
            name=name,
            namespace=namespace,
            cpu=cpu,
            memory=memory,
            image=image,
            disk_size=disk_size,
            storage_class=storage_class,
            run_strategy=run_strategy
        )

        return {
            "message": f"VM '{name}' créée avec succès",
            "vm": vm
        }
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création: {str(e)}"
        )


@router.delete("/vms/{vm_name}")
def delete_kubevirt_vm(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        current_user: Annotated[User, Depends(check_permission("vms", "delete"))] = None
):
    """
    Supprime une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:delete
    """
    try:
        client = KubeVirtClient()
        success = client.delete_vm(name=vm_name, namespace=namespace)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"VM '{vm_name}' introuvable"
            )

        return {
            "message": f"VM '{vm_name}' supprimée avec succès"
        }
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )


@router.post("/vms/{vm_name}/start")
def start_kubevirt_vm(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        current_user: Annotated[User, Depends(check_permission("vms", "update"))] = None
):
    """
    Démarre une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:update
    """
    try:
        client = KubeVirtClient()
        success = client.start_vm(name=vm_name, namespace=namespace)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"VM '{vm_name}' introuvable"
            )

        return {
            "message": f"VM '{vm_name}' démarrée avec succès"
        }
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du démarrage: {str(e)}"
        )


@router.post("/vms/{vm_name}/stop")
def stop_kubevirt_vm(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        current_user: Annotated[User, Depends(check_permission("vms", "update"))] = None
):
    """
    Arrête une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:update
    """
    try:
        client = KubeVirtClient()
        success = client.stop_vm(name=vm_name, namespace=namespace)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"VM '{vm_name}' introuvable"
            )

        return {
            "message": f"VM '{vm_name}' arrêtée avec succès"
        }
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'arrêt: {str(e)}"
        )


@router.get("/vmis")
def list_kubevirt_vmis(
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        label_selector: Annotated[Optional[str], Query(description="Sélecteur de labels")] = None,
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Liste les VirtualMachineInstances (VMs en cours d'exécution) dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        client = KubeVirtClient()
        vmis = client.list_vmis(namespace=namespace, label_selector=label_selector)

        return {
            "namespace": namespace,
            "total": len(vmis),
            "vmis": vmis
        }
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        )


@router.get("/storage-classes")
def list_storage_classes(
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Liste les StorageClasses disponibles dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        client = KubeVirtClient()
        storage_classes = client.list_storage_classes()

        return {
            "total": len(storage_classes),
            "storage_classes": storage_classes
        }
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        )


@router.get("/cluster-info")
def get_cluster_info(
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Informations sur le cluster OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        client = KubeVirtClient()

        # Récupérer quelques infos
        vms_total = len(client.list_vms())
        vmis_running = len(client.list_vmis())
        storage_classes = client.list_storage_classes()

        return {
            "connected": True,
            "mode": settings.KUBERNETES_MODE,
            "namespace_default": settings.KUBERNETES_DEFAULT_NAMESPACE,
            "vms_total": vms_total,
            "vmis_running": vmis_running,
            "storage_classes_count": len(storage_classes),
            "storage_classes": storage_classes
        }
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur de connexion au cluster: {str(e)}"
        )