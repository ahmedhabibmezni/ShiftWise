"""
Routes API pour la gestion des Migrations

Endpoints CRUD pour les migrations de VMs.
"""

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from kombu.exceptions import OperationalError as BrokerOperationalError
from kubernetes.client.exceptions import ApiException as K8sApiException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import case, func
from typing import Annotated, Optional

from app.core.config import settings
from app.core.database import get_db
from app.api.deps import check_permission
from app.core.celery_app import celery_app
from app.models.user import User
from app.models.migration import Migration, MigrationStatus, MigrationStrategy
from app.models.migration_event import MigrationEventType
from app.models.virtual_machine import VirtualMachine
from app.models.hypervisor import Hypervisor
from app.models.conversion import ConversionGroup
from app.schemas.migration import (
    MigrationCancel,
    MigrationCreate,
    MigrationUpdate,
    MigrationProgressUpdate,
    MigrationResponse,
    MigrationListResponse,
    MigrationEventResponse,
    MigrationEventListResponse,
    MigrationStats,
    MigrationStatsByGroup,
)
from app.crud import migration as crud_migration
from app.crud import migration_event as crud_migration_event
from app.crud import vm as crud_vm
from app.tasks.migration import run_migration
from app.services.migrator.service import MigratorService

logger = logging.getLogger(__name__)

router = APIRouter()

# S1192 — resource literal reused across the router.
RESOURCE_MIGRATIONS = "migrations"


def require_internal_token(
        x_internal_token: Annotated[Optional[str], Header()] = None,
) -> bool:
    """Authenticate an internal/worker call to a non-public endpoint.

    ``PUT /migrations/{id}/progress`` is driven exclusively by the Celery
    worker — it must not be reachable by a regular RBAC-authenticated API
    user (Audit B4 / H-10). The worker presents a dedicated
    ``INTERNAL_API_TOKEN`` (SV-011) in the ``X-Internal-Token`` header; it is
    NOT the JWT signing key, so a leak of this transport credential cannot be
    escalated into token forgery. When ``INTERNAL_API_TOKEN`` is unset we fall
    back to ``SECRET_KEY`` (legacy) to avoid breaking an existing deployment.
    Comparison is constant-time.

    Returns ``True`` on success; raises ``401`` otherwise.
    """
    expected = settings.INTERNAL_API_TOKEN or settings.SECRET_KEY
    if not x_internal_token or not hmac.compare_digest(
            x_internal_token, expected,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Internal endpoint — valid worker token required",
        )
    return True


@router.get("", response_model=MigrationListResponse)
def list_migrations(
        skip: Annotated[int, Query(ge=0, description="Nombre d'éléments à ignorer")] = 0,
        limit: Annotated[int, Query(ge=1, le=100, description="Nombre d'éléments à retourner")] = 50,
        status_filter: Annotated[
            Optional[MigrationStatus], Query(alias="status", description="Filtrer par statut")] = None,
        strategy: Annotated[Optional[MigrationStrategy], Query(description="Filtrer par stratégie")] = None,
        vm_id: Annotated[Optional[int], Query(description="Filtrer par VM")] = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "read"))] = None
):
    """
    Liste toutes les Migrations avec pagination et filtres.

    **Permissions requises :** migrations:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    total = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=status_filter,
        strategy=strategy, vm_id=vm_id
    )
    migrations = crud_migration.get_migrations(
        db, skip=skip, limit=limit, tenant_id=tenant_id,
        status=status_filter, strategy=strategy, vm_id=vm_id
    )

    items = [MigrationResponse.model_validate(m) for m in migrations]

    return MigrationListResponse(
        total=total,
        items=items,
        page=(skip // limit) + 1,
        page_size=limit
    )


@router.post("", response_model=MigrationResponse, status_code=status.HTTP_201_CREATED)
def create_migration(
        migration_data: MigrationCreate,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "create"))] = None
):
    """
    Crée une nouvelle Migration.

    **Permissions requises :** migrations:create
    """
    # Vérifier que la VM existe (et appartient au tenant de l'utilisateur)
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    vm = crud_vm.get_vm(db, migration_data.vm_id, tenant_id=tenant_id)

    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM avec l'ID {migration_data.vm_id} introuvable"
        )

    # Audit H-19 : verrou pessimiste sur la VM — sérialise les créations
    # concurrentes pour cette VM. Sans le verrou, deux requêtes passent
    # toutes deux le test « pas de migration active » et créent deux
    # migrations actives sur la même VM.
    vm = (
        db.query(VirtualMachine)
        .filter(VirtualMachine.id == vm.id)
        .with_for_update()
        .first()
    )

    # Vérifier que la VM peut être migrée
    if not vm.can_migrate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La VM '{vm.name}' ne peut pas être migrée (statut: {vm.status.value}, compatibilité: {vm.compatibility_status.value})"
        )

    # Vérifier qu'il n'y a pas de migration active sur cette VM
    active_migration = db.query(Migration).filter(
        Migration.vm_id == migration_data.vm_id,
        Migration.status.in_([
            MigrationStatus.PENDING, MigrationStatus.VALIDATING,
            MigrationStatus.PREPARING, MigrationStatus.TRANSFERRING,
            MigrationStatus.CONFIGURING, MigrationStatus.STARTING,
            MigrationStatus.VERIFYING
        ])
    ).first()

    if active_migration:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {vm.id} a déjà une migration active (ID: {active_migration.id})"
        )

    # Créer la migration — namespace imposé par le tenant, non configurable par le client
    migration = crud_migration.create_migration(
        db,
        data=migration_data.model_dump(exclude_unset=True),
        tenant_id=current_user.tenant_id,
        target_namespace=f"shiftwise-{current_user.tenant_id}"
    )

    return MigrationResponse.model_validate(migration)


# ---------------------------------------------------------------------------
# Routes statiques — DOIVENT être déclarées avant les routes dynamiques /{id}
# ---------------------------------------------------------------------------

def _build_tenant_breakdown(db: Session) -> list[MigrationStatsByGroup]:
    """Superuser-only per-tenant aggregation (GROUP BY tenant_id).

    Returns one row per tenant with total/completed/failed counts. The
    caller is responsible for gating this query on
    ``current_user.is_superuser`` — a non-superuser sees ``by_tenant=[]``.
    """
    tenant_rows = (
        db.query(
            Migration.tenant_id,
            func.count(Migration.id).label("total"),
            func.sum(
                case((Migration.status == MigrationStatus.COMPLETED, 1), else_=0)
            ).label("completed"),
            func.sum(
                case((Migration.status == MigrationStatus.FAILED, 1), else_=0)
            ).label("failed"),
        )
        .group_by(Migration.tenant_id)
        .order_by(Migration.tenant_id)
        .all()
    )
    return [
        MigrationStatsByGroup(
            key=row.tenant_id,
            label=row.tenant_id,
            total=int(row.total or 0),
            completed=int(row.completed or 0),
            failed=int(row.failed or 0),
        )
        for row in tenant_rows
    ]


def _build_hypervisor_breakdown(
    db: Session, *, tenant_id: Optional[str],
) -> list[MigrationStatsByGroup]:
    """Per-source-hypervisor aggregation, tenant-scoped for non-superusers.

    When ``tenant_id`` is ``None`` (superuser scope), every hypervisor's
    migrations are aggregated. When a tenant id is passed, the WHERE
    filter on ``Migration.tenant_id`` runs BEFORE the GROUP BY so a
    tenant only sees their own slice (constitution Principle III).
    """
    hyp_query = (
        db.query(
            Hypervisor.id,
            Hypervisor.name,
            func.count(Migration.id).label("total"),
            func.sum(
                case((Migration.status == MigrationStatus.COMPLETED, 1), else_=0)
            ).label("completed"),
            func.sum(
                case((Migration.status == MigrationStatus.FAILED, 1), else_=0)
            ).label("failed"),
        )
        .join(VirtualMachine, Migration.vm_id == VirtualMachine.id)
        .join(Hypervisor, VirtualMachine.source_hypervisor_id == Hypervisor.id)
    )
    if tenant_id is not None:
        hyp_query = hyp_query.filter(Migration.tenant_id == tenant_id)
    hyp_rows = (
        hyp_query
        .group_by(Hypervisor.id, Hypervisor.name)
        .order_by(Hypervisor.name)
        .all()
    )
    return [
        MigrationStatsByGroup(
            key=str(row.id),
            label=row.name,
            total=int(row.total or 0),
            completed=int(row.completed or 0),
            failed=int(row.failed or 0),
        )
        for row in hyp_rows
    ]


def _compute_average_duration_seconds(
    db: Session, *, tenant_id: Optional[str],
) -> Optional[int]:
    """Average duration across COMPLETED migrations (no in-memory load)."""
    avg_duration_query = db.query(
        func.avg(
            func.extract('epoch', Migration.completed_at)
            - func.extract('epoch', Migration.started_at)
        )
    ).filter(
        Migration.status == MigrationStatus.COMPLETED,
        Migration.started_at.isnot(None),
        Migration.completed_at.isnot(None),
    )
    if tenant_id is not None:
        avg_duration_query = avg_duration_query.filter(Migration.tenant_id == tenant_id)
    raw = avg_duration_query.scalar()
    return int(raw) if raw is not None else None


@router.get("/stats/summary", response_model=MigrationStats)
def get_migrations_stats(
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "read"))] = None
):
    """
    Statistiques globales des migrations.

    **Permissions requises :** migrations:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    total = crud_migration.get_migrations_count(db, tenant_id=tenant_id)
    completed = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.COMPLETED
    )
    failed = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.FAILED
    )
    pending = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.PENDING
    )
    cancelled = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.CANCELLED
    )
    rollback = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.ROLLBACK
    )
    rolled_back = crud_migration.get_migrations_count(
        db, tenant_id=tenant_id, status=MigrationStatus.ROLLED_BACK
    )
    in_progress = total - completed - failed - pending - cancelled - rollback - rolled_back
    success_rate = (completed / total * 100) if total > 0 else 0.0

    # Total données transférées — scopé par tenant.
    total_transferred_query = db.query(func.sum(Migration.transferred_gb))
    if tenant_id is not None:
        total_transferred_query = total_transferred_query.filter(
            Migration.tenant_id == tenant_id
        )
    total_transferred = total_transferred_query.scalar() or 0.0

    # by_tenant est visible uniquement par un superuser : un utilisateur
    # tenant voit son propre tenant via les compteurs globaux, et le
    # contrat RBAC (test_reports_stats_rbac) garantit by_tenant=[] pour
    # tous les autres rôles.
    by_tenant: list[MigrationStatsByGroup] = (
        _build_tenant_breakdown(db) if current_user.is_superuser else []
    )
    by_hypervisor = _build_hypervisor_breakdown(db, tenant_id=tenant_id)

    return MigrationStats(
        total_migrations=total,
        completed=completed,
        failed=failed,
        in_progress=in_progress,
        pending=pending,
        success_rate=success_rate,
        average_duration_seconds=_compute_average_duration_seconds(
            db, tenant_id=tenant_id,
        ),
        total_data_transferred_gb=float(total_transferred),
        by_tenant=by_tenant,
        by_hypervisor=by_hypervisor,
    )


# ---------------------------------------------------------------------------
# Routes dynamiques /{migration_id}
# ---------------------------------------------------------------------------

@router.get("/{migration_id}", response_model=MigrationResponse)
def get_migration(
        migration_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "read"))] = None
):
    """
    Récupère les détails d'une Migration.

    **Permissions requises :** migrations:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    migration = crud_migration.get_migration(db, migration_id, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    return MigrationResponse.model_validate(migration)


@router.put("/{migration_id}", response_model=MigrationResponse)
def update_migration(
        migration_id: int,
        migration_update: MigrationUpdate,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "update"))] = None
):
    """
    Met à jour une Migration.

    **Permissions requises :** migrations:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    update_data = migration_update.model_dump(exclude_unset=True)
    migration = crud_migration.update_migration(db, migration_id, update_data, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    return MigrationResponse.model_validate(migration)


@router.delete("/{migration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_migration(
        migration_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "delete"))] = None
):
    """
    Supprime une Migration.

    **Permissions requises :** migrations:delete
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    try:
        deleted = crud_migration.delete_migration(db, migration_id, tenant_id=tenant_id)
    except crud_migration.MigrationHasAuditTrail as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        ) from None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) from None

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    return None


@router.post("/{migration_id}/start", response_model=MigrationResponse)
def start_migration(
        migration_id: int,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "update"))] = None
):
    """
    Démarre une migration.

    **Permissions requises :** migrations:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    migration = crud_migration.get_migration(db, migration_id, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    # Audit H-20 : verrou pessimiste — re-lire la ligne FOR UPDATE puis
    # vérifier le statut sous verrou. Sans ça, deux requêtes /start
    # concurrentes lisent toutes deux PENDING et enfilent run_migration
    # en double.
    migration = (
        db.query(Migration)
        .filter(Migration.id == migration.id)
        .with_for_update()
        .first()
    )

    if migration.status != MigrationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La migration ne peut être démarrée (statut actuel: {migration.status.value})"
        )

    # Audit J1 — transition PENDING → VALIDATING via le chokepoint qui
    # écrit aussi l'événement audit. `set_migration_status` initialise
    # `started_at` quand la cible est VALIDATING.
    crud_migration.set_migration_status(
        db, migration.id, MigrationStatus.VALIDATING,
    )
    db.refresh(migration)

    # Enqueue l'orchestrateur Celery — la migration tourne en arrière-plan.
    # Audit H-18 : si le broker est injoignable, .delay() lève. On remet alors
    # la migration en PENDING pour qu'elle reste re-démarrable, plutôt que de
    # la laisser bloquée en VALIDATING sans tâche associée.
    #
    # Narrow exception set: kombu.OperationalError is the canonical
    # "broker unreachable" signal from Celery's transport layer;
    # ConnectionError/OSError covers a raw socket failure during
    # broker resolution. Programmer bugs (ImportError, ProgrammingError)
    # must NOT be reported as 503 — they propagate to the global handler
    # as 500 so operators see a real stack trace.
    try:
        async_result = run_migration.delay(migration.id)
    except (BrokerOperationalError, ConnectionError, OSError) as exc:
        # Surface the real broker error — operators need the root cause
        # (host/port, timeout, refused) to distinguish "Redis down" from
        # "wrong broker URL" or a transport-layer failure.
        logger.exception(
            "run_migration.delay failed for migration_id=%s broker=%s",
            migration.id, settings.CELERY_BROKER_URL,
        )
        migration.status = MigrationStatus.PENDING
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Le broker de tâches est indisponible — migration non démarrée, réessayez.",
        ) from exc

    # Audit H-16 : mémoriser l'id de la tâche pour pouvoir la révoquer si la
    # migration est annulée.
    migration.celery_task_id = async_result.id
    db.commit()

    return MigrationResponse.model_validate(migration)


def _cleanup_migration_resources(db: Session, migration: Migration) -> None:
    """Démonte, au mieux, les ressources K8s d'une migration annulée (Audit E6).

    La tâche Celery a été révoquée, mais le migrator a pu déjà créer des Jobs
    populator, des PVC cibles et la VirtualMachine. On les supprime pour qu'une
    annulation ne laisse pas fuir de ressources cluster. Toute erreur est
    avalée : la migration est déjà CANCELLED et un échec de nettoyage ne doit
    jamais faire échouer l'annulation.
    """
    if not migration.target_namespace:
        return
    # Narrow exception set — only K8s API failures and DB hiccups during the
    # ConversionGroup query are swallowed (best-effort cleanup, the migration
    # is already CANCELLED). Programmer bugs (AttributeError, KeyError,
    # ImportError) propagate to the global handler so they surface during
    # development instead of hiding behind a "best-effort" log line.
    try:
        groups = (
            db.query(ConversionGroup)
            .filter(ConversionGroup.migration_id == migration.id)
            .all()
        )
        disk_indices = sorted({
            job.disk_index for group in groups for job in group.jobs
        })
        MigratorService().cleanup(
            target_namespace=migration.target_namespace,
            migration_id=migration.id,
            disk_indices=disk_indices,
            target_vm_name=migration.target_vm_name,
        )
    except (K8sApiException, SQLAlchemyError):
        logger.warning(
            "Audit E6 — nettoyage K8s incomplet pour la migration %s "
            "(annulation tout de même effective)",
            migration.id,
            exc_info=True,
        )


@router.post("/{migration_id}/cancel", response_model=MigrationResponse)
def cancel_migration(
        migration_id: int,
        cancel_data: Optional[MigrationCancel] = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "update"))] = None
):
    """
    Annule une migration en cours.

    **Permissions requises :** migrations:update
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id
    migration = crud_migration.get_migration(db, migration_id, tenant_id=tenant_id)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    if not migration.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La migration n'est pas en cours"
        )

    # Audit H-16 : révoquer la tâche Celery — sinon le worker poursuit le
    # pipeline et écrase le statut CANCELLED, et les ressources K8s fuient.
    # Un échec de révocation (broker injoignable) ne bloque pas l'annulation.
    if migration.celery_task_id:
        try:
            celery_app.control.revoke(
                migration.celery_task_id, terminate=True, signal="SIGTERM",
            )
        except Exception:
            logger.warning(
                "Échec de révocation de la tâche Celery %s (broker injoignable ?)",
                migration.celery_task_id,
            )

    # Audit J1 — pose la raison sur la ligne AVANT la transition pour que
    # `set_migration_status` capture le message dans l'événement audit-log.
    # La fonction gère `completed_at`, `success=False`, et écrit l'événement
    # de transition vers CANCELLED dans le journal append-only.
    migration.error_message = (
        cancel_data.reason if cancel_data and cancel_data.reason
        else "Annulée par l'utilisateur"
    )
    crud_migration.set_migration_status(
        db, migration.id, MigrationStatus.CANCELLED,
    )
    db.refresh(migration)

    # Audit E6 — la tâche est révoquée ; on démonte maintenant, au mieux, les
    # ressources K8s que le migrator a pu créer avant que la révocation prenne.
    _cleanup_migration_resources(db, migration)

    return MigrationResponse.model_validate(migration)


@router.get(
    "/{migration_id}/events",
    response_model=MigrationEventListResponse,
)
def list_migration_events(
        migration_id: int,
        limit: Annotated[
            int,
            Query(ge=1, le=1000, description="Nombre maximum d'événements à retourner"),
        ] = 200,
        since_sequence_id: Annotated[
            int,
            Query(
                ge=0,
                description="Curseur de pagination delta (sequence_id strictement supérieur)",
            ),
        ] = 0,
        event_type: Annotated[
            Optional[MigrationEventType],
            Query(description="Filtre optionnel sur le type d'événement"),
        ] = None,
        db: Annotated[Session, Depends(get_db)] = None,
        current_user: Annotated[User, Depends(check_permission(RESOURCE_MIGRATIONS, "read"))] = None
):
    """
    Journal d'audit append-only d'une migration (US3).

    Retourne les événements (transitions, stage_event, classified_error,
    heartbeat) ordonnés par ``sequence_id`` ascending. Filtré par tenant
    pour les utilisateurs non-superuser ; un accès cross-tenant renvoie
    404 (jamais 403 — voir contracts/migration-events.md § 404).

    Le client polling-delta passe le ``next_since_sequence_id`` de la
    réponse précédente comme ``?since_sequence_id=`` pour ne récupérer
    que les nouveaux événements.

    **Permissions requises :** migrations:read
    """
    tenant_id = None if current_user.is_superuser else current_user.tenant_id

    # La présence de la migration et sa visibilité tenant sont vérifiées
    # via le getter standard avant de retourner les événements.
    migration = crud_migration.get_migration(db, migration_id, tenant_id=tenant_id)
    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable",
        )

    # Fetch limit + 1 pour détecter has_more sans deuxième requête.
    raw = crud_migration_event.list_events_for_migration(
        db,
        migration_id,
        tenant_id=tenant_id,
        since_sequence_id=since_sequence_id,
        event_type=event_type,
        limit=limit + 1,
    )
    has_more = len(raw) > limit
    events = raw[:limit] if has_more else raw

    items = [MigrationEventResponse.model_validate(e) for e in events]
    # ``None`` quand la page est vide : permet au client de distinguer
    # "rien à reprendre" de "curseur à la position N". Sinon, le client
    # repasse en boucle la même valeur sans pouvoir détecter la fin.
    next_since: Optional[int] = items[-1].sequence_id if items else None
    # ``total`` = taille de la page (delta-paginé). On évite un
    # ``SELECT COUNT(*)`` par poll : le client UI s'appuie sur ``has_more``
    # + ``next_since_sequence_id``, voir schemas.MigrationEventListResponse.
    return MigrationEventListResponse(
        items=items,
        total=len(items),
        next_since_sequence_id=next_since,
        has_more=has_more,
    )


@router.put("/{migration_id}/progress", response_model=MigrationResponse)
def update_migration_progress(
        migration_id: int,
        progress: MigrationProgressUpdate,
        internal_ok: Annotated[bool, Depends(require_internal_token)] = False,
        db: Annotated[Session, Depends(get_db)] = None,
):
    """
    Met à jour la progression d'une migration.

    **Endpoint interne** — réservé au worker Celery. L'authentification se
    fait via l'en-tête ``X-Internal-Token`` (Audit B4 / H-10), pas via le
    RBAC public : un utilisateur de l'API ne doit jamais piloter la
    progression d'une migration à la main.
    """
    # Audit B4 — garde au niveau du corps. require_internal_token (la
    # dépendance) lève déjà 401 sous FastAPI, mais un appel direct (tests,
    # réutilisation interne) doit lui aussi être refusé sans jeton valide.
    if not internal_ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal endpoint — worker authentication required",
        )
    # L'accès interne couvre tous les tenants — le worker n'a pas de tenant.
    migration = crud_migration.get_migration(db, migration_id, tenant_id=None)

    if not migration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Migration avec l'ID {migration_id} introuvable"
        )

    # Mettre à jour la progression
    migration.update_progress(
        percentage=progress.progress_percentage,
        step=progress.current_step,
        step_number=progress.current_step_number
    )

    if progress.transferred_gb is not None:
        migration.transferred_gb = progress.transferred_gb

    if progress.transfer_rate_mbps is not None:
        migration.transfer_rate_mbps = progress.transfer_rate_mbps

    db.commit()
    db.refresh(migration)

    return MigrationResponse.model_validate(migration)
