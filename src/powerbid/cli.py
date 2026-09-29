from __future__ import annotations

import argparse
from pathlib import Path

from powerbid.adapters.pypsa_engine import PyPSAClearingEngine
from powerbid.clearing.uniform_price import UniformPriceClearingEngine
from powerbid.optimizer import GridSearchBidOptimizer, price_grid
from powerbid.scenario_io import load_scenario


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PowerBid Lab bidding optimizer")
    parser.add_argument("scenario", type=Path, help="Path to a scenario JSON file")
    parser.add_argument("--start", type=float, default=180.0, help="Minimum bid price")
    parser.add_argument("--stop", type=float, default=400.0, help="Maximum bid price")
    parser.add_argument("--step", type=float, default=10.0, help="Bid price step")
    parser.add_argument(
        "--engine",
        choices=("builtin", "pypsa"),
        default="builtin",
        help="Market-clearing engine",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    scenario = load_scenario(args.scenario)
    engine = PyPSAClearingEngine() if args.engine == "pypsa" else UniformPriceClearingEngine()
    optimizer = GridSearchBidOptimizer(engine)
    result = optimizer.optimize(scenario, price_grid(args.start, args.stop, args.step))

    print(f"Scenario: {scenario.name}")
    print(f"Target:   {result.target_unit_id}")
    print()
    print(f"{'Bid':>10} {'Clear':>10} {'Accepted':>12} {'Profit':>14}")
    print("-" * 50)
    for trial in result.trials:
        clear = "-" if trial.clearing_price is None else f"{trial.clearing_price:.2f}"
        print(
            f"{trial.bid_price:>10.2f} {clear:>10} "
            f"{trial.accepted_mw:>12.2f} {trial.profit:>14.2f}"
        )

    best = result.best
    print("\nRecommended bid")
    print(f"  price:          {best.bid_price:.2f}")
    print(f"  clearing price: {best.clearing_price:.2f}")
    print(f"  accepted MW:    {best.accepted_mw:.2f}")
    print(f"  profit:         {best.profit:.2f}")


if __name__ == "__main__":
    main()
