"""
Schémas Pydantic pour Hypervisor

Définit les schémas de validation et sérialisation pour l'API REST.
"""

import ipaddress
import posixpath
import re
import socket
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings
from app.models.hypervisor import HypervisorType as HypervisorTypeEnum
from app.models.hypervisor import HypervisorStatus as HypervisorStatusEnum


# Audit H-03 — plages réseau interdites comme cible d'hyperviseur (SSRF).
# Un hôte link-local pointe typiquement vers le endpoint de métadonnées
# cloud (169.254.169.254) ; aucun hyperviseur légitime n'y réside.
_SSRF_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),  # link-local IPv4 (métadonnées cloud)
    ipaddress.ip_network("fe80::/10"),       # link-local IPv6
)


def _assert_ip_not_blocked(ip: ipaddress._BaseAddress, host: str) -> None:
    """Lève ``ValueError`` si ``ip`` tombe dans une plage interdite.

    Plages bloquées : non spécifiée (0.0.0.0 / ::), boucle locale
    (127.0.0.0/8, ::1) et link-local (169.254.0.0/16 — métadonnées cloud —
    et fe80::/10).

    NB délibéré (SV-008) : les plages RFC1918 (10/8, 172.16/12, 192.168/16)
    ne sont PAS bloquées. Les hyperviseurs gérés par ShiftWise résident
    légitimement sur des réseaux privés (Proxmox 172.16.x, cluster 10.9.21.x).
    Les bloquer casserait le produit ; le risque SSRF visé ici est l'accès
    aux endpoints de métadonnées / services co-localisés, pas au LAN.
    """
    if ip.is_unspecified:
        raise ValueError(f"hôte interdit : {host!r} (adresse non spécifiée)")
    if ip.is_loopback:
        raise ValueError(f"hôte interdit : {host!r} (adresse de bouclage)")
    for net in _SSRF_BLOCKED_NETWORKS:
        if ip in net:
            raise ValueError(
                f"hôte interdit : {host!r} cible la plage link-local {net} "
                "(risque de SSRF vers les métadonnées cloud)"
            )


def _check_host_not_ssrf(host: str) -> str:
    """
    Rejette un host ciblant une plage interdite — littéral IP, encodage
    numérique non standard, OU hostname se résolvant vers une telle plage.

    Le champ `host` est polymorphe (IP, hostname, URI ``qemu+ssh://``, ou
    chemin local pour VMware Workstation).

    SV-008 — le contrôle précédent n'inspectait QUE les littéraux IP dotés,
    laissant passer :
      - un hostname résolvant vers 169.254.169.254 / 127.0.0.1 / ::1 ;
      - un encodage entier/octal/hex (``2130706433``, ``0x7f000001``) que
        ``ipaddress`` rejette mais que le resolveur OS ramène à 127.0.0.1.
    On résout désormais l'hôte et on rejette si TOUTE adresse résolue est
    interdite. La résolution est tolérante aux pannes (fail-open sur échec
    DNS) : on ne veut pas refuser un hôte légitime hors-ligne au moment de
    la validation — un vrai vecteur SSRF, lui, résout avec succès. Le
    pinning anti-rebinding complet (TOCTOU) reste un durcissement ultérieur.
    """
    candidate = host.strip()
    uri_match = re.search(r"@([^/:?]+)", candidate) or re.search(r"://([^/:?@]+)", candidate)
    if uri_match:
        candidate = uri_match.group(1)
    # Strip an éventuel port "host:port" pour la résolution (IPv6 entre [] géré
    # par getaddrinfo plus bas via le littéral d'origine).
    candidate = candidate.strip("[]")

    # 1) Littéral IP standard — chemin rapide, sans réseau.
    try:
        _assert_ip_not_blocked(ipaddress.ip_address(candidate), host)
        return host
    except ValueError as exc:
        if "hôte interdit" in str(exc):
            raise
        # Sinon : pas un littéral IP dotté — on continue (hostname ou
        # encodage numérique non standard).

    # 2) Résolution (hostname + encodages numériques alternatifs). Tout ce
    #    qui résout est vérifié ; un échec de résolution est non bloquant.
    try:
        infos = socket.getaddrinfo(candidate, None)
    except (socket.gaierror, UnicodeError, ValueError):
        return host  # non résolvable ici — laissé au connecteur en aval
    for info in infos:
        sockaddr = info[4]
        resolved = sockaddr[0]
        try:
            _assert_ip_not_blocked(ipaddress.ip_address(resolved), host)
        except ValueError as exc:
            if "hôte interdit" in str(exc):
                raise
    return host


# Audit A5 — caractères de contrôle interdits dans les valeurs de chemin
# de `connection_config` (CR/LF/NUL permettraient injection d'en-tête ou
# de commande selon le consommateur en aval).
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _validate_api_path(value: object) -> str:
    """
    Valide ``connection_config["api_path"]`` (audit A5 — SSRF).

    `api_path` est concaténé tel quel dans une URL ``https://{host}{port}
    {api_path}`` (connecteur oVirt). Il doit donc rester un chemin d'URL
    relatif : commence par ``/``, ne porte ni schéma ni hôte, ne contient
    ni segment de traversée ``..`` ni caractère de contrôle. Sinon un
    `api_path` du type ``@evil.example.com/`` ou ``//evil.example.com``
    détournerait la requête vers un hôte arbitraire.
    """
    if not isinstance(value, str):
        raise ValueError("connection_config.api_path doit être une chaîne")
    candidate = value.strip()
    if not candidate:
        raise ValueError("connection_config.api_path ne doit pas être vide")
    if _CONTROL_CHARS.search(candidate):
        raise ValueError(
            "connection_config.api_path contient un caractère de contrôle interdit"
        )
    if not candidate.startswith("/"):
        raise ValueError(
            "connection_config.api_path doit être un chemin relatif "
            "(commençant par '/')"
        )
    if candidate.startswith("//"):
        raise ValueError(
            "connection_config.api_path ne doit pas commencer par '//' "
            "(serait interprété comme un hôte réseau)"
        )
    if "://" in candidate or "\\" in candidate:
        raise ValueError(
            "connection_config.api_path ne doit pas contenir de schéma "
            "ni d'hôte — uniquement un chemin"
        )
    if ".." in candidate.split("/"):
        raise ValueError(
            "connection_config.api_path ne doit pas contenir de segment "
            "de traversée '..'"
        )
    return candidate


def _validate_ssh_key_path(value: object) -> str:
    """
    Valide ``connection_config["ssh_key_path"]`` (audit A5 — path traversal).

    Le chemin est passé en `key_filename` à paramiko (connecteur KVM). Il
    doit être un chemin **absolu**, sans segment de traversée ``..``, sans
    caractère de contrôle, et — si ``settings.SSH_KEY_ALLOWED_ROOT`` est
    défini — résolu à l'intérieur de cette racine. Cela empêche un
    utilisateur d'API de faire lire au backend une clé privée arbitraire
    du système de fichiers (ex. ``/root/.ssh/id_rsa``).
    """
    if not isinstance(value, str):
        raise ValueError("connection_config.ssh_key_path doit être une chaîne")
    candidate = value.strip()
    if not candidate:
        raise ValueError("connection_config.ssh_key_path ne doit pas être vide")
    if _CONTROL_CHARS.search(candidate):
        raise ValueError(
            "connection_config.ssh_key_path contient un caractère de contrôle interdit"
        )
    # Normalise en chemin POSIX — l'hôte cible (worker Linux) est POSIX.
    normalised = candidate.replace("\\", "/")
    if not posixpath.isabs(normalised):
        raise ValueError(
            "connection_config.ssh_key_path doit être un chemin absolu"
        )
    if ".." in normalised.split("/"):
        raise ValueError(
            "connection_config.ssh_key_path ne doit pas contenir de segment "
            "de traversée '..'"
        )
    resolved = posixpath.normpath(normalised)
    allowed_root = (settings.SSH_KEY_ALLOWED_ROOT or "").strip()
    if allowed_root:
        root = posixpath.normpath(allowed_root.replace("\\", "/"))
        # Le chemin résolu doit être la racine elle-même ou un descendant.
        if resolved != root and not resolved.startswith(root.rstrip("/") + "/"):
            raise ValueError(
                "connection_config.ssh_key_path doit être situé sous "
                f"{root!r} (clé hors racine autorisée)"
            )
    return resolved


def _validate_connection_config(cfg: Optional[dict]) -> Optional[dict]:
    """
    Valide les clés sensibles de ``connection_config`` (audit A5 — SSRF).

    Ne touche que ``api_path`` et ``ssh_key_path`` ; les autres clés
    (datacenter, cluster, vm_folder, ...) sont laissées telles quelles.
    Réécrit le dict avec les valeurs normalisées des clés validées.
    """
    if cfg is None:
        return None
    if not isinstance(cfg, dict):
        raise ValueError("connection_config doit être un objet")
    validated = dict(cfg)
    if "api_path" in validated and validated["api_path"] is not None:
        validated["api_path"] = _validate_api_path(validated["api_path"])
    if "ssh_key_path" in validated and validated["ssh_key_path"] is not None:
        validated["ssh_key_path"] = _validate_ssh_key_path(validated["ssh_key_path"])
    return validated


# Schéma de base
class HypervisorBase(BaseModel):
    """Propriétés de base d'un hyperviseur.

    SV-008 — la validation SSRF de `host` n'est PAS déclarée ici : c'est un
    contrôle d'ENTRÉE (Create/Update/TestConnection), pas de sortie. La
    placer sur la base la ferait hériter par `HypervisorResponse`, qui
    re-valide alors des données déjà stockées au moment de la sérialisation —
    une ligne légitime (ex. un hôte Hyper-V local `localhost`) ferait alors
    échouer la lecture (500). Chaque schéma d'entrée porte donc son propre
    validateur `_validate_host_ssrf`.
    """
    name: str = Field(..., min_length=1, max_length=255, description="Nom de l'hyperviseur")
    description: Optional[str] = Field(None, description="Description")
    type: HypervisorTypeEnum = Field(..., description="Type d'hyperviseur")
    host: str = Field(..., min_length=1, max_length=255, description="Hostname ou IP")
    port: Optional[int] = Field(None, ge=1, le=65535, description="Port de connexion")


# Schéma pour la création (avec credentials)
class HypervisorCreate(HypervisorBase):
    """Schéma pour créer un hyperviseur"""
    username: str = Field(..., min_length=1, max_length=255, description="Nom d'utilisateur")
    password: str = Field(..., min_length=1, description="Mot de passe")
    verify_ssl: bool = Field(False, description="Vérifier les certificats SSL")
    ssl_cert_path: Optional[str] = Field(None, max_length=512, description="Chemin certificat SSL")
    connection_config: Optional[dict] = Field(None, description="Configuration avancée")
    tags: Optional[dict] = Field(None, description="Tags personnalisés")

    @field_validator("host")
    @classmethod
    def _validate_host_ssrf(cls, v: Optional[str]) -> Optional[str]:
        """Audit H-03 — refuse un hôte link-local (SSRF métadonnées cloud)."""
        return v if v is None else _check_host_not_ssrf(v)

    @field_validator("connection_config")
    @classmethod
    def _validate_connection_config(cls, v: Optional[dict]) -> Optional[dict]:
        """Audit A5 — valide api_path / ssh_key_path (SSRF, path traversal)."""
        return _validate_connection_config(v)


# Schéma pour la mise à jour
class HypervisorUpdate(BaseModel):
    """Schéma pour mettre à jour un hyperviseur"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    host: Optional[str] = Field(None, min_length=1, max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = Field(None, min_length=1, max_length=255)
    password: Optional[str] = Field(None, min_length=1)  # Mettre à jour le password
    verify_ssl: Optional[bool] = None
    ssl_cert_path: Optional[str] = Field(None, max_length=512)
    is_active: Optional[bool] = None
    connection_config: Optional[dict] = None
    tags: Optional[dict] = None

    @field_validator("host")
    @classmethod
    def _validate_host_ssrf(cls, v: Optional[str]) -> Optional[str]:
        """Audit H-03 — refuse un hôte link-local (SSRF métadonnées cloud)."""
        return v if v is None else _check_host_not_ssrf(v)

    @field_validator("connection_config")
    @classmethod
    def _validate_connection_config(cls, v: Optional[dict]) -> Optional[dict]:
        """Audit A5 — valide api_path / ssh_key_path (SSRF, path traversal)."""
        return _validate_connection_config(v)


# Schéma pour la réponse (SANS password par défaut)
class HypervisorResponse(HypervisorBase):
    """Schéma de réponse (sans credentials sensibles).

    Audit D5 — le `username` en clair n'est PAS exposé : seule la forme
    masquée `username_masked` (propriété du modèle) est servie.
    Audit D8 — `tenant_id` exposé en lecture seule (traçabilité multi-tenant).
    Audit D9 — `ssl_cert_path` exposé (champ jusque-là write-only).
    """
    id: int
    tenant_id: str  # Audit D8 — lecture seule
    username_masked: str  # Audit D5 — username masqué, jamais en clair
    verify_ssl: bool
    ssl_cert_path: Optional[str] = None  # Audit D9
    status: HypervisorStatusEnum
    is_active: bool
    last_sync_at: Optional[datetime] = None
    last_successful_connection: Optional[datetime] = None
    last_error: Optional[str] = None
    total_vms_discovered: int
    total_vms_migrated: int
    connection_config: Optional[dict] = None
    tags: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    # Propriétés calculées
    is_reachable: bool
    connection_url: str
    needs_sync: bool

    model_config = ConfigDict(from_attributes=True)


# Schéma pour liste paginée
class HypervisorListResponse(BaseModel):
    """Réponse pour liste d'hyperviseurs"""
    total: int = Field(..., description="Nombre total d'hyperviseurs")
    items: list[HypervisorResponse] = Field(..., description="Liste des hyperviseurs")
    page: int = Field(..., ge=1, description="Page actuelle")
    page_size: int = Field(..., ge=1, le=100, description="Taille de la page")

    # Audit D10 — `from_attributes` pour une construction homogène depuis l'ORM.
    model_config = ConfigDict(from_attributes=True)


# Schéma pour tester la connexion
class HypervisorTestConnection(BaseModel):
    """Schéma pour tester une connexion hyperviseur"""
    type: HypervisorTypeEnum
    host: str = Field(..., min_length=1, max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)
    verify_ssl: bool = False

    # Audit D18 — `model_config` pour la cohérence de convention.
    model_config = ConfigDict(from_attributes=True)

    @field_validator("host")
    @classmethod
    def _validate_host_ssrf(cls, v: Optional[str]) -> Optional[str]:
        """Audit H-03 — refuse un hôte link-local (SSRF métadonnées cloud)."""
        return v if v is None else _check_host_not_ssrf(v)


# Schéma de réponse du test de connexion
class HypervisorTestConnectionResponse(BaseModel):
    """Résultat du test de connexion"""
    success: bool = Field(..., description="Connexion réussie")
    message: str = Field(..., description="Message de résultat")
    vms_count: Optional[int] = Field(None, description="Nombre de VMs découvertes")
    error: Optional[str] = Field(None, description="Message d'erreur si échec")

    # Audit D18 — `model_config` pour la cohérence de convention.
    model_config = ConfigDict(from_attributes=True)
