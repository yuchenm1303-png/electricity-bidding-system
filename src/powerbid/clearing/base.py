from __future__ import annotations

from typing import Protocol

from powerbid.models import ClearingResult, MarketScenario


class ClearingEngine(Protocol):
    """Pluggable market-clearing interface.

    A clearing engine receives the same MarketScenario used by the bidding
    optimizer and returns normalized results. This lets us swap the built-in
    teaching engine for PyPSA or the teacher-provided simulator later without
    changing the bidding logic.
    """

    def clear(self, scenario: MarketScenario) -> ClearingResult:
        ...
