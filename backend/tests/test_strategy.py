from app.models.migration import MigrationStrategy
from app.services.strategy import recommend_strategy


def test_blocker_returns_none():
    assert recommend_strategy(score=65, has_blocker=True) is None
    assert recommend_strategy(score=100, has_blocker=True) is None


def test_direct_band():
    assert recommend_strategy(score=100, has_blocker=False) == MigrationStrategy.DIRECT
    assert recommend_strategy(score=90, has_blocker=False) == MigrationStrategy.DIRECT


def test_conversion_band():
    assert recommend_strategy(score=89, has_blocker=False) == MigrationStrategy.CONVERSION
    assert recommend_strategy(score=70, has_blocker=False) == MigrationStrategy.CONVERSION


def test_hybrid_band():
    assert recommend_strategy(score=69, has_blocker=False) == MigrationStrategy.HYBRID
    assert recommend_strategy(score=50, has_blocker=False) == MigrationStrategy.HYBRID


def test_cold_band():
    assert recommend_strategy(score=49, has_blocker=False) == MigrationStrategy.COLD
    assert recommend_strategy(score=0, has_blocker=False) == MigrationStrategy.COLD
