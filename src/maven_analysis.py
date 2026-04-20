"""Maven Roasters (Kaggle) analytics — pure-Python data layer.

One source, many aggregates. Reads the raw transactions parquet once,
caches all aggregates with functools.cache so the Streamlit UI re-uses
them across reruns without re-reading disk.

Columns in raw data:
  transaction_id, transaction_date, transaction_time, transaction_qty,
  store_id, store_location, product_id, unit_price, product_category,
  product_type, product_detail
"""
from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_PARQUET = ROOT / "archive" / "coffee-shop-sales-revenue.parquet"
RAW_CSV = ROOT / "data" / "raw" / "maven_roasters.csv"


@cache
def load_raw() -> pd.DataFrame:
    """Load raw Maven Roasters transactions. Cached — called once per session."""
    if RAW_PARQUET.exists():
        df = pd.read_parquet(RAW_PARQUET)
    elif RAW_CSV.exists():
        df = pd.read_csv(RAW_CSV, sep="|")
    else:
        raise FileNotFoundError(
            f"Neither {RAW_PARQUET} nor {RAW_CSV} found — put the Maven Roasters "
            "Kaggle CSV/parquet in one of those locations."
        )

    # Parse datetime column
    df["ts"] = pd.to_datetime(
        df["transaction_date"].astype(str) + " " + df["transaction_time"].astype(str)
    )
    df["date"] = pd.to_datetime(df["transaction_date"])
    df["hour"] = df["ts"].dt.hour
    df["day_of_week"] = df["ts"].dt.day_name()
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["revenue"] = df["transaction_qty"] * df["unit_price"]
    return df


# ─────────────────────────────────────────────────────────────────────
# High-level KPIs
# ─────────────────────────────────────────────────────────────────────

@cache
def top_kpis() -> dict:
    df = load_raw()
    n_tx = len(df)
    revenue = df["revenue"].sum()
    aov = revenue / n_tx
    stores = df["store_location"].nunique()
    products = df["product_detail"].nunique()
    date_min = df["date"].min().date()
    date_max = df["date"].max().date()
    return {
        "transactions": int(n_tx),
        "revenue_usd": float(revenue),
        "aov_usd": float(aov),
        "stores": int(stores),
        "products": int(products),
        "date_from": date_min,
        "date_to": date_max,
        "items_sold": int(df["transaction_qty"].sum()),
    }


# ─────────────────────────────────────────────────────────────────────
# EDA aggregates — each returns a tidy DataFrame ready for Plotly
# ─────────────────────────────────────────────────────────────────────

@cache
def daily_revenue() -> pd.DataFrame:
    """Revenue + transactions per date."""
    df = load_raw()
    agg = df.groupby("date").agg(
        revenue=("revenue", "sum"),
        transactions=("transaction_id", "count"),
        items=("transaction_qty", "sum"),
    ).reset_index()
    return agg


@cache
def hour_heatmap() -> pd.DataFrame:
    """Hour × day_of_week revenue heatmap (8 AM → 8 PM, Mon → Sun)."""
    df = load_raw()
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    pivot = (
        df.groupby(["day_of_week", "hour"])["revenue"].sum()
        .reset_index()
        .pivot(index="day_of_week", columns="hour", values="revenue")
        .reindex(weekday_order)
        .fillna(0)
    )
    return pivot


@cache
def revenue_by_category() -> pd.DataFrame:
    """Total revenue + share per product category."""
    df = load_raw()
    agg = (
        df.groupby("product_category")
        .agg(revenue=("revenue", "sum"), transactions=("transaction_id", "count"))
        .sort_values("revenue", ascending=False)
        .reset_index()
    )
    agg["share"] = agg["revenue"] / agg["revenue"].sum() * 100
    return agg


@cache
def revenue_by_store() -> pd.DataFrame:
    """Revenue + transaction count per store."""
    df = load_raw()
    agg = (
        df.groupby("store_location")
        .agg(revenue=("revenue", "sum"), transactions=("transaction_id", "count"))
        .sort_values("revenue", ascending=False)
        .reset_index()
    )
    agg["share"] = agg["revenue"] / agg["revenue"].sum() * 100
    return agg


@cache
def top_products(n: int = 10) -> pd.DataFrame:
    """Top-N products by revenue."""
    df = load_raw()
    agg = (
        df.groupby(["product_detail", "product_category"])
        .agg(revenue=("revenue", "sum"), items=("transaction_qty", "sum"))
        .sort_values("revenue", ascending=False)
        .head(n)
        .reset_index()
    )
    return agg


@cache
def category_by_store() -> pd.DataFrame:
    """Revenue pivoted: store × category."""
    df = load_raw()
    return (
        df.groupby(["store_location", "product_category"])["revenue"].sum()
        .reset_index()
        .pivot(index="store_location", columns="product_category", values="revenue")
        .fillna(0)
    )


@cache
def hourly_tx_profile() -> pd.DataFrame:
    """Average transactions per hour (across all days) — for staffing insight."""
    df = load_raw()
    agg = (
        df.groupby("hour")
        .agg(transactions=("transaction_id", "count"), revenue=("revenue", "sum"))
        .reset_index()
    )
    n_days = df["date"].nunique()
    agg["avg_transactions_per_day"] = agg["transactions"] / n_days
    agg["avg_revenue_per_day"] = agg["revenue"] / n_days
    return agg


# ─────────────────────────────────────────────────────────────────────
# Forecasting
# ─────────────────────────────────────────────────────────────────────

FORECAST_TARGETS = {
    "total_revenue": "Вся выручка (все магазины)",
    "coffee_revenue": "Выручка категории Coffee",
    "tea_revenue": "Выручка категории Tea",
    "bakery_revenue": "Выручка категории Bakery",
    "lower_manhattan": "Магазин Lower Manhattan",
    "hells_kitchen": "Магазин Hell's Kitchen",
    "astoria": "Магазин Astoria",
}


@cache
def _target_series(target: str) -> pd.DataFrame:
    """Return a series suitable for StatsForecast: columns [unique_id, ds, y]."""
    df = load_raw()

    if target == "total_revenue":
        s = df.groupby("date")["revenue"].sum()
    elif target == "coffee_revenue":
        s = df[df["product_category"] == "Coffee"].groupby("date")["revenue"].sum()
    elif target == "tea_revenue":
        s = df[df["product_category"] == "Tea"].groupby("date")["revenue"].sum()
    elif target == "bakery_revenue":
        s = df[df["product_category"] == "Bakery"].groupby("date")["revenue"].sum()
    elif target == "lower_manhattan":
        s = df[df["store_location"] == "Lower Manhattan"].groupby("date")["revenue"].sum()
    elif target == "hells_kitchen":
        s = df[df["store_location"] == "Hell's Kitchen"].groupby("date")["revenue"].sum()
    elif target == "astoria":
        s = df[df["store_location"] == "Astoria"].groupby("date")["revenue"].sum()
    else:
        raise ValueError(f"Unknown forecast target: {target}")

    # Fill missing dates (the data is dense but safety first)
    idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    s = s.reindex(idx, fill_value=0)
    return pd.DataFrame({"unique_id": target, "ds": s.index, "y": s.values})


@cache
def forecast(target: str, horizon_days: int = 30) -> dict:
    """Ensemble forecast (AutoARIMA + SeasonalNaive + HistoricAverage).

    Returns dict with keys: history (df), forecast (df with y_hat, y_hat_lo_80, y_hat_hi_80),
    wape_backtest (float), models_used (list of str).
    """
    from statsforecast import StatsForecast
    from statsforecast.models import AutoARIMA, HistoricAverage, SeasonalNaive

    series = _target_series(target)

    # Guard: need at least a few weeks of history to fit AutoARIMA
    if len(series) < 21:
        return {
            "history": series,
            "forecast": pd.DataFrame(),
            "wape_backtest": float("nan"),
            "models_used": [],
            "error": "Недостаточно истории для прогноза (<3 недель).",
        }

    # Simple 14-day backtest for WAPE
    train = series.iloc[:-14]
    test = series.iloc[-14:]

    sf = StatsForecast(
        models=[
            AutoARIMA(season_length=7),
            SeasonalNaive(season_length=7),
            HistoricAverage(),
        ],
        freq="D",
        n_jobs=1,
    )
    # Backtest
    try:
        sf.fit(df=train)
        bt = sf.predict(h=14, level=[80])
        merged = test.merge(bt, on=["unique_id", "ds"], how="left")
        y_true = merged["y"].values
        # Ensemble = mean of 3 models
        model_cols = [c for c in merged.columns if c not in ("unique_id", "ds", "y") and not c.endswith(("-lo-80", "-hi-80"))]
        ensemble = merged[model_cols].mean(axis=1).values
        wape = np.sum(np.abs(y_true - ensemble)) / max(1.0, np.sum(np.abs(y_true))) * 100
    except Exception:
        wape = float("nan")

    # Full forecast
    sf = StatsForecast(
        models=[
            AutoARIMA(season_length=7),
            SeasonalNaive(season_length=7),
            HistoricAverage(),
        ],
        freq="D",
        n_jobs=1,
    )
    sf.fit(df=series)
    fc = sf.predict(h=horizon_days, level=[80])

    # Ensemble column
    model_cols = [c for c in fc.columns if c not in ("unique_id", "ds") and not c.endswith(("-lo-80", "-hi-80"))]
    fc["y_hat"] = fc[model_cols].mean(axis=1).clip(lower=0)

    # Prefer AutoARIMA confidence interval if present
    if "AutoARIMA-lo-80" in fc.columns:
        fc["y_hat_lo_80"] = fc["AutoARIMA-lo-80"].clip(lower=0)
        fc["y_hat_hi_80"] = fc["AutoARIMA-hi-80"].clip(lower=0)
    else:
        fc["y_hat_lo_80"] = fc["y_hat"]
        fc["y_hat_hi_80"] = fc["y_hat"]

    return {
        "history": series,
        "forecast": fc[["unique_id", "ds", "y_hat", "y_hat_lo_80", "y_hat_hi_80"] + model_cols],
        "wape_backtest": float(wape),
        "models_used": ["AutoARIMA", "SeasonalNaive", "HistoricAverage"],
    }
