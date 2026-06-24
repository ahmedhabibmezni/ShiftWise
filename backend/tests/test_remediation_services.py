"""
Remediation tests — security / pipeline / SonarQube audit findings.

Each test is written TDD-style: it fails against the pre-fix code and passes
once the corresponding remediation lands. Findings are tagged in the test name
(A11, A16, A17, A19, E4, E5, E8, E9, E11, E12, E13, E14, E15, E16, E17, E18,
E20, M-26, S3776, S8392).

These tests use only in-memory fakes — no live server, no live cluster.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# A16 — bcrypt 72-byte silent truncation
# ---------------------------------------------------------------------------


class TestA16BcryptOverLength:
    def test_hash_rejects_password_over_72_bytes(self):
        from app.core.security import get_password_hash

        with pytest.raises(ValueError):
            get_password_hash("A" * 73)

    def test_hash_accepts_password_at_the_72_byte_boundary(self):
        from app.core.security import get_password_hash

        # Exactly 72 bytes must still be accepted.
        digest = get_password_hash("A" * 72)
        assert digest and digest.startswith("$2")

    def test_two_distinct_long_passwords_do_not_collide(self):
        """The pre-fix truncation made every >72-byte password sharing a
        72-byte prefix verify against the same hash. After the fix an
        over-length password is rejected outright, so this attack is moot."""
        from app.core.security import get_password_hash, verify_password

        base = "A" * 72
        digest = get_password_hash(base)
        # A different 73-byte password must be rejected, never silently
        # accepted as equal to `base`.
        with pytest.raises(ValueError):
            verify_password(base + "B", digest)

    def test_multibyte_password_length_measured_in_bytes(self):
        from app.core.security import get_password_hash

        # 30 emoji = 120 UTF-8 bytes — over the limit even though len()==30.
        with pytest.raises(ValueError):
            get_password_hash("\U0001F600" * 30)


# ---------------------------------------------------------------------------
# A11 — login throttle / audit IP must not blindly trust X-Forwarded-For
# ---------------------------------------------------------------------------


class TestA11ClientIpResolution:
    def test_xff_ignored_when_peer_is_not_a_trusted_proxy(self, monkeypatch):
        from app.core import login_throttle

        monkeypatch.setattr(
            login_throttle.settings, "TRUSTED_PROXY_IPS", [], raising=False
        )
        req = _fake_request(peer="203.0.113.9", xff="1.2.3.4, 5.6.7.8")
        # An untrusted peer's XFF is spoofable — must fall back to peer IP.
        assert login_throttle.client_ip_from_request(req) == "203.0.113.9"

    def test_xff_honored_when_peer_is_a_trusted_proxy(self, monkeypatch):
        from app.core import login_throttle

        monkeypatch.setattr(
            login_throttle.settings,
            "TRUSTED_PROXY_IPS",
            ["10.9.21.150"],
            raising=False,
        )
        req = _fake_request(peer="10.9.21.150", xff="198.51.100.7, 10.9.21.150")
        # Behind a trusted proxy, the left-most XFF entry is the real client.
        assert login_throttle.client_ip_from_request(req) == "198.51.100.7"

    def test_no_xff_header_falls_back_to_peer(self, monkeypatch):
        from app.core import login_throttle

        monkeypatch.setattr(
            login_throttle.settings,
            "TRUSTED_PROXY_IPS",
            ["10.9.21.150"],
            raising=False,
        )
        req = _fake_request(peer="10.9.21.150", xff=None)
        assert login_throttle.client_ip_from_request(req) == "10.9.21.150"


def _fake_request(*, peer: str | None, xff: str | None):
    """Minimal stand-in for a Starlette Request."""
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    client = MagicMock()
    client.host = peer
    req = MagicMock()
    req.client = client if peer is not None else None
    req.headers = headers
    return req


# ---------------------------------------------------------------------------
# A17 — Hyper-V discovery: validate host, keep script literal
# ---------------------------------------------------------------------------


class TestA17HypervHostValidation:
    def test_script_is_a_module_literal_not_built_from_input(self):
        from app.services import discovery

        # The script the remote wrapper executes must be a fixed literal.
        assert "Get-VM" in discovery._HYPERV_PS_SCRIPT
        src = inspect.getsource(discovery._build_hyperv_command)
        # HV_SCRIPT must be assigned the module constant, never a value
        # derived from hypervisor / connection_config input.
        assert "_HYPERV_PS_SCRIPT" in src

    def test_remote_discovery_rejects_a_malformed_host(self):
        from app.services.discovery import DiscoveryError, _build_hyperv_command

        with pytest.raises(DiscoveryError):
            _build_hyperv_command(
                "evil host; rm -rf /", "remote", "administrator", "pw"
            )

    def test_remote_discovery_rejects_host_with_shell_metacharacters(self):
        from app.services.discovery import DiscoveryError, _build_hyperv_command

        for bad in ("a`b", "a$b", "a|b", "a&b", "a\nb"):
            with pytest.raises(DiscoveryError):
                _build_hyperv_command(bad, "remote", "u", "p")

    def test_remote_discovery_accepts_a_valid_hostname(self):
        from app.services.discovery import _build_hyperv_command

        cmd, env = _build_hyperv_command(
            "hyperv01.corp.local", "remote", "u", "p"
        )
        assert env is not None and env["HV_HOST"] == "hyperv01.corp.local"

    def test_remote_wrapper_uses_negotiate_authentication(self):
        """WinRM against a workgroup host with an explicit PSCredential needs
        -Authentication Negotiate; without it Invoke-Command yields
        AccessDenied even with valid credentials."""
        from app.services.discovery import _build_hyperv_command

        cmd, _ = _build_hyperv_command("hyperv01.corp.local", "remote", "u", "p")
        wrapper = cmd[-1]
        assert "-Authentication Negotiate" in wrapper

    def test_local_discovery_still_works(self):
        from app.services.discovery import _build_hyperv_command

        cmd, env = _build_hyperv_command("localhost", "local", None, None)
        assert env is None


# ---------------------------------------------------------------------------
# A19 — KVM virsh dumpxml domain name must be shell-quoted
# ---------------------------------------------------------------------------


class TestA19VirshDomainQuoting:
    def test_discover_kvm_shell_quotes_domain_names(self):
        from app.services import discovery

        src = inspect.getsource(discovery.DiscoveryService._discover_kvm)
        # shlex.quote must wrap the domain name before it is interpolated
        # into a virsh command string passed to a remote shell.
        assert "shlex.quote" in src

    def test_a_domain_name_with_a_quote_cannot_break_out(self):
        import shlex

        # Sanity check on the quoting primitive itself: a name containing a
        # single quote is rendered as one safe shell token.
        malicious = "vm'; rm -rf /; echo '"
        quoted = shlex.quote(malicious)
        assert quoted.count(" ") == 0 or quoted.startswith("'")
        # The dangerous `rm` is now inside a quoted literal.
        assert quoted != malicious


# ---------------------------------------------------------------------------
# E5 — discovery must not leave a hypervisor stuck in DISCOVERING
# ---------------------------------------------------------------------------


class TestE5DiscoveringStuckState:
    def test_unexpected_exception_resets_status_away_from_discovering(self):
        from app.models.hypervisor import HypervisorStatus, HypervisorType
        from app.services.discovery import DiscoveryService

        hv = _FakeHypervisor(HypervisorType.KVM)
        db = _FakeDb(hv)
        svc = DiscoveryService(db)

        # A non-classified error (not Discovery/Connection/Timeout/OSError).
        def boom(_h):
            raise RuntimeError("driver imploded")

        svc._discover_kvm = boom  # type: ignore[assignment]

        with pytest.raises(Exception):
            svc.discover_hypervisor(hv.id)

        # The hypervisor must NOT still be DISCOVERING — that state means
        # "sync in progress" and would block the next sync forever.
        assert hv.status != HypervisorStatus.DISCOVERING


class _FakeHypervisor:
    def __init__(self, hv_type):
        from app.models.hypervisor import HypervisorStatus

        self.id = 1
        self.name = "fake-hv"
        self.type = hv_type
        self.tenant_id = "t1"
        self.status = HypervisorStatus.ACTIVE
        self.host = "qemu+ssh://root@1.2.3.4/system"
        self.connection_config = {}
        self.last_sync_at = None
        self.total_vms_discovered = 0

    def update_status(self, status, error_message=None):
        self.status = status

    def mark_sync_completed(self, success=True, total_vms=None):
        pass


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._result


class _FakeDb:
    def __init__(self, hv):
        self._hv = hv

    def query(self, _model):
        return _FakeQuery(self._hv)

    def commit(self):
        pass


# ---------------------------------------------------------------------------
# E8 — KVM discovery must not leak the paramiko client when connect() raises
# ---------------------------------------------------------------------------


class TestE8KvmSshClientLeak:
    def test_client_is_closed_when_connect_raises(self):
        from app.services import discovery

        src = inspect.getsource(discovery.DiscoveryService._discover_kvm)
        # The failure path of client.connect(...) must close() the client.
        # We assert structurally: a close() call sits on the except branch.
        assert src.count("client.close()") >= 2, (
            "connect() failure path must close the SSH client too"
        )


# ---------------------------------------------------------------------------
# E9 — K8s wait loops must pass a client-side _request_timeout
# ---------------------------------------------------------------------------


class TestE9K8sRequestTimeout:
    @pytest.mark.parametrize(
        "module_path",
        [
            "app/services/converter/k8s_jobs.py",
            "app/services/adapter/guestfish_job.py",
            "app/services/migrator/populator_job.py",
            "app/services/migrator/pvc.py",
        ],
    )
    def test_read_namespaced_job_status_has_request_timeout(self, module_path):
        text = (_BACKEND / module_path).read_text(encoding="utf-8")
        # Every poll-loop K8s read must bound the HTTP call so a hung API
        # server cannot wedge a worker thread forever.
        if "read_namespaced_job_status" in text or \
           "read_namespaced_persistent_volume_claim" in text:
            assert "_request_timeout" in text, (
                f"{module_path}: K8s poll call lacks _request_timeout"
            )


# ---------------------------------------------------------------------------
# E11 — _wait_for_conversions needs a wall-clock deadline
# ---------------------------------------------------------------------------


class TestE11ConversionWaitDeadline:
    def test_wait_loop_has_a_wall_clock_deadline(self):
        from app.tasks import migration as migration_task

        src = inspect.getsource(migration_task._wait_for_conversions)
        # A bare `while True` with no deadline can hang the orchestrator
        # indefinitely if a conversion job silently stalls.
        assert "monotonic" in src or "deadline" in src.lower()

    def test_wait_loop_raises_on_deadline(self, monkeypatch):
        """When the deadline elapses the loop must raise ConversionError,
        not spin forever."""
        from app.services.converter.errors import ConversionError
        from app.tasks import migration as migration_task

        # A group that never reaches READY.
        class _Group:
            status = _NonTerminalGroupStatus()
            jobs = []

        monkeypatch.setattr(
            migration_task.crud_conversion, "get_group", lambda *a, **k: _Group()
        )
        # Force the deadline to be already expired.
        monkeypatch.setattr(
            migration_task.settings,
            "MIGRATION_CONVERSION_WAIT_TIMEOUT",
            0,
            raising=False,
        )
        db = MagicMock()
        mig = MagicMock()
        mig.id = 1
        with pytest.raises(ConversionError):
            migration_task._wait_for_conversions(db, mig, group_id=1)


class _NonTerminalGroupStatus:
    """A ConversionGroupStatus value that is neither READY nor failed."""

    value = "in_progress"

    def __eq__(self, other):
        return False  # never equal to READY / failed states

    def __hash__(self):
        return 0


# ---------------------------------------------------------------------------
# E4 — retried run_migration must short-circuit on a terminal migration
# ---------------------------------------------------------------------------


class TestE4TerminalStateGuard:
    def test_run_migration_skips_a_completed_migration(self, monkeypatch):
        from app.models.migration import MigrationStatus
        from app.tasks import migration as migration_task

        completed = MagicMock()
        completed.id = 7
        completed.status = MigrationStatus.COMPLETED
        completed.is_completed = True

        monkeypatch.setattr(
            migration_task.crud_migration,
            "get_migration",
            lambda db, mid: completed,
        )

        # If the guard is missing, the task would call _validate and crash
        # on the MagicMock. With the guard it returns the terminal status.
        validate_called = []
        monkeypatch.setattr(
            migration_task, "_validate",
            lambda *a, **k: validate_called.append(True),
        )

        result = migration_task.run_migration(migration_id=7)
        assert result == MigrationStatus.COMPLETED.value
        assert validate_called == [], "terminal migration must not be re-run"

    def test_run_migration_proceeds_for_a_pending_migration(self, monkeypatch):
        from app.models.migration import MigrationStatus
        from app.tasks import migration as migration_task

        pending = MagicMock()
        pending.id = 8
        pending.status = MigrationStatus.PENDING
        pending.is_completed = False

        monkeypatch.setattr(
            migration_task.crud_migration,
            "get_migration",
            lambda db, mid: pending,
        )
        proceeded = []
        monkeypatch.setattr(
            migration_task, "_validate",
            lambda *a, **k: proceeded.append(True),
        )
        # Stop the pipeline right after _validate so the test stays a unit.
        monkeypatch.setattr(
            migration_task, "_prepare_conversions",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop")),
        )
        migration_task.run_migration(migration_id=8)
        assert proceeded == [True]


# ---------------------------------------------------------------------------
# E12 — converter _run_in_cluster must delete its K8s Job
# ---------------------------------------------------------------------------


class TestE12ConverterJobCleanup:
    def test_run_in_cluster_deletes_the_job(self):
        from app.services.converter.service import ConverterService

        src = inspect.getsource(ConverterService._run_in_cluster)
        assert "runner.delete(" in src or ".delete(job_name" in src, (
            "_run_in_cluster must delete the K8s Job (orphan accumulation)"
        )

    def test_job_deleted_on_success(self):
        from app.models.conversion import ConversionTool
        from app.services.converter.k8s_jobs import JobOutcome
        from app.services.converter.service import ConverterService

        runner = MagicMock()
        runner.wait_for_completion.return_value = JobOutcome(
            succeeded=True, failure_reason=None, container_exit_code=0
        )
        svc = ConverterService(runner=runner)
        job = MagicMock()
        job.tool = ConversionTool.QEMU_IMG
        job.disk_index = 0
        job.attempts = 1
        job.target_format = _qcow2_target()
        svc._run_in_cluster(job, "uuuuuuuu-1111", Path("/in"), Path("/out"))
        assert runner.delete.called, "Job must be deleted after a success"

    def test_job_deleted_even_when_conversion_fails(self):
        from app.models.conversion import ConversionTool
        from app.services.converter.errors import ConversionError
        from app.services.converter.k8s_jobs import JobOutcome
        from app.services.converter.service import ConverterService

        runner = MagicMock()
        runner.wait_for_completion.return_value = JobOutcome(
            succeeded=False, failure_reason="BackoffLimitExceeded",
            container_exit_code=1,
        )
        svc = ConverterService(runner=runner)
        job = MagicMock()
        job.tool = ConversionTool.QEMU_IMG
        job.disk_index = 0
        job.attempts = 1
        job.target_format = _qcow2_target()
        with pytest.raises(ConversionError):
            svc._run_in_cluster(job, "uuuuuuuu-2222", Path("/in"), Path("/out"))
        assert runner.delete.called, "Job must be deleted on the failure path too"


def _qcow2_target():
    from app.models.conversion import TargetFormat

    return TargetFormat.QCOW2


# ---------------------------------------------------------------------------
# E13 — transit_discovery cache must support TTL / invalidation
# ---------------------------------------------------------------------------


class TestE13TransitCacheTtl:
    def test_cache_can_be_explicitly_invalidated(self):
        from app.services.migrator import transit_discovery

        # clear_cache() is the documented invalidation path — it must exist
        # and actually reset the module cache.
        transit_discovery.clear_cache()
        assert transit_discovery._CACHE is None

    def test_cache_records_an_expiry_timestamp(self):
        from app.services.migrator import transit_discovery

        # The cache must carry a TTL so a PV redeploy is eventually picked
        # up without a full worker restart.
        src = inspect.getsource(transit_discovery)
        assert "TTL" in src or "_CACHE_EXPIRES" in src or "ttl" in src

    def test_lookup_repopulates_after_invalidation(self, monkeypatch):
        from app.services.migrator import transit_discovery

        transit_discovery.clear_cache()
        monkeypatch.setattr(
            transit_discovery.settings, "MIGRATOR_NFS_SERVER", "", raising=False
        )
        monkeypatch.setattr(
            transit_discovery.settings, "MIGRATOR_NFS_PATH", "", raising=False
        )
        calls = []

        def fake_lookup(_kv):
            calls.append(True)
            return ("nfs.example", "/export/transit")

        monkeypatch.setattr(transit_discovery, "_lookup_from_cluster", fake_lookup)

        kv = MagicMock()
        first = transit_discovery.discover_transit_nfs(kv)
        second = transit_discovery.discover_transit_nfs(kv)
        assert first == second == ("nfs.example", "/export/transit")
        # Second call is a cache hit — exactly one cluster lookup.
        assert len(calls) == 1
        transit_discovery.clear_cache()


# ---------------------------------------------------------------------------
# E14 — AnalyzerService must use a process-level model singleton
# ---------------------------------------------------------------------------


class TestE14AnalyzerModelSingleton:
    def test_two_services_share_the_same_loaded_model_object(self):
        from app.services import analyzer

        analyzer.reset_model_cache()
        a = analyzer.AnalyzerService()
        b = analyzer.AnalyzerService()
        # Same underlying model object — not two independent joblib loads.
        if a.model is not None:
            assert a.model is b.model

    def test_model_loaded_from_disk_only_once(self, monkeypatch):
        from app.services import analyzer

        analyzer.reset_model_cache()
        loads = []
        real_load = analyzer.joblib.load

        def counting_load(path, *a, **k):
            loads.append(path)
            return real_load(path, *a, **k)

        monkeypatch.setattr(analyzer.joblib, "load", counting_load)
        analyzer.AnalyzerService()
        analyzer.AnalyzerService()
        analyzer.AnalyzerService()
        # joblib.load runs at most once across three instantiations.
        assert len(loads) <= 1
        analyzer.reset_model_cache()


# ---------------------------------------------------------------------------
# E15 — ML degraded-mode must be observable
# ---------------------------------------------------------------------------


class TestE15MlDegradedModeVisible:
    def test_analyzer_exposes_a_degraded_mode_flag(self):
        from app.services.analyzer import AnalyzerService

        svc = AnalyzerService()
        # Whatever the model state, the service must expose whether it is
        # running on the rules fallback (degraded) or the ML model.
        status = svc.ml_status()
        assert "degraded" in status
        assert isinstance(status["degraded"], bool)

    def test_degraded_true_when_model_is_absent(self):
        from app.services.analyzer import AnalyzerService

        svc = AnalyzerService()
        svc.model = None
        assert svc.ml_status()["degraded"] is True

    def test_degraded_false_when_model_loaded(self):
        from app.services.analyzer import AnalyzerService

        svc = AnalyzerService()
        svc.model = object()  # stand-in for a loaded estimator
        assert svc.ml_status()["degraded"] is False


# ---------------------------------------------------------------------------
# E16 — discovery Pass-3 name fallback must be limited to NULL-source_uuid rows
# ---------------------------------------------------------------------------


class TestE16Pass3NameFallback:
    def test_pass3_filters_on_null_source_uuid(self):
        from app.services import discovery

        src = inspect.getsource(discovery.DiscoveryService._save_discovered_vms)
        # Pass-3 (name fallback) must additionally require source_uuid IS
        # NULL so it cannot hijack a row whose UUID merely changed.
        assert "source_uuid.is_(None)" in src or "source_uuid == None" in src


# ---------------------------------------------------------------------------
# E17 — converter passthrough must verify before destroying the staged file
# ---------------------------------------------------------------------------


class TestE17PassthroughVerifyBeforeMove:
    def test_passthrough_copies_then_verifies_then_removes(self, tmp_path):
        from app.services.converter.service import ConverterService

        src = tmp_path / "staged.img"
        src.write_bytes(b"disk-bytes-here")
        dst = tmp_path / "outputs" / "0.qcow2"
        dst.parent.mkdir(parents=True)

        ConverterService()._passthrough(src, dst)

        assert dst.exists() and dst.read_bytes() == b"disk-bytes-here"

    def test_passthrough_keeps_source_when_destination_write_fails(
        self, tmp_path, monkeypatch
    ):
        """If the move/copy fails, the staged source must survive so the job
        can be retried — a rename-first strategy would destroy it."""
        from app.services.converter.errors import ConversionError
        from app.services.converter.service import ConverterService

        src = tmp_path / "staged.img"
        src.write_bytes(b"precious")
        dst = tmp_path / "nonexistent-dir" / "0.qcow2"  # parent missing

        with pytest.raises(ConversionError):
            ConverterService()._passthrough(src, dst)
        # The source file must NOT have been consumed by a premature rename.
        assert src.exists() and src.read_bytes() == b"precious"


# ---------------------------------------------------------------------------
# E18 — failure-reason extraction must classify on `reason`, not `message`
# ---------------------------------------------------------------------------


class TestE18ExtractFailureReason:
    def test_converter_extract_uses_reason_only(self):
        from app.services.converter import k8s_jobs

        src = inspect.getsource(k8s_jobs.ConversionJobRunner._extract_failure_reason)
        # `cond.reason or cond.message` lets a free-text message poison the
        # exact-match classifier. Only `cond.reason` must be returned.
        assert "cond.message" not in src

    def test_adapter_extract_uses_reason_only(self):
        from app.services.adapter import guestfish_job

        src = inspect.getsource(guestfish_job._extract_failure_reason)
        assert "cond.message" not in src

    def test_migrator_extract_uses_reason_only(self):
        from app.services.migrator import populator_job

        src = inspect.getsource(populator_job._extract_failure_reason)
        assert "cond.message" not in src


# ---------------------------------------------------------------------------
# E20 — KubeVirt custom-mode client must recreate on a 401
# ---------------------------------------------------------------------------


class TestE20KubeVirtReauthOn401:
    def test_get_client_recreates_after_a_401(self, monkeypatch):
        from app.core import kubevirt_client

        # Force custom mode and a deterministic constructor.
        monkeypatch.setattr(
            kubevirt_client.settings, "KUBERNETES_MODE", "custom", raising=False
        )
        kubevirt_client._kubevirt_client_instance = None
        built = []

        class _FakeClient:
            def __init__(self):
                built.append(self)

        monkeypatch.setattr(kubevirt_client, "KubeVirtClient", _FakeClient)

        c1 = kubevirt_client.get_kubevirt_client()
        # Signal a token-expiry: the next get must rebuild in custom mode.
        kubevirt_client.invalidate_kubevirt_client()
        c2 = kubevirt_client.get_kubevirt_client()
        assert c1 is not c2
        assert len(built) == 2


# ---------------------------------------------------------------------------
# M-26 — init_db() create_all() must be gated, not run on every prod startup
# ---------------------------------------------------------------------------


class TestM26InitDbGate:
    def test_init_db_is_skipped_when_gate_is_off(self, monkeypatch):
        from app.core import database

        monkeypatch.setattr(
            database.settings, "DB_AUTO_CREATE_ALL", False, raising=False
        )
        called = []
        monkeypatch.setattr(
            database.Base.metadata, "create_all",
            lambda *a, **k: called.append(True),
        )
        database.init_db()
        assert called == [], "create_all must not run when the gate is off"

    def test_init_db_runs_create_all_when_gate_is_on(self, monkeypatch):
        from app.core import database

        monkeypatch.setattr(
            database.settings, "DB_AUTO_CREATE_ALL", True, raising=False
        )
        called = []
        monkeypatch.setattr(
            database.Base.metadata, "create_all",
            lambda *a, **k: called.append(True),
        )
        database.init_db()
        assert called == [True]


# ---------------------------------------------------------------------------
# S8392 — the dev SSH key path must come from settings, not be hardcoded
# ---------------------------------------------------------------------------


class TestS8392HardcodedSshKeyPath:
    def test_kvm_discovery_has_no_hardcoded_ssh_key_path(self):
        from app.services import discovery

        src = inspect.getsource(discovery.DiscoveryService._discover_kvm)
        assert "C:/Users/PC/.ssh/id_rsa_kvm" not in src, (
            "dev SSH key path must come from settings.*, not be hardcoded"
        )

    def test_settings_exposes_a_default_kvm_ssh_key_path(self):
        from app.core.config import settings

        assert hasattr(settings, "KVM_SSH_KEY_PATH")


# ---------------------------------------------------------------------------
# S3776 — cognitive complexity must be reduced via helper extraction
# ---------------------------------------------------------------------------


class TestS3776HelperExtraction:
    def test_discover_vmware_workstation_delegates_to_helpers(self):
        from app.services import discovery

        # Helpers extracted to cut cognitive complexity below 15.
        assert hasattr(discovery, "_collect_workstation_vmx_paths")

    def test_save_discovered_vms_delegates_to_helpers(self):
        from app.services import discovery

        assert hasattr(discovery.DiscoveryService, "_sync_one_discovered_vm") or \
            hasattr(discovery, "_lookup_existing_vm")

    def test_analyze_vm_delegates_to_helpers(self):
        from app.services import analyzer

        assert hasattr(analyzer.AnalyzerService, "_decide_grade")


# ---------------------------------------------------------------------------
# noqa -> NOSONAR — SonarQube suppression convention in service/task/core code
# ---------------------------------------------------------------------------


_BACKEND = Path(__file__).resolve().parent.parent


class TestNoqaToNosonar:
    @pytest.mark.parametrize(
        "module_path",
        [
            "app/main.py",
            "app/core/database.py",
            "app/tasks/migration.py",
            "app/tasks/conversion.py",
            "app/services/adapter/service.py",
            "app/services/migrator/service.py",
            "app/services/converter/service.py",
        ],
    )
    def test_blanket_exception_suppressions_use_nosonar(self, module_path):
        text = (_BACKEND / module_path).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "BLE001" in line:
                assert "# NOSONAR" in line, (
                    f"{module_path}:{lineno} uses `# noqa` for a SonarQube "
                    f"rule — must be `# NOSONAR`"
                )
