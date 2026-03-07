"""
ShiftWise Authentication Schemas

Schémas Pydantic pour l'authentification et l'autorisation.

Inclut :
- Login (email/password)
- Tokens (access + refresh)
- Changement de mot de passe
- Vérification d'email
"""

from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """
    Schéma pour la requête de connexion.

    Utilisé lors de POST /api/v1/auth/login
    """
    email: EmailStr = Field(
        ...,
        description="Email de l'utilisateur",
        example="ahmed.mezni@nextstep.tn"
    )

    password: str = Field(
        ...,
        min_length=1,
        description="Mot de passe",
        example="SecurePassword123!"
    )


class TokenResponse(BaseModel):
    """
    Schéma pour la réponse contenant les tokens.

    Retourné après login réussi ou refresh token.
    """
    access_token: str = Field(
        ...,
        description="Token JWT d'accès (courte durée)",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    )

    refresh_token: str = Field(
        ...,
        description="Token JWT de refresh (longue durée)",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.."
    )

    token_type: str = Field(
        default="bearer",
        description="Type de token (toujours 'bearer')"
    )

    expires_in: int = Field(
        ...,
        description="Durée de validité du access_token en secondes",
        example=1800
    )


class RefreshTokenRequest(BaseModel):
    """
    Schéma pour la requête de refresh du token.

    Utilisé lors de POST /api/v1/auth/refresh
    """
    refresh_token: str = Field(
        ...,
        description="Token de refresh à utiliser pour obtenir un nouveau access_token",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    )


class ChangePasswordRequest(BaseModel):
    """
    Schéma pour le changement de mot de passe.

    Utilisé lors de POST /api/v1/auth/change-password
    """
    current_password: str = Field(
        ...,
        min_length=1,
        description="Mot de passe actuel",
        example="OldPassword123!"
    )

    new_password: str = Field(
        ...,
        min_length=8,
        description="Nouveau mot de passe",
        example="NewSecurePassword123!"
    )


class ResetPasswordRequest(BaseModel):
    """
    Schéma pour la demande de réinitialisation de mot de passe.

    Utilisé lors de POST /api/v1/auth/reset-password/request
    """
    email: EmailStr = Field(
        ...,
        description="Email de l'utilisateur",
        example="ahmed.mezni@nextstep.tn"
    )


class ResetPasswordConfirm(BaseModel):
    """
    Schéma pour la confirmation de réinitialisation de mot de passe.

    Utilisé lors de POST /api/v1/auth/reset-password/confirm
    """
    token: str = Field(
        ...,
        description="Token de réinitialisation reçu par email",
        example="abc123xyz789"
    )

    new_password: str = Field(
        ...,
        min_length=8,
        description="Nouveau mot de passe",
        example="NewSecurePassword123!"
    )


class VerifyEmailRequest(BaseModel):
    """
    Schéma pour la vérification d'email.

    Utilisé lors de POST /api/v1/auth/verify-email
    """
    token: str = Field(
        ...,
        description="Token de vérification reçu par email",
        example="verify123abc"
    )


class MessageResponse(BaseModel):
    """
    Schéma pour les réponses simples avec message.

    Utilisé pour les confirmations d'actions.
    """
    message: str = Field(
        ...,
        description="Message de confirmation ou d'erreur",
        example="Mot de passe modifié avec succès"
    )

    success: bool = Field(
        default=True,
        description="Indique si l'opération a réussi"
    )


class TokenPayload(BaseModel):
    """
    Schéma représentant le payload d'un token JWT décodé.

    Utilisé en interne pour valider les tokens.
    """
    sub: str = Field(
        ...,
        description="Subject du token (user_id)",
        example="123"
    )

    exp: int = Field(
        ...,
        description="Timestamp d'expiration",
        example=1234567890
    )

    type: str = Field(
        ...,
        description="Type de token (access ou refresh)",
        example="access"
    )