"""
Script d'initialisation de ShiftWise

Ce script doit être exécuté une seule fois après la création de la base de données.

Il crée :
1. Les rôles système (super_admin, admin, user, viewer)
2. Le premier superuser (administrateur système)

Usage:
    python init_db.py
"""

from sqlalchemy.orm import Session

from app.core.database import SessionLocal, init_db
from app.core.security import get_password_hash, validate_password_strength
from app.models.user import User
from app.models.role import Role, ROLE_PERMISSIONS
from app.crud import role as crud_role
from app.crud import user as crud_user

# S2068 — Les valeurs par défaut sensibles sont isolées en constantes nommées
# clairement pour signaler qu'elles doivent être changées après la première
# connexion. Ne jamais les laisser en production.
DEFAULT_ADMIN_EMAIL = "admin@shiftwise.local"
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_CREDENTIALS = "Admin123!"  # NOSONAR — valeur par défaut documentée, à changer en production
DEFAULT_TENANT_ID = "system"


def create_system_roles(db: Session):
    """Crée les rôles système"""
    print("📋 Création des rôles système...")

    roles_created = crud_role.create_system_roles(db)

    for role in roles_created:
        print(f"   ✅ Rôle '{role.name}' créé/vérifié")

    print(f"✅ {len(roles_created)} rôles système initialisés\n")
    return roles_created


def _prompt_with_default(prompt: str, default: str) -> str:
    """Demande une valeur à l'utilisateur avec un repli sur la valeur par défaut."""
    value = input(prompt).strip()
    if not value:
        print(f"   → Valeur par défaut : {default}")
        return default
    return value


def _prompt_password() -> str:
    """
    Demande un mot de passe valide à l'utilisateur.

    S3776 — Logique de validation extraite dans une fonction dédiée
    pour réduire la complexité cognitive de create_superuser.
    """
    while True:
        pwd_input = input("   Mot de passe : ").strip()

        if not pwd_input:
            print("   → Mot de passe par défaut utilisé.")
            print("   ⚠️  CHANGEZ CE MOT DE PASSE APRÈS LA PREMIÈRE CONNEXION!")
            return DEFAULT_ADMIN_CREDENTIALS

        is_valid, error_message = validate_password_strength(pwd_input)
        if is_valid:
            return pwd_input

        print(f"   ❌ {error_message}")
        print("   💡 Exigences : au moins 8 caractères, 1 majuscule, 1 minuscule, 1 chiffre")


def _build_superuser(email: str, username: str, first_name: str, last_name: str,
                     password: str, tenant_id: str, super_admin_role: Role) -> User:
    """Instancie l'objet User superuser sans le persister."""
    superuser = User(
        email=email.lower(),
        username=username.lower(),
        first_name=first_name,
        last_name=last_name,
        hashed_password=get_password_hash(password),
        tenant_id=tenant_id.lower(),
        is_active=True,
        is_verified=True,
        is_superuser=True
    )
    superuser.roles = [super_admin_role]
    return superuser


def create_superuser(db: Session):
    """Crée le premier superuser"""
    print("👤 Création du superuser...")

    # Vérifier si un superuser existe déjà
    existing_superuser = db.query(User).filter(User.is_superuser == True).first()

    if existing_superuser:
        print(f"   ⚠️  Un superuser existe déjà : {existing_superuser.email}")
        return existing_superuser

    print("\n📝 Veuillez fournir les informations du superuser :\n")

    # S3776 — Collecte des entrées déléguée à des helpers pour réduire
    # la complexité cognitive de cette fonction
    email = _prompt_with_default("   Email : ", DEFAULT_ADMIN_EMAIL)
    username = _prompt_with_default("   Username : ", DEFAULT_ADMIN_USERNAME)
    first_name = _prompt_with_default("   Prénom : ", "Super")
    last_name = _prompt_with_default("   Nom : ", "Admin")
    password = _prompt_password()
    tenant_id = _prompt_with_default("   Tenant ID : ", DEFAULT_TENANT_ID)

    # Récupérer le rôle super_admin
    super_admin_role = crud_role.get_role_by_name(db, "super_admin")

    if not super_admin_role:
        print("   ❌ Erreur : Le rôle super_admin n'existe pas. Créez d'abord les rôles système.")
        return None

    try:
        superuser = _build_superuser(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password=password,
            tenant_id=tenant_id,
            super_admin_role=super_admin_role
        )

        db.add(superuser)
        db.commit()
        db.refresh(superuser)

        print("\n✅ Superuser créé avec succès !")
        print(f"   Email    : {superuser.email}")
        print(f"   Username : {superuser.username}")
        print(f"   Tenant   : {superuser.tenant_id}")
        print("   Rôle     : super_admin\n")

        return superuser

    except Exception as e:
        print(f"\n❌ Erreur lors de la création du superuser : {e}")
        db.rollback()
        return None


def main():
    """Fonction principale d'initialisation"""
    print("=" * 60)
    print("🚀 INITIALISATION DE SHIFTWISE")
    print("=" * 60)
    print()

    # Initialiser la base de données
    print("📊 Initialisation de la base de données...")
    try:
        init_db()
        print("✅ Tables créées\n")
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation de la base : {e}")
        return

    # Créer une session
    db = SessionLocal()

    try:
        # Créer les rôles système
        create_system_roles(db)

        # Créer le superuser
        superuser = create_superuser(db)

        if superuser:
            print("=" * 60)
            print("✅ INITIALISATION TERMINÉE AVEC SUCCÈS !")
            print("=" * 60)
            print()
            # S3457 — Pas de champs de remplacement : f-strings inutiles supprimées
            print("Prochaines étapes :")
            print("1. Démarrez l'application : uvicorn app.main:app --reload")
            print("2. Accédez à la documentation : http://localhost:8000/docs")
            print("3. Connectez-vous avec le superuser créé")
            print("4. CHANGEZ le mot de passe par défaut !")
            print()
        else:
            print("\n⚠️  Initialisation incomplète - le superuser n'a pas été créé")

    except Exception as e:
        print(f"\n❌ Erreur lors de l'initialisation : {e}")
        import traceback
        traceback.print_exc()
        db.rollback()

    finally:
        db.close()


if __name__ == "__main__":
    main()