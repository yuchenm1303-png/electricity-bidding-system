"""JSON API and static React frontend for the PowerBid product workspace.

The original powerbid algorithms remain the single source of truth.
"""
from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.pmss_api import router as pmss_router
from powerbid.adapters.pypsa_engine import PyPSAClearingEngine
from powerbid.clearing.uniform_price import UniformPriceClearingEngine
from powerbid.models import MarketScenario, Offer
from powerbid.optimizer import GridSearchBidOptimizer, price_grid
from powerbid.risk import RiskAwareBidOptimizer, build_stress_cases
from powerbid.scenario_io import load_scenario

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"

app = FastAPI(
    title="PowerBid Studio API",
    description="Local teaching and research simulation. Not a real-time trading service.",
    docs_url=None,
    redoc_url=None,
)


app.include_router(pmss_router)


class OfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    unit_id: str = Field(min_length=1, max_length=48)
    quantity_mw: float = Field(ge=0, le=1_000_000)
    bid_price: float = Field(ge=0, le=1_000_000)
    marginal_cost: float = Field(ge=0, le=1_000_000)


class OptimizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    demand_mw: float = Field(ge=0, le=1_000_000)
    interval_hours: float = Field(gt=0, le=24)
    target_unit_id: str = Field(min_length=1, max_length=48)
    offers: list[OfferInput] = Field(min_length=1, max_length=100)
    start: float = Field(ge=0, le=1_000_000)
    stop: float = Field(ge=0, le=1_000_000)
    step: float = Field(gt=0, le=1_000_000)
    mode: Literal["single", "risk"] = "single"
    engine: Literal["uniform", "pypsa"] = "uniform"
    demand_uncertainty: float = Field(default=0.15, ge=0, le=0.4)
    competitor_uncertainty: float = Field(default=0.15, ge=0, le=0.4)
    risk_aversion: float = Field(default=0.35, ge=0, le=1)
    tail_fraction: float = Field(default=0.25, gt=0, le=1)

    @model_validator(mode="after")
    def validate_case(self) -> OptimizationInput:
        if self.start > self.stop:
            raise ValueError("最低报价不能高于最高报价")
        if (self.stop - self.start) / self.step > 500:
            raise ValueError("候选报价超过 501 个，请增大报价步长")
        ids = [offer.unit_id.strip() for offer in self.offers]
        if len(ids) != len(set(ids)):
            raise ValueError("机组编号必须唯一")
        if self.target_unit_id not in ids:
            raise ValueError("目标机组必须存在于机组清单")
        if not all(math.isfinite(v) for v in (self.start, self.stop, self.step)):
            raise ValueError("价格必须是有效数字")
        return self


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": "teaching-simulation"}


@app.get("/api/scenario")
def scenario() -> dict[str, object]:
    sample = load_scenario(ROOT / "data" / "sample_market.json")
    return {
        "name": sample.name,
        "description": sample.description,
        "data_source": sample.data_source,
        "demand_mw": sample.demand_mw,
        "interval_hours": sample.interval_hours,
        "target_unit_id": sample.target_unit_id,
        "offers": [asdict(item) for item in sample.offers],
    }


@app.post("/api/optimize")
def optimize(payload: OptimizationInput) -> dict[str, object]:
    try:
        case = MarketScenario(
            name="PowerBid Studio interactive simulation",
            demand_mw=payload.demand_mw,
            interval_hours=payload.interval_hours,
            target_unit_id=payload.target_unit_id,
            offers=tuple(Offer(**offer.model_dump()) for offer in payload.offers),
            data_source="synthetic",
        )
        engine = (
            PyPSAClearingEngine()
            if payload.engine == "pypsa"
            else UniformPriceClearingEngine()
        )
        prices = price_grid(payload.start, payload.stop, payload.step)
        if payload.mode == "risk":
            variants = build_stress_cases(
                case,
                demand_multipliers=(
                    1 - payload.demand_uncertainty,
                    1.0,
                    1 + payload.demand_uncertainty,
                ),
                competitor_bid_multipliers=(
                    1 - payload.competitor_uncertainty,
                    1.0,
                    1 + payload.competitor_uncertainty,
                ),
            )
            result = RiskAwareBidOptimizer(
                engine,
                risk_aversion=payload.risk_aversion,
                tail_fraction=payload.tail_fraction,
                min_feasible_probability=1.0,
            ).optimize(variants, prices)
        else:
            result = GridSearchBidOptimizer(engine).optimize(case, prices)
    except (ValueError, ImportError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "mode": payload.mode,
        "target_unit_id": result.target_unit_id,
        "best": asdict(result.best),
        "trials": [asdict(trial) for trial in result.trials],
        "count": len(result.trials),
        "data_source": "synthetic",
    }


# The Vite public/ cursor assets are copied into dist/ at its root.
# Serve these exact known files as assets rather than returning SPA index HTML.
# Keeping the allowlist explicit avoids exposing other server-side files.
_CURSOR_ASSETS = {
    "listing-studio-download-cursor-v2.js": "text/javascript",
    "listing-studio-cursor-reference-v1.css": "text/css",
}


def _cursor_asset(filename: str) -> FileResponse:
    if filename not in _CURSOR_ASSETS:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset = DIST / filename
    if not asset.is_file():
        raise HTTPException(status_code=404, detail="Cursor asset not available")
    return FileResponse(
        asset,
        media_type=_CURSOR_ASSETS[filename],
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/listing-studio-download-cursor-v2.js", include_in_schema=False)
def listing_cursor_script() -> FileResponse:
    return _cursor_asset("listing-studio-download-cursor-v2.js")


@app.get("/listing-studio-cursor-reference-v1.css", include_in_schema=False)
def listing_cursor_css() -> FileResponse:
    return _cursor_asset("listing-studio-cursor-reference-v1.css")


@app.get("/")
def index() -> FileResponse:
    return _index()


def _index() -> FileResponse:
    if not (DIST / "index.html").exists():
        raise HTTPException(status_code=503, detail="React frontend has not been built")
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa_fallback(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        return _index()
