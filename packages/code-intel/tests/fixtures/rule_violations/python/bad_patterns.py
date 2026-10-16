"""Python file with intentional rule violations for testing.

Each violation is annotated with # expect: <rule-id> on the same line.
The test runner verifies every expect annotation produces a finding,
and no unexpected findings appear.
"""
import logging
from utils import *  # expect: no-star-import

logger = logging.getLogger(__name__)


def process_items(items: list, config: dict) -> None:
    """Process items with several bad patterns."""
    # Team preference: no print debugging
    print(f"Starting with {len(items)} items")  # expect: no-print-debugging

    # Team preference: no bare dict access
    api_key = config['api_key']  # expect: no-bare-dict-access

    # Team preference: no f-string in logger
    logger.info(f"Using key {api_key[:4]}...")  # expect: no-string-format-logging

    for item in items:
        print(item.name)  # expect: no-print-debugging
        status = config['default_status']  # expect: no-bare-dict-access


def clean_calculate_total(prices: list[float]) -> float:
    """Clean function — should produce NO findings."""
    total = sum(prices)
    logger.debug("Calculated total: %s", total)
    return total


def clean_load_config(path: str) -> dict:
    """Another clean function."""
    with open(path) as f:
        return {}
