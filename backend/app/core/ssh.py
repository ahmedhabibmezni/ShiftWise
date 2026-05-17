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
        logger.warning(
            "SSH_AUTO_ADD_HOST_KEYS actif — les clés d'hôte SSH ne sont PAS "
            "vérifiées (risque d'interception). À désactiver en production."
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
