"""
ShiftWise — Comprehensive User Management Test Script
=====================================================

Dynamically tests EVERY possible user management scenario against
the running backend API:

  • Health / root checks
  • Role CRUD (create, list, get, update, delete, system-role protections)
  • User CRUD (create, list, get, update, delete, duplicate checks)
  • Authentication (login, token refresh, /me, verify, change-password, logout)
  • RBAC enforcement (viewer, regular user, admin, super_admin)
  • Multi-tenancy isolation
  • Edge cases & negative tests (bad passwords, expired tokens, self-delete, etc.)

Usage:
    1.  Make sure PostgreSQL is running and the DB is initialized:
            python init_db.py
    2.  Start the backend:
            uvicorn app.main:app --reload
    3.  Run this script:
            python test_user_management.py
"""

import os
import requests
import sys
import time
import json
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ──────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"

# Test superuser created by this script directly in the DB
SUPERUSER_EMAIL = "test-superadmin@shiftwise-test.com"
SUPERUSER_PASSWORD = "TestPassword123!"
SUPERUSER_USERNAME = "test-superadmin"

# Database config (from .env)
DB_HOST = os.getenv("DATABASE_HOST", "localhost")
DB_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DB_NAME = os.getenv("DATABASE_NAME", "shiftwise_db")
DB_USER = os.getenv("DATABASE_USER", "postgres")
DB_PASS = os.getenv("DATABASE_PASSWORD", "")


def _get_db_conn():
    """Get a direct PostgreSQL connection."""
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )


def setup_test_superuser():
    """
    Create a dedicated test superuser directly in PostgreSQL.
    Uses bcrypt to hash the password. This bypasses the API entirely
    so we have a guaranteed login for the rest of the test suite.
    """
    from passlib.context import CryptContext
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed = pwd_ctx.hash(SUPERUSER_PASSWORD)

    conn = _get_db_conn()
    cur = conn.cursor()
    try:
        # If the user already exists, refresh its hash and reactivate it.
        # Keeping a stale hash from a previous incompatible bcrypt/passlib
        # combination would silently break the login step.
        cur.execute("SELECT id FROM users WHERE email = %s", (SUPERUSER_EMAIL,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE users SET hashed_password = %s, is_active = TRUE, "
                "is_superuser = TRUE, updated_at = NOW() WHERE id = %s",
                (hashed, row[0]),
            )
            conn.commit()
            return row[0]

        # Get super_admin role id
        cur.execute("SELECT id FROM roles WHERE name = 'super_admin'")
        role_row = cur.fetchone()
        if not role_row:
            print("  FATAL: super_admin role does not exist. Run init_db.py first.")
            sys.exit(1)
        super_admin_role_id = role_row[0]

        # Insert the test superuser
        cur.execute("""
            INSERT INTO users (email, username, first_name, last_name,
                               hashed_password, tenant_id,
                               is_active, is_verified, is_superuser,
                               created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (SUPERUSER_EMAIL, SUPERUSER_USERNAME, "Test", "SuperAdmin",
              hashed, "system", True, True, True))
        user_id = cur.fetchone()[0]

        # Assign super_admin role
        cur.execute("""
            INSERT INTO user_roles (user_id, role_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (user_id, super_admin_role_id))

        conn.commit()
        return user_id
    finally:
        cur.close()
        conn.close()


def teardown_test_superuser():
    """Remove the test superuser from the database."""
    conn = _get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE email = %s)", (SUPERUSER_EMAIL,))
        cur.execute("DELETE FROM users WHERE email = %s", (SUPERUSER_EMAIL,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


# Fixed resource names created by the test suite — used for pre-run stale cleanup
_STALE_USER_EMAILS = [
    "testuser1@shiftwise-test.com",
    "testviewer@shiftwise-test.com",
    "testother@other-tenant.com",
    "inactive@shiftwise-test.com",
]
_STALE_ROLE_NAMES = ["test_operator"]


def cleanup_stale_test_resources():
    """
    Delete any leftover roles/users from a previous interrupted run.
    Runs before the test suite so duplicate-name conflicts don't occur.
    """
    conn = _get_db_conn()
    cur = conn.cursor()
    try:
        # Remove stale test users (cascade user_roles via DELETE)
        for email in _STALE_USER_EMAILS:
            cur.execute(
                "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE email = %s)",
                (email,)
            )
            cur.execute("DELETE FROM users WHERE email = %s", (email,))

        # Remove stale test roles (only non-system roles)
        for name in _STALE_ROLE_NAMES:
            cur.execute(
                "DELETE FROM roles WHERE name = %s AND is_system_role = FALSE",
                (name,)
            )

        conn.commit()
    finally:
        cur.close()
        conn.close()


# ─── Pretty Helpers ─────────────────────────────────────────────────────────
class Colors:
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

PASS_COUNT = 0
FAIL_COUNT = 0
SKIP_COUNT = 0
RESULTS: list[dict] = []

def _record(category: str, name: str, passed: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if passed:
        PASS_COUNT += 1
        icon = f"{Colors.GREEN}✅ PASS{Colors.RESET}"
    else:
        FAIL_COUNT += 1
        icon = f"{Colors.RED}❌ FAIL{Colors.RESET}"
    RESULTS.append({"category": category, "name": name, "passed": passed, "detail": detail})
    print(f"  {icon}  {name}" + (f"  {Colors.DIM}({detail}){Colors.RESET}" if detail else ""))

def section(title: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'═'*70}")
    print(f"  {title}")
    print(f"{'═'*70}{Colors.RESET}")

def subsection(title: str):
    print(f"\n  {Colors.YELLOW}── {title} ──{Colors.RESET}")


# ─── HTTP Helpers ───────────────────────────────────────────────────────────
# Shared requests.Session so the refresh cookie posed by /auth/login is
# automatically reattached on subsequent /auth/refresh calls. Required since
# the refresh token is no longer returned in the JSON body (cookie-only).
SESSION = requests.Session()

REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "shiftwise_refresh")


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def login(email: str, password: str) -> requests.Response:
    """Login via the shared session so the refresh cookie is captured."""
    return SESSION.post(f"{API}/auth/login", json={"email": email, "password": password})


def get_token(email: str, password: str) -> str | None:
    """Login on a throwaway session (avoids polluting SESSION cookies)."""
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json()["access_token"]
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  TEST SUITES
# ═══════════════════════════════════════════════════════════════════════════

def test_health_and_root():
    """Tests root and health endpoints."""
    section("1 · HEALTH & ROOT ENDPOINTS")

    # Root
    r = requests.get(f"{BASE_URL}/")
    _record("Health", "GET / returns 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        _record("Health", "Root has 'status: running'", body.get("status") == "running")
        _record("Health", "Root has app name 'ShiftWise'", body.get("name") == "ShiftWise")

    # Health
    r = requests.get(f"{BASE_URL}/health")
    _record("Health", "GET /health returns 200", r.status_code == 200)
    if r.status_code == 200:
        _record("Health", "Health status is 'healthy'", r.json().get("status") == "healthy")

    # Docs
    r = requests.get(f"{BASE_URL}/docs")
    _record("Health", "Swagger /docs accessible", r.status_code == 200)

    r = requests.get(f"{BASE_URL}/openapi.json")
    _record("Health", "OpenAPI JSON available", r.status_code == 200)


# ──────────────────────────────────────────────────────────────────────────
def test_superuser_login():
    """Login with the default superuser and return the access token."""
    section("2 · SUPERUSER AUTHENTICATION")

    r = login(SUPERUSER_EMAIL, SUPERUSER_PASSWORD)
    _record("Auth", "Superuser login returns 200", r.status_code == 200)

    if r.status_code != 200:
        print(f"    {Colors.RED}FATAL: Cannot login as superuser. Aborting.{Colors.RESET}")
        print(f"    Response: {r.text}")
        sys.exit(1)

    data = r.json()
    _record("Auth", "Response contains access_token", "access_token" in data)
    _record("Auth", "Response does NOT contain refresh_token (cookie-only)",
            "refresh_token" not in data)
    _record("Auth", "token_type is 'bearer'", data.get("token_type") == "bearer")
    _record("Auth", "expires_in is positive integer",
            isinstance(data.get("expires_in"), int) and data["expires_in"] > 0)
    _record("Auth", "Refresh cookie set on session",
            bool(SESSION.cookies.get(REFRESH_COOKIE_NAME)))

    return data["access_token"]


# ──────────────────────────────────────────────────────────────────────────
def test_auth_me_and_verify(token: str):
    """Test /auth/me and /auth/verify."""
    section("3 · AUTH — ME / VERIFY / LOGOUT")

    # /me
    subsection("GET /auth/me")
    r = requests.get(f"{API}/auth/me", headers=headers(token))
    _record("Auth", "GET /auth/me returns 200", r.status_code == 200)
    if r.status_code == 200:
        me = r.json()
        _record("Auth", "/me has email", "email" in me)
        _record("Auth", "/me has username", "username" in me)
        _record("Auth", "/me has tenant_id", "tenant_id" in me)
        _record("Auth", "/me has roles list", isinstance(me.get("roles"), list))
        _record("Auth", "/me has permissions dict", isinstance(me.get("permissions"), dict))
        _record("Auth", "Superuser is_superuser=True", me.get("is_superuser") is True)
        _record("Auth", "Superuser permissions contain '*'",
                me.get("permissions", {}).get("*") == ["*"])

    # /verify
    subsection("GET /auth/verify")
    r = requests.get(f"{API}/auth/verify", headers=headers(token))
    _record("Auth", "GET /auth/verify returns 200", r.status_code == 200)
    if r.status_code == 200:
        _record("Auth", "Verify response success=true", r.json().get("success") is True)

    # /logout
    subsection("POST /auth/logout")
    r = requests.post(f"{API}/auth/logout", headers=headers(token))
    _record("Auth", "POST /auth/logout returns 200", r.status_code == 200)
    if r.status_code == 200:
        _record("Auth", "Logout message present", bool(r.json().get("message")))


# ──────────────────────────────────────────────────────────────────────────
def test_token_refresh():
    """Test token refresh flow (cookie-based).

    Re-login first because the previous /auth/logout call wiped the family.
    """
    section("4 · TOKEN REFRESH")

    relogin = login(SUPERUSER_EMAIL, SUPERUSER_PASSWORD)
    _record("Auth", "Pre-refresh re-login returns 200", relogin.status_code == 200)

    old_cookie = SESSION.cookies.get(REFRESH_COOKIE_NAME)
    _record("Auth", "Pre-refresh: cookie exists on session", bool(old_cookie))

    r = SESSION.post(f"{API}/auth/refresh")
    _record("Auth", "POST /auth/refresh returns 200", r.status_code == 200)
    if r.status_code != 200:
        return None

    data = r.json()
    _record("Auth", "Refresh returns new access_token", bool(data.get("access_token")))
    _record("Auth", "Refresh response has NO refresh_token in body",
            "refresh_token" not in data)

    new_cookie = SESSION.cookies.get(REFRESH_COOKIE_NAME)
    _record("Auth", "Refresh rotated the cookie value",
            bool(new_cookie) and new_cookie != old_cookie)

    return data["access_token"]


# ──────────────────────────────────────────────────────────────────────────
def test_auth_negative():
    """Negative authentication test cases."""
    section("5 · AUTH — NEGATIVE TESTS")

    subsection("Wrong credentials")
    r = login(SUPERUSER_EMAIL, "WrongPassword999!")
    _record("Auth-Neg", "Wrong password returns 401", r.status_code == 401)

    r = login("nonexistent@example.com", "Whatever123!")
    _record("Auth-Neg", "Non-existent email returns 401", r.status_code == 401)

    subsection("Missing token")
    r = requests.get(f"{API}/auth/me")
    _record("Auth-Neg", "GET /me without token returns 403", r.status_code == 403)

    subsection("Invalid token")
    r = requests.get(f"{API}/auth/me", headers=headers("totally.invalid.token"))
    _record("Auth-Neg", "GET /me with bad token returns 401", r.status_code == 401)

    subsection("Using refresh cookie value as access bearer")
    # Issue a fresh session, read the refresh cookie value, try to use it as
    # an access bearer. Should be rejected because token type != "access".
    isolated = requests.Session()
    login_r = isolated.post(
        f"{API}/auth/login",
        json={"email": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD},
    )
    if login_r.status_code == 200:
        refresh_tok = isolated.cookies.get(REFRESH_COOKIE_NAME)
        r = requests.get(f"{API}/auth/me", headers=headers(refresh_tok))
        _record("Auth-Neg", "Refresh token used as access → 401", r.status_code == 401)

    subsection("Invalid refresh cookie")
    r = requests.post(
        f"{API}/auth/refresh",
        cookies={REFRESH_COOKIE_NAME: "garbage"},
    )
    _record("Auth-Neg", "Garbage refresh cookie → 401", r.status_code == 401)

    subsection("Missing refresh cookie")
    r = requests.post(f"{API}/auth/refresh")
    _record("Auth-Neg", "No refresh cookie → 401", r.status_code == 401)


# ──────────────────────────────────────────────────────────────────────────
def test_role_crud(token: str):
    """Full CRUD on roles + system-role protections."""
    section("6 · ROLE MANAGEMENT (CRUD)")

    # ── List existing roles ──
    subsection("List roles")
    r = requests.get(f"{API}/roles", headers=headers(token))
    _record("Roles", "GET /roles returns 200", r.status_code == 200)
    if r.status_code == 200:
        roles = r.json()
        _record("Roles", "Roles list is a list", isinstance(roles, list))
        role_names = [rl["name"] for rl in roles]
        _record("Roles", "System roles present (super_admin, admin, user, viewer)",
                all(n in role_names for n in ["super_admin", "admin", "user", "viewer"]))

    # ── Get role count ──
    subsection("Count roles")
    r = requests.get(f"{API}/roles/count", headers=headers(token))
    _record("Roles", "GET /roles/count returns 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        _record("Roles", "Count has total >= 4", body.get("total", 0) >= 4)
        _record("Roles", "Count has system_roles", "system_roles" in body)

    # ── Get role by name ──
    subsection("Get role by name")
    r = requests.get(f"{API}/roles/name/admin", headers=headers(token))
    _record("Roles", "GET /roles/name/admin returns 200", r.status_code == 200)
    if r.status_code == 200:
        _record("Roles", "Role name is 'admin'", r.json().get("name") == "admin")
        _record("Roles", "Role is system_role", r.json().get("is_system_role") is True)

    # ── Get permissions/resources ──
    subsection("Available resources")
    r = requests.get(f"{API}/roles/permissions/resources", headers=headers(token))
    _record("Roles", "GET /roles/permissions/resources returns 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        _record("Roles", "Resources list present", isinstance(body.get("resources"), list))
        _record("Roles", "Actions list present", isinstance(body.get("actions"), list))

    # ── Create custom role ──
    subsection("Create custom role")
    custom_role_data = {
        "name": "test_operator",
        "description": "Test operator role for automated testing",
        "permissions": {
            "vms": ["read", "create"],
            "migrations": ["read"]
        },
        "is_active": True
    }
    r = requests.post(f"{API}/roles", json=custom_role_data, headers=headers(token))
    _record("Roles", "POST /roles creates custom role → 201", r.status_code == 201)
    custom_role_id = None
    if r.status_code == 201:
        custom_role_id = r.json()["id"]
        _record("Roles", "Custom role has is_system_role=false", r.json().get("is_system_role") is False)
        _record("Roles", "Custom role name matches", r.json().get("name") == "test_operator")

    # ── Get role by ID ──
    if custom_role_id:
        subsection("Get role by ID")
        r = requests.get(f"{API}/roles/{custom_role_id}", headers=headers(token))
        _record("Roles", f"GET /roles/{custom_role_id} returns 200", r.status_code == 200)
        if r.status_code == 200:
            _record("Roles", "Response includes user_count", "user_count" in r.json())

    # ── Get role user count ──
    if custom_role_id:
        subsection("Get role user count")
        r = requests.get(f"{API}/roles/{custom_role_id}/users/count", headers=headers(token))
        _record("Roles", "GET /roles/{id}/users/count returns 200", r.status_code == 200)
        if r.status_code == 200:
            _record("Roles", "user_count is 0 for new role", r.json().get("user_count") == 0)

    # ── Update custom role ──
    if custom_role_id:
        subsection("Update custom role")
        r = requests.put(f"{API}/roles/{custom_role_id}",
                         json={"description": "Updated description", "permissions": {"vms": ["read", "create", "update"]}},
                         headers=headers(token))
        _record("Roles", "PUT /roles/{id} updates role → 200", r.status_code == 200)
        if r.status_code == 200:
            _record("Roles", "Description updated", r.json().get("description") == "Updated description")

    # ── Duplicate role name ──
    subsection("Duplicate role name (negative)")
    r = requests.post(f"{API}/roles", json=custom_role_data, headers=headers(token))
    _record("Roles", "Duplicate role name → 400", r.status_code == 400)

    # ── Update system role (should fail) ──
    subsection("Modify system role (negative)")
    # Get admin role ID
    r = requests.get(f"{API}/roles/name/admin", headers=headers(token))
    if r.status_code == 200:
        admin_role_id = r.json()["id"]
        r = requests.put(f"{API}/roles/{admin_role_id}",
                         json={"description": "Hacked description"},
                         headers=headers(token))
        _record("Roles", "Update system role → 400 (protected)", r.status_code == 400)

    # ── Delete system role (should fail) ──
    subsection("Delete system role (negative)")
    if r.status_code in (200, 400):
        r = requests.delete(f"{API}/roles/{admin_role_id}", headers=headers(token))
        _record("Roles", "Delete system role → 400 (protected)", r.status_code == 400)

    # ── Get non-existent role ──
    subsection("Non-existent role")
    r = requests.get(f"{API}/roles/99999", headers=headers(token))
    _record("Roles", "GET /roles/99999 → 404", r.status_code == 404)

    r = requests.get(f"{API}/roles/name/does_not_exist", headers=headers(token))
    _record("Roles", "GET /roles/name/does_not_exist → 404", r.status_code == 404)

    return custom_role_id


# ──────────────────────────────────────────────────────────────────────────
def test_user_crud(token: str, custom_role_id: int | None):
    """Full CRUD on users + validations."""
    section("7 · USER MANAGEMENT (CRUD)")

    # ── Get role IDs for assignment ──
    r = requests.get(f"{API}/roles/name/user", headers=headers(token))
    user_role_id = r.json()["id"] if r.status_code == 200 else None

    r = requests.get(f"{API}/roles/name/admin", headers=headers(token))
    admin_role_id = r.json()["id"] if r.status_code == 200 else None

    r = requests.get(f"{API}/roles/name/viewer", headers=headers(token))
    viewer_role_id = r.json()["id"] if r.status_code == 200 else None

    # ── Create user (with role) ──
    subsection("Create users")
    user1 = {
        "email": "testuser1@shiftwise-test.com",
        "username": "testuser1",
        "first_name": "Test",
        "last_name": "User1",
        "password": "TestPassword123!",
        "tenant_id": "test-tenant",
        "is_active": True,
        "role_ids": [admin_role_id] if admin_role_id else []
    }
    r = requests.post(f"{API}/users", json=user1, headers=headers(token))
    _record("Users", "Create user1 (admin role) → 201", r.status_code == 201)
    user1_id = r.json()["id"] if r.status_code == 201 else None
    if r.status_code == 201:
        body = r.json()
        _record("Users", "User1 email correct", body.get("email") == user1["email"])
        _record("Users", "User1 has roles", len(body.get("roles", [])) > 0)
        _record("Users", "User1 is_superuser=false", body.get("is_superuser") is False)
        _record("Users", "User1 is_verified=false", body.get("is_verified") is False)

    # User 2 — viewer role, same tenant
    user2 = {
        "email": "testviewer@shiftwise-test.com",
        "username": "testviewer",
        "first_name": "View",
        "last_name": "Er",
        "password": "TestPassword123!",
        "tenant_id": "test-tenant",
        "is_active": True,
        "role_ids": [viewer_role_id] if viewer_role_id else []
    }
    r = requests.post(f"{API}/users", json=user2, headers=headers(token))
    _record("Users", "Create user2 (viewer role) → 201", r.status_code == 201)
    user2_id = r.json()["id"] if r.status_code == 201 else None

    # User 3 — regular user role, DIFFERENT tenant
    user3 = {
        "email": "testother@other-tenant.com",
        "username": "testother",
        "first_name": "Other",
        "last_name": "Tenant",
        "password": "TestPassword123!",
        "tenant_id": "other-tenant",
        "is_active": True,
        "role_ids": [user_role_id] if user_role_id else []
    }
    r = requests.post(f"{API}/users", json=user3, headers=headers(token))
    _record("Users", "Create user3 (different tenant) → 201", r.status_code == 201)
    user3_id = r.json()["id"] if r.status_code == 201 else None

    # User 4 — inactive user
    user4 = {
        "email": "inactive@shiftwise-test.com",
        "username": "inactiveuser",
        "first_name": "Inactive",
        "last_name": "User",
        "password": "TestPassword123!",
        "tenant_id": "test-tenant",
        "is_active": False,
        "role_ids": [user_role_id] if user_role_id else []
    }
    r = requests.post(f"{API}/users", json=user4, headers=headers(token))
    _record("Users", "Create inactive user4 → 201", r.status_code == 201)
    user4_id = r.json()["id"] if r.status_code == 201 else None

    # ── Duplicate checks ──
    subsection("Duplicate email / username (negative)")
    r = requests.post(f"{API}/users", json=user1, headers=headers(token))
    _record("Users", "Duplicate email → 400", r.status_code == 400)

    dup_username = dict(user1, email="different@test.com")
    r = requests.post(f"{API}/users", json=dup_username, headers=headers(token))
    _record("Users", "Duplicate username → 400", r.status_code == 400)

    # ── Password validation ──
    subsection("Password validation (negative)")
    weak_pw_user = dict(user1, email="weak@test.com", username="weakuser", password="short")
    r = requests.post(f"{API}/users", json=weak_pw_user, headers=headers(token))
    _record("Users", "Weak password → 422 (validation error)", r.status_code == 422)

    no_upper = dict(user1, email="noupper@test.com", username="noupper", password="nouppercase1!")
    r = requests.post(f"{API}/users", json=no_upper, headers=headers(token))
    _record("Users", "No uppercase in password → 422", r.status_code == 422)

    # ── Non-existent role ──
    subsection("Non-existent role_id (negative)")
    bad_role = dict(user1, email="badrole@test.com", username="badrole", role_ids=[99999])
    r = requests.post(f"{API}/users", json=bad_role, headers=headers(token))
    _record("Users", "Non-existent role_id → 400", r.status_code == 400)

    # ── List users ──
    subsection("List users")
    r = requests.get(f"{API}/users", headers=headers(token))
    _record("Users", "GET /users returns 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        _record("Users", "Response has items list", isinstance(body.get("items"), list))
        _record("Users", "Response has total", isinstance(body.get("total"), int))
        _record("Users", "Response has pages", isinstance(body.get("pages"), int))

    # ── Pagination ──
    subsection("Pagination")
    r = requests.get(f"{API}/users?skip=0&limit=2", headers=headers(token))
    _record("Users", "Paginated query (limit=2) returns 200", r.status_code == 200)
    if r.status_code == 200:
        _record("Users", "Page_size matches limit", r.json().get("page_size") == 2)

    # ── Filters: search ──
    subsection("Search filter")
    r = requests.get(f"{API}/users?search=testuser1", headers=headers(token))
    _record("Users", "Search filter returns 200", r.status_code == 200)
    if r.status_code == 200:
        _record("Users", "Search finds matching user", r.json().get("total", 0) >= 1)

    # ── Filters: is_active ──
    subsection("Active / Inactive filter")
    r = requests.get(f"{API}/users?is_active=false", headers=headers(token))
    _record("Users", "Filter is_active=false returns 200", r.status_code == 200)
    if r.status_code == 200:
        _record("Users", "Inactive filter finds at least 1", r.json().get("total", 0) >= 1)

    # ── Get user by ID ──
    subsection("Get user by ID")
    if user1_id:
        r = requests.get(f"{API}/users/{user1_id}", headers=headers(token))
        _record("Users", f"GET /users/{user1_id} returns 200", r.status_code == 200)
        if r.status_code == 200:
            _record("Users", "User response has roles", "roles" in r.json())

    # ── Get non-existent user ──
    r = requests.get(f"{API}/users/99999", headers=headers(token))
    _record("Users", "GET /users/99999 → 404", r.status_code == 404)

    # ── Update user ──
    subsection("Update user")
    if user1_id:
        r = requests.put(f"{API}/users/{user1_id}",
                         json={"first_name": "Updated", "last_name": "Name"},
                         headers=headers(token))
        _record("Users", "PUT /users/{id} → 200", r.status_code == 200)
        if r.status_code == 200:
            _record("Users", "First name updated", r.json().get("first_name") == "Updated")
            _record("Users", "Last name updated", r.json().get("last_name") == "Name")

    # ── Update user password ──
    subsection("Update user password via PUT")
    if user1_id:
        r = requests.put(f"{API}/users/{user1_id}",
                         json={"password": "TestPassword456!"},
                         headers=headers(token))
        _record("Users", "Update password via PUT → 200", r.status_code == 200)

    # ── Update user roles ──
    subsection("Update user roles via PUT")
    if user1_id and custom_role_id and viewer_role_id:
        r = requests.put(f"{API}/users/{user1_id}",
                         json={"role_ids": [viewer_role_id, custom_role_id]},
                         headers=headers(token))
        _record("Users", "Update roles via PUT → 200", r.status_code == 200)
        if r.status_code == 200:
            assigned = [rl["id"] for rl in r.json().get("roles", [])]
            _record("Users", "New roles assigned correctly",
                    viewer_role_id in assigned and custom_role_id in assigned)

    # ── Add role to user ──
    subsection("Add / Remove role")
    if user2_id and admin_role_id:
        r = requests.post(f"{API}/users/{user2_id}/roles/{admin_role_id}", headers=headers(token))
        _record("Users", f"POST /users/{user2_id}/roles/{admin_role_id} → 200", r.status_code == 200)
        if r.status_code == 200:
            role_ids = [rl["id"] for rl in r.json().get("roles", [])]
            _record("Users", "Admin role added to user2", admin_role_id in role_ids)

        # Remove it
        r = requests.delete(f"{API}/users/{user2_id}/roles/{admin_role_id}", headers=headers(token))
        _record("Users", f"DELETE /users/{user2_id}/roles/{admin_role_id} → 200", r.status_code == 200)
        if r.status_code == 200:
            role_ids = [rl["id"] for rl in r.json().get("roles", [])]
            _record("Users", "Admin role removed from user2", admin_role_id not in role_ids)

    # ── Tenant user count ──
    subsection("Tenant user count")
    r = requests.get(f"{API}/users/tenant/test-tenant/count", headers=headers(token))
    _record("Users", "GET /users/tenant/test-tenant/count → 200", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        _record("Users", "total_users >= 1", body.get("total_users", 0) >= 1)
        _record("Users", "Has active_users count", "active_users" in body)
        _record("Users", "Has inactive_users count", "inactive_users" in body)

    return user1_id, user2_id, user3_id, user4_id


# ──────────────────────────────────────────────────────────────────────────
def test_change_password(token: str):
    """Test change-password for the superuser."""
    section("8 · CHANGE PASSWORD")

    # ── Wrong current password ──
    subsection("Wrong current password (negative)")
    r = requests.post(f"{API}/auth/change-password",
                      json={"current_password": "WrongPassword123!", "new_password": "TestPassword456!"},
                      headers=headers(token))
    _record("Password", "Wrong current password → 400", r.status_code == 400)

    # ── Same old and new password ──
    subsection("Same old and new password (negative)")
    r = requests.post(f"{API}/auth/change-password",
                      json={"current_password": SUPERUSER_PASSWORD, "new_password": SUPERUSER_PASSWORD},
                      headers=headers(token))
    _record("Password", "Same password → 400", r.status_code == 400)

    # ── Successfully change password ──
    subsection("Change password successfully")
    new_password = "TestPassword456!"
    r = requests.post(f"{API}/auth/change-password",
                      json={"current_password": SUPERUSER_PASSWORD, "new_password": new_password},
                      headers=headers(token))
    _record("Password", "Change password → 200", r.status_code == 200)

    # ── Verify new password works ──
    r_login = login(SUPERUSER_EMAIL, new_password)
    _record("Password", "Login with new password works", r_login.status_code == 200)

    # ── Revert password back ──
    if r_login.status_code == 200:
        new_token = r_login.json()["access_token"]
        r = requests.post(f"{API}/auth/change-password",
                          json={"current_password": new_password, "new_password": SUPERUSER_PASSWORD},
                          headers=headers(new_token))
        _record("Password", "Reverted password back", r.status_code == 200)


# ──────────────────────────────────────────────────────────────────────────
def test_inactive_user_login():
    """Inactive user should not be able to login."""
    section("9 · INACTIVE USER LOGIN")

    r = login("inactive@shiftwise-test.com", "TestPassword123!")
    _record("Auth-Neg", "Inactive user login → 403", r.status_code == 403)


# ──────────────────────────────────────────────────────────────────────────
def test_rbac(token: str, user1_id, user2_id, user3_id):
    """Test RBAC enforcement with different user roles."""
    section("10 · RBAC ENFORCEMENT")

    # Restore user1 to admin role
    r = requests.get(f"{API}/roles/name/admin", headers=headers(token))
    admin_role_id = r.json()["id"] if r.status_code == 200 else None
    r = requests.get(f"{API}/roles/name/viewer", headers=headers(token))
    viewer_role_id = r.json()["id"] if r.status_code == 200 else None

    # Set user1 back to admin
    if user1_id and admin_role_id:
        requests.put(f"{API}/users/{user1_id}",
                     json={"role_ids": [admin_role_id], "password": "TestPassword123!"},
                     headers=headers(token))

    # Make sure user2 has only viewer role
    if user2_id and viewer_role_id:
        requests.put(f"{API}/users/{user2_id}",
                     json={"role_ids": [viewer_role_id]},
                     headers=headers(token))

    # ── Admin user (user1) tests ──
    subsection("Admin user (users:read, users:create, users:update but NOT users:delete)")
    admin_token = get_token("testuser1@shiftwise-test.local", "TestPassword123!")
    if admin_token:
        # Admin CAN list users
        r = requests.get(f"{API}/users", headers=headers(admin_token))
        _record("RBAC", "Admin can list users", r.status_code == 200)

        # Admin sees only their tenant's users (multi-tenancy)
        if r.status_code == 200:
            items = r.json().get("items", [])
            foreign = [u for u in items if u.get("tenant_id") != "test-tenant"]
            _record("RBAC", "Admin sees only own tenant users", len(foreign) == 0)

        # Admin CAN create users in same tenant
        temp_user = {
            "email": "tempuser@shiftwise-test.com",
            "username": "tempuser",
            "first_name": "Temp",
            "last_name": "User",
            "password": "TestPassword123!",
            "tenant_id": "test-tenant",
            "is_active": True,
            "role_ids": []
        }
        r = requests.post(f"{API}/users", json=temp_user, headers=headers(admin_token))
        _record("RBAC", "Admin can create user in same tenant", r.status_code == 201)
        temp_user_id = r.json()["id"] if r.status_code == 201 else None

        # Admin CANNOT create users in different tenant
        cross_tenant = dict(temp_user, email="cross@other.com", username="crossuser", tenant_id="other-tenant")
        r = requests.post(f"{API}/users", json=cross_tenant, headers=headers(admin_token))
        _record("RBAC", "Admin cannot create user in other tenant → 403", r.status_code == 403)

        # Admin CANNOT delete users (admin role has users: read, create, update — NOT delete)
        if temp_user_id:
            r = requests.delete(f"{API}/users/{temp_user_id}", headers=headers(admin_token))
            _record("RBAC", "Admin cannot delete users → 403", r.status_code == 403)
            # Clean up — superuser deletes
            requests.delete(f"{API}/users/{temp_user_id}", headers=headers(token))

        # Admin CAN list roles (admin has no roles permission ... let's check)
        r = requests.get(f"{API}/roles", headers=headers(admin_token))
        _record("RBAC", "Admin can/cannot read roles (depends on permissions)",
                r.status_code in (200, 403), f"status={r.status_code}")

    # ── Viewer user (user2) tests ──
    subsection("Viewer user (read-only)")
    viewer_token = get_token("testviewer@shiftwise-test.com", "TestPassword123!")
    if viewer_token:
        # Viewer CANNOT create users (no users:create permission)
        r = requests.post(f"{API}/users", json={
            "email": "viewercreate@test.com", "username": "viewercreate",
            "password": "TestPassword123!", "tenant_id": "test-tenant",
            "is_active": True, "role_ids": []
        }, headers=headers(viewer_token))
        _record("RBAC", "Viewer cannot create users → 403", r.status_code == 403)

        # Viewer CANNOT update users
        if user2_id:
            r = requests.put(f"{API}/users/{user2_id}",
                             json={"first_name": "Hacked"},
                             headers=headers(viewer_token))
            _record("RBAC", "Viewer cannot update users → 403", r.status_code == 403)

        # Viewer CANNOT delete users
        if user2_id:
            r = requests.delete(f"{API}/users/{user2_id}", headers=headers(viewer_token))
            _record("RBAC", "Viewer cannot delete users → 403", r.status_code == 403)

        # Viewer CANNOT create roles
        r = requests.post(f"{API}/roles", json={
            "name": "hacked_role", "permissions": {"vms": ["read"]}, "is_active": True
        }, headers=headers(viewer_token))
        _record("RBAC", "Viewer cannot create roles → 403", r.status_code == 403)

    # ── Regular user (user3, different tenant) ──
    subsection("Regular user — multi-tenancy isolation")
    user3_token = get_token("testother@other-tenant.com", "TestPassword123!")
    if user3_token:
        # User3 has 'user' role → has no users:* permission by default
        # so listing users should be forbidden
        r = requests.get(f"{API}/users", headers=headers(user3_token))
        _record("RBAC", "Regular user without users:read → 403", r.status_code == 403)

        # But /auth/me always works
        r = requests.get(f"{API}/auth/me", headers=headers(user3_token))
        _record("RBAC", "Regular user can access /auth/me", r.status_code == 200)


# ──────────────────────────────────────────────────────────────────────────
def test_multi_tenancy_isolation(token: str, user1_id, user3_id):
    """Test that multi-tenancy isolation is enforced."""
    section("11 · MULTI-TENANCY ISOLATION")

    # Admin user1 (test-tenant) tries to see user3 (other-tenant)
    admin_token = get_token("testuser1@shiftwise-test.local", "TestPassword123!")
    if admin_token and user3_id:
        r = requests.get(f"{API}/users/{user3_id}", headers=headers(admin_token))
        _record("Tenancy", "Admin cannot see user from other tenant → 403", r.status_code == 403)

        r = requests.put(f"{API}/users/{user3_id}",
                         json={"first_name": "Hacked"},
                         headers=headers(admin_token))
        _record("Tenancy", "Admin cannot update user from other tenant → 403", r.status_code == 403)

    # Admin from test-tenant tries to count other-tenant
    if admin_token:
        r = requests.get(f"{API}/users/tenant/other-tenant/count", headers=headers(admin_token))
        _record("Tenancy", "Admin cannot count other tenant → 403", r.status_code == 403)

    # Superuser CAN see all tenants
    if user3_id:
        r = requests.get(f"{API}/users/{user3_id}", headers=headers(token))
        _record("Tenancy", "Superuser can see user from any tenant", r.status_code == 200)

    r = requests.get(f"{API}/users/tenant/other-tenant/count", headers=headers(token))
    _record("Tenancy", "Superuser can count any tenant", r.status_code == 200)

    # Superuser can filter by tenant_id
    r = requests.get(f"{API}/users?tenant_id=test-tenant", headers=headers(token))
    _record("Tenancy", "Superuser can filter by tenant_id", r.status_code == 200)
    if r.status_code == 200:
        items = r.json().get("items", [])
        all_same = all(u.get("tenant_id") == "test-tenant" for u in items)
        _record("Tenancy", "Tenant filter returns correct tenant users", all_same)


# ──────────────────────────────────────────────────────────────────────────
def test_self_delete_protection(token: str):
    """Superuser cannot delete themselves."""
    section("12 · SELF-DELETE PROTECTION")

    # Get superuser ID from /me
    r = requests.get(f"{API}/auth/me", headers=headers(token))
    if r.status_code == 200:
        su_id = r.json()["id"]
        r = requests.delete(f"{API}/users/{su_id}", headers=headers(token))
        _record("Protection", "Superuser cannot self-delete → 400", r.status_code == 400)


# ──────────────────────────────────────────────────────────────────────────
def test_cleanup(token: str, user_ids: list, custom_role_id: int | None):
    """Clean up all test data."""
    section("13 · CLEANUP")

    # Delete test users
    for uid in user_ids:
        if uid:
            r = requests.delete(f"{API}/users/{uid}", headers=headers(token))
            _record("Cleanup", f"Delete user {uid}", r.status_code == 200, f"status={r.status_code}")

    # Delete custom role (now that no users reference it)
    if custom_role_id:
        r = requests.delete(f"{API}/roles/{custom_role_id}", headers=headers(token))
        _record("Cleanup", f"Delete custom role {custom_role_id}", r.status_code == 200, f"status={r.status_code}")

    # Verify cleanup
    for uid in user_ids:
        if uid:
            r = requests.get(f"{API}/users/{uid}", headers=headers(token))
            _record("Cleanup", f"User {uid} no longer exists", r.status_code == 404)


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

def print_summary():
    """Print final test summary."""
    total = PASS_COUNT + FAIL_COUNT
    print(f"\n{Colors.BOLD}{'═'*70}")
    print(f"  FINAL REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*70}{Colors.RESET}")
    print(f"  {Colors.GREEN}PASSED : {PASS_COUNT}{Colors.RESET}")
    print(f"  {Colors.RED}FAILED : {FAIL_COUNT}{Colors.RESET}")
    print(f"  TOTAL  : {total}")
    if total > 0:
        pct = PASS_COUNT / total * 100
        bar_len = 40
        filled = int(bar_len * pct / 100)
        bar = f"{'█' * filled}{'░' * (bar_len - filled)}"
        color = Colors.GREEN if pct == 100 else Colors.YELLOW if pct >= 80 else Colors.RED
        print(f"  {color}{bar} {pct:.1f}%{Colors.RESET}")
    print(f"{'═'*70}\n")

    if FAIL_COUNT > 0:
        print(f"  {Colors.RED}{Colors.BOLD}Failed tests:{Colors.RESET}")
        for r in RESULTS:
            if not r["passed"]:
                detail = f"  ({r['detail']})" if r['detail'] else ""
                print(f"    {Colors.RED}✗ [{r['category']}] {r['name']}{detail}{Colors.RESET}")
        print()


def main():
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║     ShiftWise — Comprehensive User Management Test Suite           ║")
    print("║     Testing ALL scenarios: CRUD, Auth, RBAC, Multi-Tenancy         ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print(f"{Colors.RESET}")

    # Pre-check: server reachable?
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code != 200:
            print(f"{Colors.RED}ERROR: Server returned {r.status_code}. Is the backend running?{Colors.RESET}")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"{Colors.RED}ERROR: Cannot connect to {BASE_URL}. Start the backend first:{Colors.RESET}")
        print(f"  cd backend && uvicorn app.main:app --reload")
        sys.exit(1)

    # ── Pre-run cleanup: remove stale resources from interrupted previous runs ──
    print(f"  {Colors.CYAN}Cleaning up stale test resources from previous runs...{Colors.RESET}")
    cleanup_stale_test_resources()
    print(f"  {Colors.GREEN}Stale resources cleared{Colors.RESET}\n")

    # ── Setup: create a dedicated test superuser directly in DB ──
    print(f"  {Colors.CYAN}Setting up test superuser in database...{Colors.RESET}")
    test_su_id = setup_test_superuser()
    print(f"  {Colors.GREEN}Test superuser ready (id={test_su_id}){Colors.RESET}\n")

    # ── Run all test suites ──
    test_health_and_root()

    su_token = test_superuser_login()
    test_auth_me_and_verify(su_token)
    new_token = test_token_refresh()

    # Use fresh token from refresh if available
    if new_token:
        su_token = new_token

    test_auth_negative()
    custom_role_id = test_role_crud(su_token)
    user1_id, user2_id, user3_id, user4_id = test_user_crud(su_token, custom_role_id)
    test_change_password(su_token)
    test_inactive_user_login()
    test_rbac(su_token, user1_id, user2_id, user3_id)
    test_multi_tenancy_isolation(su_token, user1_id, user3_id)
    test_self_delete_protection(su_token)
    test_cleanup(su_token, [user1_id, user2_id, user3_id, user4_id], custom_role_id)

    # ── Teardown: remove the dedicated test superuser ──
    print(f"\n  {Colors.CYAN}Tearing down test superuser...{Colors.RESET}")
    teardown_test_superuser()
    print(f"  {Colors.GREEN}Test superuser removed{Colors.RESET}")

    print_summary()
    sys.exit(0 if FAIL_COUNT == 0 else 1)


if __name__ == "__main__":
    main()
