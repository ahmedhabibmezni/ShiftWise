"""
ShiftWise Authentication Routes.

Modèle :
- /login : pose un refresh token en cookie HttpOnly + retourne l'access dans
  le body. Crée une famille refresh côté Redis.
- /refresh : lit le cookie, valide (family_id, jti) contre Redis, rotate,
  repose un nouveau cookie. Détecte le reuse (token rejoué après rotation)
  et révoque toute la famille dans ce cas.
- /logout : efface le cookie + supprime la famille du store.
- /me, /change-password, /verify : inchangés (utilisent l'access token).

Stockage des refresh tokens : voir app.core.refresh_token_store.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.login_throttle import (
    check_lockout,
    record_failure,
    reset as reset_throttle,
)
from app.core.refresh_token_store import (
    RotateOk,
    RotateReuseDetected,
    RotateUnknown,
    create_family,
    revoke_family,
    rotate,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    validate_password_strength,
    verify_password,
    verify_token_type,
)
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    TokenResponse,
)
from app.schemas.user import UserReadWithPermissions
from app.crud import user as crud_user
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()

CREDENTIALS_INVALID_MSG = "Email ou mot de passe incorrect"
ACCOUNT_INACTIVE_MSG = "Compte inactif. Contactez l'administrateur."
REFRESH_INVALID_MSG = "Refresh token invalide ou expiré"

# En-tête signalant une désactivation de compte. Le frontend l'utilise pour
# notifier l'utilisateur puis le déconnecter proprement.
INACTIVE_ACCOUNT_HEADERS = {"X-Account-Status": "deactivated"}


def _set_refresh_cookie(response: Response, refresh_jwt: str) -> None:
    """Attach the refresh cookie with hardened attributes."""
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_jwt,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
    )


def _issue_access_token(user_id: int) -> TokenResponse:
    access = create_access_token(
        subject=str(user_id),
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(
        access_token=access,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _mint_refresh(user_id: int) -> str:
    """Create a new refresh family and return the signed JWT."""
    family_id, jti = create_family(user_id)
    return create_refresh_token(
        subject=str(user_id),
        family_id=family_id,
        jti=jti,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def _rotate_refresh(family_id: str, jti: str, user_id: int) -> str:
    """Rotate the refresh JWT inside an existing family."""
    result = rotate(family_id, jti, user_id)
    if isinstance(result, RotateReuseDetected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session révoquée : token rejoué détecté",
        )
    if isinstance(result, RotateUnknown):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=REFRESH_INVALID_MSG,
        )
    assert isinstance(result, RotateOk)
    return create_refresh_token(
        subject=str(user_id),
        family_id=family_id,
        jti=result.new_jti,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def _client_ip(request: Request) -> str | None:
    """Return the client IP for audit-trail purposes.

    Uses `request.client.host` as the single source. In production behind
    a reverse proxy this is set correctly when uvicorn is launched with
    `--proxy-headers --forwarded-allow-ips=<proxy CIDR>` — that's where
    the trust decision belongs, not in this handler.
    """
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse)
def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Authentifie l'utilisateur et émet la paire (access body + refresh cookie).

    - Brute-force protection: per-email + per-IP throttle in Redis (DB 1).
      Locked-out attempts short-circuit before bcrypt to avoid the
      authenticate cost amplifying a DoS.
    - Audit trail: stamps `last_login_at` + `last_login_ip` on success.
    """
    ip = _client_ip(request)

    # Throttle check first — locked-out attackers must not pay the
    # bcrypt cost or rotate the audit timestamp.
    lockout = check_lockout(login_data.email, ip)
    if lockout is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Trop de tentatives. Réessayez dans "
                f"{lockout.retry_after_seconds} secondes."
            ),
            headers={"Retry-After": str(lockout.retry_after_seconds)},
        )

    user = crud_user.authenticate_user(
        db,
        email=login_data.email,
        password=login_data.password,
    )
    if not user:
        # Wrong email OR wrong password — both count toward the lockout.
        # Same key (lowercased email) regardless of whether the email
        # actually exists, so a probe attack can't enumerate accounts by
        # comparing throttle behaviour.
        record_failure(login_data.email, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=CREDENTIALS_INVALID_MSG,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        # Inactive accounts also feed the counter so an attacker can't
        # use a deactivated account to probe whether their target user
        # still exists.
        record_failure(login_data.email, ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ACCOUNT_INACTIVE_MSG,
            headers=INACTIVE_ACCOUNT_HEADERS,
        )

    # Genuine success — clear both throttle buckets so the operator
    # isn't punished by their own earlier typos.
    reset_throttle(login_data.email, ip)

    # Stamp the audit fields BEFORE minting tokens — we want the trail
    # to be persisted even if the cookie write below somehow fails. The
    # IP is truncated at 45 chars (IPv6 max) so a forged absurdly-long
    # header from a misconfigured proxy can't blow up the column.
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip[:45] if ip else None
    db.commit()

    refresh_jwt = _mint_refresh(user.id)
    _set_refresh_cookie(response, refresh_jwt)
    return _issue_access_token(user.id)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token_endpoint(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    refresh_cookie: Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)] = None,
):
    """
    Renouvelle l'access token via le cookie refresh HttpOnly.

    Valide la famille/jti contre Redis, détecte le reuse, rotate.
    """
    if not refresh_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=REFRESH_INVALID_MSG,
        )

    payload = decode_token(refresh_cookie)
    if payload is None or not verify_token_type(payload, "refresh"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=REFRESH_INVALID_MSG,
        )

    user_id_str = payload.get("sub")
    family_id = payload.get("fam")
    jti = payload.get("jti")
    if not user_id_str or not family_id or not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=REFRESH_INVALID_MSG,
        )

    try:
        user_id = int(user_id_str)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=REFRESH_INVALID_MSG,
        )

    user = crud_user.get_user(db, user_id=user_id)
    if not user:
        # User deleted between refreshes — wipe the family preemptively.
        revoke_family(family_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=REFRESH_INVALID_MSG,
        )
    if not user.is_active:
        revoke_family(family_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ACCOUNT_INACTIVE_MSG,
            headers=INACTIVE_ACCOUNT_HEADERS,
        )

    new_refresh_jwt = _rotate_refresh(family_id, jti, user_id)
    _set_refresh_cookie(response, new_refresh_jwt)
    return _issue_access_token(user_id)


@router.post("/logout", response_model=MessageResponse)
def logout(
    response: Response,
    refresh_cookie: Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)] = None,
):
    """
    Déconnexion : efface le cookie et révoque la famille refresh.

    Volontairement non authentifié (pas de dépendance sur l'access token) :
    permet un logout cohérent même si l'access est déjà expiré.
    """
    if refresh_cookie:
        payload = decode_token(refresh_cookie)
        if payload and verify_token_type(payload, "refresh"):
            family_id = payload.get("fam")
            if family_id:
                revoke_family(family_id)

    _clear_refresh_cookie(response)
    return MessageResponse(message="Déconnexion réussie", success=True)


@router.get("/me", response_model=UserReadWithPermissions)
def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Récupère les informations de l'utilisateur connecté."""
    user_data = UserReadWithPermissions.model_validate(current_user)
    user_data.permissions = current_user.get_all_permissions()
    return user_data


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    password_data: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Change le mot de passe de l'utilisateur connecté."""
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe actuel incorrect",
        )
    if password_data.current_password == password_data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit être différent de l'ancien",
        )

    is_valid, error_msg = validate_password_strength(password_data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    current_user.hashed_password = get_password_hash(password_data.new_password)
    db.commit()
    return MessageResponse(
        message="Mot de passe modifié avec succès",
        success=True,
    )


@router.get(
    "/verify",
    response_model=MessageResponse,
    dependencies=[Depends(get_current_user)],
)
def verify_token():
    """Vérifie la validité de l'access token courant."""
    return MessageResponse(message="Token valide", success=True)
