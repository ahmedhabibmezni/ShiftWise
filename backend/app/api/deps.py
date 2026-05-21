"""
ShiftWise API Dependencies

Dépendances FastAPI pour :
- Injection de la session de base de données
- Authentification JWT
- Vérification des permissions RBAC
- Isolation multi-tenancy

Ces dépendances sont utilisées dans les routes avec Depends().
"""

from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token, verify_token_type
from app.models.user import User
from app.crud import user as crud_user

# Security scheme pour JWT Bearer Token
security = HTTPBearer()

# S1192 — header WWW-Authenticate réutilisé sur chaque 401 d'authentification.
_WWW_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}


def get_current_user(
        db: Annotated[Session, Depends(get_db)],
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> User:
    """
    Récupère l'utilisateur actuellement authentifié.

    Décode le token JWT et récupère l'utilisateur depuis la BDD.

    Args:
        db: Session de base de données (injectée)
        credentials: Credentials HTTP Bearer (token JWT)

    Returns:
        User: Utilisateur authentifié

    Raises:
        HTTPException 401: Si token invalide/expiré, utilisateur introuvable
            ou compte inactif
        HTTPException 403: Si utilisateur inactif

    Usage dans une route:
        @router.get("/me")
        def get_me(current_user: Annotated[User, Depends(get_current_user)]):
            return current_user
    """
    # Récupérer le token depuis l'en-tête Authorization
    token = credentials.credentials

    # Décoder le token
    payload = decode_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers=_WWW_AUTHENTICATE,
        )

    # Vérifier que c'est un access token
    if not verify_token_type(payload, "access"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Type de token invalide",
            headers=_WWW_AUTHENTICATE,
        )

    # Récupérer l'user_id depuis le payload
    user_id: str = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide",
            headers=_WWW_AUTHENTICATE,
        )

    # Convertir l'ID — un sub non numérique indique un JWT corrompu
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide — identifiant utilisateur malformé",
            headers=_WWW_AUTHENTICATE,
        ) from None

    # Récupérer l'utilisateur depuis la BDD
    user = crud_user.get_user(db, user_id=user_id_int)

    if user is None:
        # Audit C-16 : un compte supprimé entre l'émission du token et son
        # usage retourne un 401 générique — surtout pas un 404, qui
        # confirmerait l'inexistence d'un id et permettrait l'énumération.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers=_WWW_AUTHENTICATE,
        )

    # Vérifier que l'utilisateur est actif
    if not user.is_active:
        # L'en-tête X-Account-Status permet au frontend de distinguer une
        # désactivation de compte d'un simple refus de permission RBAC —
        # les deux retournent un 403.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte utilisateur inactif",
            headers={"X-Account-Status": "deactivated"}
        )

    return user


def get_current_active_user(
        current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Alias pour get_current_user (pour compatibilité).

    Vérifie déjà que l'utilisateur est actif dans get_current_user.

    Args:
        current_user: Utilisateur authentifié

    Returns:
        User: Utilisateur actif
    """
    return current_user


def get_current_superuser(
        current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Vérifie que l'utilisateur actuel est un superuser.

    Args:
        current_user: Utilisateur authentifié

    Returns:
        User: Superuser

    Raises:
        HTTPException 403: Si l'utilisateur n'est pas superuser

    Usage:
        @router.delete("/users/{user_id}")
        def delete_user(
            user_id: int,
            current_user: Annotated[User, Depends(get_current_superuser)],
        ):
            # Seulement les superusers peuvent accéder
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions insuffisantes : superuser requis"
        )

    return current_user


def check_permission(resource: str, action: str):
    """
    Factory pour créer une dépendance de vérification de permission.

    Crée une fonction qui vérifie si l'utilisateur a une permission spécifique.

    Args:
        resource: Nom de la ressource (ex: "vms", "hypervisors")
        action: Action demandée (ex: "read", "create", "update", "delete")

    Returns:
        Fonction de dépendance FastAPI

    Raises:
        HTTPException 403: Si permission manquante

    Usage:
        @router.post("/vms")
        def create_vm(
            vm_data: VMCreate,
            current_user: Annotated[User, Depends(check_permission("vms", "create"))],
        ):
            # Seulement si l'utilisateur a la permission vms:create
    """

    def permission_checker(
            current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        """Vérifie la permission pour l'utilisateur actuel"""

        # Superuser a toutes les permissions
        if current_user.is_superuser:
            return current_user

        # Vérifier la permission
        if not current_user.has_permission(resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission manquante : {resource}:{action}"
            )

        return current_user

    return permission_checker



def get_current_user_tenant(
        current_user: Annotated[User, Depends(get_current_user)],
) -> str:
    """
    Récupère le tenant_id de l'utilisateur actuel.

    Utile pour filtrer automatiquement les requêtes par tenant.

    Args:
        current_user: Utilisateur authentifié

    Returns:
        str: tenant_id de l'utilisateur

    Usage:
        @router.get("/my-vms")
        def get_my_vms(
            tenant_id: Annotated[str, Depends(get_current_user_tenant)],
            db: Annotated[Session, Depends(get_db)],
        ):
            # Récupère automatiquement les VMs du tenant de l'utilisateur
            return crud_vm.get_vms_by_tenant(db, tenant_id)
    """
    return current_user.tenant_id


def validate_kubevirt_namespace(
        current_user: Annotated[User, Depends(get_current_user)],
        namespace: str | None = None,
) -> str:
    """
    Valide que le namespace demandé appartient au tenant de l'utilisateur.

    - Superuser : accepte n'importe quel namespace, ou retourne le namespace du tenant par défaut.
    - Utilisateur normal : namespace doit être shiftwise-{tenant_id} ou absent.

    Args:
        namespace: Namespace OpenShift demandé (optionnel)
        current_user: Utilisateur authentifié

    Returns:
        str: Namespace validé

    Raises:
        HTTPException 403: Si le namespace ne correspond pas au tenant de l'utilisateur
    """
    allowed = f"shiftwise-{current_user.tenant_id}"

    if current_user.is_superuser:
        return namespace or allowed

    if namespace and namespace != allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Accès interdit au namespace '{namespace}'"
        )
    return allowed


class PermissionChecker:
    """
    Classe pour vérifier plusieurs permissions à la fois.

    Permet de vérifier si l'utilisateur a AU MOINS UNE des permissions listées.

    Usage:
        # L'utilisateur doit avoir soit vms:read soit vms:update
        permission_checker = PermissionChecker([
            ("vms", "read"),
            ("vms", "update")
        ])

        @router.get("/vms")
        def get_vms(
            current_user: Annotated[User, Depends(permission_checker)],
        ):
            ...
    """

    def __init__(self, permissions: list[tuple[str, str]]):
        """
        Initialise le checker avec une liste de permissions.

        Args:
            permissions: Liste de tuples (resource, action)
        """
        self.permissions = permissions

    def __call__(
            self,
            current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        """
        Vérifie que l'utilisateur a au moins une des permissions.

        Args:
            current_user: Utilisateur authentifié

        Returns:
            User: Utilisateur avec permission

        Raises:
            HTTPException 403: Si aucune permission trouvée
        """
        # Superuser a toutes les permissions
        if current_user.is_superuser:
            return current_user

        # Vérifier chaque permission
        for resource, action in self.permissions:
            if current_user.has_permission(resource, action):
                return current_user

        # Aucune permission trouvée
        permissions_str = ", ".join([f"{r}:{a}" for r, a in self.permissions])
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Au moins une de ces permissions est requise : {permissions_str}"
        )

