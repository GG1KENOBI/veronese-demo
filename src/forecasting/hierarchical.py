"""
Demand forecasting pipeline.

- StatsForecast ensemble (AutoARIMA, AutoETS, Theta, SeasonalNaive, Naive)
  trained in parallel across all SKUs
- Hierarchical reconciliation (MinTrace-shrink) for coherent forecasts at
  Total / Form / Brand / SKU levels
- Walk-forward cross-validation with WAPE, MAPE, RMSE

Reads:   data/processed/demand_history.parquet, hierarchy.parquet
Writes:  data/processed/forecasts.parquet
         data/processed/cv_metrics.parquet
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from hierarchicalforecast.core import HierarchicalReconciliation
from hierarchicalforecast.methods import BottomUp, MinTrace
from hierarchicalforecast.utils import aggregate
from statsforecast import StatsForecast
from statsforecast.models import (
    AutoARIMA,
    AutoETS,
    HistoricAverage,
    Naive,
    SeasonalNaive,
    Theta,
)

ROOT = Path(__file__).resolve().parents[2]
DATA_PROC = ROOT / "data" / "processed"


def load_inputs():
    hist = pd.read_parquet(DATA_PROC / "demand_history.parquet")
    hier = pd.read_parquet(DATA_PROC / "hierarchy.parquet")
    cat = pd.read_parquet(DATA_PROC / "sku_catalog.parquet")
    # Enrich hist with hierarchy fields
    hist = hist.merge(hier[["sku_id", "brand", "form"]], left_on="unique_id", right_on="sku_id").drop(columns=["sku_id"])
    return hist, hier, cat


def build_hierarchical_Ydf(hist: pd.DataFrame, freq: str = "W"):
    """Aggregate daily history into weekly series and build Y_df, S, tags.

    Daily retail data has two seasonalities (weekly + yearly). Training on
    DAILY with season_length=7 only captures weekly cycle and misses yearly
    peaks (December New Year, holidays). For the demo, we aggregate to WEEKLY
    and use season_length=52 to capture yearly patterns — this gives a
    forecast that actually reproduces the December spike visible in history.
    """
    base = hist[["ds", "form", "brand", "unique_id", "y"]].rename(columns={"unique_id": "sku"})
    if freq.upper().startswith("W"):
        base["ds"] = pd.to_datetime(base["ds"])
        # Floor to week start (Monday) so weeks align across all series
        base["ds"] = base["ds"] - pd.to_timedelta((base["ds"].dt.dayofweek), unit="D")
        base = base.groupby(["ds", "form", "brand", "sku"], as_index=False)["y"].sum()
    spec = [["form"], ["form", "brand"], ["form", "brand", "sku"]]
    Y_df, S_df, tags = aggregate(base, spec)
    return Y_df, S_df, tags


def run_base_forecasts(Y_df: pd.DataFrame, h: int = 12, freq: str = "W", levels=(80, 95)):
    """Fit ensemble of statistical models on each (weekly) series.

    season_length=52 captures yearly seasonality (Russian coffee seasonality:
    Sep-Feb peak, summer dip, December New Year spike).
    """
    season = 52 if freq.upper().startswith("W") else 7
    models = [
        AutoARIMA(season_length=season),
        AutoETS(season_length=season),
        Theta(season_length=season),
        SeasonalNaive(season_length=season),
        HistoricAverage(),
    ]
    sf = StatsForecast(models=models, freq=freq, n_jobs=-1, fallback_model=Naive())
    Y_hat_df = sf.forecast(df=Y_df, h=h, level=list(levels), fitted=True)
    Y_fitted_df = sf.forecast_fitted_values()
    return sf, Y_hat_df, Y_fitted_df


def reconcile(Y_hat_df: pd.DataFrame, Y_fitted_df: pd.DataFrame, S_df: pd.DataFrame, tags: dict):
    """Apply multiple reconcilers: BottomUp, MinTrace-shrink, MinTrace-OLS.

    Y_fitted_df must contain: unique_id, ds, y, and model columns (in-sample preds).
    """
    reconcilers = [
        BottomUp(),
        MinTrace(method="mint_shrink"),
        MinTrace(method="ols"),
    ]
    hrec = HierarchicalReconciliation(reconcilers=reconcilers)
    Y_rec = hrec.reconcile(Y_hat_df=Y_hat_df, Y_df=Y_fitted_df, S_df=S_df, tags=tags)
    return Y_rec


def cross_validate(Y_df: pd.DataFrame, h: int = 4, n_windows: int = 4, step_size: int = 4, freq: str = "W"):
    """Walk-forward CV on bottom-level SKU series only (weekly)."""
    bottom_mask = Y_df["unique_id"].str.count("/") == 2
    bottom = Y_df[bottom_mask].copy()
    season = 52 if freq.upper().startswith("W") else 7
    models = [
        AutoARIMA(season_length=season),
        AutoETS(season_length=season),
        Theta(season_length=season),
        SeasonalNaive(season_length=season),
    ]
    sf = StatsForecast(models=models, freq=freq, n_jobs=-1, fallback_model=Naive())
    cv = sf.cross_validation(df=bottom, h=h, step_size=step_size, n_windows=n_windows)
    cv = cv.reset_index() if "unique_id" not in cv.columns else cv
    return cv


def compute_cv_metrics(cv: pd.DataFrame) -> pd.DataFrame:
    """Aggregate CV results into per-model metrics."""
    model_cols = [c for c in cv.columns if c not in ("unique_id", "ds", "cutoff", "y")]
    rows = []
    for m in model_cols:
        err = cv[m] - cv["y"]
        abs_err = err.abs()
        denom = cv["y"].abs().sum()
        wape = 100 * abs_err.sum() / denom if denom > 0 else np.nan
        mape = 100 * (abs_err / cv["y"].replace(0, np.nan)).mean()
        rmse = np.sqrt((err ** 2).mean())
        bias = err.mean()
        rows.append({"model": m, "WAPE_%": wape, "MAPE_%": mape, "RMSE": rmse, "Bias": bias})
    return pd.DataFrame(rows).sort_values("WAPE_%").reset_index(drop=True)


def ensemble_forecast(Y_rec: pd.DataFrame,
                       base_models=("AutoARIMA", "SeasonalNaive", "Theta", "AutoETS")) -> pd.DataFrame:
    """Build ensemble column = mean of top models (reconciled variants preferred).

    We explicitly include **SeasonalNaive** because with only 2 years of data and
    season_length=52, AutoETS/Theta often default to non-seasonal and produce a
    flat line. SeasonalNaive grounds the ensemble in the observed annual cycle.
    """
    cols = Y_rec.columns
    ens_cols = []
    for m in base_models:
        cand = [c for c in cols if c.startswith(m + "/MinTrace_method-mint_shrink")]
        if not cand:
            cand = [c for c in cols if c.startswith(m + "/BottomUp")]
        if not cand:
            cand = [c for c in cols if c == m]
        if cand:
            ens_cols.append(cand[0])
    Y_rec = Y_rec.copy()
    if ens_cols:
        Y_rec["Ensemble"] = Y_rec[ens_cols].mean(axis=1)
    return Y_rec


def main():
    print("Loading data...")
    hist, hier, cat = load_inputs()
    print(f"  {hist['unique_id'].nunique()} SKUs, {hist['ds'].nunique()} days")

    print("Building hierarchical Y_df, S, tags...")
    Y_df, S_df, tags = build_hierarchical_Ydf(hist)
    print(f"  Y_df: {len(Y_df)} rows across {Y_df['unique_id'].nunique()} series")
    print(f"  S_df: {S_df.shape}")
    print(f"  tags levels: {list(tags.keys())}")

    # Save tags & S for later use by dashboard
    S_df.to_parquet(DATA_PROC / "summing_matrix.parquet")
    # Y_df to parquet for dashboard
    Y_df.to_parquet(DATA_PROC / "Y_hier.parquet", index=False)
    # Tags: store as DataFrame
    tag_rows = [{"level": k, "unique_id": uid} for k, lst in tags.items() for uid in lst]
    pd.DataFrame(tag_rows).to_parquet(DATA_PROC / "hier_tags.parquet", index=False)

    print("Running base forecasts on WEEKLY data with season_length=52...")
    # h=12 weeks
    sf, Y_hat_df, Y_fitted_df = run_base_forecasts(Y_df, h=12, freq="W")
    print(f"  forecast shape: {Y_hat_df.shape}")

    print("Reconciling forecasts (BottomUp + MinTrace-shrink + OLS)...")
    Y_rec = reconcile(Y_hat_df, Y_fitted_df, S_df, tags)
    Y_rec = ensemble_forecast(Y_rec)
    Y_rec.to_parquet(DATA_PROC / "forecasts.parquet", index=False)
    print(f"  forecasts.parquet: {len(Y_rec)} rows, columns={list(Y_rec.columns)[:6]}...")

    print("Running walk-forward cross-validation (SKU level, 4 windows × 4 нед)...")
    cv = cross_validate(Y_df, h=4, n_windows=4, step_size=4, freq="W")
    cv.to_parquet(DATA_PROC / "cv_results.parquet", index=False)
    metrics = compute_cv_metrics(cv)
    metrics.to_parquet(DATA_PROC / "cv_metrics.parquet", index=False)
    print("CV metrics:")
    print(metrics.to_string(index=False))

    print("Forecasting complete.")


if __name__ == "__main__":
    main()
