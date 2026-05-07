"""
Non-interactive DB bootstrap — pour le Job OpenShift d'init.

1. Crée le schéma complet via SQLAlchemy `Base.metadata.create_all()` puis
   marque les migrations Alembic comme appliquées (`alembic stamp head`).
   Raison : la 1ère migration `b8951ce66d27` fait des `ALTER TABLE roles`
   en supposant que les tables `roles`/`users` existent déjà — historiquement
   créées par `init_db.py` (create_all). Sans ce chemin l'upgrade échoue
   sur une base vierge.
2. Seed les 4 rôles système (super_admin / admin / user / viewer).
3. (Optionnel) Crée un superuser si BOOTSTRAP_SUPERUSER_EMAIL est défini —
   sinon skip pour éviter de créer un compte avec un mot de passe par défaut.

Variables d'env reconnues (toutes optionnelles sauf marquées) :
    BOOTSTRAP_SUPERUSER_EMAIL     (déclencheur — si absent, pas de superuser)
    BOOTSTRAP_SUPERUSER_USERNAME  (défaut: admin)
    BOOTSTRAP_SUPERUSER_PASSWORD  (REQUIS si email fourni)
    BOOTSTRAP_SUPERUSER_TENANT    (défaut: system)

Le script est idempotent : peut être ré-exécuté en toute sécurité — `create_all`
ne touche pas les tables existantes, `alembic stamp head` est no-op si la
révision courante est déjà head.
"""

from __future__ import annotations

import os
import subprocess
import sys

# Importe tous les modèles pour peupler Base.metadata avant create_all
# (effet de bord à l'import — les imports semblent inutilisés mais ils
# enregistrent les classes auprès de Base.metadata).
from app.models import (  # noqa: F401
    user as _user_module,
    role as _role_module,
    hypervisor as _hypervisor_module,
    virtual_machine as _vm_module,
    migration as _migration_module,
    conversion as _conversion_module,
)
from app.core.database import Base, SessionLocal, engine
from app.core.security import get_password_hash, validate_password_strength
from app.crud import role as crud_role
from app.models.user import User


def run_schema_bootstrap() -> None:
    print("[bootstrap] create_all (SQLAlchemy)", flush=True)
    Base.metadata.create_all(bind=engine)

    print("[bootstrap] alembic stamp head", flush=True)
    result = subprocess.run(
        ["alembic", "stamp", "head"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, flush=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr, flush=True)
        sys.exit(result.returncode)


def seed_system_roles(db) -> None:
    print("[bootstrap] seeding system roles", flush=True)
    roles = crud_role.create_system_roles(db)
    for r in roles:
        print(f"  - {r.name}", flush=True)


def maybe_create_superuser(db) -> None:
    email = os.getenv("BOOTSTRAP_SUPERUSER_EMAIL")
    if not email:
        print("[bootstrap] BOOTSTRAP_SUPERUSER_EMAIL not set — skipping superuser", flush=True)
        return

    password = os.getenv("BOOTSTRAP_SUPERUSER_PASSWORD")
    if not password:
        print("[bootstrap] BOOTSTRAP_SUPERUSER_PASSWORD missing — abort", file=sys.stderr, flush=True)
        sys.exit(2)

    valid, err = validate_password_strength(password)
    if not valid:
        print(f"[bootstrap] superuser password rejected: {err}", file=sys.stderr, flush=True)
        sys.exit(2)

    if db.query(User).filter(User.email == email.lower()).first():
        print(f"[bootstrap] superuser {email} already exists — skip", flush=True)
        return

    role = crud_role.get_role_by_name(db, "super_admin")
    if role is None:
        print("[bootstrap] super_admin role missing — seed_system_roles failed", file=sys.stderr, flush=True)
        sys.exit(3)

    user = User(
        email=email.lower(),
        username=os.getenv("BOOTSTRAP_SUPERUSER_USERNAME", "admin").lower(),
        hashed_password=get_password_hash(password),
        tenant_id=os.getenv("BOOTSTRAP_SUPERUSER_TENANT", "system").lower(),
        is_active=True,
        is_verified=True,
        is_superuser=True,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    print(f"[bootstrap] superuser created: {user.email}", flush=True)


def main() -> None:
    run_schema_bootstrap()
    db = SessionLocal()
    try:
        seed_system_roles(db)
        maybe_create_superuser(db)
    finally:
        db.close()
    print("[bootstrap] done", flush=True)


if __name__ == "__main__":
    main()
