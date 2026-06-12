"""
Politique de vérification des clés d'hôte SSH (audit H-02).

paramiko.AutoAddPolicy accepte aveuglément n'importe quelle clé d'hôte au
premier contact : un attaquant en position d'homme du milieu peut alors se
faire passer pour l'hyperviseur et capturer le mot de passe SSH en clair.

apply_host_key_policy() charge les known_hosts du système et REJETTE les
hôtes inconnus par défaut. Le mode « trust on first use » (AutoAddPolicy)
reste disponible pour le dev / POC via le réglage SSH_AUTO_ADD_HOST_KEYS.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def apply_host_key_policy(client) -> None:
    """
    Configure la vérification des clés d'hôte sur un client SSH paramiko.

    Args:
        client: une instance ``paramiko.SSHClient`` déjà créée.
    """
    import paramiko

    client.load_system_host_keys()

    if settings.SSH_AUTO_ADD_HOST_KEYS:
        # SV-010 — le « trust on first use » (AutoAddPolicy) accepte n'importe
        # quelle clé d'hôte au premier contact : un MITM capture alors le mot
        # de passe SSH en clair (hyperviseur / bastion). C'est tolérable en
        # dev / POC, jamais en production. On refuse FRANCHEMENT le drapeau
        # hors DEBUG plutôt que de le laisser silencieusement affaiblir la
        # sécurité d'un déploiement de prod.
        if not settings.DEBUG:
            raise RuntimeError(
                "SSH_AUTO_ADD_HOST_KEYS=True est interdit en production "
                "(DEBUG=False) : il désactive la vérification des clés d'hôte "
                "SSH (MITM). Pré-provisionner un known_hosts et laisser le "
                "drapeau à False."
            )
        logger.warning(
            "SSH_AUTO_ADD_HOST_KEYS actif — les clés d'hôte SSH ne sont PAS "
            "vérifiées (risque d'interception). Dev/POC uniquement."
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
