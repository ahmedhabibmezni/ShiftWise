"""
Tests for the Analyzer service and compatibility rules engine.

Covers:
  - Individual rule logic (pass/fail paths)
  - Feature extraction output shape stability
  - ML model loading and prediction
  - Rules fallback when model is missing
  - Integration: analyze real VMs in DB
  - Idempotency: re-running doesn't mutate protected fields
  - Concurrency: row lock prevents double-write
"""

import pytest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.user import User
from app.models.hypervisor import Hypervisor, HypervisorType, HypervisorStatus
from app.models.virtual_machine import (
    VirtualMachine, VMStatus, CompatibilityStatus, OSType
)
from app.services.compatibility_rules import (
    rule_os_supported, rule_cpu_min,
    rule_memory_min, rule_disk_min, rule_disk_format,
    SEVERITY_BLOCKER, SEVERITY_WARNING,
)
from app.services.feature_extractor import (
    FEATURE_NAMES, extract_vector
)
from app.services.analyzer import AnalyzerService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """In-memory SQLite session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def test_tenant(db_session):
    """Create a test tenant (user)."""
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password="dummy",
        tenant_id="test_tenant",
        is_superuser=False,
    )
    db_session.add(user)
    db_session.commit()
    return user.tenant_id


@pytest.fixture
def test_hypervisor(db_session, test_tenant):
    """Create a test KVM hypervisor."""
    hv = Hypervisor(
        name="test-kvm",
        tenant_id=test_tenant,
        type=HypervisorType.KVM,
        host="qemu+ssh://root@192.168.1.100/system",
        username="root",
        status=HypervisorStatus.ACTIVE,
        total_vms_discovered=0,
    )
    db_session.add(hv)
    db_session.commit()
    return hv


@pytest.fixture
def test_vm_compatible(db_session, test_tenant, test_hypervisor):
    """Create a test VM with COMPATIBLE characteristics."""
    vm = VirtualMachine(
        name="test-ubuntu",
        tenant_id=test_tenant,
        source_hypervisor_id=test_hypervisor.id,
        source_uuid="uuid-compat",
        source_name="test-ubuntu",
        cpu_cores=4,
        memory_mb=8192,
        disk_gb=100,
        os_type=OSType.LINUX,
        os_name="Ubuntu 22.04 LTS",
        os_version="22.04",
        status=VMStatus.DISCOVERED,
        compatibility_status=CompatibilityStatus.UNKNOWN,
        custom_metadata={"power_state": "running"},
    )
    db_session.add(vm)
    db_session.commit()
    return vm


@pytest.fixture
def test_vm_partial(db_session, test_tenant, test_hypervisor):
    """Create a test VM with PARTIAL characteristics (low memory)."""
    vm = VirtualMachine(
        name="test-low-mem",
        tenant_id=test_tenant,
        source_hypervisor_id=test_hypervisor.id,
        source_uuid="uuid-partial",
        source_name="test-low-mem",
        cpu_cores=2,
        memory_mb=768,
        disk_gb=50,
        os_type=OSType.LINUX,
        os_name="CentOS 7",
        os_version="7",
        status=VMStatus.DISCOVERED,
        compatibility_status=CompatibilityStatus.UNKNOWN,
        custom_metadata={"power_state": "stopped"},
    )
    db_session.add(vm)
    db_session.commit()
    return vm


@pytest.fixture
def test_hypervisor_vmware(db_session, test_tenant):
    """Create a test VMware Workstation hypervisor (non-soft — OS rules are hard)."""
    hv = Hypervisor(
        name="test-vmware",
        tenant_id=test_tenant,
        type=HypervisorType.VMWARE_WORKSTATION,
        host="local",
        username="user",
        status=HypervisorStatus.ACTIVE,
        total_vms_discovered=0,
    )
    db_session.add(hv)
    db_session.commit()
    return hv


@pytest.fixture
def test_vm_incompatible(db_session, test_tenant, test_hypervisor_vmware):
    """Create a test VM with INCOMPATIBLE characteristics (unsupported OS on a
    non-soft hypervisor — OS rules emit a hard BLOCKER here)."""
    vm = VirtualMachine(
        name="test-unsupported",
        tenant_id=test_tenant,
        source_hypervisor_id=test_hypervisor_vmware.id,
        source_uuid="uuid-incompat",
        source_name="test-unsupported",
        cpu_cores=1,
        memory_mb=2048,
        disk_gb=30,
        os_type=OSType.OTHER,
        os_name="Solaris 10",
        os_version="10",
        status=VMStatus.DISCOVERED,
        compatibility_status=CompatibilityStatus.UNKNOWN,
        custom_metadata={"power_state": "running"},
    )
    db_session.add(vm)
    db_session.commit()
    return vm


# ---------------------------------------------------------------------------
# Unit Tests — Rules
# ---------------------------------------------------------------------------

class TestRulesEngine:
    """Test individual rules."""

    def test_rule_os_supported_linux_compatible(self):
        vm = {
            "os_type": "linux",
            "os_name": "Ubuntu 22.04 LTS",
            "os_version": "22.04",
            "hypervisor_type": "kvm",
        }
        rule = rule_os_supported(vm)
        assert rule["passed"] is True
        assert rule["id"] == "os_supported"
        assert rule["severity"] == SEVERITY_BLOCKER

    def test_rule_os_supported_linux_unsupported(self):
        vm = {
            "os_type": "linux",
            "os_name": "Ubuntu 16.04",
            "os_version": "16.04",
            "hypervisor_type": "kvm",
        }
        rule = rule_os_supported(vm)
        assert rule["passed"] is False
        assert rule["severity"] == SEVERITY_BLOCKER

    def test_rule_os_supported_hyperv_unknown(self):
        """Hyper-V UNKNOWN OS → WARNING, not BLOCKER."""
        vm = {
            "os_type": "unknown",
            "os_name": "",
            "os_version": "",
            "hypervisor_type": "hyper_v",
        }
        rule = rule_os_supported(vm)
        assert rule["passed"] is False
        assert rule["severity"] == SEVERITY_WARNING

    def test_rule_os_supported_kvm_unknown(self):
        """KVM UNKNOWN OS → WARNING, not BLOCKER."""
        vm = {
            "os_type": "unknown",
            "os_name": "",
            "os_version": "",
            "hypervisor_type": "kvm",
        }
        rule = rule_os_supported(vm)
        assert rule["passed"] is False
        assert rule["severity"] == SEVERITY_WARNING

    def test_rule_cpu_min_pass(self):
        vm = {"cpu_cores": 4}
        rule = rule_cpu_min(vm)
        assert rule["passed"] is True

    def test_rule_cpu_min_fail(self):
        vm = {"cpu_cores": 0}
        rule = rule_cpu_min(vm)
        assert rule["passed"] is False

    def test_rule_memory_min_blocker(self):
        """< 512 MB → BLOCKER."""
        vm = {"memory_mb": 256}
        rule = rule_memory_min(vm)
        assert rule["passed"] is False
        assert rule["severity"] == SEVERITY_BLOCKER

    def test_rule_memory_min_warning(self):
        """512-1023 MB → WARNING."""
        vm = {"memory_mb": 768}
        rule = rule_memory_min(vm)
        assert rule["passed"] is False
        assert rule["severity"] == SEVERITY_WARNING

    def test_rule_memory_min_pass(self):
        """≥ 1024 MB → pass."""
        vm = {"memory_mb": 2048}
        rule = rule_memory_min(vm)
        assert rule["passed"] is True

    def test_rule_disk_min_kvm_zero(self):
        """KVM disk_gb=0 → WARNING (known artefact)."""
        vm = {"disk_gb": 0, "hypervisor_type": "kvm"}
        rule = rule_disk_min(vm)
        assert rule["passed"] is False
        assert rule["severity"] == SEVERITY_WARNING
        assert "qemu-img" in rule["message"]

    def test_rule_disk_format_native(self):
        """QCOW2 → pass."""
        vm = {"disk_format": "qcow2"}
        rule = rule_disk_format(vm)
        assert rule["passed"] is True

    def test_rule_disk_format_convertible(self):
        """VMDK → WARNING."""
        vm = {"disk_format": "vmdk", "hypervisor_type": "vmware_workstation"}
        rule = rule_disk_format(vm)
        assert rule["passed"] is False
        assert rule["severity"] == SEVERITY_WARNING

    def test_rule_disk_format_blocker(self):
        """ISO → BLOCKER."""
        vm = {"disk_format": "iso"}
        rule = rule_disk_format(vm)
        assert rule["passed"] is False
        assert rule["severity"] == SEVERITY_BLOCKER


# ---------------------------------------------------------------------------
# Unit Tests — Feature Extraction
# ---------------------------------------------------------------------------

class TestFeatureExtraction:
    """Test feature extraction shape and stability."""

    def test_feature_vector_shape(self):
        """Vector should have exactly len(FEATURE_NAMES) elements."""
        vm = {
            "cpu_cores": 4,
            "memory_mb": 8192,
            "disk_gb": 100,
            "os_type": "linux",
            "os_name": "Ubuntu 22.04",
            "os_version": "22.04",
            "hypervisor_type": "kvm",
            "custom_metadata": {"power_state": "running"},
        }
        vector = extract_vector(vm)
        assert len(vector) == len(FEATURE_NAMES)
        assert all(isinstance(x, float) for x in vector)

    def test_feature_extraction_consistency(self):
        """Same VM should produce the same vector."""
        vm = {
            "cpu_cores": 4,
            "memory_mb": 8192,
            "disk_gb": 100,
            "os_type": "linux",
            "os_name": "Ubuntu 22.04",
            "os_version": "22.04",
            "hypervisor_type": "kvm",
        }
        v1 = extract_vector(vm)
        v2 = extract_vector(vm)
        assert v1 == v2

    def test_physical_hypervisor_one_hot_column_exists(self):
        """A physical (P2V) source must light up its own one-hot column,
        not collapse to 'other'/'unknown'."""
        assert "hypervisor_type_physical" in FEATURE_NAMES
        from app.services.feature_extractor import rules_features
        feats = rules_features({
            "cpu_cores": 4, "memory_mb": 8192, "disk_gb": 100,
            "os_type": "linux", "os_name": "Debian GNU/Linux", "os_version": "13",
            "hypervisor_type": "physical",
        })
        assert feats["hypervisor_type_physical"] == 1
        assert feats["hypervisor_type_other"] == 0
        assert feats["hypervisor_type_unknown"] == 0

    def test_physical_disk_format_inferred_raw(self):
        """Physical P2V captures raw images → native format, no convert warning."""
        verdict = rule_disk_format({"hypervisor_type": "physical"})
        assert verdict["passed"] is True
        assert "raw" in verdict["message"].lower()


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestAnalyzerIntegration:
    """Integration tests with actual DB and rules."""

    def test_analyze_compatible_vm(self, db_session, test_vm_compatible):
        """Analyze a VM that should be COMPATIBLE."""
        analyzer = AnalyzerService()
        result = analyzer.analyze_vm(db_session, test_vm_compatible.id)

        assert result is not None
        vm = db_session.query(VirtualMachine).filter(
            VirtualMachine.id == test_vm_compatible.id
        ).first()
        assert vm.compatibility_status == CompatibilityStatus.COMPATIBLE
        # Audit C-06: the analyzer must promote the lifecycle status so the VM
        # becomes migration-eligible (can_migrate) — not leave it DISCOVERED.
        assert vm.status == VMStatus.COMPATIBLE
        assert vm.can_migrate is True
        assert vm.compatibility_details is not None
        assert vm.compatibility_details["grade"] == "COMPATIBLE"

    def test_analyze_partial_vm(self, db_session, test_vm_partial):
        """Analyze a VM that should be PARTIAL."""
        analyzer = AnalyzerService()
        result = analyzer.analyze_vm(db_session, test_vm_partial.id)

        assert result is not None
        vm = db_session.query(VirtualMachine).filter(
            VirtualMachine.id == test_vm_partial.id
        ).first()
        assert vm.compatibility_status == CompatibilityStatus.PARTIAL
        # Audit C-06: PARTIAL VMs must also become migration-eligible.
        assert vm.status == VMStatus.PARTIAL
        assert vm.can_migrate is True

    def test_analyze_incompatible_vm(self, db_session, test_vm_incompatible):
        """Analyze a VM that should be INCOMPATIBLE."""
        analyzer = AnalyzerService()
        result = analyzer.analyze_vm(db_session, test_vm_incompatible.id)

        assert result is not None
        vm = db_session.query(VirtualMachine).filter(
            VirtualMachine.id == test_vm_incompatible.id
        ).first()
        assert vm.compatibility_status == CompatibilityStatus.INCOMPATIBLE
        # Audit C-06: INCOMPATIBLE VMs get the INCOMPATIBLE status and stay
        # non-migratable.
        assert vm.status == VMStatus.INCOMPATIBLE
        assert vm.can_migrate is False

    def test_idempotency(self, db_session, test_vm_compatible):
        """Re-running analyze on the same VM should not mutate protected fields."""
        analyzer = AnalyzerService()

        # First analysis
        analyzer.analyze_vm(db_session, test_vm_compatible.id)
        vm1 = db_session.query(VirtualMachine).filter(
            VirtualMachine.id == test_vm_compatible.id
        ).first()
        source_uuid_1 = vm1.source_uuid
        cpu_1 = vm1.cpu_cores

        db_session.refresh(vm1)

        # Second analysis (re-run without force)
        analyzer.analyze_vm(db_session, test_vm_compatible.id, force=False)
        vm2 = db_session.query(VirtualMachine).filter(
            VirtualMachine.id == test_vm_compatible.id
        ).first()

        # Protected fields must not change
        assert vm2.source_uuid == source_uuid_1
        assert vm2.cpu_cores == cpu_1

    def test_force_reanalyze(self, db_session, test_vm_compatible):
        """force=true should re-analyze even if already classified."""
        analyzer = AnalyzerService()

        # Manually set to INCOMPATIBLE
        vm = db_session.query(VirtualMachine).filter(
            VirtualMachine.id == test_vm_compatible.id
        ).first()
        vm.compatibility_status = CompatibilityStatus.INCOMPATIBLE
        db_session.commit()

        # Re-analyze with force=true
        analyzer.analyze_vm(db_session, test_vm_compatible.id, force=True)
        db_session.refresh(vm)

        # Should be back to COMPATIBLE (the actual grade)
        assert vm.compatibility_status == CompatibilityStatus.COMPATIBLE

    def test_rules_fallback_when_model_missing(self, db_session, test_vm_compatible):
        """When model file is missing, use rules engine fallback."""
        # Audit E14 — model loading moved to a process-level cache; force
        # degraded mode by stubbing the cache loader.
        with patch("app.services.analyzer._get_cached_model", return_value=None):
            analyzer = AnalyzerService()
            assert analyzer.model is None

            result = analyzer.analyze_vm(db_session, test_vm_compatible.id)
            assert result is not None

            vm = db_session.query(VirtualMachine).filter(
                VirtualMachine.id == test_vm_compatible.id
            ).first()
            # Should still classify correctly using rules
            assert vm.compatibility_status in (
                CompatibilityStatus.COMPATIBLE,
                CompatibilityStatus.PARTIAL
            )
            # engine should be "rules"
            assert vm.compatibility_details["engine"] == "rules"

    def test_analyze_stats(self, db_session, test_vm_compatible, test_vm_partial, test_vm_incompatible):
        """Test stats aggregation."""
        analyzer = AnalyzerService()

        # Analyze all three VMs
        analyzer.analyze_vm(db_session, test_vm_compatible.id)
        analyzer.analyze_vm(db_session, test_vm_partial.id)
        analyzer.analyze_vm(db_session, test_vm_incompatible.id)

        stats = analyzer.get_stats(db_session)
        assert stats["compatible"] == 1
        assert stats["partial"] == 1
        assert stats["incompatible"] == 1

    def test_batch_analyze(self, db_session, test_vm_compatible, test_vm_partial):
        """Test batch analysis."""
        analyzer = AnalyzerService()
        result = analyzer.analyze_batch(
            db_session,
            [test_vm_compatible.id, test_vm_partial.id],
            force=False
        )

        assert result["total"] == 2
        assert result["analyzed"] == 2
        assert result["failed"] == 0
        assert len(result["results"]) == 2

    def test_batch_cap_enforced(self, db_session):
        """Batch cap of 20 should be enforced."""
        analyzer = AnalyzerService()
        vm_ids = list(range(1, 51))  # 50 IDs

        result = analyzer.analyze_batch(db_session, vm_ids)
        # Only 20 should be processed
        assert len(result["results"]) <= 20

    def test_model_grade_uses_model_class_order(self, db_session, test_vm_compatible):
        """Audit C-11: the model grade must come from model.classes_, not a
        hard-coded label tuple — sklearn orders classes_ alphabetically, so a
        hard-coded ('COMPATIBLE','PARTIAL','INCOMPATIBLE') tuple mislabels."""
        class _FakeModel:
            classes_ = ["COMPATIBLE", "INCOMPATIBLE", "PARTIAL"]

            def predict_proba(self, _x):
                return [[0.05, 0.05, 0.90]]  # argmax -> index 2

        analyzer = AnalyzerService()
        analyzer.model = _FakeModel()
        analyzer.threshold = 0.0  # force the model branch

        analyzer.analyze_vm(db_session, test_vm_compatible.id)
        vm = db_session.query(VirtualMachine).filter(
            VirtualMachine.id == test_vm_compatible.id
        ).first()

        # classes_[2] is "PARTIAL"; the bug read labels[2] == "INCOMPATIBLE".
        assert vm.compatibility_details["model_grade"] == "PARTIAL"
        assert vm.compatibility_details["engine"] == "model"


def test_analyze_stores_recommended_strategy():
    from app.services import analyzer as analyzer_mod
    from app.services.strategy import recommend_strategy
    from app.models.migration import MigrationStrategy

    # The pure mapping is the source of truth for the value the analyzer stores.
    assert recommend_strategy(score=100, has_blocker=False) == MigrationStrategy.DIRECT
    # Contract: analyze_vm writes 'recommended_strategy' into compatibility_details.
    assert "recommended_strategy" in analyzer_mod.CompatibilityAnalyzer._details_keys()
