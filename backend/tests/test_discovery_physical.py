from app.models.hypervisor import HypervisorType


def test_physical_hypervisor_type_exists():
    assert HypervisorType.PHYSICAL.value == "physical"
    # SQLAlchemy binds the member NAME (uppercase) to the PG enum label.
    assert HypervisorType.PHYSICAL.name == "PHYSICAL"
