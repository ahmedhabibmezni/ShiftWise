"""
tests/test_kvm_sync.py
======================
Discovery + DB Sync Test — KVM (libvirt / qemu+ssh)
=====================================================

Tests the 3 sync scenarios against a live running server:

  Scenario 1 — INSERT  : VM exists in KVM but NOT in DB
  Scenario 2 — UPDATE  : VM exists in both → update only if fields changed
  Scenario 3 — ARCHIVE : VM exists in DB but no longer in KVM → ARCHIVED

Usage
-----
  1. Start the server:
       uvicorn app.main:app --reload

  2. Run this script:
       python tests/test_kvm_sync.py

Configuration
-------------
  Edit the constants in the CONFIG section below to match your environment.
  The script uses the /api/v1/auth/login endpoint to get a JWT token,
  then calls /api/v1/hypervisors/{id}/sync and the VMs endpoint to verify.

Notes
-----
  - KVM discovery requires a reachable Ubuntu KVM host with libvirt.
  - Passwordless SSH must be set up (see Task 1.1–1.4 in the plan).
  - The test is safe to re-run: leftover ghost VMs from previous runs are
    cleaned up automatically at the start of Scenario 3.
  - Expected VMs on KVM host: "test-kvm-alpine" (running).
    "test-kvm-alpine2" must exist for a clean INSERT run (re-create via
    virt-install if it was removed during Scenario 3 of the plan).
"""

import sys
import json
import time
import requests

# ============================================================================
# CONFIG — edit these to match your environment
# ============================================================================

BASE_URL      = "http://localhost:8000"
API_PREFIX    = "/api/v1"

# Credentials of an existing user that has hypervisors:update permission
ADMIN_EMAIL   = "ahmed.mezni@nextstep.tn"
ADMIN_PASS    = "SecurePass123!"

# The KVM hypervisor ID registered in Task 4.2 of the plan (id=36)
HYPERVISOR_ID = 36

# Expected VMs discovered from KVM (used in assertions)
# VM 1 — running
EXPECTED_VM1_NAME        = "test-kvm-alpine"
EXPECTED_VM1_POWER_STATE = "running"
EXPECTED_VM1_CPU_CORES   = 1
EXPECTED_VM1_MEMORY_MB   = 512

# VM 2 — shut off (may not exist if Task 5.3 was run without Task 5.5 cleanup)
EXPECTED_VM2_NAME        = "test-kvm-alpine2"
EXPECTED_VM2_POWER_STATE = "stopped"

# KVM OS type is inferred from the VM name when no guest agent is present.
# Keywords that trigger OSType.LINUX (mirrors _KVM_LINUX_KEYWORDS in discovery.py)
_KVM_LINUX_KEYWORDS = [
    "linux", "ubuntu", "centos", "alpine", "debian",
    "fedora", "rhel", "suse", "arch", "gentoo",
]

def _infer_os_type(vm_name: str) -> str:
    """
    Mirror the name-based OS heuristic used by _parse_kvm_domain_xml.
    Returns 'linux', 'windows', or 'unknown'.
    """
    name_lower = vm_name.lower()
    if any(k in name_lower for k in _KVM_LINUX_KEYWORDS):
        return "linux"
    if any(k in name_lower for k in ("windows", "win")):
        return "windows"
    return "unknown"

# ============================================================================
# Console helpers
# ============================================================================

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg):  print(f"  {RED}❌ {msg}{RESET}"); sys.exit(1)
def info(msg):  print(f"  {CYAN}ℹ  {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠  {msg}{RESET}")

def section(title):
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

def assert_eq(label, actual, expected):
    if actual == expected:
        ok(f"{label}: {actual!r}")
    else:
        fail(f"{label} — expected {expected!r}, got {actual!r}")

def assert_in(label, actual, choices):
    if actual in choices:
        ok(f"{label}: {actual!r}")
    else:
        fail(f"{label} — expected one of {choices!r}, got {actual!r}")

# ============================================================================
# Authenticated session
# ============================================================================

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})

def login():
    section("AUTH — Getting JWT token")
    r = session.post(
        f"{BASE_URL}{API_PREFIX}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
    )
    if r.status_code != 200:
        fail(f"Login failed ({r.status_code}): {r.text}")
    token = r.json().get("access_token")
    if not token:
        fail(f"No access_token in response: {r.json()}")
    session.headers.update({"Authorization": f"Bearer {token}"})
    ok(f"Logged in as '{ADMIN_EMAIL}'")
    return token

# ============================================================================
# API helpers
# ============================================================================

def get_hypervisor():
    r = session.get(f"{BASE_URL}{API_PREFIX}/hypervisors/{HYPERVISOR_ID}")
    if r.status_code != 200:
        fail(f"GET hypervisor failed ({r.status_code}): {r.text}")
    return r.json()

def get_hypervisor_vms():
    """Returns the VMs response from GET /hypervisors/{id}/vms."""
    r = session.get(f"{BASE_URL}{API_PREFIX}/hypervisors/{HYPERVISOR_ID}/vms")
    if r.status_code != 200:
        fail(f"GET hypervisor VMs failed ({r.status_code}): {r.text}")
    return r.json()

def get_all_vms():
    """Returns all VMs from GET /vms filtered to this hypervisor."""
    r = session.get(
        f"{BASE_URL}{API_PREFIX}/vms",
        params={"hypervisor_id": HYPERVISOR_ID, "limit": 100},
    )
    if r.status_code != 200:
        fail(f"GET vms failed ({r.status_code}): {r.text}")
    data = r.json()
    return data.get("items", data) if isinstance(data, dict) else data

def run_sync():
    """POST /hypervisors/{id}/sync and return the full response dict."""
    info("Calling POST /hypervisors/{id}/sync …")
    r = session.post(f"{BASE_URL}{API_PREFIX}/hypervisors/{HYPERVISOR_ID}/sync")
    if r.status_code != 200:
        fail(f"Sync failed ({r.status_code}): {r.text}")
    return r.json()

def inject_fake_vm_in_db(source_uuid: str, name: str):
    """
    Insert a fake VM via POST /vms so we can test the ARCHIVE scenario.
    This VM does NOT exist on the real KVM host — the next sync must
    mark it ARCHIVED.
    """
    payload = {
        "name": name,
        "source_hypervisor_id": HYPERVISOR_ID,
        "source_uuid": source_uuid,
        "source_name": name,
        "cpu_cores": 1,
        "memory_mb": 512,
        "disk_gb": 10,
        "os_type": "unknown",
        "os_version": "N/A",
        "os_name": "N/A",
        "status": "discovered",
        "compatibility_status": "unknown",
    }
    r = session.post(f"{BASE_URL}{API_PREFIX}/vms", json=payload)
    if r.status_code not in (200, 201):
        fail(f"Inject fake VM failed ({r.status_code}): {r.text}")
    vm = r.json()
    ok(f"Fake VM injected: id={vm['id']}  uuid={source_uuid}")
    return vm

def find_vm_by_uuid(vms, uuid):
    for vm in vms:
        if vm.get("source_uuid") == uuid:
            return vm
    return None

def find_vm_by_name(vms, name):
    for vm in vms:
        if vm.get("name") == name:
            return vm
    return None

# ============================================================================
# SCENARIO 1 — INSERT (first sync, VMs not yet in DB)
# ============================================================================

def scenario_1_insert():
    section("SCENARIO 1 — INSERT: VMs in KVM, not yet in DB")

    info("State BEFORE sync:")
    vms_before   = get_hypervisor_vms()
    count_before = vms_before.get("total_vms", len(vms_before.get("vms", [])))
    hyp_before   = get_hypervisor()
    info(f"  VMs in DB for this hypervisor : {count_before}")
    info(f"  hypervisor.total_vms_discovered = {hyp_before.get('total_vms_discovered')}")
    info(f"  hypervisor.status               = {hyp_before.get('status')}")
    info(f"  hypervisor.last_sync_at         = {hyp_before.get('last_sync_at')}")

    print()
    info("Running sync …")
    sync_result = run_sync()
    info(f"Sync response: {json.dumps(sync_result, indent=2)}")

    stats = sync_result.get("statistics", sync_result)

    print()
    info("State AFTER sync:")
    vms_after   = get_hypervisor_vms()
    count_after = vms_after.get("total_vms", len(vms_after.get("vms", [])))
    hyp_after   = get_hypervisor()
    info(f"  VMs in DB for this hypervisor : {count_after}")
    info(f"  hypervisor.total_vms_discovered = {hyp_after.get('total_vms_discovered')}")
    info(f"  hypervisor.status               = {hyp_after.get('status')}")
    info(f"  hypervisor.last_sync_at         = {hyp_after.get('last_sync_at')}")

    print()
    # ── Sync-stats assertions ──────────────────────────────────────────────
    new_vms = stats.get("new_vms", 0)
    if new_vms > 0:
        ok(f"new_vms = {new_vms} — at least one VM was INSERTed")
    else:
        warn(
            "new_vms = 0 — OK only if both KVM VMs were already in DB before this run.\n"
            "             Delete their rows and re-run for a clean INSERT test."
        )

    if count_after > count_before:
        ok(f"VM count grew: {count_before} → {count_after}")
    elif count_after == count_before and new_vms == 0:
        warn("VM count unchanged — DB was already populated (not an error).")
    else:
        fail(f"Unexpected VM count: before={count_before} after={count_after}")

    # ── Hypervisor metadata assertions ────────────────────────────────────
    assert_in(
        "hypervisor.status after sync",
        hyp_after.get("status"),
        ["active", "ACTIVE"],
    )
    if hyp_after.get("last_sync_at"):
        ok(f"hypervisor.last_sync_at is set: {hyp_after['last_sync_at']}")
    else:
        fail("hypervisor.last_sync_at was NOT updated after sync")

    live_count = count_after
    total_disc = hyp_after.get("total_vms_discovered", -1)
    if total_disc == live_count:
        ok(f"hypervisor.total_vms_discovered = {total_disc} (matches live VM count)")
    else:
        warn(
            f"hypervisor.total_vms_discovered = {total_disc} "
            f"but live count = {live_count}"
        )

    # ── Verify VM1: test-kvm-alpine ────────────────────────────────────────
    all_vms = get_all_vms()
    vm1 = find_vm_by_name(all_vms, EXPECTED_VM1_NAME)

    if vm1:
        ok(f"VM '{EXPECTED_VM1_NAME}' found in DB (id={vm1.get('id')})")

        assert_eq("name",      vm1.get("name"),      EXPECTED_VM1_NAME)
        assert_eq("cpu_cores", vm1.get("cpu_cores"), EXPECTED_VM1_CPU_CORES)
        assert_eq("memory_mb", vm1.get("memory_mb"), EXPECTED_VM1_MEMORY_MB)

        # source_uuid must be 32-char lowercase no-dash
        uuid = vm1.get("source_uuid", "")
        if len(uuid) == 32 and uuid == uuid.lower() and "-" not in uuid:
            ok(f"source_uuid format valid: {uuid!r}")
        else:
            fail(
                f"source_uuid format invalid: {uuid!r}\n"
                "  Expected 32-char lowercase no-dash (e.g. 'aabbccdd...')"
            )

        # disk_gb — allow 0 if disk not in a libvirt storage pool
        disk = vm1.get("disk_gb", 0)
        if disk > 0:
            ok(f"disk_gb = {disk}")
        else:
            warn(
                "disk_gb = 0 — disk may not be registered in a libvirt storage pool.\n"
                "             Acceptable per plan risk register."
            )

        # OS type — validated against name-based heuristic (mirrors discovery.py)
        actual_os   = str(vm1.get("os_type", "")).lower()
        expected_os = _infer_os_type(EXPECTED_VM1_NAME)
        if actual_os == expected_os:
            ok(f"os_type = {actual_os!r} — matches name-based inference for '{EXPECTED_VM1_NAME}'")
        else:
            fail(
                f"os_type = {actual_os!r} — expected {expected_os!r} "
                f"(inferred from VM name '{EXPECTED_VM1_NAME}').\n"
                "  Check _KVM_LINUX_KEYWORDS in discovery.py."
            )

        assert_in("os_version", vm1.get("os_version"), ["N/A", None])
        assert_in("os_name",    vm1.get("os_name"),    ["N/A", None])
        assert_in("status",     vm1.get("status", "").lower(), ["discovered"])

        # power_state stored in custom_metadata
        meta = vm1.get("custom_metadata") or {}
        actual_power = meta.get("power_state", "").lower()
        if actual_power == EXPECTED_VM1_POWER_STATE:
            ok(f"custom_metadata.power_state = {actual_power!r}")
        else:
            warn(
                f"custom_metadata.power_state = {actual_power!r} "
                f"(expected {EXPECTED_VM1_POWER_STATE!r} — VM state may have changed)"
            )
    else:
        warn(
            f"VM '{EXPECTED_VM1_NAME}' not found in DB.\n"
            "  Ensure the VM is defined on the KVM host and the SSH connection works.\n"
            "  Run: ssh ubuntu@10.9.21.131 'virsh list --all'"
        )

    # ── Verify VM2: test-kvm-alpine2 (optional — may have been removed) ───
    vm2 = find_vm_by_name(all_vms, EXPECTED_VM2_NAME)
    if vm2:
        ok(f"VM '{EXPECTED_VM2_NAME}' found in DB (id={vm2.get('id')})")

        uuid2 = vm2.get("source_uuid", "")
        if len(uuid2) == 32 and uuid2 == uuid2.lower() and "-" not in uuid2:
            ok(f"source_uuid format valid: {uuid2!r}")
        else:
            fail(f"source_uuid format invalid for VM2: {uuid2!r}")

        meta2 = vm2.get("custom_metadata") or {}
        actual_power2 = meta2.get("power_state", "").lower()
        if actual_power2 == EXPECTED_VM2_POWER_STATE:
            ok(f"custom_metadata.power_state = {actual_power2!r}")
        else:
            warn(
                f"custom_metadata.power_state = {actual_power2!r} "
                f"(expected {EXPECTED_VM2_POWER_STATE!r})"
            )
    else:
        warn(
            f"VM '{EXPECTED_VM2_NAME}' not found — it may have been permanently removed\n"
            f"  during Scenario 3 of the plan (--remove-all-storage).\n"
            f"  Run Task 5.5 (virt-install) to recreate it before re-running this test."
        )

    # ── Print discovered VMs ───────────────────────────────────────────────
    print()
    info("Discovered VMs:")
    for vm in all_vms:
        info(
            f"  [{vm.get('id'):>4}] {vm.get('name', '?')!r:25s}  "
            f"uuid={str(vm.get('source_uuid', 'N/A'))[:32]:32s}  "
            f"os={str(vm.get('os_type', '?')):8s}  "
            f"status={vm.get('status', '?'):12s}  "
            f"power={((vm.get('custom_metadata') or {}).get('power_state', 'N/A'))}"
        )

    return all_vms

# ============================================================================
# SCENARIO 2 — UPDATE (second sync, same VMs, check change detection)
# ============================================================================

def scenario_2_update(vms_after_s1):
    section("SCENARIO 2 — UPDATE: VMs in KVM AND in DB")

    if not vms_after_s1:
        warn("No VMs found after Scenario 1 — skipping UPDATE test.")
        return

    info("Running a second sync immediately …")
    sync_result = run_sync()
    info(f"Sync response: {json.dumps(sync_result, indent=2)}")

    stats = sync_result.get("statistics", sync_result)

    print()
    new_vms     = stats.get("new_vms", 0)
    updated_vms = stats.get("updated_vms", 0)
    unchanged   = stats.get("unchanged_vms", 0)
    archived    = stats.get("archived_vms", 0)

    ok(
        f"new_vms={new_vms}  updated_vms={updated_vms}  "
        f"unchanged_vms={unchanged}  archived_vms={archived}"
    )

    # No duplicate INSERTs — source_uuid dedup must hold
    if new_vms == 0:
        ok("No duplicate INSERTs on second sync — source_uuid dedup working correctly")
    else:
        fail(f"Second sync created {new_vms} new VMs — duplicate INSERT bug!")

    # Total processed = updated + unchanged (should equal live VMs from S1)
    live_s1 = [v for v in vms_after_s1 if v.get("status", "").lower() != "archived"]
    total_processed = updated_vms + unchanged
    if total_processed == len(live_s1):
        ok(f"All {total_processed} existing VMs processed (updated or unchanged)")
    else:
        warn(
            f"Processed {total_processed} VM(s) but expected {len(live_s1)} — "
            "some may have been archived (check KVM host)"
        )

    # Verify last_seen_at was refreshed for all live VMs
    vms_now = get_all_vms()
    for original_vm in live_s1:
        current = find_vm_by_uuid(vms_now, original_vm.get("source_uuid"))
        if not current:
            warn(f"VM {original_vm.get('name')!r} no longer found — may have been archived")
            continue
        old_ts = original_vm.get("last_seen_at")
        new_ts = current.get("last_seen_at")
        if old_ts != new_ts:
            ok(f"last_seen_at updated for {current.get('name')!r}: {old_ts} → {new_ts}")
        else:
            info(
                f"last_seen_at unchanged for {current.get('name')!r} "
                "(same-second sync — not an error)"
            )

    # Verify test-kvm-alpine is still DISCOVERED and not accidentally archived
    vm1 = find_vm_by_name(vms_now, EXPECTED_VM1_NAME)
    if vm1:
        status = vm1.get("status", "").lower()
        if status == "discovered":
            ok(f"'{EXPECTED_VM1_NAME}' still 'discovered' after second sync")
        else:
            fail(f"'{EXPECTED_VM1_NAME}' status changed unexpectedly to {status!r}")
    else:
        warn(f"'{EXPECTED_VM1_NAME}' not found in second sync results")

    # Verify os_type was not silently overwritten between syncs
    if vm1:
        actual_os   = str(vm1.get("os_type", "")).lower()
        expected_os = _infer_os_type(EXPECTED_VM1_NAME)
        if actual_os == expected_os:
            ok(f"os_type still = {actual_os!r} after second sync (stable, not overwritten)")
        else:
            fail(f"os_type changed to {actual_os!r} on second sync — expected {expected_os!r}, regression!")

    # Verify source_uuid format did not change (normalization must be stable)
    if vm1:
        uuid = vm1.get("source_uuid", "")
        if len(uuid) == 32 and uuid == uuid.lower() and "-" not in uuid:
            ok(f"source_uuid format still valid after second sync: {uuid!r}")
        else:
            fail(
                f"source_uuid format changed on second sync: {uuid!r}\n"
                "  UUID normalization must be stable across syncs."
            )

# ============================================================================
# SCENARIO 3 — ARCHIVE (VM in DB but not reported by KVM)
# ============================================================================

def scenario_3_archive():
    section("SCENARIO 3 — ARCHIVE: VM in DB, gone from KVM")

    FAKE_UUID = "deadbeef000000000000000000000036"
    FAKE_NAME = "ghost-kvm-vm-test"

    info(f"Injecting a fake VM into the DB: name={FAKE_NAME!r}  uuid={FAKE_UUID!r}")
    info("This VM does NOT exist on the real KVM host.")

    # ── Clean up leftovers from previous runs ─────────────────────────────
    vms_resp = session.get(
        f"{BASE_URL}{API_PREFIX}/vms",
        params={"search": FAKE_NAME, "limit": 10},
    )
    if vms_resp.ok:
        items = vms_resp.json()
        if isinstance(items, dict):
            items = items.get("items", [])
        for vm in items:
            if vm.get("name") == FAKE_NAME:
                del_r = session.delete(f"{BASE_URL}{API_PREFIX}/vms/{vm['id']}")
                if del_r.status_code in (200, 204):
                    info(f"Cleaned up leftover ghost VM (id={vm['id']}) from previous run")
                else:
                    warn(f"Could not delete ghost VM id={vm['id']}: {del_r.status_code}")

    fake_vm    = inject_fake_vm_in_db(FAKE_UUID, FAKE_NAME)
    fake_vm_id = fake_vm["id"]
    info(f"Fake VM created: id={fake_vm_id}, status={fake_vm.get('status')!r}")

    print()
    info("Running sync — fake VM should be marked ARCHIVED …")
    sync_result = run_sync()
    info(f"Sync response: {json.dumps(sync_result, indent=2)}")

    stats          = sync_result.get("statistics", sync_result)
    archived_count = stats.get("archived_vms", 0)

    print()
    if archived_count > 0:
        ok(f"archived_vms = {archived_count} (≥1 VM was archived)")
    else:
        fail("archived_vms = 0 — the fake VM was NOT archived!")

    # ── Fetch fake VM directly — must still exist, not be deleted ─────────
    r = session.get(f"{BASE_URL}{API_PREFIX}/vms/{fake_vm_id}")
    if r.status_code == 404:
        fail("Fake VM was DELETED instead of being ARCHIVED — wrong behavior!")

    vm_after  = r.json()
    vm_status = vm_after.get("status", "").lower()

    if vm_status == "archived":
        ok(f"VM id={fake_vm_id} status is now 'archived' — correct behavior")
    else:
        fail(
            f"VM id={fake_vm_id} has status={vm_status!r} instead of 'archived'\n"
            f"Full VM: {json.dumps(vm_after, indent=2)}"
        )

    ok(f"Fake VM still exists in DB (id={fake_vm_id}) — not deleted, only archived")

    # ── Verify test-kvm-alpine was NOT affected by the archive pass ────────
    all_vms = get_all_vms()
    vm1 = find_vm_by_name(all_vms, EXPECTED_VM1_NAME)
    if vm1:
        mig_status = vm1.get("status", "").lower()
        if mig_status == "discovered":
            ok(
                f"'{EXPECTED_VM1_NAME}' still 'discovered' — "
                "only the ghost VM was archived"
            )
        else:
            fail(
                f"'{EXPECTED_VM1_NAME}' was wrongly set to status={mig_status!r} "
                "during the ghost VM archive pass!"
            )
    else:
        warn(
            f"'{EXPECTED_VM1_NAME}' not found after archive sync — "
            "was it removed from the KVM host?"
        )

    # ── Archived VM must not appear in the live list ──────────────────────
    vms_resp = get_hypervisor_vms()
    live_vms = vms_resp.get("vms", get_all_vms())
    still_live = find_vm_by_uuid(live_vms, FAKE_UUID)
    if still_live:
        warn(
            f"Archived VM still appearing in /hypervisors/{HYPERVISOR_ID}/vms — "
            "check if that endpoint filters ARCHIVED VMs"
        )
    else:
        ok("Archived VM no longer appears in the live VM list for this hypervisor")

    hyp = get_hypervisor()
    info(
        f"hypervisor.total_vms_discovered after archive = "
        f"{hyp.get('total_vms_discovered')} (should NOT count the ghost VM)"
    )

    return fake_vm_id

# ============================================================================
# BONUS — Verify hypervisors ↔ virtual_machines JOIN integrity
# ============================================================================

def verify_join():
    section("BONUS — Verify hypervisors ↔ virtual_machines JOIN")

    hyp      = get_hypervisor()
    vms_data = get_hypervisor_vms()
    all_vms  = get_all_vms()

    info(f"Hypervisor  id               : {hyp.get('id')}")
    info(f"Hypervisor  name             : {hyp.get('name')!r}")
    info(f"Hypervisor  type             : {hyp.get('type')!r}")
    info(f"Hypervisor  host             : {hyp.get('host')!r}")
    info(f"Hypervisor  total_vms_disc.  : {hyp.get('total_vms_discovered')}")
    info(f"Hypervisor  last_sync_at     : {hyp.get('last_sync_at')}")
    info(f"  /hypervisors/{HYPERVISOR_ID}/vms  → total_vms = {vms_data.get('total_vms')}")
    info(f"  /vms?hypervisor_id={HYPERVISOR_ID} → count     = {len(all_vms)}")

    print()

    # All VMs from /hypervisors/{id}/vms must have correct source_hypervisor_id
    bad_fk = [
        vm for vm in vms_data.get("vms", [])
        if vm.get("source_hypervisor_id") != HYPERVISOR_ID
    ]
    if bad_fk:
        fail(
            f"{len(bad_fk)} VM(s) have wrong source_hypervisor_id: "
            + ", ".join(str(v.get("id")) for v in bad_fk)
        )
    else:
        ok(f"All VMs from /hypervisors/{HYPERVISOR_ID}/vms have correct source_hypervisor_id")

    # total_vms_discovered must match non-archived VM count
    non_archived = [v for v in all_vms if v.get("status", "").lower() != "archived"]
    total_disc   = hyp.get("total_vms_discovered", -1)
    if total_disc == len(non_archived):
        ok(
            f"hypervisor.total_vms_discovered ({total_disc}) matches "
            f"non-archived VM count ({len(non_archived)})"
        )
    else:
        warn(
            f"hypervisor.total_vms_discovered = {total_disc} "
            f"but non-archived VM count = {len(non_archived)}"
        )

    # Every VM must have a source_uuid
    missing_uuid = [v for v in all_vms if not v.get("source_uuid")]
    if missing_uuid:
        warn(f"{len(missing_uuid)} VM(s) missing source_uuid — check legacy rows")
    else:
        ok("All VMs have a source_uuid")

    # All source_uuids must be 32-char lowercase no-dash
    bad_uuid_format = [
        v for v in all_vms
        if v.get("source_uuid") and (
            len(v["source_uuid"]) != 32
            or v["source_uuid"] != v["source_uuid"].lower()
            or "-" in v["source_uuid"]
        )
    ]
    if bad_uuid_format:
        fail(
            f"{len(bad_uuid_format)} VM(s) have malformed source_uuid — "
            "must be 32-char lowercase no-dash:\n"
            + "\n".join(f"  id={v['id']} uuid={v['source_uuid']!r}" for v in bad_uuid_format)
        )
    else:
        ok("All source_uuids are 32-char lowercase no-dash (KVM UUID normalization correct)")

    # All KVM VMs must have an os_type consistent with the name-based heuristic
    os_mismatches = [
        v for v in all_vms
        if v.get("source_hypervisor_id") == HYPERVISOR_ID
        and str(v.get("os_type", "")).lower() != _infer_os_type(v.get("name", ""))
        and v.get("status", "").lower() != "archived"   # ghost VMs injected as 'unknown' are exempt
    ]
    if os_mismatches:
        fail(
            f"{len(os_mismatches)} KVM VM(s) have os_type inconsistent with their name heuristic:\n"
            + "\n".join(
                f"  id={v['id']} name={v['name']!r} "
                f"got={str(v.get('os_type','')).lower()!r} "
                f"expected={_infer_os_type(v.get('name',''))!r}"
                for v in os_mismatches
            )
        )
    else:
        ok("All KVM VMs have os_type consistent with name-based inference (discovery.py heuristic)")

    # Verify libvirt connection_config is present and correct
    conn_cfg = hyp.get("connection_config", {})
    if conn_cfg.get("auth_mode") == "ssh_key":
        ok(f"connection_config.auth_mode = 'ssh_key'")
    else:
        warn(
            f"connection_config.auth_mode = {conn_cfg.get('auth_mode')!r} "
            "(expected 'ssh_key')"
        )

    # Snapshot of all VMs
    print()
    info("VM snapshot (id | name | uuid | cpu | mem | disk | os | status | power):")
    for vm in all_vms:
        meta  = vm.get("custom_metadata") or {}
        power = meta.get("power_state", "N/A")
        info(
            f"  [{vm.get('id'):>4}] {vm.get('name', '?')!r:25s}  "
            f"uuid={str(vm.get('source_uuid', 'N/A'))[:32]:32s}  "
            f"cpu={vm.get('cpu_cores', '?'):>2}  "
            f"mem={vm.get('memory_mb', '?'):>5}MB  "
            f"disk={vm.get('disk_gb', '?'):>3}GB  "
            f"os={str(vm.get('os_type', '?')):8s}  "
            f"{vm.get('status', '?'):12s}  "
            f"power={power}"
        )

    # Detailed snapshot of test-kvm-alpine
    vm1 = find_vm_by_name(all_vms, EXPECTED_VM1_NAME)
    if vm1:
        print()
        info(f"'{EXPECTED_VM1_NAME}' final state:")
        info(f"  id               : {vm1.get('id')}")
        info(f"  name             : {vm1.get('name')!r}")
        info(f"  source_uuid      : {vm1.get('source_uuid')!r}")
        info(f"  cpu_cores        : {vm1.get('cpu_cores')}")
        info(f"  memory_mb        : {vm1.get('memory_mb')}")
        info(f"  disk_gb          : {vm1.get('disk_gb')}")
        info(f"  os_type          : {vm1.get('os_type')!r}")
        info(f"  os_version       : {vm1.get('os_version')!r}")
        info(f"  os_name          : {vm1.get('os_name')!r}")
        info(f"  status           : {vm1.get('status')!r}")
        info(f"  custom_metadata  : {vm1.get('custom_metadata')}")
        info(f"  ip_address       : {vm1.get('ip_address')}")
        info(f"  discovered_at    : {vm1.get('discovered_at')}")
        info(f"  last_seen_at     : {vm1.get('last_seen_at')}")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  ShiftWise — KVM Discovery Sync Test Suite{RESET}")
    print(f"{BOLD}  Server        : {BASE_URL}{RESET}")
    print(f"{BOLD}  Hypervisor ID : {HYPERVISOR_ID}{RESET}")
    print(f"{BOLD}  KVM host      : qemu+ssh://ubuntu@10.9.21.131/system{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    # ── Server health check ───────────────────────────────────────────────
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code == 200:
            ok(f"Server is up — {r.json().get('status', 'ok')}")
        else:
            fail(f"Server health check failed: {r.status_code}")
    except requests.exceptions.ConnectionError:
        fail(
            f"Cannot reach {BASE_URL} — is the server running?\n"
            "  Start it with: uvicorn app.main:app --reload"
        )

    # ── Authenticate ──────────────────────────────────────────────────────
    login()

    # ── Verify hypervisor exists and is KVM type ──────────────────────────
    hyp = get_hypervisor()
    info(
        f"Hypervisor found: id={hyp['id']}  "
        f"name={hyp['name']!r}  "
        f"type={hyp.get('type')!r}"
    )
    hyp_type = str(hyp.get("type", "")).lower()
    if hyp_type not in ("kvm", "qemu", "libvirt"):
        warn(
            f"Hypervisor id={HYPERVISOR_ID} has type={hyp_type!r} — "
            "expected 'KVM'.  Check HYPERVISOR_ID in CONFIG."
        )

    # ── Run all scenarios ─────────────────────────────────────────────────
    vms_s1 = scenario_1_insert()
    time.sleep(1)           # small gap so last_seen_at timestamps differ
    scenario_2_update(vms_s1)
    time.sleep(1)
    scenario_3_archive()
    verify_join()

    # ── Final summary ─────────────────────────────────────────────────────
    section("FINAL SUMMARY")
    hyp_final  = get_hypervisor()
    vms_final  = get_hypervisor_vms()
    all_final  = get_all_vms()

    archived_count   = sum(1 for v in all_final if v.get("status", "").lower() == "archived")
    discovered_count = sum(1 for v in all_final if v.get("status", "").lower() != "archived")

    ok(f"Hypervisor status            : {hyp_final.get('status')}")
    ok(f"Hypervisor last_sync_at      : {hyp_final.get('last_sync_at')}")
    ok(f"Hypervisor total_vms_disc.   : {hyp_final.get('total_vms_discovered')}")
    ok(f"Live VMs in DB               : {discovered_count}")
    ok(f"Archived VMs in DB           : {archived_count}")
    ok(f"/hypervisors/{HYPERVISOR_ID}/vms total : {vms_final.get('total_vms')}")

    print(f"\n{BOLD}{GREEN}All KVM sync scenarios completed.{RESET}\n")


if __name__ == "__main__":
    main()
