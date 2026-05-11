"""
Tests for the per-tenant ResourceQuota helper.

Covers:
- skip when no MIGRATOR_QUOTA_* dimension is configured (back-compat)
- quota created on a fresh tenant namespace
- quota also applied on an existing namespace (retrofit)
- existing quota is left untouched (idempotent)
- 409 on quota create is silently ignored (concurrent worker race)
- 403 on quota create → ERR_MIG_NAMESPACE_FORBIDDEN
- only populated dimensions land in the `hard` block
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kubernetes.client.rest import ApiException

from app.services.migrator.errors import MigratorError


@pytest.fixture(autouse=True)
def _reset_quota_settings(monkeypatch):
    """Default every quota dimension to empty before each test so cases
    have to opt-in explicitly. Keeps the matrix readable."""
    from app.core import config as _config

    for attr in (
        "MIGRATOR_QUOTA_REQUESTS_CPU",
        "MIGRATOR_QUOTA_REQUESTS_MEMORY",
        "MIGRATOR_QUOTA_LIMITS_CPU",
        "MIGRATOR_QUOTA_LIMITS_MEMORY",
        "MIGRATOR_QUOTA_REQUESTS_STORAGE",
        "MIGRATOR_QUOTA_PVC_COUNT",
        "MIGRATOR_QUOTA_POD_COUNT",
    ):
        monkeypatch.setattr(_config.settings, attr, "")


class TestApplyDefaultResourceQuota:

    def test_skips_entirely_when_no_dimension_is_configured(self):
        """Back-compat: empty config → no API call, no quota object."""
        from app.services.migrator.namespace import apply_default_resource_quota

        fake_kv = MagicMock()
        apply_default_resource_quota(fake_kv, "shiftwise-tnt1", "tnt1")

        fake_kv.core_api.read_namespaced_resource_quota.assert_not_called()
        fake_kv.core_api.create_namespaced_resource_quota.assert_not_called()

    def test_creates_quota_when_absent(self, monkeypatch):
        from app.core import config as _config
        from app.services.migrator.namespace import apply_default_resource_quota

        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_CPU", "10")
        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_MEMORY", "32Gi")
        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_PVC_COUNT", "20")

        fake_kv = MagicMock()
        fake_kv.core_api.read_namespaced_resource_quota.side_effect = ApiException(status=404)

        apply_default_resource_quota(fake_kv, "shiftwise-tnt1", "tnt1")

        fake_kv.core_api.create_namespaced_resource_quota.assert_called_once()
        kwargs = fake_kv.core_api.create_namespaced_resource_quota.call_args.kwargs
        assert kwargs["namespace"] == "shiftwise-tnt1"
        body = kwargs["body"]
        assert body.metadata.name == "shiftwise-default-quota"
        assert body.metadata.labels["app.shiftwise.io/tenant"] == "tnt1"
        # Only the dimensions we set should appear.
        assert body.spec.hard == {
            "requests.cpu": "10",
            "requests.memory": "32Gi",
            "persistentvolumeclaims": "20",
        }

    def test_existing_quota_is_a_noop(self, monkeypatch):
        """If the quota object is already there, leave it alone — admins
        may have tuned it manually and we shouldn't clobber that."""
        from app.core import config as _config
        from app.services.migrator.namespace import apply_default_resource_quota

        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_CPU", "10")

        fake_kv = MagicMock()
        fake_kv.core_api.read_namespaced_resource_quota.return_value = MagicMock()

        apply_default_resource_quota(fake_kv, "shiftwise-tnt1", "tnt1")

        fake_kv.core_api.create_namespaced_resource_quota.assert_not_called()

    def test_409_on_create_is_silently_ignored(self, monkeypatch):
        """Two workers racing on the same fresh namespace: one wins, the
        other gets 409 and treats it as success."""
        from app.core import config as _config
        from app.services.migrator.namespace import apply_default_resource_quota

        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_CPU", "10")

        fake_kv = MagicMock()
        fake_kv.core_api.read_namespaced_resource_quota.side_effect = ApiException(status=404)
        fake_kv.core_api.create_namespaced_resource_quota.side_effect = ApiException(status=409)

        apply_default_resource_quota(fake_kv, "shiftwise-tnt1", "tnt1")  # no raise

    def test_403_on_create_raises_namespace_forbidden(self, monkeypatch):
        from app.core import config as _config
        from app.services.migrator.namespace import apply_default_resource_quota

        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_CPU", "10")

        fake_kv = MagicMock()
        fake_kv.core_api.read_namespaced_resource_quota.side_effect = ApiException(status=404)
        fake_kv.core_api.create_namespaced_resource_quota.side_effect = ApiException(status=403)

        with pytest.raises(MigratorError) as exc:
            apply_default_resource_quota(fake_kv, "shiftwise-tnt1", "tnt1")
        assert exc.value.code == "ERR_MIG_NAMESPACE_FORBIDDEN"

    def test_503_on_create_is_retryable(self, monkeypatch):
        from app.core import config as _config
        from app.services.migrator.namespace import apply_default_resource_quota

        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_CPU", "10")

        fake_kv = MagicMock()
        fake_kv.core_api.read_namespaced_resource_quota.side_effect = ApiException(status=404)
        fake_kv.core_api.create_namespaced_resource_quota.side_effect = ApiException(status=503)

        with pytest.raises(MigratorError) as exc:
            apply_default_resource_quota(fake_kv, "shiftwise-tnt1", "tnt1")
        assert exc.value.code == "ERR_MIG_K8S_TIMEOUT"
        assert exc.value.is_retryable is True

    def test_403_on_quota_read_raises_forbidden(self, monkeypatch):
        """If the worker SA can't even read quotas, fail loudly so the
        operator fixes RBAC before the next migration kicks off."""
        from app.core import config as _config
        from app.services.migrator.namespace import apply_default_resource_quota

        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_CPU", "10")

        fake_kv = MagicMock()
        fake_kv.core_api.read_namespaced_resource_quota.side_effect = ApiException(status=403)

        with pytest.raises(MigratorError) as exc:
            apply_default_resource_quota(fake_kv, "shiftwise-tnt1", "tnt1")
        assert exc.value.code == "ERR_MIG_NAMESPACE_FORBIDDEN"


class TestEnsureTenantNamespaceAppliesQuota:
    """Integration of apply_default_resource_quota inside the namespace flow.

    These tests verify the public entrypoint (`ensure_tenant_namespace`)
    delegates to the quota helper on every branch (create-new,
    already-exists, concurrent-create) so day-1 and retrofit cases both
    end up quotaed.
    """

    def test_quota_applied_after_namespace_create(self, monkeypatch):
        from app.core import config as _config
        from app.services.migrator.namespace import ensure_tenant_namespace

        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_CPU", "10")

        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.side_effect = ApiException(status=404)
        fake_kv.core_api.read_namespaced_resource_quota.side_effect = ApiException(status=404)

        ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")

        fake_kv.core_api.create_namespace.assert_called_once()
        fake_kv.core_api.create_namespaced_resource_quota.assert_called_once()

    def test_quota_applied_on_existing_namespace_retrofit(self, monkeypatch):
        """A tenant created before quotas were configured still gets
        quotaed on the next migration."""
        from app.core import config as _config
        from app.services.migrator.namespace import ensure_tenant_namespace

        monkeypatch.setattr(_config.settings, "MIGRATOR_QUOTA_REQUESTS_CPU", "10")

        fake_kv = MagicMock()
        fake_kv.core_api.read_namespace.return_value = MagicMock()
        fake_kv.core_api.read_namespaced_resource_quota.side_effect = ApiException(status=404)

        ensure_tenant_namespace(fake_kv, "shiftwise-tnt1", "tnt1")

        fake_kv.core_api.create_namespace.assert_not_called()
        fake_kv.core_api.create_namespaced_resource_quota.assert_called_once()
