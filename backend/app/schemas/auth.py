"""
ShiftWise Authentication Schemas

Schémas Pydantic pour l'authentification et l'autorisation.

Inclut :
- Login (email/password)
- Tokens (access + refresh)
- Changement de mot de passe
- Vérification d'email
"""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """
    Schéma pour la requête de connexion.

    Utilisé lors de POST /api/v1/auth/login
    """
    email: EmailStr = Field(
        ...,
        description="Email de l'utilisateur",
        json_schema_extra={"example": "ahmed.mezni@nextstep.tn"}
    )

    password: str = Field(
        ...,
        min_length=1,
        description="Mot de passe",
        json_schema_extra={"example": "SecurePassword123!"}
    )


class TokenResponse(BaseModel):
    """
    Réponse contenant l'access token.

    Le refresh token n'est PAS retourné dans le body : il est posé en cookie
    HttpOnly / Secure / SameSite=Strict par /login et /refresh. Le client
    JavaScript n'y a jamais accès, ce qui élimine la classe de vols par XSS.
    """
    access_token: str = Field(
        ...,
        description="Token JWT d'accès (courte durée)",
        json_schema_extra={"example": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}
    )

    token_type: str = Field(
        default="bearer",
        description="Type de token (toujours 'bearer')"
    )

    expires_in: int = Field(
        ...,
        description="Durée de validité de l'access_token en secondes",
        json_schema_extra={"example": 900}
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
        json_schema_extra={"example": "OldPassword123!"}
    )

    new_password: str = Field(
        ...,
        min_length=8,
        description="Nouveau mot de passe",
        json_schema_extra={"example": "NewSecurePassword123!"}
    )


class ResetPasswordRequest(BaseModel):
    """
    Schéma pour la demande de réinitialisation de mot de passe.

    Utilisé lors de POST /api/v1/auth/reset-password/request
    """
    email: EmailStr = Field(
        ...,
        description="Email de l'utilisateur",
        json_schema_extra={"example": "ahmed.mezni@nextstep.tn"}
    )


class ResetPasswordConfirm(BaseModel):
    """
    Schéma pour la confirmation de réinitialisation de mot de passe.

    Utilisé lors de POST /api/v1/auth/reset-password/confirm
    """
    token: str = Field(
        ...,
        description="Token de réinitialisation reçu par email",
        json_schema_extra={"example": "abc123xyz789"}
    )

    new_password: str = Field(
        ...,
        min_length=8,
        description="Nouveau mot de passe",
        json_schema_extra={"example": "NewSecurePassword123!"}
    )


class VerifyEmailRequest(BaseModel):
    """
    Schéma pour la vérification d'email.

    Utilisé lors de POST /api/v1/auth/verify-email
    """
    token: str = Field(
        ...,
        description="Token de vérification reçu par email",
        json_schema_extra={"example": "verify123abc"}
    )


class MessageResponse(BaseModel):
    """
    Schéma pour les réponses simples avec message.

    Utilisé pour les confirmations d'actions.
    """
    message: str = Field(
        ...,
        description="Message de confirmation ou d'erreur",
        json_schema_extra={"example": "Mot de passe modifié avec succès"}
    )

    success: bool = Field(
        default=True,
        description="Indique si l'opération a réussi"
    )


class TokenPayload(BaseModel):
    """
    Schéma représentant le payload d'un token JWT décodé.

    Les champs `fam` et `jti` ne sont présents que sur les refresh tokens.
    """
    sub: str = Field(..., description="Subject (user_id)")
    exp: int = Field(..., description="Timestamp d'expiration")
    type: str = Field(..., description="access | refresh")
    fam: str | None = Field(default=None, description="Family id (refresh only)")
    jti: str | None = Field(default=None, description="Token id (refresh only)")