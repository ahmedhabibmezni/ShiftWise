"""
ShiftWise Base Model

Modèle de base contenant les champs communs à toutes les tables :
- id : Identifiant unique
- created_at : Date de création
- updated_at : Date de dernière modification
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, DateTime
from app.core.database import Base


def utc_now():
    """Retourne un datetime UTC timezone-aware."""
    return datetime.now(timezone.utc)


class BaseModel(Base):
    """
    Modèle abstrait de base pour toutes les tables.

    Fournit automatiquement :
    - Un ID auto-incrémenté
    - created_at : timestamp de création
    - updated_at : timestamp de dernière modification

    Usage:
        class User(BaseModel):
            __tablename__ = "users"
            email = Column(String)
    """

    __abstract__ = True  # Cette classe ne créera pas de table

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        comment="Date de création de l'enregistrement"
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
        comment="Date de dernière modification"
    )

    def __repr__(self) -> str:
        """Représentation string du modèle"""
        return f"<{self.__class__.__name__}(id={self.id})>"