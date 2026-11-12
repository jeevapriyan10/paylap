from typing import Any, Dict, List


class BuyerAgent:
    """Simulated buyer agent that posts milestone contracts and defines task requirements."""

    def __init__(self, buyer_id: str = "buyer_arena_agent"):
        self.buyer_id = buyer_id

    def create_contract_payload(
        self,
        scenario_name: str,
        title: str,
        worker_id: str,
        worker_email: str = "worker@arena.ai",
        budget_usd: str = "5.00",
        milestones: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Construct a contract creation payload for the specified arena scenario."""
        if milestones is None:
            milestones = [
                {
                    "title": "Calculate Exponential Backoff",
                    "amount": budget_usd,
                    "spec": "Implement calculate_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float",
                    "public_tests": (
                        "from solution import calculate_backoff\n"
                        "def test_initial(): assert calculate_backoff(1, 1.0, 60.0) == 1.0\n"
                        "def test_second(): assert calculate_backoff(2, 1.0, 60.0) == 2.0\n"
                    ),
                    "hidden_tests": (
                        "from solution import calculate_backoff\n"
                        "def test_cap(): assert calculate_backoff(10, 1.0, 60.0) == 60.0\n"
                        "def test_zero(): assert calculate_backoff(0, 1.0, 60.0) == 1.0\n"
                    ),
                }
            ]

        return {
            "title": title,
            "buyer_id": self.buyer_id,
            "worker_id": worker_id,
            "worker_email": worker_email,
            "max_attempts": 2,
            "milestones": milestones,
        }
