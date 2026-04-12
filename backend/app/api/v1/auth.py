"""
ShiftWise Authentication Routes

Routes pour l'authentification et la gestion des tokens :
- Login (email + password)
- Refresh token
- Changement de mot de passe
- Récupération du profil utilisateur

Toutes les routes retournent des réponses JSON standardisées.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_token_type,
    get_password_hash,
    verify_password,
    validate_password_strength
)
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    ChangePasswordRequest,
    MessageResponse
)
from app.schemas.user import UserReadWithPermissions
from app.crud import user as crud_user
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(
        login_data: LoginRequest,
        db: Annotated[Session, Depends(get_db)]
):
    """
    Authentifie un utilisateur et retourne les tokens JWT.

    **Process :**
    1. Vérifie email + mot de passe
    2. Génère access_token (courte durée)
    3. Génère refresh_token (longue durée)

    **Returns :**
    - access_token : Pour les requêtes API (30 min)
    - refresh_token : Pour renouveler l'access_token (7 jours)
    - token_type : "bearer"
    - expires_in : Durée de validité en secondes

    **Errors :**
    - 401 : Email ou mot de passe incorrect
    - 403 : Compte inactif

    **Example :**
    ```json
    POST /api/v1/auth/login
    {
        "email": "ahmed@nextstep.tn",
        "password": "SecurePassword123!"
    }
    ```
    """
    # Authentifier l'utilisateur
    user = crud_user.authenticate_user(
        db,
        email=login_data.email,
        password=login_data.password
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Vérifier que le compte est actif
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte inactif. Contactez l'administrateur."
        )

    # Générer les tokens
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=str(user.id),
        expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_token = create_refresh_token(
        subject=str(user.id),
        expires_delta=refresh_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # En secondes
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
        refresh_data: RefreshTokenRequest,
        db: Annotated[Session, Depends(get_db)]
):
    """
    Renouvelle l'access_token en utilisant le refresh_token.

    **Process :**
    1. Valide le refresh_token
    2. Vérifie que l'utilisateur existe et est actif
    3. Génère un nouvel access_token

    **Returns :**
    - Nouveaux tokens (access + refresh)

    **Errors :**
    - 401 : Refresh token invalide ou expiré
    - 403 : Compte inactif
    - 404 : Utilisateur non trouvé

    **Example :**
    ```json
    POST /api/v1/auth/refresh
    {
        "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    }
    ```
    """
    # Décoder le refresh token
    payload = decode_token(refresh_data.refresh_token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Vérifier que c'est bien un refresh token
    if not verify_token_type(payload, "refresh"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Type de token invalide",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Récupérer l'utilisateur
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide",
        )

    user = crud_user.get_user(db, user_id=int(user_id))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )

    # Vérifier que le compte est actif
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte inactif"
        )

    # Générer de nouveaux tokens
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=str(user.id),
        expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    new_refresh_token = create_refresh_token(
        subject=str(user.id),
        expires_delta=refresh_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.get("/me", response_model=UserReadWithPermissions)
def get_current_user_info(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)]
):
    """
    Récupère les informations de l'utilisateur connecté.

    **Returns :**
    - Profil utilisateur complet
    - Rôles assignés
    - Permissions calculées

    **Requires :**
    - Token JWT valide dans l'en-tête Authorization

    **Example :**
    ```
    GET /api/v1/auth/me
    Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    ```

    **Response :**
    ```json
    {
        "id": 1,
        "email": "ahmed@nextstep.tn",
        "username": "ahmedm",
        "full_name": "Ahmed MEZNI",
        "tenant_id": "nextstep",
        "roles": [
            {
                "id": 1,
                "name": "admin",
                "permissions": {"vms": ["*"], "hypervisors": ["*"]}
            }
        ],
        "permissions": {
            "vms": ["read", "create", "update", "delete"],
            "hypervisors": ["read", "create", "update", "delete"]
        }
    }
    ```
    """
    # Construire la réponse avec permissions
    user_data = UserReadWithPermissions.model_validate(current_user)
    user_data.permissions = current_user.get_all_permissions()

    return user_data


@router.post("/change-password", response_model=MessageResponse)
def change_password(
        password_data: ChangePasswordRequest,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)]
):
    """
    Change le mot de passe de l'utilisateur connecté.

    **Process :**
    1. Vérifie le mot de passe actuel
    2. Hash le nouveau mot de passe
    3. Met à jour en base de données

    **Returns :**
    - Message de confirmation

    **Errors :**
    - 400 : Mot de passe actuel incorrect

    **Example :**
    ```json
    POST /api/v1/auth/change-password
    Authorization: Bearer <token>
    {
        "current_password": "OldPassword123!",
        "new_password": "NewSecurePassword123!"
    }
    ```
    """
    # Vérifier le mot de passe actuel
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe actuel incorrect"
        )

    # Vérifier que le nouveau mot de passe est différent
    if password_data.current_password == password_data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit être différent de l'ancien"
        )

    # Valider la force du nouveau mot de passe
    is_valid, error_msg = validate_password_strength(password_data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Hasher et mettre à jour le mot de passe
    current_user.hashed_password = get_password_hash(password_data.new_password)
    db.commit()

    return MessageResponse(
        message="Mot de passe modifié avec succès",
        success=True
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
        current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Déconnexion de l'utilisateur.

    **Note :** Avec JWT, la déconnexion côté serveur n'est pas nécessaire.
    Le client doit simplement supprimer ses tokens.

    Cette route existe pour la cohérence de l'API et pourrait être étendue
    pour ajouter le token à une blacklist si nécessaire.

    **Returns :**
    - Message de confirmation

    **Example :**
    ```
    POST /api/v1/auth/logout
    Authorization: Bearer <token>
    ```
    """
    return MessageResponse(
        message="Déconnexion réussie. Supprimez vos tokens côté client.",
        success=True
    )


@router.get("/verify", response_model=MessageResponse)
def verify_token(
        current_user: Annotated[User, Depends(get_current_user)]
):
    """
    Vérifie la validité du token JWT.

    **Returns :**
    - Message de confirmation si token valide

    **Errors :**
    - 401 : Token invalide ou expiré

    **Example :**
    ```
    GET /api/v1/auth/verify
    Authorization: Bearer <token>
    ```

    **Response :**
    ```json
    {
        "message": "Token valide",
        "success": true
    }
    ```
    """
    return MessageResponse(
        message="Token valide",
        success=True
    )