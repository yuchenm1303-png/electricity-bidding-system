"""EX-POST spatial shape of PMSS-vs-local DC nodal price residuals.

For each hour, removing the median signed residual minimizes MAE over one
FREE constant shift shared by all observed nodes. That shift is fitted to
observed HISTORICAL prices, and is NEVER a deployable price correction,
PMSS cap, true settlement rule, or a forward predictor.

We intentionally expose NO node identities, raw node prices or bids.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import Sequence


@dataclass(frozen=True, slots=True)
class PriceResidualShape:
    compared_nodes: int
    signed_median_shift: float | None
    raw_mae: float | None
    centered_mae: float | None
    residual_range: float | None
    uniform_shift_within_tolerance: bool | None


def price_residual_shape(
    simulated_minus_observed: Sequence[float],
    *,
    uniform_tolerance: float = 1e-5,
) -> PriceResidualShape:
    """Describe an hour, with >=2 observed buses for spatial interpretation.

    One observed node cannot identify a common-mode shift vs spatial spread.
    Its raw MAE is reported but the median and corrected MAE are intentionally
    None, rather than manufacturing an apparently perfect 0-MAE fit.
    """
    if (
        type(uniform_tolerance) not in (int, float)
        or not isfinite(uniform_tolerance)
        or not 0 <= uniform_tolerance <= 0.1
    ):
        raise ValueError("Uniform residual tolerance must be between 0 and 0.1")
    if isinstance(simulated_minus_observed, (str, bytes)):
        raise ValueError("Expected per-node signed numeric residuals")
    try:
        values = tuple(float(v) for v in simulated_minus_observed)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid PMSS nodal price residual") from exc
    if any(not isfinite(v) for v in values):
        raise ValueError("Observed nodal price residual must be finite")
    if len(values) > 150:
        raise ValueError("Too many DC nodes")
    n = len(values)
    raw_mae = sum(abs(v) for v in values) / n if n else None
    if n < 2:
        return PriceResidualShape(n, None, raw_mae, None, None, None)
    shift = float(median(values))
    centered = sum(abs(v-shift) for v in values) / n
    width = max(values)-min(values)
    return PriceResidualShape(
        compared_nodes=n,
        signed_median_shift=shift,
        raw_mae=raw_mae,
        centered_mae=centered,
        residual_range=width,
        uniform_shift_within_tolerance=width <= uniform_tolerance,
    )
