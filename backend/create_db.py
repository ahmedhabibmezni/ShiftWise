"""
Script de création automatique de la base de données ShiftWise
À exécuter AVANT init_db.py
"""

import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Forcer l'encodage UTF-8 sur Windows
if sys.platform == "win32":
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'

print("=" * 60)
print("🗄️  CRÉATION DE LA BASE DE DONNÉES SHIFTWISE")
print("=" * 60)
print()

# Récupérer les informations de connexion
db_host = os.getenv("DATABASE_HOST", "localhost")
db_port = int(os.getenv("DATABASE_PORT", "5432"))
db_name = os.getenv("DATABASE_NAME", "shiftwise_db")
db_user = os.getenv("DATABASE_USER", "postgres")
db_password = os.getenv("DATABASE_PASSWORD", "")

print("📋 Configuration :")
print(f"   Host     : {db_host}")
print(f"   Port     : {db_port}")
print(f"   Database : {db_name}")
print(f"   User     : {db_user}")
print()

# Étape 1 : Se connecter à la base "postgres" (qui existe toujours)
print("🔌 Connexion au serveur PostgreSQL...")

try:
    # Connexion à la base postgres par défaut
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        database='postgres',  # Base par défaut
        user=db_user,
        password=db_password,
        client_encoding='UTF8'
    )

    # Activer autocommit pour créer la base
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

    cursor = conn.cursor()

    print("✅ Connexion réussie au serveur PostgreSQL")
    print()

    # Vérifier la version
    cursor.execute("SELECT version();")
    version = cursor.fetchone()[0]
    print(f"📦 Version PostgreSQL : {version[:60]}...")
    print()

except Exception as e:
    print(f"❌ Erreur de connexion : {e}")
    print()
    print("Vérifiez que :")
    print("  - PostgreSQL est démarré")
    print("  - Les identifiants dans .env sont corrects")
    print("  - Le port 5432 est accessible")
    sys.exit(1)

# Étape 2 : Vérifier si la base existe déjà
print(f"🔍 Vérification de l'existence de '{db_name}'...")

try:
    cursor.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s;",
        (db_name,)
    )

    exists = cursor.fetchone()

    if exists:
        print(f"⚠️  La base de données '{db_name}' existe déjà !")
        print()

        response = input("Voulez-vous la supprimer et la recréer ? (oui/non) : ").strip().lower()

        if response in ['oui', 'o', 'yes', 'y']:
            print(f"🗑️  Suppression de '{db_name}'...")

            # Forcer la déconnexion de tous les utilisateurs
            cursor.execute(f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{db_name}'
                AND pid <> pg_backend_pid();
            """)

            # Supprimer la base
            cursor.execute(f"DROP DATABASE {db_name};")
            print(f"✅ Base '{db_name}' supprimée")
            print()
        else:
            print("❌ Opération annulée. La base existante est conservée.")
            cursor.close()
            conn.close()
            sys.exit(0)

except Exception as e:
    print(f"❌ Erreur lors de la vérification : {e}")
    cursor.close()
    conn.close()
    sys.exit(1)

# Étape 3 : Créer la base de données
print(f"🔨 Création de la base de données '{db_name}'...")

try:
    # Créer la base avec encodage UTF8
    cursor.execute(f"""
        CREATE DATABASE {db_name}
        WITH 
        ENCODING = 'UTF8'
        LC_COLLATE = 'French_France.1252'
        LC_CTYPE = 'French_France.1252'
        TEMPLATE = template0;
    """)

    print(f"✅ Base de données '{db_name}' créée avec succès !")
    print()

except Exception as e:
    # Si l'erreur est due aux locales, essayer avec C
    print(f"⚠️  Erreur avec les locales françaises : {e}")
    print("🔄 Tentative avec les locales par défaut...")

    try:
        cursor.execute(f"""
            CREATE DATABASE {db_name}
            WITH 
            ENCODING = 'UTF8'
            LC_COLLATE = 'C'
            LC_CTYPE = 'C'
            TEMPLATE = template0;
        """)

        print(f"✅ Base de données '{db_name}' créée avec les locales par défaut")
        print()

    except Exception as e2:
        print(f"❌ Erreur lors de la création : {e2}")
        cursor.close()
        conn.close()
        sys.exit(1)

# Étape 4 : Vérifier la création
print("🔍 Vérification de la création...")

try:
    cursor.execute("""
        SELECT 
            datname, 
            pg_encoding_to_char(encoding) as encoding,
            datcollate,
            datctype
        FROM pg_database 
        WHERE datname = %s;
    """, (db_name,))

    result = cursor.fetchone()

    if result:
        print("✅ Vérification réussie :")
        print(f"   Nom      : {result[0]}")
        print(f"   Encoding : {result[1]}")
        print(f"   Collate  : {result[2]}")
        print(f"   Ctype    : {result[3]}")
        print()

except Exception as e:
    print(f"⚠️  Impossible de vérifier : {e}")
    print()

# Fermer la connexion
cursor.close()
conn.close()

print("=" * 60)
print("✅ BASE DE DONNÉES CRÉÉE AVEC SUCCÈS !")
print("=" * 60)
print()
print("🎯 Prochaines étapes :")
print("1. Lancez le patch : python patch_database.py")
print("2. Lancez l'initialisation : python init_db_alt.py")
print("   OU directement : python init_db.py")
print()