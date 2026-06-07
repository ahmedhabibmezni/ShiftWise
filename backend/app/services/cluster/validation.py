"""
Validation des configurations de connexion cluster (feature 002).

Fonctions pures, sans I/O ni session — facilement testables (R5). Chaque
fonction lève une exception spécifique du catalogue ci-dessous ; le routeur
les mappe sur des codes HTTP/erreur (cf. contracts/infrastructure-api.md).
"""

from __future__ import annotations

import os

import yaml

from app.models.cluster_config import ClusterScopeType, ClusterMode
# Réutilise le garde SSRF du domaine hyperviseur (Constitution Principe II :
# toute URL/hôte fourni par l'utilisateur doit passer par ce contrôle).
from app.schemas.hypervisor import _check_host_not_ssrf


class ClusterConfigValidationError(Exception):
    """Base des erreurs de validation de config cluster."""


class KubeconfigTooLarge(ClusterConfigValidationError):
    """Le fichier kubeconfig dépasse la taille maximale autorisée."""


class InvalidKubeconfig(ClusterConfigValidationError):
    """Le contenu n'est pas un kubeconfig bien formé."""


class ModeNotApplicable(ClusterConfigValidationError):
    """Le mode choisi ne peut pas s'appliquer dans cet environnement/scope."""


def validate_kubeconfig_bytes(raw: bytes, max_bytes: int) -> dict:
    """Valide un kubeconfig uploadé et retourne le document YAML parsé.

    Étapes : borne de taille → parse YAML → forme minimale d'un kubeconfig
    (``apiVersion``, ``clusters[].cluster.server``, ``contexts``, ``users``).

    Raises:
        KubeconfigTooLarge: si ``len(raw) > max_bytes``.
        InvalidKubeconfig: si le contenu n'est pas un kubeconfig valide.
    """
    if not raw:
        raise InvalidKubeconfig("fichier kubeconfig vide")
    if len(raw) > max_bytes:
        raise KubeconfigTooLarge(
            f"kubeconfig de {len(raw)} octets dépasse la limite de {max_bytes}"
        )

    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise InvalidKubeconfig(f"YAML invalide : {exc}") from exc

    if not isinstance(doc, dict):
        raise InvalidKubeconfig("le kubeconfig doit être un mapping YAML")

    _assert_kubeconfig_shape(doc)
    return doc


def _assert_kubeconfig_shape(doc: dict) -> None:
    """Vérifie la présence des clés essentielles d'un kubeconfig."""
    if "apiVersion" not in doc:
        raise InvalidKubeconfig("clé 'apiVersion' manquante")

    clusters = doc.get("clusters")
    if not isinstance(clusters, list) or not clusters:
        raise InvalidKubeconfig("section 'clusters' manquante ou vide")

    # Chaque ``clusters[*].cluster.server`` est une URL fournie par
    # l'utilisateur : elle DOIT passer par le même garde SSRF que ``api_url``
    # (Constitution Principe II). Sans cela, un kubeconfig pointant son server
    # vers 127.0.0.1 / 169.254.169.254 / loopback contournerait le contrôle
    # appliqué au mode custom — asymétrie de validateur.
    for cluster in clusters:
        server = (cluster or {}).get("cluster", {}).get("server")
        if not server:
            raise InvalidKubeconfig("'clusters[*].cluster.server' manquant")
        try:
            _check_host_not_ssrf(server)
        except ValueError as exc:
            raise InvalidKubeconfig(f"cluster.server refusé : {exc}") from exc

    if not isinstance(doc.get("contexts"), list) or not doc["contexts"]:
        raise InvalidKubeconfig("section 'contexts' manquante ou vide")

    if not isinstance(doc.get("users"), list) or not doc["users"]:
        raise InvalidKubeconfig("section 'users' manquante ou vide")


def assert_mode_applicable(scope_type: ClusterScopeType, mode: ClusterMode) -> None:
    """Garantit que ``mode`` est applicable pour ``scope_type`` ici.

    - ``INCLUSTER`` n'est valable que pour le scope défaut plateforme ET
      uniquement si le process tourne dans un cluster
      (``KUBERNETES_SERVICE_HOST`` présent) — c'est le cas "in-cluster sur un
      poste Windows" qui doit échouer franchement.

    Raises:
        ModeNotApplicable: si la combinaison scope/mode/environnement est
            inapplicable.
    """
    if mode != ClusterMode.INCLUSTER:
        return

    if scope_type != ClusterScopeType.PLATFORM_DEFAULT:
        raise ModeNotApplicable(
            "le mode in-cluster n'est disponible que pour le défaut plateforme"
        )

    if not os.getenv("KUBERNETES_SERVICE_HOST"):
        raise ModeNotApplicable(
            "le mode in-cluster est indisponible : le service ne tourne pas "
            "dans un cluster Kubernetes (KUBERNETES_SERVICE_HOST absent)"
        )
