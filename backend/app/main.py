"""
ShiftWise - Migration Intelligente de VMs vers OpenShift

Point d'entrée principal de l'application FastAPI.

Ce fichier configure :
- L'application FastAPI
- Les routes API
- Le CORS
- La documentation automatique
- L'initialisation de la base de données
"""

import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, init_db
from app.api.v1 import auth, users, roles, vms, hypervisors, migrations, kubevirt, conversions, reports

logger = logging.getLogger("shiftwise")


# US4 — refuse to start if REFRESH_COOKIE_DOMAIN is set to a non-empty
# value. The constitution forbids a wildcard-subdomain cookie scope on a
# shared OpenShift cluster (lateral-movement surface); the only safe
# scope is host-only, expressed by an empty/unset REFRESH_COOKIE_DOMAIN.
if (settings.REFRESH_COOKIE_DOMAIN or "").strip():
    logger.critical(
        "REFRESH_COOKIE_DOMAIN must be empty for host-only cookie scope; "
        "got %r. Refusing to start (constitution Security Requirements).",
        settings.REFRESH_COOKIE_DOMAIN,
    )
    sys.exit(1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifecycle: startup and shutdown events."""
    # Startup
    print(f"🚀 Démarrage de {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"📊 Base de données : {settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}")
    init_db()
    print("✅ Base de données initialisée")
    print("📖 Documentation disponible sur : http://localhost:8000/docs")
    print(f"🔐 Mode debug : {settings.DEBUG}")

    yield

    # Shutdown
    print(f"🛑 Arrêt de {settings.APP_NAME}")


# Création de l'application FastAPI
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    description="""
    **ShiftWise** - Plateforme intelligente de migration de machines virtuelles vers OpenShift.

    ## Fonctionnalités principales

    * **Authentification JWT** - Connexion sécurisée avec tokens
    * **RBAC** - Contrôle d'accès basé sur les rôles
    * **Multi-tenancy** - Isolation complète des données par organisation
    * **Gestion des utilisateurs** - CRUD complet avec permissions
    * **Gestion des rôles** - Rôles système et personnalisés

    ## Authentification

    1. Obtenez un token via `/api/v1/auth/login`
    2. Utilisez le token dans l'en-tête : `Authorization: Bearer <token>`
    3. Renouvelez le token avec `/api/v1/auth/refresh`

    ## Permissions

    Les permissions sont gérées via RBAC :
    - **super_admin** : Accès complet au système
    - **admin** : Gestion complète du tenant
    - **user** : Accès aux ressources assignées
    - **viewer** : Lecture seule

    ## Multi-tenancy

    Chaque utilisateur appartient à un tenant (organisation).
    Les données sont automatiquement isolées par tenant.
    """,
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
    openapi_url="/openapi.json"
)

# Configuration CORS — listes explicites (pas de wildcard).
# allow_credentials=True est obligatoire pour que le cookie refresh circule
# en cross-origin (dev : 5173 -> 8000 ; prod : selon déploiement).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin).rstrip("/") for origin in settings.BACKEND_CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    expose_headers=[],
    max_age=600,
)


# Route racine
@app.get("/", tags=["Health"])
def read_root():
    """
    Route racine de l'API.

    Retourne les informations de base sur l'application.

    **Response :**
    ```json
    {
        "name": "ShiftWise",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }
    ```
    """
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "description": "Migration Intelligente de VMs vers OpenShift"
    }


def _probe_database(db: Session) -> dict:
    """Run a cheap `SELECT 1` against Postgres."""
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000), "error": None}
    except Exception as exc:  # NOSONAR — surface any driver failure
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _probe_redis_auth() -> dict:
    """Ping the auth Redis (DB 1). Imported lazily so /health degrades
    gracefully when the redis package or the connection is misbehaving."""
    started = time.perf_counter()
    try:
        from app.core.redis_client import get_redis  # local import: avoids
        # eager connection on app import + lets tests monkeypatch easily.
        client = get_redis()
        pong = client.ping()
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not pong:
            return {"ok": False, "latency_ms": latency_ms, "error": "PING returned falsy"}
        return {"ok": True, "latency_ms": latency_ms, "error": None}
    except Exception as exc:  # NOSONAR — surface any redis/transport failure
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _probe_analyzer_ml() -> dict:
    """Report the Analyzer ML engine state (Audit E15).

    The compatibility analyzer falls back to its rule engine when the ML
    model artifact fails to load. That degradation was previously silent;
    surfacing it here lets ops notice the analyzer is running without ML.
    A degraded analyzer does NOT make the service unhealthy — the rules
    fallback is fully functional — so this never flips the HTTP status.
    """
    try:
        from app.services.analyzer import AnalyzerService  # lazy: heavy import
        status = AnalyzerService().ml_status()
        return {
            "ok": True,
            "degraded": bool(status.get("degraded", True)),
            "engine": status.get("engine", "rules"),
            "error": None,
        }
    except Exception as exc:  # NOSONAR — analyzer probe must never 500 /health
        return {
            "ok": False,
            "degraded": True,
            "engine": "unknown",
            "error": f"{type(exc).__name__}: {exc}",
        }


# Health check endpoint
@app.get("/health", tags=["Health"])
def health_check(db: Annotated[Session, Depends(get_db)]):
    """
    Liveness + readiness probe for monitoring and load balancers.

    Probes the two operational dependencies declared in CLAUDE.md:
    - **Postgres** (`SELECT 1`) — required for every endpoint.
    - **Redis auth DB** (`PING`) — required for `/api/v1/auth/*` only.

    Severity model:
    - `healthy` (HTTP 200): both probes ok.
    - `degraded` (HTTP 200): DB ok but Redis down — read-only endpoints
      still serve, auth flows return 5xx. Load balancers can keep the
      pod in rotation; an alert should already be paging the SRE.
    - `unhealthy` (HTTP 503): DB down. Nothing meaningful can be served;
      the LB should evict this replica.

    **Response (healthy):**
    ```json
    {
        "status": "healthy",
        "app": "ShiftWise",
        "version": "1.0.0",
        "checks": {
            "database": {"ok": true, "latency_ms": 4, "error": null},
            "redis_auth": {"ok": true, "latency_ms": 1, "error": null}
        }
    }
    ```
    """
    db_check = _probe_database(db)
    redis_check = _probe_redis_auth()
    analyzer_check = _probe_analyzer_ml()

    if not db_check["ok"]:
        overall = "unhealthy"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif not redis_check["ok"] or analyzer_check["degraded"]:
        # Redis down OR analyzer running on the rules fallback — the service
        # still answers, but an operator should be paged. Audit E15.
        overall = "degraded"
        http_status = status.HTTP_200_OK
    else:
        overall = "healthy"
        http_status = status.HTTP_200_OK

    payload = {
        "status": overall,
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "checks": {
            "database": db_check,
            "redis_auth": redis_check,
            "analyzer_ml": analyzer_check,
        },
    }
    return JSONResponse(status_code=http_status, content=payload)


# Inclusion des routers API v1
app.include_router(
    auth.router,
    prefix=f"{settings.API_V1_PREFIX}/auth",
    tags=["Authentication"],
)

app.include_router(
    users.router,
    prefix=f"{settings.API_V1_PREFIX}/users",
    tags=["Users"],
)

app.include_router(
    roles.router,
    prefix=f"{settings.API_V1_PREFIX}/roles",
    tags=["Roles"],
)

app.include_router(
    vms.router,
    prefix=f"{settings.API_V1_PREFIX}/vms",
    tags=["VirtualMachines"],
)

app.include_router(
    hypervisors.router,
    prefix=f"{settings.API_V1_PREFIX}/hypervisors",
    tags=["Hypervisors"],
)

app.include_router(
    migrations.router,
    prefix=f"{settings.API_V1_PREFIX}/migrations",
    tags=["Migrations"],
)

app.include_router(
    kubevirt.router,
    prefix=f"{settings.API_V1_PREFIX}/kubevirt",
    tags=["KubeVirt / OpenShift"],
)

app.include_router(
    conversions.router,
    prefix=f"{settings.API_V1_PREFIX}/conversions",
    tags=["Conversions"],
)

app.include_router(
    reports.router,
    prefix=f"{settings.API_V1_PREFIX}/reports",
    tags=["Reports"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Gestionnaire d'exceptions global.

    Capture toutes les exceptions non gérées et retourne
    une réponse JSON standardisée.
    """
    # Audit C-02 — journaliser le détail complet côté serveur (avec un
    # identifiant de corrélation + la stack trace), ne JAMAIS le renvoyer au
    # client. Le message d'exception, son type et l'URL fuiteraient sinon des
    # informations internes (SQL, hôtes, structure applicative) — y compris
    # quand DEBUG=True.
    correlation_id = uuid.uuid4().hex[:12]
    logger.error(
        "Unhandled exception [%s] on %s %s",
        correlation_id,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Une erreur interne est survenue. Contactez l'administrateur.",
            "correlation_id": correlation_id,
        },
    )


# Point d'entrée pour uvicorn
if __name__ == "__main__":
    import uvicorn

    # S8392 — Éviter de lier l'application à toutes les interfaces réseau (0.0.0.0).
    # En production, utiliser une interface spécifique définie dans la configuration.
    # "0.0.0.0" expose le serveur sur toutes les interfaces, ce qui est un risque
    # de sécurité en dehors d'un environnement containerisé contrôlé.
    uvicorn.run(
        "app.main:app",
        host=settings.SERVER_HOST,
        port=8000,
        reload=settings.DEBUG,  # Auto-reload en mode debug
        log_level="info"
    )
