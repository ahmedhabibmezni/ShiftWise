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

    # Audit M-26 — `init_db()` exécute `Base.metadata.create_all()`. C'est
    # acceptable en dev / test (base vierge) mais DANGEREUX en production :
    # `create_all` est lancé à chaque démarrage et masque toute dérive de
    # schéma qui devrait passer par une migration Alembic. Ce drapeau gate
    # l'appel. Défaut False = production sûre (le schéma est géré par
    # `alembic upgrade head`). Mettre True uniquement en dev / CI.
    DB_AUTO_CREATE_ALL: bool = False

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
    # Audit C-01 : SECRET_KEY est un champ OBLIGATOIRE sans valeur par défaut.
    # pydantic-settings la charge depuis l'environnement / .env ; l'application
    # refuse de démarrer si elle est absente, trop courte, ou laissée à un
    # placeholder (voir validate_secret_key). Une clé publique ou faible
    # permet la forge de tokens JWT (HS256 — la clé signe ET vérifie).
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Refresh token cookie (HttpOnly, Secure, SameSite=Strict).
    # COOKIE_DOMAIN reste vide en dev (host == "localhost" suffit). En prod,
    # remplir avec le registrable domain partagé entre frontend et backend,
    # ex. ".migration.nextstep-it.com" pour autoriser le cookie sur les deux
    # sous-domaines.
    #
    # Audit A10 — REFRESH_COOKIE_SECURE vaut True par défaut : le cookie de
    # refresh n'est émis que sur HTTPS, ce qui empêche sa fuite sur une
    # connexion en clair. La valeur reste surchargeable par variable
    # d'environnement : un développeur sur http://localhost (sans TLS) peut
    # poser REFRESH_COOKIE_SECURE=False dans son .env local — et uniquement
    # là. Ne jamais le passer à False en production.
    REFRESH_COOKIE_NAME: str = "shiftwise_refresh"
    REFRESH_COOKIE_PATH: str = "/api/v1/auth"
    REFRESH_COOKIE_SAMESITE: str = "strict"
    REFRESH_COOKIE_SECURE: bool = True
    REFRESH_COOKIE_DOMAIN: str | None = None

    @field_validator("REFRESH_COOKIE_SAMESITE")
    @classmethod
    def validate_cookie_samesite(cls, v: str) -> str:
        """SameSite must be one of strict|lax|none (lowercased)."""
        allowed = {"strict", "lax", "none"}
        v_low = v.lower()
        if v_low not in allowed:
            raise ValueError(
                f"REFRESH_COOKIE_SAMESITE must be one of: {', '.join(sorted(allowed))}"
            )
        return v_low

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """
        Audit C-01 — refuse une SECRET_KEY faible ou par défaut.

        La clé signe tous les JWT (HS256). Une clé publique, trop courte, ou
        laissée à un placeholder permettrait la forge de tokens et le
        contournement complet de l'authentification.
        """
        weak_defaults = {
            "GENEREZ_UNE_CLE_SECRETE_ICI",
            "dev-only-secret-not-for-production",
            "changeme",
            "secret",
        }
        if v in weak_defaults:
            raise ValueError(
                "SECRET_KEY ne doit pas être une valeur par défaut/placeholder — "
                "générez une clé aléatoire : "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if len(v) < 32:
            raise ValueError("SECRET_KEY doit contenir au moins 32 caractères")
        return v

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
    # SSH (connecteurs hyperviseurs KVM / Proxmox)
    # ============================================
    #
    # Audit H-02 — vérification des clés d'hôte SSH. Par défaut (False), une
    # connexion SSH rejette tout hôte absent des known_hosts du système, ce
    # qui empêche l'interception (MITM) et le vol du mot de passe SSH. Mettre
    # à True active le « trust on first use » (AutoAddPolicy) — pratique en
    # dev / POC, à NE PAS utiliser en production.
    SSH_AUTO_ADD_HOST_KEYS: bool = False

    # Chemin de la clé privée SSH utilisée par le connecteur KVM/libvirt
    # (qemu+ssh://). Audit S8392 — ne pas coder en dur un chemin de poste
    # de dev dans le code source. Vide => paramiko utilise les clés
    # standard de l'agent / ~/.ssh (look_for_keys=True). Une connexion
    # KVM peut aussi surcharger ce chemin via
    # connection_config["ssh_key_path"].
    KVM_SSH_KEY_PATH: str = ""

    # Audit A5 (SSRF / path traversal) — racine autorisée pour tout chemin
    # de clé privée SSH fourni dans `connection_config["ssh_key_path"]`.
    # La validation du schéma Hypervisor refuse un chemin relatif, un
    # chemin contenant `..`, ou un chemin résolu hors de cette racine.
    # Par défaut `/etc/shiftwise/ssh` : les clés SSH d'hyperviseur sont
    # provisionnées là par l'opérateur. Vide => aucune restriction de
    # racine (le chemin doit tout de même être absolu et sans `..`).
    SSH_KEY_ALLOWED_ROOT: str = "/etc/shiftwise/ssh"

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

    # Namespace OpenShift pour les Jobs in-cluster (qemu-img / virt-v2v).
    # Doit être le namespace où la transit-pvc est déployée, parce que les
    # Jobs converter montent cette PVC. Le migrator lit aussi cette PVC ici
    # pour découvrir le NFS (transit_discovery.discover_transit_nfs).
    CONVERTER_K8S_NAMESPACE: str = "shiftwise"

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
    # TENANT RESOURCE QUOTA (opt-in)
    # ============================================
    #
    # Limites par défaut appliquées au namespace tenant via une
    # ResourceQuota nommée `shiftwise-default-quota`. Toutes les
    # dimensions sont opt-in : laisser la chaîne vide désactive la
    # contrainte sur cette dimension. Si TOUTES sont vides, aucune
    # ResourceQuota n'est créée (rétro-compatible avec les déploiements
    # existants — les tenants sans quota restent illimités).
    #
    # Exemples pour un tenant de taille moyenne :
    #   MIGRATOR_QUOTA_REQUESTS_CPU="10"
    #   MIGRATOR_QUOTA_REQUESTS_MEMORY="32Gi"
    #   MIGRATOR_QUOTA_REQUESTS_STORAGE="500Gi"
    #   MIGRATOR_QUOTA_PVC_COUNT="20"
    #   MIGRATOR_QUOTA_POD_COUNT="30"
    MIGRATOR_QUOTA_REQUESTS_CPU: str = ""
    MIGRATOR_QUOTA_REQUESTS_MEMORY: str = ""
    MIGRATOR_QUOTA_LIMITS_CPU: str = ""
    MIGRATOR_QUOTA_LIMITS_MEMORY: str = ""
    MIGRATOR_QUOTA_REQUESTS_STORAGE: str = ""
    MIGRATOR_QUOTA_PVC_COUNT: str = ""
    MIGRATOR_QUOTA_POD_COUNT: str = ""

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

    # Redis dédié au store des refresh tokens (familles, détection de reuse).
    # DB logique distincte de Celery pour ne pas mélanger keyspaces, mais
    # même serveur en pratique.
    REDIS_AUTH_URL: str = "redis://localhost:6379/1"

    # ============================================
    # LOGIN THROTTLE (brute-force protection)
    # ============================================
    #
    # Compteurs sliding-window dans Redis (DB 1, partagé avec les
    # refresh tokens). Désactivé en mettant MAX_ATTEMPTS <= 0 — utile
    # pour les environnements de dev / CI.
    #
    # Défaut : 5 tentatives ratées sur une fenêtre de 15 minutes
    # déclenche un lockout, par email ET par IP source.
    LOGIN_THROTTLE_MAX_ATTEMPTS: int = 5
    LOGIN_THROTTLE_WINDOW_SECONDS: int = 15 * 60

    # ============================================
    # TRUSTED REVERSE PROXIES (A11)
    # ============================================
    #
    # Audit A11 — la résolution de l'IP cliente (throttle login + audit
    # trail) ne doit faire confiance à l'en-tête `X-Forwarded-For` que si
    # la connexion TCP provient effectivement d'un proxy de confiance.
    # Sinon n'importe quel client peut usurper son IP (et contourner le
    # throttle / fausser l'audit) en envoyant un faux XFF.
    #
    # Liste des IP des reverse proxies / load-balancers placés devant le
    # backend (ex. le HAProxy du bastion 10.9.21.150). Vide = on ne fait
    # JAMAIS confiance au XFF, on utilise toujours l'IP du peer TCP.
    #
    # NOTE déploiement : lancer uvicorn avec
    #   --proxy-headers --forwarded-allow-ips=<CIDR du proxy>
    # est complémentaire (cela fait confiance au proxy pour réécrire
    # request.client.host) ; ce réglage couvre le parsing applicatif du
    # XFF quand on lit l'en-tête directement.
    TRUSTED_PROXY_IPS: List[str] = []

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

    # Audit E11 — délai mur (wall-clock) maximum pendant lequel
    # l'orchestrateur de migration attend que le groupe de conversion
    # atteigne un état terminal. Sans cette borne, un Job de conversion
    # silencieusement bloqué fige la migration indéfiniment dans la
    # boucle de polling `_wait_for_conversions`. Au-delà du délai la
    # boucle lève ConversionError. Doit rester < CELERY_TASK_TIME_LIMIT.
    MIGRATION_CONVERSION_WAIT_TIMEOUT: int = 3 * 60 * 60   # 3h

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
