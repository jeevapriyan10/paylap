import pytest
from app.schemas import cents_to_usd_str, usd_str_to_cents, ContractCreate, MilestoneCreate


def test_cents_to_usd_str():
    assert cents_to_usd_str(100) == "1.00"
    assert cents_to_usd_str(250) == "2.50"
    assert cents_to_usd_str(5) == "0.05"
    assert cents_to_usd_str(0) == "0.00"
    assert cents_to_usd_str(123456) == "1234.56"


def test_usd_str_to_cents_valid():
    assert usd_str_to_cents("1.00") == 100
    assert usd_str_to_cents("2.50") == 250
    assert usd_str_to_cents("0.05") == 5
    assert usd_str_to_cents("5") == 500
    assert usd_str_to_cents("5.5") == 550
    assert usd_str_to_cents("1234.56") == 123456


def test_usd_str_to_cents_rejects_floats_and_bad_types():
    with pytest.raises(TypeError):
        usd_str_to_cents(2.50)  # Float forbidden!

    with pytest.raises(TypeError):
        usd_str_to_cents(100)

    with pytest.raises(TypeError):
        cents_to_usd_str(2.50)


def test_usd_str_to_cents_rejects_invalid_strings():
    # Negative amounts
    with pytest.raises(ValueError):
        usd_str_to_cents("-5.00")

    # Zero
    with pytest.raises(ValueError):
        usd_str_to_cents("0.00")

    # More than 2 decimal places
    with pytest.raises(ValueError):
        usd_str_to_cents("1.234")

    # Non-numeric garbage
    with pytest.raises(ValueError):
        usd_str_to_cents("abc")

    with pytest.raises(ValueError):
        usd_str_to_cents("1.2.3")


def test_contract_milestones_validation():
    # Valid contract with 2 milestones
    c = ContractCreate(
        title="Build ML Feature",
        buyer_id="buyer-1",
        worker_id="worker-2",
        worker_email="worker@example.com",
        milestones=[
            MilestoneCreate(
                title="M1",
                amount="2.50",
                spec="Spec 1",
                public_tests="def test_1(): pass",
            ),
            MilestoneCreate(
                title="M2",
                amount="1.50",
                spec="Spec 2",
                public_tests="def test_2(): pass",
            ),
        ],
    )
    assert len(c.milestones) == 2
    cents_1 = usd_str_to_cents(c.milestones[0].amount)
    cents_2 = usd_str_to_cents(c.milestones[1].amount)
    total_cents = cents_1 + cents_2
    assert total_cents == 400
    assert cents_to_usd_str(total_cents) == "4.00"


def test_contract_rejects_invalid_milestone_counts():
    # 0 milestones
    with pytest.raises(Exception):
        ContractCreate(
            title="Test",
            buyer_id="b",
            worker_id="w",
            worker_email="w@example.com",
            milestones=[],
        )

    # 4 milestones (max allowed is 3)
    with pytest.raises(Exception):
        ContractCreate(
            title="Test",
            buyer_id="b",
            worker_id="w",
            worker_email="w@example.com",
            milestones=[
                MilestoneCreate(title=f"M{i}", amount="1.00", spec="s", public_tests="t")
                for i in range(4)
            ],
        )
