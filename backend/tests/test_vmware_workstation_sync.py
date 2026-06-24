"""
tests/test_sync.py
==================
Discovery + DB Sync Test — VMware Workstation
=============================================

Tests the 3 sync scenarios against a live running server:

  Scenario 1 — INSERT  : VM exists in hypervisor but NOT in DB
  Scenario 2 — UPDATE  : VM exists in both → update only if fields changed
  Scenario 3 — ARCHIVE : VM exists in DB but no longer in hypervisor → ARCHIVED

Usage
-----
  1. Start the server:
       uvicorn app.main:app --reload

  2. Run this script:
       python tests/test_sync.py

Configuration
-------------
  Edit the constants in the CONFIG section below to match your environment.
  The script uses the /api/v1/auth/login endpoint to get a JWT token,
  then calls /api/v1/hypervisors/{id}/sync and the VMs endpoint to verify.
"""

import sys
import json
import time
import requests

# ============================================================================
# CONFIG — edit these to match your environment
# ============================================================================

BASE_URL        = "http://localhost:8000"
API_PREFIX      = "/api/v1"

# Credentials of an existing user that has hypervisors:update permission

ADMIN_EMAIL = "ahmed.mezni@nextstep.tn"
ADMIN_PASS  = "SecurePass123!"

# The hypervisor ID in your database (id=10 from your row)
HYPERVISOR_ID   = 10

# ============================================================================
# Helpers
# ============================================================================

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg): print(f"  {RED}❌ {msg}{RESET}"); sys.exit(1)
def info(msg): print(f"  {CYAN}ℹ  {msg}{RESET}")
def warn(msg): print(f"  {YELLOW}⚠  {msg}{RESET}")
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
# Session with auth token
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
    """Returns the VMs list from GET /hypervisors/{id}/vms"""
    r = session.get(f"{BASE_URL}{API_PREFIX}/hypervisors/{HYPERVISOR_ID}/vms")
    if r.status_code != 200:
        fail(f"GET hypervisor VMs failed ({r.status_code}): {r.text}")
    return r.json()

def get_all_vms():
    """Returns all VMs from GET /vms (filtered to hypervisor source)"""
    r = session.get(
        f"{BASE_URL}{API_PREFIX}/vms",
        params={"hypervisor_id": HYPERVISOR_ID, "limit": 100},
    )
    if r.status_code != 200:
        fail(f"GET vms failed ({r.status_code}): {r.text}")
    data = r.json()
    # Handle both list and paginated responses
    return data.get("items", data) if isinstance(data, dict) else data

def run_sync():
    """POST /hypervisors/{id}/sync and return the stats dict."""
    info("Calling POST /hypervisors/{id}/sync …")
    r = session.post(f"{BASE_URL}{API_PREFIX}/hypervisors/{HYPERVISOR_ID}/sync")
    if r.status_code != 200:
        fail(f"Sync failed ({r.status_code}): {r.text}")
    return r.json()

def inject_fake_vm_in_db(source_uuid: str, name: str):
    """
    Directly inserts a fake VM via POST /vms so we can test the ARCHIVE scenario.
    This VM will NOT exist in the real hypervisor — on the next sync it should
    be marked ARCHIVED.
    """
    payload = {
        "name": name,
        "source_hypervisor_id": HYPERVISOR_ID,
        "source_uuid": source_uuid,
        "source_name": name,
        "cpu_cores": 2,
        "memory_mb": 2048,
        "disk_gb": 20,
        "os_type": "linux",
        "os_version": "Fake OS 1.0",
        "os_name": "Fake Linux (test)",
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
# SCENARIO 1 — INSERT (first sync, DB is empty for this hypervisor)
# ============================================================================

def scenario_1_insert():
    section("SCENARIO 1 — INSERT: VM in hypervisor, not in DB")

    info("State BEFORE sync:")
    vms_before = get_hypervisor_vms()
    vm_count_before = vms_before["total_vms"]
    info(f"  VMs in DB for this hypervisor: {vm_count_before}")

    hyp_before = get_hypervisor()
    info(f"  hypervisor.total_vms_discovered = {hyp_before.get('total_vms_discovered')}")
    info(f"  hypervisor.status               = {hyp_before.get('status')}")
    info(f"  hypervisor.last_sync_at         = {hyp_before.get('last_sync_at')}")

    print()
    info("Running sync …")
    sync_result = run_sync()
    info(f"Sync response: {json.dumps(sync_result, indent=2)}")

    stats = sync_result.get("statistics", {})

    print()
    info("State AFTER sync:")
    vms_after = get_hypervisor_vms()
    vm_count_after = vms_after["total_vms"]
    hyp_after = get_hypervisor()

    info(f"  VMs in DB for this hypervisor: {vm_count_after}")
    info(f"  hypervisor.total_vms_discovered = {hyp_after.get('total_vms_discovered')}")
    info(f"  hypervisor.status               = {hyp_after.get('status')}")
    info(f"  hypervisor.last_sync_at         = {hyp_after.get('last_sync_at')}")

    print()
    # Assertions
    new_vms = stats.get("new_vms", 0)
    if new_vms > 0:
        ok(f"new_vms = {new_vms} — at least one VM was INSERTed")
    else:
        warn("new_vms = 0 — this is only OK if VMs were already in DB before this test.")
        warn("If this is a fresh DB, check that the hypervisor's VMX paths are configured.")

    if vm_count_after > vm_count_before:
        ok(f"VM count grew: {vm_count_before} → {vm_count_after}")
    elif vm_count_after == vm_count_before and new_vms == 0:
        warn("VM count unchanged — DB may already have been populated.")
    else:
        fail(f"Unexpected VM count: before={vm_count_before} after={vm_count_after}")

    # Hypervisor sync metadata must be updated
    assert_in(
        "hypervisor.status after sync",
        hyp_after.get("status"),
        ["active", "ACTIVE"]
    )
    if hyp_after.get("last_sync_at"):
        ok(f"hypervisor.last_sync_at is set: {hyp_after['last_sync_at']}")
    else:
        fail("hypervisor.last_sync_at was NOT updated after sync")

    # total_vms_discovered must equal the live non-archived count
    live_count = vm_count_after
    tdiscovered = hyp_after.get("total_vms_discovered", -1)
    if tdiscovered == live_count:
        ok(f"hypervisor.total_vms_discovered = {tdiscovered} (matches live VM count)")
    else:
        warn(f"hypervisor.total_vms_discovered = {tdiscovered} but live count = {live_count}")

    # Print discovered VMs
    print()
    info("Discovered VMs:")
    for vm in vms_after.get("vms", []):
        info(
            f"  [{vm.get('id')}] {vm.get('name')!r:20s}  "
            f"uuid={vm.get('source_uuid', 'N/A')!r:36s}  "
            f"status={vm.get('status')!r}  "
            f"ip={vm.get('ip_address')!r}"
        )

    return vms_after.get("vms", [])

# ============================================================================
# SCENARIO 2 — UPDATE (second sync, same VMs, check change detection)
# ============================================================================

def scenario_2_update(vms_after_s1):
    section("SCENARIO 2 — UPDATE: VM in hypervisor AND in DB")

    if not vms_after_s1:
        warn("No VMs found after Scenario 1 — skipping UPDATE test.")
        return

    info("Running a second sync immediately …")
    sync_result = run_sync()
    info(f"Sync response: {json.dumps(sync_result, indent=2)}")

    stats = sync_result.get("statistics", {})

    print()
    # On second sync with no external changes, most VMs should be unchanged
    new_vms      = stats.get("new_vms", 0)
    updated_vms  = stats.get("updated_vms", 0)
    unchanged    = stats.get("unchanged_vms", 0)
    archived     = stats.get("archived_vms", 0)

    ok(f"new_vms={new_vms}  updated_vms={updated_vms}  unchanged_vms={unchanged}  archived_vms={archived}")

    if new_vms == 0:
        ok("No duplicate INSERTs on second sync — source_uuid dedup working correctly")
    else:
        fail(f"Second sync created {new_vms} new VMs — duplicate INSERT bug detected!")

    total_processed = updated_vms + unchanged
    if total_processed == len(vms_after_s1):
        ok(f"All {total_processed} existing VMs were processed (updated or unchanged)")
    else:
        warn(
            f"Processed {total_processed} VMs but expected {len(vms_after_s1)} — "
            "some VMs may have been archived (missing VMX path?)"
        )

    # Verify last_seen_at was refreshed
    vms_now = get_hypervisor_vms().get("vms", [])
    for original_vm in vms_after_s1:
        current = find_vm_by_uuid(vms_now, original_vm.get("source_uuid"))
        if not current:
            warn(f"VM {original_vm.get('name')!r} no longer found — may have been archived")
            continue
        old_ts = original_vm.get("last_seen_at")
        new_ts = current.get("last_seen_at")
        if old_ts != new_ts:
            ok(f"last_seen_at updated for {current.get('name')!r}: {old_ts} → {new_ts}")
        else:
            # last_seen_at may be the same if both syncs happened in the same second
            info(f"last_seen_at unchanged for {current.get('name')!r} (same-second sync)")

# ============================================================================
# SCENARIO 3 — ARCHIVE (VM in DB but not in hypervisor)
# ============================================================================

def scenario_3_archive():
    section("SCENARIO 3 — ARCHIVE: VM in DB, gone from hypervisor")

    FAKE_UUID = "ffffffff-test-dead-beef-000000000000"
    FAKE_NAME = "ghost-vm-test-sync"

    info(f"Injecting a fake VM into the DB: name={FAKE_NAME!r}  uuid={FAKE_UUID!r}")
    info("This VM does NOT exist in the real VMware Workstation hypervisor.")

    # Clean up ghost VM from any previous run before injecting
    vms_resp = session.get(
        f"{BASE_URL}{API_PREFIX}/vms",
        params={"search": FAKE_NAME, "limit": 10},
    )
    if vms_resp.ok:
        for vm in vms_resp.json().get("items", []):
            if vm["name"] == FAKE_NAME:
                del_r = session.delete(f"{BASE_URL}{API_PREFIX}/vms/{vm['id']}")
                if del_r.status_code in (200, 204):
                    info(f"Cleaned up leftover ghost VM (id={vm['id']}) from previous run")
                else:
                    warn(f"Could not delete ghost VM id={vm['id']}: {del_r.status_code}")

    fake_vm = inject_fake_vm_in_db(FAKE_UUID, FAKE_NAME)
    fake_vm_id = fake_vm["id"]

    info(f"Fake VM created with id={fake_vm_id}, status={fake_vm.get('status')!r}")

    print()
    info("Running sync — fake VM should be marked ARCHIVED …")
    sync_result = run_sync()
    info(f"Sync response: {json.dumps(sync_result, indent=2)}")

    stats = sync_result.get("statistics", {})
    archived_count = stats.get("archived_vms", 0)

    print()
    if archived_count > 0:
        ok(f"archived_vms = {archived_count} (≥1 VM was archived)")
    else:
        fail("archived_vms = 0 — the fake VM was NOT archived!")

    # Fetch the fake VM directly to verify its status
    r = session.get(f"{BASE_URL}{API_PREFIX}/vms/{fake_vm_id}")
    if r.status_code == 404:
        fail("Fake VM was DELETED instead of being ARCHIVED — wrong behavior!")

    vm_after = r.json()
    vm_status = vm_after.get("status", "").lower()

    if vm_status == "archived":
        ok(f"VM id={fake_vm_id} status is now 'archived' — correct behavior")
    else:
        fail(
            f"VM id={fake_vm_id} has status={vm_status!r} instead of 'archived'\n"
            f"Full VM: {json.dumps(vm_after, indent=2)}"
        )

    # Verify the VM still exists in DB (not deleted)
    ok(f"VM still exists in DB (id={fake_vm_id}) — not deleted, only archived")

    # Verify it no longer appears in the live (non-archived) VM count
    hyp = get_hypervisor()
    vms_live = get_hypervisor_vms()
    live_vms = vms_live.get("vms", [])

    still_live = find_vm_by_uuid(live_vms, FAKE_UUID)
    if still_live:
        warn(
            f"Archived VM still appearing in /hypervisors/{HYPERVISOR_ID}/vms — "
            "check if that endpoint filters out ARCHIVED VMs"
        )
    else:
        ok("Archived VM no longer appears in the live VM list for this hypervisor")

    total_disc = hyp.get("total_vms_discovered", -1)
    info(f"hypervisor.total_vms_discovered after archive = {total_disc}")
    info("(Should NOT count the archived VM)")

    return fake_vm_id

# ============================================================================
# BONUS — Verify JOIN between hypervisors and virtual_machines tables
# ============================================================================

def verify_join():
    section("BONUS — Verify hypervisors ↔ virtual_machines JOIN")

    hyp = get_hypervisor()
    vms_data = get_hypervisor_vms()
    all_vms  = get_all_vms()

    info(f"Hypervisor  id               : {hyp.get('id')}")
    info(f"Hypervisor  name             : {hyp.get('name')!r}")
    info(f"Hypervisor  total_vms_disc.  : {hyp.get('total_vms_discovered')}")
    info(f"Hypervisor  last_sync_at     : {hyp.get('last_sync_at')}")
    info(f"  /hypervisors/{HYPERVISOR_ID}/vms  → total_vms = {vms_data.get('total_vms')}")
    info(f"  /vms?hypervisor_id={HYPERVISOR_ID} → count     = {len(all_vms)}")

    print()

    # Every VM returned by /hypervisors/{id}/vms must have source_hypervisor_id == HYPERVISOR_ID
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

    # total_vms_discovered on the hypervisor row should match non-archived VMs
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
        warn(f"{len(missing_uuid)} VM(s) are missing source_uuid — check legacy rows")
    else:
        ok("All VMs have a source_uuid")

    print()
    info("VM snapshot (id | name | uuid | status | ip):")
    for vm in all_vms:
        info(
            f"  [{vm.get('id'):>4}] {vm.get('name', '?')!r:22s}  "
            f"{str(vm.get('source_uuid', 'N/A'))[:36]:36s}  "
            f"{vm.get('status', '?'):12s}  "
            f"{vm.get('ip_address') or 'N/A'}"
        )

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  ShiftWise — Discovery Sync Test Suite{RESET}")
    print(f"{BOLD}  Server : {BASE_URL}{RESET}")
    print(f"{BOLD}  Hypervisor ID : {HYPERVISOR_ID}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    # Check server is up
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

    # Authenticate
    login()

    # Verify hypervisor exists
    hyp = get_hypervisor()
    info(f"Hypervisor found: id={hyp['id']}  name={hyp['name']!r}  type={hyp.get('type')!r}")

    # Run scenarios
    vms_s1 = scenario_1_insert()
    time.sleep(1)           # small gap so last_seen_at timestamps differ
    scenario_2_update(vms_s1)
    time.sleep(1)
    scenario_3_archive()
    verify_join()

    # Final summary
    section("FINAL SUMMARY")
    hyp_final = get_hypervisor()
    vms_final  = get_hypervisor_vms()
    all_final  = get_all_vms()

    archived_count   = sum(1 for v in all_final if v.get("status","").lower() == "archived")
    discovered_count = sum(1 for v in all_final if v.get("status","").lower() != "archived")

    ok(f"Hypervisor status            : {hyp_final.get('status')}")
    ok(f"Hypervisor last_sync_at      : {hyp_final.get('last_sync_at')}")
    ok(f"Hypervisor total_vms_disc.   : {hyp_final.get('total_vms_discovered')}")
    ok(f"Live VMs in DB               : {discovered_count}")
    ok(f"Archived VMs in DB           : {archived_count}")
    ok(f"/hypervisors/{HYPERVISOR_ID}/vms total : {vms_final.get('total_vms')}")

    print(f"\n{BOLD}{GREEN}All scenarios completed.{RESET}\n")


if __name__ == "__main__":
    main()
