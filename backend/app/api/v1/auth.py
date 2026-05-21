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
    client_ip_from_request,
    record_failure,
    reset as reset_throttle,
)
from app.core import refresh_token_store
from app.core.refresh_token_store import (
    RotateOk,
    RotateReuseDetected,
    RotateUnknown,
    create_family,
    family_user_id,
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


def _revoke_all_refresh_families(user_id: int) -> int:
    """Revoke every refresh-token family owned by `user_id`.

    Audit A-15 — a password change must invalidate every outstanding
    session. The family store has no user→family index, so we scan the
    `<prefix><family>:meta` keys (one per family, short-lived) and revoke
    the families whose meta `user_id` matches. Returns the family count.

    The scan reuses the store's own Redis handle (and is patched together
    with it in tests), so it stays consistent with the store keyspace.
    """
    redis = refresh_token_store.get_redis()
    meta_pattern = f"{refresh_token_store._FAM_PREFIX}*:meta"
    revoked = 0
    for meta_key in redis.scan_iter(match=meta_pattern, count=100):
        owner = redis.hget(meta_key, "user_id")
        if owner is None or int(owner) != user_id:
            continue
        # Key shape: "<prefix><family_id>:meta" — strip the fixed bookends.
        family_id = meta_key[len(refresh_token_store._FAM_PREFIX):-len(":meta")]
        revoke_family(family_id)
        revoked += 1
    return revoked


def _client_ip(request: Request) -> str | None:
    """Return the client IP for the throttle counters + audit trail.

    Audit A11 — delegates to ``client_ip_from_request``: ``X-Forwarded-For``
    is honoured only when the TCP peer is a configured trusted proxy
    (``settings.TRUSTED_PROXY_IPS``). Behind the OpenShift Route this
    yields the real client IP rather than the router's — so the per-IP
    login throttle keys per attacker and ``last_login_ip`` stays accurate.
    """
    return client_ip_from_request(request)


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
    # Audit A-09 — user-enumeration hardening: wrong email, wrong password
    # AND inactive account all return the SAME 401 with the SAME body and
    # NO distinguishing header. An attacker probing /login cannot tell a
    # non-existent account from a disabled one from a bad password.
    if not user or not user.is_active:
        # Every rejected attempt feeds the lockout counter on the same key
        # (lowercased email) regardless of the rejection reason, so the
        # throttle behaviour can't be used as an oracle either.
        record_failure(login_data.email, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=CREDENTIALS_INVALID_MSG,
            headers={"WWW-Authenticate": "Bearer"},
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
        ) from None

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

    Audit A-18 — la famille n'est révoquée que si le cookie en prouve la
    propriété : le `sub` du JWT doit correspondre au propriétaire enregistré
    de la famille. Sans cette vérification, un JWT forgé (`sub` quelconque,
    `fam` = famille d'une victime) permettrait de déconnecter un tiers (DoS).
    Le cookie est effacé dans tous les cas — un logout ne doit jamais échouer.
    """
    if refresh_cookie:
        payload = decode_token(refresh_cookie)
        if payload and verify_token_type(payload, "refresh"):
            family_id = payload.get("fam")
            subject = payload.get("sub")
            if family_id and subject is not None:
                owner_id = family_user_id(family_id)
                if owner_id is not None and str(owner_id) == str(subject):
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

    # Audit A-15 — a password change must terminate every other session:
    # revoke all the user's refresh-token families so a stolen refresh
    # token (the credential a password change is meant to neutralise)
    # can no longer be rotated into fresh access tokens.
    _revoke_all_refresh_families(current_user.id)

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
