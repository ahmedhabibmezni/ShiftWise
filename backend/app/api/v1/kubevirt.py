"""
Routes API pour l'intégration KubeVirt / OpenShift Virtualization

Endpoints pour interagir directement avec le cluster OpenShift.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Annotated, Optional

from app.core.config import settings
from app.core.kubevirt_client import KubeVirtClient, KubeVirtClientError, get_kubevirt_client
from app.api.deps import check_permission, validate_kubevirt_namespace
from app.models.user import User
from app.schemas.kubevirt import KubeVirtVMCreate

router = APIRouter()


@router.get("/vms")
def list_kubevirt_vms(
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        label_selector: Annotated[Optional[str], Query(description="Sélecteur de labels")] = None,
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Liste les VirtualMachines dans OpenShift.

    **Permissions requises :** vms:read

    Utilise le KubeVirtClient pour interroger directement le cluster OpenShift.
    """
    try:
        vms = kube_client.list_vms(namespace=namespace, label_selector=label_selector)

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
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Récupère les détails d'une VM dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        vm = kube_client.get_vm(name=vm_name, namespace=namespace)

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
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Récupère le statut détaillé d'une VM dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        status_info = kube_client.get_vm_status(name=vm_name, namespace=namespace)

        return status_info
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        )


@router.post("/vms")
def create_kubevirt_vm(
        vm_data: KubeVirtVMCreate,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
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
        vm = kube_client.create_vm(
            name=vm_data.name,
            namespace=namespace,
            cpu=vm_data.cpu,
            memory=vm_data.memory,
            image=vm_data.image,
            disk_size=vm_data.disk_size,
            storage_class=vm_data.storage_class,
            run_strategy=vm_data.run_strategy
        )

        return {
            "message": f"VM '{vm_data.name}' créée avec succès",
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
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission("vms", "delete"))] = None
):
    """
    Supprime une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:delete
    """
    try:
        success = kube_client.delete_vm(name=vm_name, namespace=namespace)

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
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission("vms", "update"))] = None
):
    """
    Démarre une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:update
    """
    try:
        success = kube_client.start_vm(name=vm_name, namespace=namespace)

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
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission("vms", "update"))] = None
):
    """
    Arrête une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:update
    """
    try:
        success = kube_client.stop_vm(name=vm_name, namespace=namespace)

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
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        label_selector: Annotated[Optional[str], Query(description="Sélecteur de labels")] = None,
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Liste les VirtualMachineInstances (VMs en cours d'exécution) dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        vmis = kube_client.list_vmis(namespace=namespace, label_selector=label_selector)

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
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Liste les StorageClasses disponibles dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        storage_classes = kube_client.list_storage_classes()

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
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission("vms", "read"))] = None
):
    """
    Informations sur le cluster OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        vms_total = len(kube_client.list_vms())
        vmis_running = len(kube_client.list_vmis())
        storage_classes = kube_client.list_storage_classes()

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
