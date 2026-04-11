"""
ShiftWise Configuration Module

Ce module charge et valide toutes les variables d'environnement
nécessaires au fonctionnement de l'application.

Utilise Pydantic Settings pour la validation automatique des types
et la gestion des valeurs par défaut.
"""

import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator
from urllib.parse import quote_plus


class Settings(BaseSettings):
    """
    Classe de configuration principale de ShiftWise.

    Charge automatiquement les variables depuis le fichier .env
    et valide leur format.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Application Info
    APP_NAME: str = "ShiftWise"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    SERVER_HOST: str = "127.0.0.1"

    # Database Configuration
    DATABASE_HOST: str
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # ============================================
    # KUBERNETES / OPENSHIFT CONFIGURATION
    # ============================================

    # Mode de connexion au cluster Kubernetes
    # Options:
    #   - "kubeconfig": Utilise un fichier kubeconfig (dev local)
    #   - "incluster": Utilise le ServiceAccount du pod (production)
    #   - "custom": Utilise URL et token personnalisés (production externe)
    KUBERNETES_MODE: str = "kubeconfig"

    # Chemin vers le fichier kubeconfig (mode: kubeconfig)
    KUBECONFIG_PATH: str | None = "./config/kubeconfig"

    # Utiliser la configuration in-cluster (mode: incluster)
    USE_IN_CLUSTER: bool = False

    # Configuration custom (mode: custom)
    KUBERNETES_API_URL: str | None = None
    KUBERNETES_TOKEN: str | None = None
    KUBERNETES_VERIFY_SSL: bool = False

    # Namespace par défaut pour les VMs
    KUBERNETES_DEFAULT_NAMESPACE: str = "default"

    @field_validator("KUBERNETES_MODE")
    @classmethod
    def validate_kubernetes_mode(cls, v: str) -> str:
        """
        Valide le mode de connexion Kubernetes.
        """
        allowed_modes = ["kubeconfig", "incluster", "custom"]
        if v not in allowed_modes:
            raise ValueError(
                f"KUBERNETES_MODE doit être l'un de : {', '.join(allowed_modes)}"
            )
        return v

    @property
    def is_kubernetes_incluster(self) -> bool:
        """
        Indique si l'application tourne dans un cluster Kubernetes.
        Détecté automatiquement via la présence de variables d'environnement.
        """
        return bool(os.getenv("KUBERNETES_SERVICE_HOST"))

    @property
    def DATABASE_URL(self) -> str:
        """
        Construit l'URL de connexion PostgreSQL.
        Format: postgresql://user:password@host:port/database
        """

        encoded_password = quote_plus(self.DATABASE_PASSWORD)
        encoded_user = quote_plus(self.DATABASE_USER)

        return (
            f"postgresql://{encoded_user}:{encoded_password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    # Security & JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS - Origins autorisées pour les requêtes cross-origin
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str] | str:
        """
        Valide et transforme les origines CORS.
        Accepte une liste ou une chaîne JSON.
        """
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # API Configuration
    API_V1_PREFIX: str = "/api/v1"

    # ============================================
    # LOGGING
    # ============================================

    LOG_LEVEL: str = "INFO"

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """
        Valide le niveau de log.
        """
        allowed_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in allowed_levels:
            raise ValueError(
                f"LOG_LEVEL doit être l'un de : {', '.join(allowed_levels)}"
            )
        return v_upper


# Instance globale des settings
# À importer dans les autres modules : from app.core.config import settings
settings = Settings()
