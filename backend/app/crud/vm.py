"""
ShiftWise VirtualMachine CRUD Operations

Opérations CRUD (Create, Read, Update, Delete) pour les machines virtuelles.

Toutes les fonctions prennent une session SQLAlchemy en paramètre
et retournent des objets du modèle VirtualMachine.
Filtrage multi-tenancy via tenant_id optionnel.
"""

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.virtual_machine import VirtualMachine, VMStatus, CompatibilityStatus


def get_vm(
        db: Session,
        vm_id: int,
        tenant_id: Optional[str] = None
) -> Optional[VirtualMachine]:
    """
    Recupere une VM par son ID.

    Args:
        db: Session de base de donnees
        vm_id: ID de la VM
        tenant_id: Si fourni, filtre par tenant (multi-tenancy)

    Returns:
        VirtualMachine si trouvee, None sinon
    """
    query = db.query(VirtualMachine).filter(VirtualMachine.id == vm_id)
    if tenant_id is not None:
        query = query.filter(VirtualMachine.tenant_id == tenant_id)
    return query.first()


def get_vm_by_name(db: Session, name: str) -> Optional[VirtualMachine]:
    """
    Recupere une VM par son nom.

    Args:
        db: Session de base de donnees
        name: Nom de la VM

    Returns:
        VirtualMachine si trouvee, None sinon
    """
    return db.query(VirtualMachine).filter(VirtualMachine.name == name).first()


def get_vms(
        db: Session,
        skip: int = 0,
        limit: int = 50,
        tenant_id: Optional[str] = None,
        status: Optional[VMStatus] = None,
        compatibility: Optional[CompatibilityStatus] = None,
        hypervisor_id: Optional[int] = None,
        search: Optional[str] = None
) -> List[VirtualMachine]:
    """
    Recupere une liste de VMs avec filtres et pagination.

    Args:
        db: Session de base de donnees
        skip: Nombre d'elements a ignorer (pagination)
        limit: Nombre maximum d'elements a retourner
        tenant_id: Filtrer par tenant (multi-tenancy)
        status: Filtrer par statut VM
        compatibility: Filtrer par statut de compatibilite
        hypervisor_id: Filtrer par hyperviseur source
        search: Rechercher par nom, IP ou hostname (ilike)

    Returns:
        Liste de VMs
    """
    query = db.query(VirtualMachine)

    if tenant_id is not None:
        query = query.filter(VirtualMachine.tenant_id == tenant_id)

    if status is not None:
        query = query.filter(VirtualMachine.status == status)

    if compatibility is not None:
        query = query.filter(VirtualMachine.compatibility_status == compatibility)

    if hypervisor_id is not None:
        query = query.filter(VirtualMachine.source_hypervisor_id == hypervisor_id)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                VirtualMachine.name.ilike(search_filter),
                VirtualMachine.ip_address.ilike(search_filter),
                VirtualMachine.hostname.ilike(search_filter)
            )
        )

    return query.offset(skip).limit(limit).all()


def get_vms_count(
        db: Session,
        tenant_id: Optional[str] = None,
        status: Optional[VMStatus] = None,
        compatibility: Optional[CompatibilityStatus] = None,
        hypervisor_id: Optional[int] = None,
        search: Optional[str] = None
) -> int:
    """
    Compte le nombre total de VMs avec les memes filtres.

    Args:
        db: Session de base de donnees
        tenant_id: Filtrer par tenant
        status: Filtrer par statut
        compatibility: Filtrer par compatibilite
        hypervisor_id: Filtrer par hyperviseur source
        search: Rechercher par nom, IP ou hostname

    Returns:
        Nombre de VMs correspondantes
    """
    query = db.query(VirtualMachine)

    if tenant_id is not None:
        query = query.filter(VirtualMachine.tenant_id == tenant_id)

    if status is not None:
        query = query.filter(VirtualMachine.status == status)

    if compatibility is not None:
        query = query.filter(VirtualMachine.compatibility_status == compatibility)

    if hypervisor_id is not None:
        query = query.filter(VirtualMachine.source_hypervisor_id == hypervisor_id)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                VirtualMachine.name.ilike(search_filter),
                VirtualMachine.ip_address.ilike(search_filter),
                VirtualMachine.hostname.ilike(search_filter)
            )
        )

    return query.count()


def create_vm(db: Session, data: dict, tenant_id: str) -> VirtualMachine:
    """
    Cree une nouvelle VM.

    Args:
        db: Session de base de donnees
        data: Champs de la VM (depuis schema.model_dump)
        tenant_id: Tenant proprietaire

    Returns:
        VirtualMachine creee

    Raises:
        ValueError: Si une VM avec ce nom existe deja
    """
    existing = get_vm_by_name(db, data.get("name", ""))
    if existing:
        raise ValueError(f"Une VM avec le nom '{data['name']}' existe deja")

    vm = VirtualMachine(
        **data,
        tenant_id=tenant_id,
        status=VMStatus.DISCOVERED,
        compatibility_status=CompatibilityStatus.UNKNOWN
    )

    db.add(vm)
    db.commit()
    db.refresh(vm)

    return vm


# Champs proteges — geres exclusivement par Discovery Service et Analyzer
_VM_PROTECTED_FIELDS = {"status", "compatibility_status"}


def update_vm(
        db: Session,
        vm_id: int,
        update_data: dict,
        tenant_id: Optional[str] = None
) -> Optional[VirtualMachine]:
    """
    Met a jour une VM existante.

    Les champs proteges (status, compatibility_status) sont exclus
    automatiquement — ils sont geres par Discovery Service et Analyzer.

    Args:
        db: Session de base de donnees
        vm_id: ID de la VM a mettre a jour
        update_data: Champs a mettre a jour (exclude_unset=True)
        tenant_id: Si fourni, filtre par tenant

    Returns:
        VirtualMachine mise a jour si trouvee, None sinon
    """
    vm = get_vm(db, vm_id, tenant_id=tenant_id)
    if not vm:
        return None

    for field, value in update_data.items():
        if field not in _VM_PROTECTED_FIELDS:
            setattr(vm, field, value)

    db.commit()
    db.refresh(vm)

    return vm


def delete_vm(
        db: Session,
        vm_id: int,
        tenant_id: Optional[str] = None
) -> bool:
    """
    Supprime une VM.

    Args:
        db: Session de base de donnees
        vm_id: ID de la VM a supprimer
        tenant_id: Si fourni, filtre par tenant

    Returns:
        True si supprimee, False si non trouvee

    Note:
        Les migrations associees seront supprimees en cascade (CASCADE).
    """
    vm = get_vm(db, vm_id, tenant_id=tenant_id)
    if not vm:
        return False

    db.delete(vm)
    db.commit()

    return True
