"""
ShiftWise Security Module

Ce module gère :
- Le hashing des mots de passe (bcrypt)
- La génération et validation des tokens JWT
- La création de tokens d'accès et de refresh
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext

from app.core.config import settings

# Context pour le hashing des mots de passe avec bcrypt
# bcrypt est recommandé pour les mots de passe (lent = plus sécurisé contre brute force)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bcrypt has a maximum password length of 72 bytes
MAX_PASSWORD_LENGTH = 72


def _truncate_password(password: str) -> str:
    """
    Tronque le mot de passe à 72 bytes pour bcrypt.

    Bcrypt a une limite de 72 bytes. Si le mot de passe est plus long,
    on le tronque de manière sécurisée.

    Args:
        password: Mot de passe en clair

    Returns:
        str: Mot de passe tronqué si nécessaire
    """
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > MAX_PASSWORD_LENGTH:
        # Tronquer à 72 bytes de manière sécurisée
        return password_bytes[:MAX_PASSWORD_LENGTH].decode('utf-8', errors='ignore')
    return password


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Vérifie si un mot de passe en clair correspond au hash.

    Args:
        plain_password: Mot de passe en clair saisi par l'utilisateur
        hashed_password: Hash stocké en base de données

    Returns:
        bool: True si le mot de passe est correct, False sinon

    Example:
        >>> verify_password("MonMotDePasse123", "$2b$12$...")
        True
    """
    # Tronquer le mot de passe si nécessaire avant vérification
    plain_password = _truncate_password(plain_password)
    return pwd_context.verify(plain_password, hashed_password)


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
        ValueError: Si le mot de passe est vide
    """
    if not password:
        raise ValueError("Le mot de passe ne peut pas être vide")

    # Tronquer le mot de passe si nécessaire avant hashing
    password = _truncate_password(password)
    return pwd_context.hash(password)


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
        expires_delta: timedelta | None = None
) -> str:
    """
    Crée un token JWT de refresh.

    Le refresh token permet d'obtenir un nouveau access token
    sans redemander les credentials. Il a une durée de vie plus longue.

    Args:
        subject: Identifiant de l'utilisateur (généralement user_id)
        expires_delta: Durée de validité du token (optionnel)

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
        "type": "refresh"  # Type refresh pour distinguer
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
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
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


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Valide la force d'un mot de passe.

    Args:
        password: Mot de passe à valider

    Returns:
        tuple[bool, str]: (est_valide, message_erreur)

    Example:
        >>> validate_password_strength("abc")
        (False, "Le mot de passe doit contenir au moins 8 caractères")
    """
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

    return True, ""