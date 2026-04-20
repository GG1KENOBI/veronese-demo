"""Data-loading layer. Single entry point for all parquets.

Reads from `data/processed/scenarios/{key}/` when a scenario is selected
and precomputed; otherwise falls back to `data/processed/` directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import pandas as pd
import streamlit as st

from app.scenarios import DATA_PROC, scenario_dir, scenario_exists

# Frames that live in the scenario-specific dir
_SCENARIO_SCOPED = {
    "production_plan.parquet",
    "inventory_trajectory.parquet",
    "shadow_prices.parquet",
    "cost_breakdown.parquet",
    "schedule.parquet",
    "schedule_summary.parquet",
    "oee_results.parquet",
    "oee_waterfall.parquet",
    "six_big_losses.parquet",
    "changeover_breakdown.parquet",
}
# Frames that never change with scenarios (history, catalog, forecasts)
_GLOBAL = {
    "demand_history.parquet",
    "sku_catalog.parquet",
    "forecasts.parquet",
    "cv_metrics.parquet",
}


@st.cache_data(ttl=3600, show_spinner=False)
def _read_parquet(path_str: str, _mtime: float) -> pd.DataFrame:
    """Cache-keyed on mtime so file replacements invalidate the entry."""
    p = Path(path_str)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def load_frame(filename: str, scenario_key: str = "base") -> pd.DataFrame:
    """Load a single parquet, honoring the selected scenario dir.

    `scenario_key` is used only for files in _SCENARIO_SCOPED. For global
    frames (history, catalog, forecasts) the key is ignored.
    """
    if filename in _SCENARIO_SCOPED:
        sc_dir = scenario_dir(scenario_key)
        candidate = sc_dir / filename
        if candidate.exists():
            return _read_parquet(str(candidate), candidate.stat().st_mtime)
    fallback = DATA_PROC / filename
    if fallback.exists():
        return _read_parquet(str(fallback), fallback.stat().st_mtime)
    return pd.DataFrame()


@dataclass
class DemoData:
    """All frames the UI needs, bundled."""

    # Global (same for every scenario)
    hist: pd.DataFrame
    cat: pd.DataFrame
    forecasts: pd.DataFrame
    cv_metrics: pd.DataFrame
    # Scenario-scoped
    plan: pd.DataFrame
    inv: pd.DataFrame
    sp: pd.DataFrame
    cost: pd.DataFrame
    sched: pd.DataFrame
    sched_sum: pd.DataFrame
    oee_res: pd.DataFrame
    oee_wf: pd.DataFrame
    six: pd.DataFrame
    bd: pd.DataFrame

    @property
    def scheduled_precomputed(self) -> bool:
        """True if the active scenario's parquets all exist precomputed."""
        return not self.sched.empty


def load_all(scenario_key: str = "base") -> DemoData:
    """Load every dataframe the demo needs, in one call."""
    return DemoData(
        hist=load_frame("demand_history.parquet"),
        cat=load_frame("sku_catalog.parquet"),
        forecasts=load_frame("forecasts.parquet"),
        cv_metrics=load_frame("cv_metrics.parquet"),
        plan=load_frame("production_plan.parquet", scenario_key),
        inv=load_frame("inventory_trajectory.parquet", scenario_key),
        sp=load_frame("shadow_prices.parquet", scenario_key),
        cost=load_frame("cost_breakdown.parquet", scenario_key),
        sched=load_frame("schedule.parquet", scenario_key),
        sched_sum=load_frame("schedule_summary.parquet", scenario_key),
        oee_res=load_frame("oee_results.parquet", scenario_key),
        oee_wf=load_frame("oee_waterfall.parquet", scenario_key),
        six=load_frame("six_big_losses.parquet", scenario_key),
        bd=load_frame("changeover_breakdown.parquet", scenario_key),
    )


# ─────────────────────────────────────────────────────────────────────
# Curated SKU picks for forecast tab (instead of exposing all 29)
# ─────────────────────────────────────────────────────────────────────
CURATED_FORECAST_SKUS = [
    # Hand-picked to span "works great / promo-heavy / new uncertain"
    ("VRN_GROUND_DARK_250", "🟢 Стабильный товар (молотый тёмный)", "clean_seasonality"),
    ("VRN_GROUND_FLAV_IRISH_250", "🟡 Промо-пик (ароматизированный Irish)", "promo_sensitive"),
    ("VRN_GROUND_DECAF_250", "🟠 Нишевый товар (без кофеина)", "sparse_history"),
]


def available_forecast_skus(cat: pd.DataFrame, forecasts: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Return curated list filtered to SKUs that actually have data."""
    if cat.empty or forecasts.empty:
        return []
    existing = set(cat["sku_id"].tolist())
    return [t for t in CURATED_FORECAST_SKUS if t[0] in existing]
