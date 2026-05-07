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
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-only-secret-not-for-production")
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
    # ANALYZER CONFIGURATION
    # ============================================

    ANALYZER_CONFIDENCE_THRESHOLD: float = 0.75

    @field_validator("ANALYZER_CONFIDENCE_THRESHOLD")
    @classmethod
    def validate_analyzer_confidence_threshold(cls, v: float) -> float:
        """Validate that confidence threshold is between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("ANALYZER_CONFIDENCE_THRESHOLD must be between 0 and 1")
        return v

    # ============================================
    # CONVERTER CONFIGURATION
    # ============================================

    # Racine NFS de la zone de transit (vu depuis le worker / pod)
    CONVERTER_TRANSIT_ROOT: str = "/mnt/shiftwise-transit" # if it fails try /nfs-storage/openshift-vms

    # Multiplicateur d'espace requis sur NFS avant staging (sécurité)
    CONVERTER_FREE_SPACE_FACTOR: float = 2.2

    # TTL des outputs READY avant cleanup (en jours)
    CONVERTER_OUTPUT_TTL_DAYS: int = 7

    # TTL du dossier work/ après terminaison du job (en heures)
    CONVERTER_WORK_TTL_HOURS: int = 24

    # Concurrence Celery pour la file converter
    CONVERTER_WORKER_CONCURRENCY: int = 2

    # Cap par tenant des jobs in-flight
    CONVERTER_MAX_INFLIGHT_PER_TENANT: int = 3

    # Namespace OpenShift pour les Jobs in-cluster (qemu-img / virt-v2v)
    CONVERTER_K8S_NAMESPACE: str = "shiftwise-converter"

    # Image conteneur pour les Jobs de conversion
    CONVERTER_CONTAINER_IMAGE: str = "quay.io/shiftwise/converter:latest"

    # PVC RWX backed par NFS, monté dans les Jobs
    CONVERTER_TRANSIT_PVC: str = "transit-pvc"

    # ============================================
    # MIGRATOR CONFIGURATION
    # ============================================

    # StorageClass utilisée pour les PVC cibles dans les namespaces tenants.
    MIGRATOR_TARGET_STORAGE_CLASS: str = "nfs-client"

    # Image conteneur du populator Job (doit contenir qemu-img >= 6.0).
    # Par défaut : la même image que le converter, qui embarque déjà qemu-img.
    MIGRATOR_POPULATOR_IMAGE: str = "quay.io/shiftwise/converter:latest"

    # ServiceAccount avec lequel le populator Job est lancé dans le namespace
    # tenant. Par défaut, le SA "default" du namespace.
    MIGRATOR_POPULATOR_SA: str = "default"

    # Source NFS pour le populator Job (pas de PVC cross-namespace possible).
    # Le populator tourne dans le namespace tenant, donc on monte le NFS en
    # direct via volumes.nfs (built-in K8s, pas de driver CSI requis). Doit
    # être surchargé par variable d'environnement ; pas de défaut hardcodé.
    MIGRATOR_NFS_SERVER: str = ""
    MIGRATOR_NFS_PATH: str = ""

    # Timeout d'attente du Bound d'un PVC cible (secondes).
    MIGRATOR_PVC_BIND_TIMEOUT: int = 300

    # Timeout d'attente d'un populator Job (secondes). Cap haut pour disques
    # de 100+ GB sur NFS lent.
    MIGRATOR_POPULATOR_TIMEOUT: int = 4 * 3600

    # Timeout d'attente du passage VMI -> Running (secondes).
    MIGRATOR_VMI_RUNNING_TIMEOUT: int = 600

    # ============================================
    # ADAPTER CONFIGURATION
    # ============================================

    # Image conteneur du Job adapter. Doit fournir libguestfs-tools
    # (virt-customize, virt-inspector, virt-ls). Par défaut on utilise la
    # même image que le backend, qui inclut libguestfs depuis le Dockerfile.
    ADAPTER_IMAGE: str = "docker.io/dida1609/shiftwise-backend:latest"

    # Timeout d'attente du Job adapter (secondes). virt-customize sur 5 GB
    # avec KVM = ~30 s ; sans KVM (TCG) jusqu'à 5 min.
    ADAPTER_TIMEOUT: int = 30 * 60

    # Mode privileged sur le pod adapter — requis pour accéder à /dev/kvm
    # (accélération hardware de libguestfs). Si False, libguestfs tombe sur
    # TCG (émulation pure) — ~5x plus lent mais fonctionne sans escalation
    # de privilège ni SCC custom. Recommandé en prod : False, sauf si vous
    # avez configuré le KubeVirt device plugin pour /dev/kvm.
    ADAPTER_PRIVILEGED: bool = False

    # ============================================
    # CELERY / REDIS (orchestration des migrations)
    # ============================================

    # URL du broker Redis. Format : redis://[:password@]host:port/db
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"

    # Backend de résultats — même Redis par défaut, peut etre None pour
    # désactiver complètement le stockage des résultats.
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Sérialiseur — json est obligatoire en production (sécurité, portabilité).
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"

    # Mode eager (synchrone) : les tâches s'exécutent dans le process appelant.
    # Indispensable pour les tests unitaires sans broker.
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # Durée max d'une tâche avant kill (en secondes). Une migration peut etre
    # longue : on prend large. Le SOFT signale, le HARD kill.
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3 * 60 * 60   # 3h
    CELERY_TASK_TIME_LIMIT: int = 4 * 60 * 60        # 4h

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
