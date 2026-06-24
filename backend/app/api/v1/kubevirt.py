"""
Routes API pour l'intégration KubeVirt / OpenShift Virtualization

Endpoints pour interagir directement avec le cluster OpenShift.
"""

import socket

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Annotated, NoReturn, Optional

from urllib3.exceptions import HTTPError as Urllib3HTTPError

from app.core.config import settings
from app.core.kubevirt_client import KubeVirtClient, KubeVirtClientError, get_kubevirt_client
from app.api.deps import check_permission, validate_kubevirt_namespace
from app.models.user import User
from app.schemas.kubevirt import KubeVirtVMCreate

router = APIRouter()

# Audit I / S1192 — resource + action literals reused across the router.
RESOURCE_VMS = "vms"
ACTION_READ = "read"
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"

# Audit C-10 / H-24 — connectivity failures the kubernetes client raises when
# the cluster API server is unreachable. They do NOT subclass ApiException, so
# without this set they escaped the handlers as a raw 500 (and leaked the
# internal cluster hostname). Mapped to 503 with a clean message instead.
_CONNECTIVITY_ERRORS = (Urllib3HTTPError, ConnectionError, socket.timeout, OSError)

_CLUSTER_UNREACHABLE_MSG = (
    "Cluster OpenShift injoignable — réessayez plus tard."
)


def _raise_cluster_unreachable() -> NoReturn:
    """503 for a cluster-connectivity failure (Audit C-10).

    The raw exception is intentionally not echoed: it carries the internal
    API-server hostname (see Audit C-02 / K2).
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_CLUSTER_UNREACHABLE_MSG,
    )


@router.get("/vms")
def list_kubevirt_vms(
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        label_selector: Annotated[Optional[str], Query(description="Sélecteur de labels")] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_READ))] = None
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
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        ) from e


@router.get("/vms/{vm_name}")
def get_kubevirt_vm(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_READ))] = None
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
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        ) from e


@router.get("/vms/{vm_name}/status")
def get_kubevirt_vm_status(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_READ))] = None
):
    """
    Récupère le statut détaillé d'une VM dans OpenShift.

    **Permissions requises :** vms:read
    """
    try:
        status_info = kube_client.get_vm_status(name=vm_name, namespace=namespace)

        return status_info
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        ) from e


@router.post("/vms", status_code=status.HTTP_201_CREATED)
def create_kubevirt_vm(
        vm_data: KubeVirtVMCreate,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_CREATE))] = None
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
            run_strategy=vm_data.run_strategy
        )

        return {
            "message": f"VM '{vm_data.name}' créée avec succès",
            "vm": vm
        }
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création: {str(e)}"
        ) from e


@router.delete("/vms/{vm_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kubevirt_vm(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_DELETE))] = None
):
    """
    Supprime une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:delete

    Retourne 204 No Content en cas de succès (aucun corps de réponse).
    """
    try:
        success = kube_client.delete_vm(name=vm_name, namespace=namespace)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"VM '{vm_name}' introuvable"
            )

        return None
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        ) from e


@router.post("/vms/{vm_name}/start", status_code=status.HTTP_202_ACCEPTED)
def start_kubevirt_vm(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_UPDATE))] = None
):
    """
    Démarre une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:update

    Retourne 202 Accepted — le démarrage du VMI est asynchrone côté cluster.
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
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du démarrage: {str(e)}"
        ) from e


@router.post("/vms/{vm_name}/stop", status_code=status.HTTP_202_ACCEPTED)
def stop_kubevirt_vm(
        vm_name: str,
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_UPDATE))] = None
):
    """
    Arrête une VirtualMachine dans OpenShift.

    **Permissions requises :** vms:update

    Retourne 202 Accepted — l'arrêt du VMI est asynchrone côté cluster.
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
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'arrêt: {str(e)}"
        ) from e


@router.get("/vmis")
def list_kubevirt_vmis(
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        label_selector: Annotated[Optional[str], Query(description="Sélecteur de labels")] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_READ))] = None
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
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        ) from e


@router.get("/storage-classes")
def list_storage_classes(
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_READ))] = None
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
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur KubeVirt: {str(e)}"
        ) from e


@router.get("/namespace-info")
def get_namespace_info(
        namespace: Annotated[str, Depends(validate_kubevirt_namespace)],
        kube_client: Annotated[KubeVirtClient, Depends(get_kubevirt_client)],
        current_user: Annotated[User, Depends(check_permission(RESOURCE_VMS, ACTION_READ))] = None
):
    """
    Informations sur le namespace OpenShift du tenant.

    **Permissions requises :** vms:read

    Audit B5 / H-11 — les compteurs VM/VMI sont scopés au namespace du tenant
    (``validate_kubevirt_namespace``). Sans ce scope, un utilisateur voyait
    le décompte de VMs de tous les tenants du cluster.
    """
    try:
        vms_total = len(kube_client.list_vms(namespace=namespace))
        vmis_running = len(kube_client.list_vmis(namespace=namespace))
        storage_classes = kube_client.list_storage_classes()

        return {
            "connected": True,
            "mode": settings.KUBERNETES_MODE,
            "namespace": namespace,
            "vms_total": vms_total,
            "vmis_running": vmis_running,
            "storage_classes_count": len(storage_classes),
            "storage_classes": storage_classes
        }
    except _CONNECTIVITY_ERRORS:
        _raise_cluster_unreachable()
    except KubeVirtClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur de connexion au cluster: {str(e)}"
        ) from e
