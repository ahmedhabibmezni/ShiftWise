from app.models.migration import MigrationStrategy
from app.api.v1.migrations import _auto_strategy_for_vm


class _VM:
    def __init__(self, details):
        self.compatibility_details = details


def test_auto_strategy_reads_recommended_from_details():
    vm = _VM({"recommended_strategy": "hybrid"})
    assert _auto_strategy_for_vm(vm) == MigrationStrategy.HYBRID


def test_auto_strategy_defaults_to_auto_when_missing():
    assert _auto_strategy_for_vm(_VM(None)) == MigrationStrategy.AUTO
    assert _auto_strategy_for_vm(_VM({})) == MigrationStrategy.AUTO


def test_auto_strategy_invalid_value_falls_back_to_auto():
    assert _auto_strategy_for_vm(_VM({"recommended_strategy": "NONSENSE"})) == MigrationStrategy.AUTO
