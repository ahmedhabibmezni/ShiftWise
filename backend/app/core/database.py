"""
ShiftWise Database Module

Ce module gère la connexion à PostgreSQL et les sessions de base de données.
Implémentation SYNCHRONE basée sur SQLAlchemy 2.0.
Compatible avec FastAPI et Alembic.
"""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import (
    sessionmaker,
    Session,
    DeclarativeBase,
)

from app.core.config import settings


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
    """
    # Importer tous les modèles pour que SQLAlchemy les enregistre dans Base.metadata
    from app.models import user, role, hypervisor, virtual_machine, migration  # noqa: F401
    Base.metadata.create_all(bind=engine)
