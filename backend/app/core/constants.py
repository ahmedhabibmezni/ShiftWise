"""
ShiftWise Core Constants

Constantes partagées pour éviter la duplication entre schemas et routes.
"""

VALID_ACTIONS: frozenset[str] = frozenset({"create", "read", "update", "delete", "*"})

VALID_RESOURCES: frozenset[str] = frozenset({
    "users", "roles", "hypervisors", "vms", "migrations", "reports", "settings"
})
