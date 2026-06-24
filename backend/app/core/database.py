"""
ShiftWise Database Module

Ce module gère la connexion à PostgreSQL et les sessions de base de données.
Implémentation SYNCHRONE basée sur SQLAlchemy 2.0.
Compatible avec FastAPI et Alembic.
"""

import logging
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import (
    sessionmaker,
    Session,
    DeclarativeBase,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Base SQLAlchemy (parent de tous les modèles)
# -------------------------------------------------------------------
class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy."""
    pass


# -------------------------------------------------------------------
# Engine PostgreSQL
# -------------------------------------------------------------------
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,                 # Logs SQL en mode DEBUG
    pool_pre_ping=True,                  # Vérifie la connexion avant usage
    pool_size=settings.DATABASE_POOL_SIZE,     # Pool principal
    max_overflow=settings.DATABASE_MAX_OVERFLOW,  # Connexions supplémentaires
    future=True                          # SQLAlchemy 2.0 style
)


# -------------------------------------------------------------------
# Session factory
# -------------------------------------------------------------------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


# -------------------------------------------------------------------
# Dependency FastAPI
# -------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """
    Fournit une session SQLAlchemy par requête HTTP.

    - Ouvre une session
    - La fournit à la route FastAPI
    - La ferme automatiquement après la requête
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -------------------------------------------------------------------
# Initialisation BDD (DEV / TEST uniquement)
# -------------------------------------------------------------------
def init_db() -> None:
    """
    Initialise la base de données en créant les tables.

    ⚠️ À utiliser UNIQUEMENT en développement.
    En production, utiliser Alembic :
        alembic upgrade head

    Audit M-26 — `init_db()` est appelé au démarrage de l'application
    (lifespan FastAPI). Exécuter `create_all()` à CHAQUE démarrage, y
    compris en production, masque toute dérive de schéma qui devrait
    passer par une migration Alembic versionnée. L'appel est désormais
    gardé par `settings.DB_AUTO_CREATE_ALL` (défaut False). En production
    le drapeau reste à False : `init_db()` ne fait rien et le schéma est
    géré exclusivement par `alembic upgrade head`. Mettre le drapeau à
    True uniquement en dev / CI sur une base vierge.
    """
    if not settings.DB_AUTO_CREATE_ALL:
        logger.info(
            "init_db(): DB_AUTO_CREATE_ALL=False — création de schéma ignorée "
            "(le schéma de production est géré par `alembic upgrade head`)."
        )
        return

    # Importer tous les modèles pour que SQLAlchemy les enregistre dans Base.metadata.
    # Audit C-10 : `conversion` doit figurer dans la liste, sinon les tables
    # conversion_groups / conversion_jobs / conversion_attempts ne sont jamais
    # créées par init_db() (pipeline de conversion cassé sur une base vierge).
    from app.models import (  # NOSONAR — import pour enregistrement ORM
        user, role, hypervisor, virtual_machine, migration, conversion,
    )
    logger.warning(
        "init_db(): DB_AUTO_CREATE_ALL=True — exécution de Base.metadata.create_all() "
        "(à n'utiliser qu'en dev / CI sur une base vierge)."
    )
    Base.metadata.create_all(bind=engine)
