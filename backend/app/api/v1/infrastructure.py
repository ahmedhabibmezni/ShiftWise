"""
Router Infrastructure — gestion de la connectivité cluster (feature 002).

Endpoints sous ``/api/v1/infrastructure``. RBAC via
``check_permission("infrastructure", ...)`` (superuser bypass). Le scoping
tenant est appliqué DANS le corps des handlers (``_resolve_and_authorize_scope``)
pour rester visible au site d'appel (Constitution III) et testable
directement.

Ordre des routes : segments statiques (``/scopes``) AVANT la route dynamique
``/{scope}`` (Constitution VI).
"""

from __future__ import annotations

from typing import Annotated, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import check_permission
from app.core.config import settings
from app.core.database import get_db
from app.crud import cluster_config as crud_cluster
from app.models.cluster_config import ClusterScopeType
from app.models.user import User
from app.schemas.cluster_config import (
    ClusterConfigRead,
    ClusterConfigScopeEntry,
    ClusterConfigScopeList,
    ClusterConfigUpsert,
    ConnectionTestResult,
)
from app.services.cluster import resolver
from app.services.cluster.validation import (
    InvalidKubeconfig,
    KubeconfigTooLarge,
    ModeNotApplicable,
    assert_mode_applicable,
    validate_kubeconfig_bytes,
)

router = APIRouter()

# S1192 — littéral réutilisé.
RESOURCE_INFRA = "infrastructure"
ACTION_READ = "read"
ACTION_UPDATE = "update"

_PLATFORM_DEFAULT_SCOPE = "platform-default"
_TENANT_PREFIX = "tenant:"

# Codes d'erreur (contracts/infrastructure-api.md).
ERR_MODE_NOT_APPLICABLE = "ERR_MODE_NOT_APPLICABLE"
ERR_INVALID_HOST = "ERR_INVALID_HOST"
ERR_INVALID_KUBECONFIG = "ERR_INVALID_KUBECONFIG"
ERR_KUBECONFIG_TOO_LARGE = "ERR_KUBECONFIG_TOO_LARGE"
ERR_CANNOT_DELETE_DEFAULT = "ERR_CANNOT_DELETE_DEFAULT"
ERR_FORBIDDEN_SCOPE = "ERR_FORBIDDEN_SCOPE"


def _err(status_code: int, code: str, message: str) -> HTTPException:
    """Construit une HTTPException au format d'erreur du contrat."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _parse_scope(scope: str) -> Tuple[ClusterScopeType, Optional[str]]:
    """Décode le param de chemin en (scope_type, tenant_id)."""
    if scope == _PLATFORM_DEFAULT_SCOPE:
        return ClusterScopeType.PLATFORM_DEFAULT, None
    if scope.startswith(_TENANT_PREFIX):
        tenant_id = scope[len(_TENANT_PREFIX):]
        if tenant_id:
            return ClusterScopeType.TENANT, tenant_id
    raise _err(
        status.HTTP_404_NOT_FOUND, ERR_FORBIDDEN_SCOPE,
        f"unknown scope '{scope}'",
    )


def _resolve_and_authorize_scope(
    scope: str, current_user: User
) -> Tuple[ClusterScopeType, Optional[str]]:
    """Décode le scope et vérifie que l'appelant a le droit d'y accéder.

    Garde explicite (Constitution III) : un non-superuser ne peut viser que
    son propre tenant ; le défaut plateforme et les autres tenants sont
    interdits.
    """
    scope_type, tenant_id = _parse_scope(scope)
    if current_user.is_superuser:
        return scope_type, tenant_id
    if scope_type == ClusterScopeType.PLATFORM_DEFAULT or tenant_id != current_user.tenant_id:
        raise _err(
            status.HTTP_403_FORBIDDEN, ERR_FORBIDDEN_SCOPE,
            "not authorized for this configuration scope",
        )
    return scope_type, tenant_id


def _to_read(cfg) -> ClusterConfigRead:
    return ClusterConfigRead.model_validate(cfg)


# ---------------------------------------------------------------------------
# Routes statiques d'abord
# ---------------------------------------------------------------------------

@router.get("/scopes", response_model=ClusterConfigScopeList)
def list_scopes(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(check_permission(RESOURCE_INFRA, ACTION_READ))],
) -> ClusterConfigScopeList:
    """Liste les scopes visibles par l'appelant."""
    if current_user.is_superuser:
        return _list_scopes_superuser(db)
    return _list_scopes_tenant(db, current_user.tenant_id)


def _list_scopes_superuser(db: Session) -> ClusterConfigScopeList:
    """Défaut plateforme + une entrée par tenant ayant une config propre."""
    items: list[ClusterConfigScopeEntry] = []
    default = crud_cluster.get_platform_default(db)
    items.append(
        ClusterConfigScopeEntry(
            scope_type=ClusterScopeType.PLATFORM_DEFAULT,
            tenant_id=None,
            using_platform_default=False,
            config=_to_read(default) if default else None,
        )
    )
    for cfg in crud_cluster.list_all(db):
        if cfg.scope_type == ClusterScopeType.TENANT:
            items.append(
                ClusterConfigScopeEntry(
                    scope_type=ClusterScopeType.TENANT,
                    tenant_id=cfg.tenant_id,
                    using_platform_default=False,
                    config=_to_read(cfg),
                )
            )
    return ClusterConfigScopeList(items=items)


def _list_scopes_tenant(db: Session, tenant_id: str) -> ClusterConfigScopeList:
    """Vue tenant admin : uniquement son propre scope."""
    cfg = crud_cluster.get_tenant_config(db, tenant_id)
    entry = ClusterConfigScopeEntry(
        scope_type=ClusterScopeType.TENANT,
        tenant_id=tenant_id,
        using_platform_default=cfg is None,
        config=_to_read(cfg) if cfg else None,
    )
    return ClusterConfigScopeList(items=[entry])


@router.post("/{scope}/kubeconfig", response_model=ClusterConfigRead)
def upload_kubeconfig(
    scope: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(check_permission(RESOURCE_INFRA, ACTION_UPDATE))],
    file: Annotated[UploadFile, File(...)],
) -> ClusterConfigRead:
    """Upload d'un kubeconfig (multipart) pour un scope — chiffré, appliqué."""
    scope_type, tenant_id = _resolve_and_authorize_scope(scope, current_user)
    raw = file.file.read()
    try:
        validate_kubeconfig_bytes(raw, settings.CLUSTER_KUBECONFIG_MAX_BYTES)
    except KubeconfigTooLarge as exc:
        raise _err(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, ERR_KUBECONFIG_TOO_LARGE, str(exc)) from exc
    except InvalidKubeconfig as exc:
        raise _err(status.HTTP_422_UNPROCESSABLE_ENTITY, ERR_INVALID_KUBECONFIG, str(exc)) from exc

    cfg = crud_cluster.set_kubeconfig(
        db,
        scope_type=scope_type,
        tenant_id=tenant_id,
        raw_bytes=raw,
        actor_user_id=current_user.id,
    )
    resolver.invalidate_scope(cfg.scope_key)
    return _to_read(cfg)


@router.post("/{scope}/test", response_model=ConnectionTestResult)
def test_connection(
    scope: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(check_permission(RESOURCE_INFRA, ACTION_READ))],
) -> ConnectionTestResult:
    """Sonde de connectivité live (non mutante) — réponse 200 même en échec."""
    scope_type, tenant_id = _resolve_and_authorize_scope(scope, current_user)
    return resolver.run_connection_test(db, scope_type, tenant_id)


# ---------------------------------------------------------------------------
# Route dynamique en dernier
# ---------------------------------------------------------------------------

@router.get("/{scope}", response_model=ClusterConfigScopeEntry)
def get_scope_config(
    scope: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(check_permission(RESOURCE_INFRA, ACTION_READ))],
) -> ClusterConfigScopeEntry:
    """Lecture d'un scope (config + santé) — sans secret."""
    scope_type, tenant_id = _resolve_and_authorize_scope(scope, current_user)
    cfg = crud_cluster.get_scope(db, scope_type, tenant_id)
    using_default = cfg is None and scope_type == ClusterScopeType.TENANT
    return ClusterConfigScopeEntry(
        scope_type=scope_type,
        tenant_id=tenant_id,
        using_platform_default=using_default,
        config=_to_read(cfg) if cfg else None,
    )


@router.put("/{scope}", response_model=ClusterConfigRead)
def upsert_scope_config(
    scope: str,
    payload: ClusterConfigUpsert,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(check_permission(RESOURCE_INFRA, ACTION_UPDATE))],
) -> ClusterConfigRead:
    """Crée/met à jour le mode + la charge utile non-kubeconfig d'un scope."""
    scope_type, tenant_id = _resolve_and_authorize_scope(scope, current_user)

    try:
        assert_mode_applicable(scope_type, payload.mode)
    except ModeNotApplicable as exc:
        raise _err(status.HTTP_422_UNPROCESSABLE_ENTITY, ERR_MODE_NOT_APPLICABLE, str(exc)) from exc

    cfg = crud_cluster.upsert(
        db,
        scope_type=scope_type,
        tenant_id=tenant_id,
        data=payload,
        actor_user_id=current_user.id,
    )
    resolver.invalidate_scope(cfg.scope_key)
    return _to_read(cfg)


@router.delete("/{scope}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scope_config(
    scope: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(check_permission(RESOURCE_INFRA, ACTION_UPDATE))],
) -> None:
    """Efface l'override d'un tenant → retombe sur le défaut plateforme.

    Le défaut plateforme n'est pas supprimable (409).
    """
    scope_type, tenant_id = _resolve_and_authorize_scope(scope, current_user)
    if scope_type == ClusterScopeType.PLATFORM_DEFAULT:
        raise _err(
            status.HTTP_409_CONFLICT, ERR_CANNOT_DELETE_DEFAULT,
            "the platform-default configuration cannot be deleted",
        )
    crud_cluster.delete_tenant_override(db, tenant_id or "", current_user.id)
    resolver.invalidate_scope(f"{_TENANT_PREFIX}{tenant_id}")
    return None
