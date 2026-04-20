"""Sales analytics — pure-Python data layer.

Анонимизированные транзакции сети кофеен (3 региона РФ, 6 мес 2023).
Данные локализованы (RUB, русские названия). Источник — NDA.

One source, many aggregates. Reads the raw transactions parquet once,
caches all aggregates with functools.cache so the Streamlit UI re-uses
them across reruns without re-reading disk.

Columns after load:
  transaction_id, transaction_date, transaction_time, transaction_qty,
  store_id, store_location, product_id, unit_price, product_category,
  product_type, product_detail (все строки — на русском, цены — в RUB)
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

# USD → RUB конверсия. Source CSV — в долларах; выручка
# в клиентских отчётах — в рублях. Множитель × 100 даёт реалистичные
# для российского specialty-рынка цены (латте $3 → 300 ₽).
USD_TO_RUB = 100

# ─── Локализация: английские значения → русские ─────────────────────
STORE_LOCATIONS_RU = {
    "Lower Manhattan": "Москва · Центр",
    "Hell's Kitchen": "Санкт-Петербург",
    "Astoria": "Екатеринбург",
}

CATEGORIES_RU = {
    "Coffee": "Кофе",
    "Tea": "Чай",
    "Bakery": "Выпечка",
    "Drinking Chocolate": "Горячий шоколад",
    "Coffee beans": "Зерно в розницу",
    "Branded": "Брендированное",
    "Loose Tea": "Листовой чай",
    "Flavours": "Сиропы",
    "Packaged Chocolate": "Упакованный шоколад",
}

PRODUCT_TYPES_RU = {
    "Barista Espresso": "Эспрессо-напитки",
    "Biscotti": "Бискотти",
    "Black tea": "Чёрный чай (упаковка)",
    "Brewed Black tea": "Чёрный чай",
    "Brewed Chai tea": "Чай масала",
    "Brewed Green tea": "Зелёный чай",
    "Brewed herbal tea": "Травяной чай",
    "Chai tea": "Чай масала (упаковка)",
    "Clothing": "Одежда",
    "Drinking Chocolate": "Шоколад упаковка",
    "Drip coffee": "Фильтр-кофе",
    "Espresso Beans": "Зерно для эспрессо",
    "Gourmet Beans": "Зерно премиум",
    "Gourmet brewed coffee": "Спешелти-кофе",
    "Green beans": "Зелёное зерно",
    "Green tea": "Зелёный чай (упаковка)",
    "Herbal tea": "Травяной чай (упаковка)",
    "Hot chocolate": "Горячий шоколад",
    "House blend Beans": "Бленд зерно",
    "Housewares": "Посуда и аксессуары",
    "Organic Beans": "Органик-зерно",
    "Organic Chocolate": "Органик-шоколад",
    "Organic brewed coffee": "Органик-кофе",
    "Pastry": "Выпечка",
    "Premium Beans": "Зерно премиум",
    "Premium brewed coffee": "Премиум-кофе",
    "Regular syrup": "Сиропы",
    "Scone": "Сконы",
    "Sugar free syrup": "Сиропы без сахара",
}

# Базовые продукты — без суффиксов размера
_BASE_PRODUCT_RU = {
    # Coffee beverages / drinks
    "Latte": "Латте",
    "Cappuccino": "Капучино",
    "Espresso Roast": "Эспрессо",
    "Espresso shot": "Шот эспрессо",
    "Primo Espresso Roast": "Эспрессо премиум",
    "Ouro Brasileiro shot": "Бразильский шот",
    "Brazilian": "Бразилия",
    "Columbian Medium Roast": "Колумбия (средняя обжарка)",
    "Ethiopia": "Эфиопия",
    "Guatemalan Sustainably Grown": "Гватемала эко",
    "Jamacian Coffee River": "Ямайка Кофе Ривер",  # typo в исходных данных
    "Jamaican Coffee River": "Ямайка Кофе Ривер",
    "Sustainably Grown Organic": "Органик спешелти",
    "Our Old Time Diner Blend": "Классический бленд",
    "Organic Decaf Blend": "Бленд без кофеина",
    "Civet Cat": "Копи Лювак",
    "Brazilian - Organic": "Бразилия органик (зерно)",
    # Tea
    "Earl Grey": "Эрл Грей",
    "English Breakfast": "Английский завтрак",
    "Morning Sunrise Chai": "Утренний чай",
    "Spicy Eye Opener Chai": "Пряный масала",
    "Traditional Blend Chai": "Традиционный масала",
    "Serenity Green Tea": "Зелёный «Безмятежность»",
    "Lemon Grass": "Лемонграсс",
    "Peppermint": "Мята",
    # Drinking Chocolate
    "Dark chocolate": "Тёмный шоколад",
    "Chili Mayan": "Шоколад «Майя» с чили",
    # Bakery
    "Almond Croissant": "Миндальный круассан",
    "Chocolate Croissant": "Шоколадный круассан",
    "Croissant": "Круассан",
    "Cranberry Scone": "Скон клюквенный",
    "Ginger Scone": "Скон имбирный",
    "Jumbo Savory Scone": "Скон сытный",
    "Oatmeal Scone": "Скон овсяный",
    "Scottish Cream Scone": "Скон шотландский",
    "Chocolate Chip Biscotti": "Бискотти шоколад",
    "Ginger Biscotti": "Бискотти имбирь",
    "Hazelnut Biscotti": "Бискотти фундук",
    # Syrups
    "Carmel syrup": "Сироп карамель",
    "Chocolate syrup": "Сироп шоколад",
    "Hazelnut syrup": "Сироп фундук",
    "Sugar Free Vanilla syrup": "Сироп ваниль (без сахара)",
    # Branded
    "I Need My Bean! Diner mug": "Кружка фирменная «Diner»",
    "I Need My Bean! Latte cup": "Стакан фирменный «Latte»",
    "I Need My Bean! T-shirt": "Футболка фирменная",
}

_SIZE_SUFFIX_RU = {
    " Lg": " большой",
    " Rg": " средний",
    " Sm": " малый",
}


def _ru_product_detail(s: str) -> str:
    """Перевод product_detail с обработкой суффикса размера."""
    s = s.strip()
    # Трим суффикса Scotts Scone имеет trailing space — нормализуем
    # Сначала попробуем снять суффикс размера
    base = s
    suffix_ru = ""
    for suf_en, suf_ru in _SIZE_SUFFIX_RU.items():
        if s.endswith(suf_en):
            base = s[: -len(suf_en)]
            suffix_ru = suf_ru
            break
    ru_base = _BASE_PRODUCT_RU.get(base, base)
    return f"{ru_base}{suffix_ru}".strip()


@cache
def load_raw() -> pd.DataFrame:
    """Load and russify transactions. Cached — called once per session."""
    if RAW_PARQUET.exists():
        df = pd.read_parquet(RAW_PARQUET)
    elif RAW_CSV.exists():
        df = pd.read_csv(RAW_CSV, sep="|")
    else:
        raise FileNotFoundError(
            f"Neither {RAW_PARQUET} nor {RAW_CSV} found."
        )

    # ─── Localize to Russian ─────────────────────────────────────
    df["store_location"] = df["store_location"].map(STORE_LOCATIONS_RU).fillna(df["store_location"])
    df["product_category"] = df["product_category"].map(CATEGORIES_RU).fillna(df["product_category"])
    df["product_type"] = df["product_type"].map(PRODUCT_TYPES_RU).fillna(df["product_type"])
    df["product_detail"] = df["product_detail"].apply(_ru_product_detail)
    # Convert USD → RUB
    df["unit_price"] = df["unit_price"] * USD_TO_RUB

    # Parse datetime
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


_DAYS_RU = {
    "Monday": "Пн", "Tuesday": "Вт", "Wednesday": "Ср", "Thursday": "Чт",
    "Friday": "Пт", "Saturday": "Сб", "Sunday": "Вс",
}


@cache
def hour_heatmap() -> pd.DataFrame:
    """Hour × day_of_week revenue heatmap (8 AM → 8 PM, Пн → Вс)."""
    df = load_raw()
    weekday_order_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    pivot = (
        df.groupby(["day_of_week", "hour"])["revenue"].sum()
        .reset_index()
        .pivot(index="day_of_week", columns="hour", values="revenue")
        .reindex(weekday_order_en)
        .fillna(0)
    )
    # Rename index to Russian short names
    pivot.index = [_DAYS_RU[d] for d in pivot.index]
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
    "total_revenue": "Вся сеть — суммарная выручка",
    "coffee_revenue": "Категория «Кофе»",
    "tea_revenue": "Категория «Чай»",
    "bakery_revenue": "Категория «Выпечка»",
    "moscow": "Магазин Москва · Центр",
    "spb": "Магазин Санкт-Петербург",
    "ekb": "Магазин Екатеринбург",
}


@cache
def _target_series(target: str) -> pd.DataFrame:
    """Return a series suitable for StatsForecast: columns [unique_id, ds, y]."""
    df = load_raw()

    if target == "total_revenue":
        s = df.groupby("date")["revenue"].sum()
    elif target == "coffee_revenue":
        s = df[df["product_category"] == "Кофе"].groupby("date")["revenue"].sum()
    elif target == "tea_revenue":
        s = df[df["product_category"] == "Чай"].groupby("date")["revenue"].sum()
    elif target == "bakery_revenue":
        s = df[df["product_category"] == "Выпечка"].groupby("date")["revenue"].sum()
    elif target == "moscow":
        s = df[df["store_location"] == "Москва · Центр"].groupby("date")["revenue"].sum()
    elif target == "spb":
        s = df[df["store_location"] == "Санкт-Петербург"].groupby("date")["revenue"].sum()
    elif target == "ekb":
        s = df[df["store_location"] == "Екатеринбург"].groupby("date")["revenue"].sum()
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
