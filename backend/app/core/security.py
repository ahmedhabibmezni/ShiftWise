"""
ShiftWise Security Module

Ce module gère :
- Le hashing des mots de passe (bcrypt)
- La génération et validation des tokens JWT
- La création de tokens d'accès et de refresh
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
import jwt

from app.core.config import settings

# SV-022 — hashing bcrypt via la bibliothèque ``bcrypt`` directement, sans
# passlib. passlib 1.7.4 est abandonné et incompatible avec bcrypt >= 4.1
# (il lit le shim retiré ``bcrypt.__about__``), ce qui figeait la stack sur
# bcrypt 4.0.1 et empêchait de prendre les futurs correctifs de sécurité. Le
# format de hash reste ``$2b$`` : les hashes existants restent valides
# (``bcrypt.checkpw`` les vérifie), seules les internes changent.

# Bcrypt has a maximum password length of 72 bytes
MAX_PASSWORD_LENGTH = 72


def _reject_over_length(password: str) -> None:
    """
    Rejette un mot de passe dépassant la limite bcrypt de 72 bytes.

    Audit A16 — bcrypt ignore silencieusement tout octet au-delà du 72e.
    Tronquer (l'ancien comportement) faisait que deux mots de passe
    distincts partageant un préfixe de 72 octets produisaient le même
    hash : un mot de passe long est alors équivalent à son préfixe, ce
    qui affaiblit l'entropie effective. On refuse explicitement la valeur
    plutôt que de la tronquer. La longueur est mesurée en OCTETS UTF-8,
    pas en caractères (les caractères multi-octets comptent pour plus).

    Raises:
        ValueError: Si le mot de passe encodé en UTF-8 dépasse 72 octets.
    """
    if len(password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Le mot de passe ne peut pas dépasser {MAX_PASSWORD_LENGTH} octets "
            "(limite bcrypt)"
        )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Vérifie si un mot de passe en clair correspond au hash.

    Args:
        plain_password: Mot de passe en clair saisi par l'utilisateur
        hashed_password: Hash stocké en base de données

    Returns:
        bool: True si le mot de passe est correct, False sinon

    Raises:
        ValueError: Si le mot de passe dépasse 72 octets (Audit A16).

    Example:
        >>> verify_password("MonMotDePasse123", "$2b$12$...")
        True
    """
    # Audit A16 — un mot de passe trop long ne peut pas correspondre : il
    # n'aurait jamais pu être haché. On rejette au lieu de tronquer.
    _reject_over_length(plain_password)
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # Hash malformé / non-bcrypt en base — traité comme non-correspondance
        # plutôt que de propager une exception au point d'authentification.
        return False


def get_password_hash(password: str) -> str:
    """
    Hash un mot de passe en clair avec bcrypt.

    Args:
        password: Mot de passe en clair à hasher

    Returns:
        str: Hash bcrypt du mot de passe

    Example:
        >>> get_password_hash("MonMotDePasse123")
        '$2b$12$KIXqF7...'

    Raises:
        ValueError: Si le mot de passe est vide ou dépasse 72 octets (A16).
    """
    if not password:
        raise ValueError("Le mot de passe ne peut pas être vide")

    # Audit A16 — refuser un mot de passe au-delà de la limite bcrypt
    # plutôt que de le tronquer silencieusement.
    _reject_over_length(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(
        subject: str,
        expires_delta: timedelta | None = None
) -> str:
    """
    Crée un token JWT d'accès.

    Le token contient l'identifiant de l'utilisateur (subject)
    et une date d'expiration.

    Args:
        subject: Identifiant de l'utilisateur (généralement user_id)
        expires_delta: Durée de validité du token (optionnel)

    Returns:
        str: Token JWT encodé

    Example:
        >>> create_access_token(subject="user123")
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    # Payload du token
    to_encode = {
        "exp": expire,  # Date d'expiration
        "sub": str(subject),  # Subject (user_id)
        "type": "access"  # Type de token
    }

    # Encoder le token avec la clé secrète
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(
        subject: str,
        family_id: str,
        jti: str,
        expires_delta: timedelta | None = None
) -> str:
    """
    Crée un token JWT de refresh.

    Le refresh token embarque (family_id, jti) pour permettre la détection
    de reuse côté serveur via le store Redis (voir refresh_token_store).
    L'absence de ces deux claims rend le token inexploitable.

    Args:
        subject: Identifiant de l'utilisateur (user_id)
        family_id: Identifiant de la famille de refresh (uuid hex)
        jti: Identifiant unique du token dans la famille (uuid hex)
        expires_delta: Durée de validité (optionnel)

    Returns:
        str: Refresh token JWT encodé
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "refresh",
        "fam": family_id,
        "jti": jti,
    }

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """
    Décode et valide un token JWT.

    Args:
        token: Token JWT à décoder

    Returns:
        dict: Payload du token si valide, None sinon

    Example:
        >>> decode_token("eyJhbGciOiJIUzI1...")
        {'exp': 1234567890, 'sub': 'user123', 'type': 'access'}
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            # SV-003 — `settings.ALGORITHM` is allowlisted to HS256/384/512 by
            # the config validator, so `none` / asymmetric confusion can never
            # reach here.
            # SV-004 — require the structural claims explicitly: a token minted
            # without `exp` would otherwise be accepted forever (PyJWT only
            # validates `exp` when it is present). Fail-closed on any token
            # missing expiry / subject / type.
            options={"require": ["exp", "sub", "type"]},
        )
        return payload
    except jwt.PyJWTError:
        return None


def verify_token_type(payload: dict, token_type: str) -> bool:
    """
    Vérifie que le token est du bon type (access ou refresh).

    Args:
        payload: Payload décodé du token
        token_type: Type attendu ("access" ou "refresh")

    Returns:
        bool: True si le type correspond, False sinon
    """
    return payload.get("type") == token_type


# SV-019 — jeu de caractères spéciaux unique, partagé par TOUS les points
# d'entrée (création de compte, reset admin, self-service change-password) afin
# qu'un seul et même plancher de robustesse s'applique au même secret.
PASSWORD_SPECIAL_CHARS = r'[!@#$%^&*(),.?":{}|<>]'


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Valide la force d'un mot de passe (validateur unique — SV-019).

    Exigences : >= 8 caractères, au plus 72 octets (limite bcrypt), au moins
    une minuscule, une majuscule, un chiffre ET un caractère spécial. C'est
    la seule source de vérité de la politique : `schemas/user.py` (création /
    update) et `/auth/change-password` délèguent tous ici pour éviter trois
    politiques divergentes pour le même secret.

    Args:
        password: Mot de passe à valider

    Returns:
        tuple[bool, str]: (est_valide, message_erreur)

    Example:
        >>> validate_password_strength("abc")
        (False, "Le mot de passe doit contenir au moins 8 caractères")
    """
    import re

    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères"

    if len(password.encode('utf-8')) > MAX_PASSWORD_LENGTH:
        return False, f"Le mot de passe ne peut pas dépasser {MAX_PASSWORD_LENGTH} bytes"

    # Vérifier la présence de différents types de caractères
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)

    if not (has_lower and has_upper and has_digit):
        return False, "Le mot de passe doit contenir au moins une minuscule, une majuscule et un chiffre"

    if not re.search(PASSWORD_SPECIAL_CHARS, password):
        return False, "Le mot de passe doit contenir au moins un caractère spécial"

    return True, ""
