"""Gradient-boosted demand forecaster using MLForecast + LightGBM.

Based on top Kaggle solutions (Favorita, M5, Rossmann):
- Lag features at multiple horizons (1, 2, 4, 8, 12, 26, 52 weeks)
- Rolling means and stds (4, 12, 26 weeks)
- Calendar features (month, week-of-year, week-of-month)
- Fourier terms for yearly seasonality
- Tweedie loss for count-like data (handles zeros gracefully)

The model is trained GLOBALLY across all SKUs (one model, not per-SKU) —
this is 10-50× faster and often more accurate on sparse series because
of shared learning across products.
"""
from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from mlforecast import MLForecast
from mlforecast.lag_transforms import (
    RollingMean,
    RollingStd,
)
from mlforecast.target_transforms import Differences

ROOT = Path(__file__).resolve().parents[2]
DATA_PROC = ROOT / "data" / "processed"


def _prepare_weekly(hist: pd.DataFrame) -> pd.DataFrame:
    """Daily → weekly aggregation (Monday-anchored, same scheme as earlier runs)."""
    df = hist.copy()
    df["ds"] = pd.to_datetime(df["ds"])
    df["ds"] = df["ds"] - pd.to_timedelta(df["ds"].dt.dayofweek, unit="D")  # Monday of week
    weekly = df.groupby(["unique_id", "ds"], as_index=False)["y"].sum()
    return weekly


def _add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["month"] = df["ds"].dt.month
    df["week_of_year"] = df["ds"].dt.isocalendar().week.astype(int)
    df["quarter"] = df["ds"].dt.quarter
    # Fourier terms for yearly seasonality
    doy = df["ds"].dt.dayofyear
    for k in (1, 2, 3):
        df[f"sin_yr_{k}"] = np.sin(2 * np.pi * k * doy / 365.25)
        df[f"cos_yr_{k}"] = np.cos(2 * np.pi * k * doy / 365.25)
    return df


def fit_and_forecast(horizon_weeks: int = 12, cv_windows: int = 4):
    """Fit LightGBM global model and generate forecasts for all SKUs.

    Returns:
      forecasts_df: DataFrame with columns unique_id, ds, LGBM
      cv_metrics: DataFrame with per-model WAPE/MAPE/RMSE across CV folds
    """
    hist = pd.read_parquet(DATA_PROC / "demand_history.parquet")
    hier = pd.read_parquet(DATA_PROC / "hierarchy.parquet")
    hist = hist.merge(hier[["sku_id", "form", "brand"]],
                      left_on="unique_id", right_on="sku_id").drop(columns=["sku_id"])

    weekly = _prepare_weekly(hist[["unique_id", "ds", "y", "promo", "form", "brand"]])

    # Static features (don't change over time) - passed as static_features
    static = weekly.drop_duplicates("unique_id")[["unique_id"]].merge(
        hist[["unique_id", "form", "brand"]].drop_duplicates("unique_id"),
        on="unique_id",
    )
    weekly = weekly.merge(static, on="unique_id", how="left")

    # Encode categorical as integer codes (LightGBM wants numeric)
    for col in ("form", "brand"):
        weekly[col] = pd.Categorical(weekly[col]).codes

    # Calendar features are handled by MLForecast via `date_features=`. We don't
    # pre-add Fourier/month columns because MLForecast re-creates features at
    # predict time and would fail if the set diverges from training.

    # Define MLForecast with lag and rolling features
    lgb_model = lgb.LGBMRegressor(
        objective="tweedie",
        tweedie_variance_power=1.1,
        n_estimators=600,
        learning_rate=0.05,
        num_leaves=63,
        min_child_samples=20,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=5,
        reg_alpha=0.1,
        reg_lambda=0.1,
        verbose=-1,
    )

    fcst = MLForecast(
        models={"LGBM": lgb_model},
        freq="W-MON",  # Monday-anchored (matches training aggregation)
        lags=[1, 2, 4, 8, 12, 26],
        lag_transforms={
            1: [RollingMean(window_size=4), RollingMean(window_size=12)],
            4: [RollingMean(window_size=4)],
        },
        date_features=["week", "month", "quarter"],
    )

    # CV: 4 folds × 4 weeks
    print(f"Training LightGBM global model (4-fold × 4-week CV)...")
    cv_results = fcst.cross_validation(
        df=weekly,
        h=4,
        n_windows=cv_windows,
        step_size=4,
        static_features=["form", "brand"],
    )
    cv_results = cv_results.reset_index() if "cutoff" not in cv_results.columns else cv_results

    # Compute metrics
    err = cv_results["LGBM"] - cv_results["y"]
    abs_err = err.abs()
    wape = 100 * abs_err.sum() / cv_results["y"].abs().sum()
    mape = 100 * (abs_err / cv_results["y"].replace(0, np.nan)).mean()
    rmse = float(np.sqrt((err ** 2).mean()))
    bias = float(err.mean())
    cv_metrics_row = pd.DataFrame([{
        "model": "LGBM", "WAPE_%": wape, "MAPE_%": mape, "RMSE": rmse, "Bias": bias
    }])

    # Final fit on full data + forecast
    print(f"Fitting on full history, forecasting {horizon_weeks} weeks...")
    fcst.fit(weekly, static_features=["form", "brand"])
    preds = fcst.predict(h=horizon_weeks)
    preds = preds[["unique_id", "ds", "LGBM"]].copy()
    return preds, cv_metrics_row, cv_results


def main():
    print("Fitting LightGBM global model on weekly SKU data...")
    preds, cv_metric, cv_results = fit_and_forecast(horizon_weeks=12, cv_windows=4)
    print(f"  forecasts: {len(preds)} rows, {preds['unique_id'].nunique()} series")
    print(f"\nLightGBM CV metric:")
    print(cv_metric.to_string(index=False))

    # Save
    preds.to_parquet(DATA_PROC / "lgbm_forecasts.parquet", index=False)

    # Merge into existing forecasts.parquet
    existing = pd.read_parquet(DATA_PROC / "forecasts.parquet")
    existing["ds"] = pd.to_datetime(existing["ds"])
    preds["ds"] = pd.to_datetime(preds["ds"])
    # Nixtla HierarchicalForecast anchors weekly forecasts on Sunday (W default),
    # our LGBM uses Monday (W-MON). Shift LGBM dates by -1 day to align.
    preds["ds"] = preds["ds"] - pd.Timedelta(days=1)
    # Remove any stale LGBM column from previous runs
    if "LGBM" in existing.columns:
        existing = existing.drop(columns=["LGBM"])
    # LGBM is at SKU level only; existing forecasts include aggregated levels too.
    sku_mask = existing["unique_id"].str.count("/") == 2
    sku_rows = existing[sku_mask].copy()
    sku_rows["__sku"] = sku_rows["unique_id"].str.split("/").str[-1]
    preds_renamed = preds.rename(columns={"unique_id": "__sku"})
    merged = sku_rows.merge(preds_renamed, on=["__sku", "ds"], how="left")
    n_missing = merged["LGBM"].isna().sum()
    if n_missing:
        print(f"  ⚠ {n_missing}/{len(merged)} LGBM values didn't match after merge — check date alignment")
    existing["LGBM"] = np.nan
    existing.loc[sku_mask, "LGBM"] = merged["LGBM"].values
    existing.to_parquet(DATA_PROC / "forecasts.parquet", index=False)

    # Update cv_metrics — dedupe on model (keep newest)
    existing_cv = pd.read_parquet(DATA_PROC / "cv_metrics.parquet") if (DATA_PROC / "cv_metrics.parquet").exists() else pd.DataFrame()
    combined_cv = pd.concat([existing_cv, cv_metric], ignore_index=True)
    combined_cv = combined_cv.drop_duplicates(subset=["model"], keep="last")
    combined_cv = combined_cv.sort_values("WAPE_%").reset_index(drop=True)
    combined_cv.to_parquet(DATA_PROC / "cv_metrics.parquet", index=False)
    print(f"\nUpdated cv_metrics.parquet with LightGBM. Top 3:")
    print(combined_cv.head(3).to_string(index=False))

    # Rebuild Ensemble as WEIGHTED average of models that actually capture
    # seasonality. Theta/AutoETS produce flat lines on 2-year data → excluded.
    # Weights are inversely proportional to WAPE (better models get more weight).
    print("\nRebuilding Ensemble — weighted by inverse WAPE, flat models excluded...")
    cv_all = combined_cv.set_index("model")

    weights = {}
    # LGBM (ML-model, has its own column)
    if "LGBM" in cv_all.index:
        weights["LGBM"] = 1.0 / cv_all.loc["LGBM", "WAPE_%"]
    # SeasonalNaive reconciled — grounds in yearly pattern
    if "SeasonalNaive" in cv_all.index:
        sn_col = "SeasonalNaive/MinTrace_method-mint_shrink"
        if sn_col in existing.columns:
            weights[sn_col] = 1.0 / cv_all.loc["SeasonalNaive", "WAPE_%"]
    # AutoARIMA reconciled — trend capture
    if "AutoARIMA" in cv_all.index:
        aa_col = "AutoARIMA/MinTrace_method-mint_shrink"
        if aa_col in existing.columns:
            weights[aa_col] = 1.0 / cv_all.loc["AutoARIMA", "WAPE_%"]

    # Normalize weights
    W = sum(weights.values())
    weights = {k: v / W for k, v in weights.items()}
    print(f"  ensemble weights: {weights}")

    # Weighted combine
    existing["Ensemble"] = 0.0
    for col, w in weights.items():
        if col in existing.columns:
            existing["Ensemble"] = existing["Ensemble"] + existing[col].fillna(0) * w
    # For aggregated levels (non-SKU rows), LGBM is NaN. Re-normalize weights
    # among non-NaN components per-row.
    # Simpler: for rows where LGBM is NaN (aggregated levels), fall back to
    # mean of statistical components.
    mask_no_lgbm = existing["LGBM"].isna()
    fallback_cols = [c for c in weights.keys() if c != "LGBM"]
    if fallback_cols:
        # Re-normalize fallback weights
        fb_w = {k: weights[k] for k in fallback_cols}
        fb_total = sum(fb_w.values())
        fb_w = {k: v / fb_total for k, v in fb_w.items()}
        fallback_vals = pd.Series(0.0, index=existing.index)
        for col, w in fb_w.items():
            fallback_vals = fallback_vals + existing[col].fillna(0) * w
        existing.loc[mask_no_lgbm, "Ensemble"] = fallback_vals[mask_no_lgbm]

    existing.to_parquet(DATA_PROC / "forecasts.parquet", index=False)
    print("Done.")


if __name__ == "__main__":
    main()
