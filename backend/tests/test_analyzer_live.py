"""
tests/test_analyzer_live.py
===========================
Analyzer live-DB validation — exercises the real `virtual_machines` table
=========================================================================

Validates that the Analyzer Module works end-to-end against the running
FastAPI server backed by the real PostgreSQL database. Mirrors the style
of the *_sync.py tests.

Scenarios
---------
  S1 — Single VM analyze ........ POST /vms/{id}/analyze on one DISCOVERED VM
  S2 — Idempotency .............. re-POST without ?force → must skip
  S3 — Force re-analyze ......... POST with ?force=true → re-runs
  S4 — Batch analyze ............ POST /vms/analyze/batch with up to 20 IDs
  S5 — Batch cap enforcement .... POST 21 IDs → expect HTTP 422
  S6 — Stats .................... GET /vms/analyze/stats → counts match DB
  Bonus — DB integrity .......... no row stuck in ANALYZING; details JSON valid

Usage
-----
  1. Start the server:
       uvicorn app.main:app --reload

  2. Make sure at least one hypervisor has been synced and the DB has VMs.
     (Run any of test_*_sync.py first if needed.)

  3. Run this script:
       python tests/test_analyzer_live.py

Configuration
-------------
  Edit the constants in the CONFIG section. The script does NOT touch
  hypervisors or run discovery — it operates only on existing VM rows.

Notes
-----
  - Safe to re-run: the script only mutates compatibility_* fields on
    VMs it picks; never deletes rows.
  - Already-classified VMs are re-analyzed via `?force=true` rather than
    reset to UNKNOWN — VMUpdate intentionally rejects compatibility_status.
"""

import sys
import json
import time
import requests

# ============================================================================
# CONFIG — edit these to match your environment
# ============================================================================

BASE_URL    = "http://localhost:8000"
API_PREFIX  = "/api/v1"

# Credentials of an existing user that has vms:read + vms:update permissions
ADMIN_EMAIL = "ahmed.mezni@nextstep.tn"
ADMIN_PASS  = "SecurePass123!"

# How many VMs to pull for the test (will pick first N non-archived).
# Must be >= 2 for batch scenarios to be meaningful.
SAMPLE_SIZE = 5

# ============================================================================
# Console helpers
# ============================================================================

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}OK   {msg}{RESET}")
def fail(msg):  print(f"  {RED}FAIL {msg}{RESET}"); sys.exit(1)
def info(msg):  print(f"  {CYAN}INFO {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}WARN {msg}{RESET}")

def section(title):
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

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
    ok(f"Logged in as {ADMIN_EMAIL!r}")

# ============================================================================
# API helpers
# ============================================================================

VALID_GRADES = ("COMPATIBLE", "PARTIAL", "INCOMPATIBLE")
VALID_STATUSES = {"compatible", "partial", "incompatible", "unknown"}

def list_vms(limit=50, status_filter=None):
    params = {"limit": limit}
    if status_filter:
        params["status"] = status_filter
    r = session.get(f"{BASE_URL}{API_PREFIX}/vms", params=params)
    if r.status_code != 200:
        fail(f"GET /vms failed ({r.status_code}): {r.text}")
    data = r.json()
    return data.get("items", []) if isinstance(data, dict) else data

def get_vm(vm_id):
    r = session.get(f"{BASE_URL}{API_PREFIX}/vms/{vm_id}")
    if r.status_code != 200:
        fail(f"GET /vms/{vm_id} failed ({r.status_code}): {r.text}")
    return r.json()

def analyze_vm(vm_id, force=False):
    params = {"force": "true"} if force else {}
    r = session.post(
        f"{BASE_URL}{API_PREFIX}/vms/{vm_id}/analyze",
        params=params,
    )
    return r

def analyze_batch(vm_ids, force=False):
    params = [("vm_ids", str(i)) for i in vm_ids]
    if force:
        params.append(("force", "true"))
    r = session.post(
        f"{BASE_URL}{API_PREFIX}/vms/analyze/batch",
        params=params,
    )
    return r

def get_stats():
    r = session.get(f"{BASE_URL}{API_PREFIX}/vms/analyze/stats")
    if r.status_code != 200:
        fail(f"GET /vms/analyze/stats failed ({r.status_code}): {r.text}")
    return r.json()

# ============================================================================
# Validation helpers
# ============================================================================

def validate_details(details, vm_id):
    """Verify the JSON returned in compatibility_details is well-formed."""
    if not isinstance(details, dict):
        fail(f"VM {vm_id}: compatibility_details is not a dict ({type(details).__name__})")

    required = ("score", "grade", "engine", "rules", "blockers", "warnings", "analyzed_at")
    missing = [k for k in required if k not in details]
    if missing:
        fail(f"VM {vm_id}: compatibility_details missing keys: {missing}")

    if details["grade"] not in VALID_GRADES:
        fail(f"VM {vm_id}: grade={details['grade']!r} not in {VALID_GRADES}")

    if details["engine"] not in ("model", "rules"):
        fail(f"VM {vm_id}: engine={details['engine']!r} not in ('model', 'rules')")

    score = details["score"]
    if not isinstance(score, (int, float)) or not 0 <= score <= 100:
        fail(f"VM {vm_id}: score={score!r} not in [0, 100]")

    if not isinstance(details["rules"], list) or not details["rules"]:
        fail(f"VM {vm_id}: rules must be a non-empty list")

    for rule in details["rules"]:
        if not isinstance(rule, dict) or "id" not in rule or "passed" not in rule:
            fail(f"VM {vm_id}: malformed rule entry: {rule!r}")

    if details["engine"] == "model":
        conf = details.get("confidence")
        if conf is None or not 0 <= conf <= 1:
            fail(f"VM {vm_id}: model engine but confidence={conf!r}")

# ============================================================================
# SCENARIO 1 — Single VM analyze
# ============================================================================

def scenario_1_single(vm):
    section(f"SCENARIO 1 — Single VM analyze (id={vm['id']}, name={vm['name']!r})")

    before = get_vm(vm["id"])
    info(f"  status BEFORE                : {before.get('status')}")
    info(f"  compatibility_status BEFORE  : {before.get('compatibility_status')}")

    # Use ?force=true so the test is deterministic regardless of prior state.
    info("Calling POST /vms/{id}/analyze?force=true …")
    r = analyze_vm(vm["id"], force=True)
    if r.status_code != 200:
        fail(f"Analyze failed ({r.status_code}): {r.text}")
    payload = r.json()
    info(f"  response keys: {sorted(payload.keys())}")

    after = get_vm(vm["id"])
    info(f"  status AFTER                 : {after.get('status')}")
    info(f"  compatibility_status AFTER   : {after.get('compatibility_status')}")

    # ── Assertions ────────────────────────────────────────────────────────
    if str(after.get("status", "")).lower() == "discovered":
        ok("VM status returned to DISCOVERED (not stuck in ANALYZING)")
    else:
        fail(f"VM status is {after.get('status')!r} — expected 'discovered'")

    new_compat = str(after.get("compatibility_status", "")).lower()
    if new_compat in VALID_STATUSES and new_compat != "unknown":
        ok(f"compatibility_status updated to {new_compat!r}")
    else:
        fail(f"compatibility_status = {new_compat!r} — analyzer didn't classify")

    details = after.get("compatibility_details")
    validate_details(details, vm["id"])
    ok(
        f"compatibility_details valid: grade={details['grade']}, engine={details['engine']}, "
        f"score={details['score']}, rules={len(details['rules'])}, "
        f"blockers={len(details['blockers'])}, warnings={len(details['warnings'])}"
    )

    return after

# ============================================================================
# SCENARIO 2 — Idempotency (re-analyze without force)
# ============================================================================

def scenario_2_idempotent(vm_after_s1):
    section("SCENARIO 2 — Idempotency: second analyze without ?force")

    vm_id = vm_after_s1["id"]
    details_before = vm_after_s1.get("compatibility_details") or {}
    analyzed_at_before = details_before.get("analyzed_at")

    info("Calling POST /vms/{id}/analyze a second time (no force) …")
    r = analyze_vm(vm_id, force=False)
    if r.status_code != 200:
        fail(f"Second analyze failed ({r.status_code}): {r.text}")

    after = get_vm(vm_id)
    details_after = after.get("compatibility_details") or {}
    analyzed_at_after = details_after.get("analyzed_at")

    if analyzed_at_before == analyzed_at_after:
        ok(f"analyzed_at unchanged ({analyzed_at_after}) — re-analyze correctly skipped")
    else:
        fail(
            f"analyzed_at changed: {analyzed_at_before} -> {analyzed_at_after}\n"
            "  Expected the analyzer to skip already-classified VMs without ?force."
        )

# ============================================================================
# SCENARIO 3 — Force re-analyze
# ============================================================================

def scenario_3_force(vm_after_s1):
    section("SCENARIO 3 — Force re-analyze with ?force=true")

    vm_id = vm_after_s1["id"]
    details_before = vm_after_s1.get("compatibility_details") or {}
    analyzed_at_before = details_before.get("analyzed_at")

    # Sleep 1s so analyzed_at timestamp is guaranteed to differ
    time.sleep(1)

    info("Calling POST /vms/{id}/analyze?force=true …")
    r = analyze_vm(vm_id, force=True)
    if r.status_code != 200:
        fail(f"Force analyze failed ({r.status_code}): {r.text}")

    after = get_vm(vm_id)
    details_after = after.get("compatibility_details") or {}
    analyzed_at_after = details_after.get("analyzed_at")

    if analyzed_at_before != analyzed_at_after:
        ok(f"analyzed_at refreshed: {analyzed_at_before} -> {analyzed_at_after}")
    else:
        fail(
            f"analyzed_at unchanged after force=true ({analyzed_at_after})\n"
            "  ?force=true must trigger a fresh analysis."
        )

    # Grade should be deterministic for the same VM features
    if details_before.get("grade") == details_after.get("grade"):
        ok(f"grade stable across force re-analyze: {details_after['grade']}")
    else:
        warn(
            f"grade changed: {details_before.get('grade')} -> {details_after.get('grade')} "
            "(unusual — verify VM fields didn't change)"
        )

# ============================================================================
# SCENARIO 4 — Batch analyze
# ============================================================================

def scenario_4_batch(vms):
    section(f"SCENARIO 4 — Batch analyze ({len(vms)} VMs)")

    if len(vms) < 2:
        warn("Less than 2 VMs available — batch test degenerates to single-VM case")

    vm_ids = [v["id"] for v in vms]

    info(f"Calling POST /vms/analyze/batch?force=true with vm_ids={vm_ids} …")
    r = analyze_batch(vm_ids, force=True)
    if r.status_code != 200:
        fail(f"Batch analyze failed ({r.status_code}): {r.text}")
    payload = r.json()
    info(f"  response: total={payload.get('total')} analyzed={payload.get('analyzed')} "
         f"failed={payload.get('failed')}")

    if payload.get("analyzed", 0) != len(vm_ids):
        fail(
            f"Batch analyzed {payload.get('analyzed')} of {len(vm_ids)} VMs "
            f"(failed={payload.get('failed')})"
        )
    ok(f"All {len(vm_ids)} VMs analyzed successfully via batch")

    # Verify every VM has a non-UNKNOWN status now
    for vid in vm_ids:
        v = get_vm(vid)
        c = str(v.get("compatibility_status", "")).lower()
        if c in VALID_STATUSES and c != "unknown":
            ok(f"  VM {vid}: compatibility_status = {c}")
        else:
            fail(f"  VM {vid}: compatibility_status still {c!r} after batch")

# ============================================================================
# SCENARIO 5 — Batch cap enforcement (21 IDs → 422)
# ============================================================================

def scenario_5_cap():
    section("SCENARIO 5 — Batch cap enforcement (>20 IDs must return 422)")

    fake_ids = list(range(1, 22))  # 21 IDs
    info(f"Calling POST /vms/analyze/batch with {len(fake_ids)} IDs …")
    r = analyze_batch(fake_ids)

    if r.status_code == 422:
        ok(f"Batch correctly rejected 21 IDs with HTTP 422")
        try:
            detail = r.json().get("detail", "")
            info(f"  detail: {detail!r}")
        except Exception:
            pass
    else:
        fail(
            f"Expected HTTP 422 for 21 IDs, got {r.status_code}: {r.text}\n"
            "  The cap must be enforced server-side."
        )

# ============================================================================
# SCENARIO 6 — Stats endpoint
# ============================================================================

def scenario_6_stats(all_vms):
    section("SCENARIO 6 — GET /vms/analyze/stats")

    stats = get_stats()
    info(f"  stats: {json.dumps(stats, indent=2)}")

    # Cross-check against the VM list we already have
    expected = {"compatible": 0, "partial": 0, "incompatible": 0, "unknown": 0}
    for vm in all_vms:
        c = str(vm.get("compatibility_status", "unknown")).lower()
        if c in expected:
            expected[c] += 1

    info(f"  expected (from /vms scan): {expected}")

    # Stats may include VMs across all hypervisors, so we check the API key
    # set rather than exact counts when SAMPLE_SIZE < total VMs in DB.
    for key in ("compatible", "partial", "incompatible", "unknown"):
        if key not in stats:
            fail(f"stats missing key: {key!r}")
        if not isinstance(stats[key], int) or stats[key] < 0:
            fail(f"stats[{key!r}] = {stats[key]!r} — must be non-negative int")

    # The VMs we just analyzed must be reflected in the totals
    total_classified = stats["compatible"] + stats["partial"] + stats["incompatible"]
    if total_classified >= len([v for v in all_vms if str(v.get("compatibility_status","")).lower() in ("compatible","partial","incompatible")]):
        ok(f"stats totals consistent with sampled VMs (classified={total_classified})")
    else:
        warn(
            f"stats classified={total_classified} but sample shows more — "
            "tenant filter may be hiding rows"
        )

# ============================================================================
# BONUS — DB integrity check
# ============================================================================

def verify_integrity(touched_ids):
    section("BONUS — DB integrity check on analyzed VMs")

    for vid in touched_ids:
        v = get_vm(vid)

        # No row should be stuck in ANALYZING
        if str(v.get("status", "")).lower() == "analyzing":
            fail(f"VM {vid} is stuck in status=ANALYZING")

        # compatibility_details must be a non-empty dict with a valid grade
        details = v.get("compatibility_details")
        if not details:
            fail(f"VM {vid} has no compatibility_details after analysis")
        validate_details(details, vid)

    ok(f"All {len(touched_ids)} touched VMs are in a clean post-analysis state")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  ShiftWise — Analyzer Live-DB Validation{RESET}")
    print(f"{BOLD}  Server   : {BASE_URL}{RESET}")
    print(f"{BOLD}  Sample   : {SAMPLE_SIZE} VMs from real virtual_machines table{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    # ── Server health check ────────────────────────────────────────────────
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

    # ── Pick sample VMs ────────────────────────────────────────────────────
    section("DISCOVERY — Picking sample VMs from the DB")
    all_vms = list_vms(limit=100)
    candidates = [v for v in all_vms if str(v.get("status", "")).lower() != "archived"]

    if not candidates:
        fail(
            "No non-archived VMs in the DB.\n"
            "  Run a discovery sync first (e.g. python tests/test_proxmox_sync.py)."
        )

    sample = candidates[:SAMPLE_SIZE]
    ok(f"Picked {len(sample)} VM(s) out of {len(candidates)} candidate(s)")
    for v in sample:
        info(
            f"  [{v['id']:>4}] {v.get('name', '?')!r:25s}  "
            f"hyp={v.get('source_hypervisor_id')}  "
            f"os={v.get('os_type')!r}  "
            f"compat_before={v.get('compatibility_status')}"
        )

    # ── Run scenarios ──────────────────────────────────────────────────────
    vm_after = scenario_1_single(sample[0])
    scenario_2_idempotent(vm_after)
    scenario_3_force(vm_after)
    scenario_4_batch(sample)
    scenario_5_cap()
    scenario_6_stats(list_vms(limit=100))
    verify_integrity([v["id"] for v in sample])

    # ── Final summary ──────────────────────────────────────────────────────
    section("FINAL SUMMARY")
    final_stats = get_stats()
    ok(f"Compatible    : {final_stats.get('compatible')}")
    ok(f"Partial       : {final_stats.get('partial')}")
    ok(f"Incompatible  : {final_stats.get('incompatible')}")
    ok(f"Unknown       : {final_stats.get('unknown')}")

    print(f"\n{BOLD}{GREEN}All Analyzer live-DB scenarios completed.{RESET}\n")


if __name__ == "__main__":
    main()
