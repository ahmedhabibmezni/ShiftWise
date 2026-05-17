"""
ShiftWise Core Constants

Constantes partagées pour éviter la duplication entre schemas et routes.
"""

VALID_ACTIONS: frozenset[str] = frozenset({"create", "read", "update", "delete", "*"})

# Audit B8 / D12 — `conversions` and `kubevirt` are real RBAC-protected
# resources (the conversions API + the KubeVirt cluster endpoints).
# They were missing here, so any role granting permissions on them was
# rejected by the RoleBase / RoleUpdate permission validator.
VALID_RESOURCES: frozenset[str] = frozenset({
    "users", "roles", "hypervisors", "vms", "migrations",
    "conversions", "kubevirt", "reports", "settings",
})
