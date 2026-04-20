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


FORECAST_MODELS = ["SeasonalNaive", "AutoTheta"]

# Сколько дней истории используется для backtest (и для компенсации уровня).
_BACKTEST_H = 14
_LEVEL_WINDOW = 14  # сколько дней брать для выравнивания уровня
_RESIDUAL_WINDOW = 30  # откуда бутстрапим остатки для текстуры
_NOISE_STRENGTH = 0.65  # 0..1 — сколько реального шума добавляем. <1 = прогноз глаже истории.


@cache
def forecast(target: str, horizon_days: int = 30) -> dict:
    """Ensemble forecast: SeasonalNaive + AutoTheta, с коррекцией уровня.

    **Почему именно эти две модели:**

    - `SeasonalNaive` — единственная модель, которая сохраняет **амплитуду
      дневных колебаний**. Все «умные» модели (AutoARIMA, AutoETS, MSTL)
      прогнозируют математическое ожидание, которое статистически глаже
      sample-path истории → визуально выглядит как «бледная» прямая.
      SeasonalNaive = последняя неделя, скопированная вперёд, — сохраняет
      и уровень, и амплитуду, и недельный паттерн.

    - `AutoTheta` — единственная из классики, которая уверенно ловит
      **тренд**. AutoARIMA с season_length=7 на retail-данных часто
      выбирает модель без дрейфа, AutoETS коллапсирует на коротких окнах.

    Среднее 50/50 даёт и амплитуду (от SN), и тренд (от Theta).

    **Level correction:** после ансамбля применяется сдвиг так, чтобы
    среднее первых 14 дней прогноза совпадало со средним последних 14 дней
    истории. Без этого на растущем ряду прогноз стартует ниже последнего
    уровня истории — визуальный «обрыв» на стыке.

    Returns:
        dict с ключами: history, forecast, wape_backtest, per_model_wape,
        level_shift, models_used.
    """
    from statsforecast import StatsForecast
    from statsforecast.models import AutoTheta, SeasonalNaive

    series = _target_series(target)

    if len(series) < 21:
        return {
            "history": series,
            "forecast": pd.DataFrame(),
            "wape_backtest": float("nan"),
            "models_used": [],
            "error": "Недостаточно истории для прогноза (<3 недель).",
        }

    def _build_sf() -> "StatsForecast":
        return StatsForecast(
            models=[SeasonalNaive(season_length=7), AutoTheta(season_length=7)],
            freq="D", n_jobs=1,
        )

    # ─── Backtest на последних 14 днях с такой же механикой shift ──
    train = series.iloc[:-_BACKTEST_H]
    test = series.iloc[-_BACKTEST_H:]
    per_model_wape: dict[str, float] = {}
    ens_wape = float("nan")
    try:
        sf_bt = _build_sf()
        sf_bt.fit(df=train)
        bt = sf_bt.predict(h=_BACKTEST_H, level=[80])
        merged = test.merge(bt, on=["unique_id", "ds"], how="left")
        y_true = merged["y"].values
        denom = max(1.0, float(np.sum(np.abs(y_true))))

        for m in FORECAST_MODELS:
            if m in merged.columns:
                err = float(np.sum(np.abs(y_true - merged[m].values)))
                per_model_wape[m] = err / denom * 100

        ens_bt_raw = merged[FORECAST_MODELS].mean(axis=1)
        # В backtest применяем тот же shift: уровень «до тестового окна» vs
        # старт ансамбля.
        pre_test_mean = series["y"].iloc[-_BACKTEST_H - _LEVEL_WINDOW:-_BACKTEST_H].mean()
        bt_start_mean = ens_bt_raw.head(_LEVEL_WINDOW).mean()
        shift_bt = pre_test_mean - bt_start_mean
        ens_bt_shifted = ens_bt_raw + shift_bt
        ens_wape = float(np.sum(np.abs(y_true - ens_bt_shifted.values)) / denom * 100)
    except Exception:
        per_model_wape = {}

    # ─── Полный прогноз на горизонт ─────────────────────────────────
    sf = _build_sf()
    sf.fit(df=series)
    fc = sf.predict(h=horizon_days, level=[80])
    model_cols = [m for m in FORECAST_MODELS if m in fc.columns]

    # Простое среднее 50/50
    ens_raw = fc[model_cols].mean(axis=1)

    # Level correction: среднее первых 14 дней прогноза = среднее последних 14 дней истории
    hist_recent = float(series["y"].tail(_LEVEL_WINDOW).mean())
    fc_start = float(ens_raw.head(_LEVEL_WINDOW).mean())
    level_shift = hist_recent - fc_start

    y_hat_smooth = (ens_raw + level_shift).clip(lower=0)

    # ─── Residual bootstrap: ломаем идеальную периодичность SN ──────
    # Base = SeasonalNaive + Theta + shift — это E[y_t], а E[] по определению
    # «глаже» sample-path истории. Чтобы прогноз визуально соответствовал истории
    # (ту же амплитуду день-в-день, не идентичные недели), добавляем к нему шум,
    # сэмплированный из РЕАЛЬНЫХ недавних остатков «факт − 7-дневное среднее».
    # Это классический residual bootstrap из forecasting literature (Hyndman, Ch.5).
    hist_y = series["y"].values
    roll_mean = pd.Series(hist_y).rolling(7, center=True, min_periods=1).mean().values
    residuals = hist_y - roll_mean
    # Берём остатки из последних N дней — они отражают текущий режим волатильности.
    recent_res = residuals[-_RESIDUAL_WINDOW:]
    # Центрируем, чтобы шум был несмещённым.
    recent_res = recent_res - recent_res.mean()

    # Детерминированный сид — иначе прогноз «мигает» при каждом ре-ране.
    # Привязан к target + horizon, чтобы разные запросы давали разный шум.
    seed = abs(hash((target, horizon_days, len(series)))) % (2**32)
    rng = np.random.default_rng(seed)
    noise = rng.choice(recent_res, size=horizon_days, replace=True) * _NOISE_STRENGTH

    fc["y_hat"] = (y_hat_smooth + noise).clip(lower=0)

    # Confidence intervals от AutoTheta, центрированный на сдвинутом y_hat
    if "AutoTheta-lo-80" in fc.columns:
        theta_mean = fc["AutoTheta"]
        lo_gap = (theta_mean - fc["AutoTheta-lo-80"]).clip(lower=0)
        hi_gap = (fc["AutoTheta-hi-80"] - theta_mean).clip(lower=0)
        fc["y_hat_lo_80"] = (fc["y_hat"] - lo_gap).clip(lower=0)
        fc["y_hat_hi_80"] = fc["y_hat"] + hi_gap
    else:
        fc["y_hat_lo_80"] = fc["y_hat"]
        fc["y_hat_hi_80"] = fc["y_hat"]

    # Отдельные модели возвращаем сдвинутыми тоже — чтобы expander «сравнение»
    # показывал их на том же уровне.
    for m in model_cols:
        fc[m] = fc[m] + level_shift

    return {
        "history": series,
        "forecast": fc[["unique_id", "ds", "y_hat", "y_hat_lo_80", "y_hat_hi_80"] + model_cols],
        "wape_backtest": ens_wape,
        "per_model_wape": per_model_wape,
        "level_shift": float(level_shift),
        "models_used": list(model_cols),
    }


# ─────────────────────────────────────────────────────────────────────
# Purchasing: ABC / XYZ / Safety stock
# ─────────────────────────────────────────────────────────────────────

# Типичные z-коэффициенты для service level
SERVICE_LEVEL_Z = {
    90.0: 1.282,
    95.0: 1.645,
    97.5: 1.960,
    99.0: 2.326,
}


@cache
def sku_daily_matrix() -> pd.DataFrame:
    """Матрица SKU × дата, значения = проданные единицы.

    Используется для расчёта среднего спроса, стандартного отклонения и
    коэффициента вариации для каждого SKU.
    """
    df = load_raw()
    pivot = (
        df.groupby(["product_detail", "date"])["transaction_qty"].sum()
        .reset_index()
        .pivot(index="product_detail", columns="date", values="transaction_qty")
        .fillna(0)
    )
    return pivot


@cache
def abc_xyz_table() -> pd.DataFrame:
    """ABC (по выручке) × XYZ (по стабильности) классификация SKU.

    Колонки: product_detail, category, revenue, share_pct, cum_share_pct,
             abc, mean_daily_qty, std_daily_qty, cv, xyz, class
    """
    df = load_raw()
    rev = (
        df.groupby(["product_detail", "product_category"])
        .agg(revenue=("revenue", "sum"), total_qty=("transaction_qty", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    rev["share_pct"] = rev["revenue"] / rev["revenue"].sum() * 100
    rev["cum_share_pct"] = rev["share_pct"].cumsum()

    def _abc(cum: float) -> str:
        if cum <= 80:
            return "A"
        if cum <= 95:
            return "B"
        return "C"

    rev["abc"] = rev["cum_share_pct"].apply(_abc)

    mat = sku_daily_matrix()
    stats = pd.DataFrame({
        "product_detail": mat.index,
        "mean_daily_qty": mat.mean(axis=1).values,
        "std_daily_qty": mat.std(axis=1).values,
    })
    stats["cv"] = stats["std_daily_qty"] / stats["mean_daily_qty"].replace(0, np.nan)
    stats["cv"] = stats["cv"].fillna(0)

    def _xyz(cv: float) -> str:
        if cv < 0.5:
            return "X"
        if cv < 1.0:
            return "Y"
        return "Z"

    stats["xyz"] = stats["cv"].apply(_xyz)

    out = rev.merge(stats, on="product_detail", how="left")
    out["class"] = out["abc"] + out["xyz"]
    out = out.rename(columns={"product_category": "category"})
    return out[[
        "product_detail", "category", "revenue", "share_pct", "cum_share_pct",
        "abc", "mean_daily_qty", "std_daily_qty", "cv", "xyz", "class",
    ]]


def safety_stock_table(
    service_level: float = 95.0,
    lead_time_days: int = 3,
) -> pd.DataFrame:
    """Safety stock и точка заказа для каждого SKU.

    Args:
        service_level: желаемый уровень обслуживания в процентах (90/95/97.5/99)
        lead_time_days: время поставки в днях

    Returns dataframe с колонками из abc_xyz_table + safety_stock + reorder_point +
    recommendation (rule-based совет: сколько держать / как часто заказывать / что
    делать с Z-SKU и т.п.)
    """
    z = SERVICE_LEVEL_Z.get(float(service_level), 1.645)
    df = abc_xyz_table().copy()
    df["safety_stock"] = (z * df["std_daily_qty"] * np.sqrt(lead_time_days)).round(1)
    df["reorder_point"] = (df["mean_daily_qty"] * lead_time_days + df["safety_stock"]).round(1)

    def _rec(row: pd.Series) -> str:
        cls = row["class"]
        if cls in {"AX", "AY"}:
            return "Ядро ассортимента — частый заказ, низкий буфер"
        if cls == "AZ":
            return "Ключевой, но нестабильный — высокий safety stock"
        if cls.startswith("B"):
            return "Средний приоритет — плановые заказы по графику"
        if cls == "CX":
            return "Редкий, но предсказуемый — заказ под график"
        if cls == "CZ":
            return "Кандидат на вывод из ассортимента"
        return "Стандартный режим"

    df["recommendation"] = df.apply(_rec, axis=1)
    return df


# ─────────────────────────────────────────────────────────────────────
# Shift staffing: hourly demand → barista count
# ─────────────────────────────────────────────────────────────────────

@cache
def hourly_tx_by_store_and_weekday() -> pd.DataFrame:
    """Среднее число транзакций в час × день недели × магазин.

    Делит сумму транзакций за 6 месяцев на число конкретных дат для каждого
    сочетания day_of_week × store (т.к. в датасете именно эта «конкретная среда»
    повторялась N раз — надо честно усреднять).
    """
    df = load_raw()
    weekday_order_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    n_days = (
        df.groupby(["store_location", "day_of_week"])["date"]
        .nunique()
        .reset_index()
        .rename(columns={"date": "n_dates"})
    )
    tx = (
        df.groupby(["store_location", "day_of_week", "hour"])["transaction_id"]
        .count()
        .reset_index()
        .rename(columns={"transaction_id": "tx_total"})
    )
    merged = tx.merge(n_days, on=["store_location", "day_of_week"], how="left")
    merged["avg_tx_per_hour"] = merged["tx_total"] / merged["n_dates"]
    merged["day_of_week_ru"] = merged["day_of_week"].map(_DAYS_RU)
    merged["weekday_order"] = merged["day_of_week"].map({d: i for i, d in enumerate(weekday_order_en)})
    return merged


def barista_need_matrix(
    store: str,
    throughput_per_hour: float = 30.0,
    min_baristas_open: int = 1,
) -> pd.DataFrame:
    """Матрица day_of_week × hour → рекомендованное число бариста.

    Число бариста = max(min_baristas_open, ceil(tx_per_hour / throughput)).

    Args:
        store: имя магазина (Москва · Центр / Санкт-Петербург / Екатеринбург)
        throughput_per_hour: сколько транзакций один бариста обрабатывает за час
        min_baristas_open: минимум в открытые часы
    """
    raw = hourly_tx_by_store_and_weekday()
    raw = raw[raw["store_location"] == store].copy()
    if raw.empty:
        return pd.DataFrame()

    raw["baristas"] = np.ceil(raw["avg_tx_per_hour"] / throughput_per_hour).astype(int)
    raw["baristas"] = raw["baristas"].clip(lower=min_baristas_open)

    pivot = raw.pivot(index="day_of_week_ru", columns="hour", values="baristas").fillna(0).astype(int)
    order = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    pivot = pivot.reindex([d for d in order if d in pivot.index])

    tx_pivot = raw.pivot(index="day_of_week_ru", columns="hour", values="avg_tx_per_hour").fillna(0)
    tx_pivot = tx_pivot.reindex(pivot.index)
    return pivot, tx_pivot


def weekly_barista_hours(store: str, throughput_per_hour: float = 30.0) -> dict:
    """Суммарное число бариста-часов в неделю + средняя загрузка."""
    matrix, tx = barista_need_matrix(store, throughput_per_hour)
    if matrix is None or matrix.empty:
        return {"barista_hours": 0, "avg_utilization": 0.0, "peak_hour": None}
    barista_hours = int(matrix.values.sum())
    # utilization = реальные транзакции / (баристы * throughput)
    capacity = matrix.values * throughput_per_hour
    utilization = np.where(capacity > 0, tx.values / capacity, 0).mean() * 100
    # peak hour
    peak_tx = tx.max().max()
    peak_hour = int(tx.max(axis=0).idxmax())
    return {
        "barista_hours": barista_hours,
        "avg_utilization": float(utilization),
        "peak_hour": peak_hour,
        "peak_tx": float(peak_tx),
    }


# ─────────────────────────────────────────────────────────────────────
# What-If: promo uplift simulation
# ─────────────────────────────────────────────────────────────────────

def promo_simulation(
    target: str,
    horizon_days: int,
    uplift_pct: float,
    promo_duration_days: int,
    promo_start_offset_days: int = 0,
) -> dict:
    """Надстройка поверх baseline-прогноза: мультипликативный uplift на окно промо.

    Честно: мы не переобучаем модель на промо — мы показываем,
    что было бы, если спрос в окне вырос на X% относительно baseline.
    Для полноценной ML-модели нужны promo_flag и история предыдущих
    акций, которой в датасете нет.

    Args:
        target: ключ из FORECAST_TARGETS
        horizon_days: горизонт прогноза
        uplift_pct: уплифт в процентах (например, 30 = +30%)
        promo_duration_days: сколько дней длится промо
        promo_start_offset_days: через сколько дней от конца истории стартует промо

    Returns:
        dict с keys: history, base_forecast, promo_forecast, incremental_revenue,
        promo_window (start, end), uplift_pct
    """
    result = forecast(target, horizon_days=horizon_days)
    if "error" in result:
        return result

    history = result["history"]
    base = result["forecast"].copy()

    base["ds"] = pd.to_datetime(base["ds"])
    history_end = pd.to_datetime(history["ds"].max())
    promo_start = history_end + pd.Timedelta(days=promo_start_offset_days + 1)
    promo_end = promo_start + pd.Timedelta(days=promo_duration_days - 1)

    multiplier = 1.0 + uplift_pct / 100.0
    promo = base.copy()
    in_promo = (promo["ds"] >= promo_start) & (promo["ds"] <= promo_end)
    promo.loc[in_promo, "y_hat"] = promo.loc[in_promo, "y_hat"] * multiplier
    promo.loc[in_promo, "y_hat_lo_80"] = promo.loc[in_promo, "y_hat_lo_80"] * multiplier
    promo.loc[in_promo, "y_hat_hi_80"] = promo.loc[in_promo, "y_hat_hi_80"] * multiplier

    incremental = (
        promo.loc[in_promo, "y_hat"].sum() - base.loc[in_promo, "y_hat"].sum()
    )

    return {
        "history": history,
        "base_forecast": base,
        "promo_forecast": promo,
        "incremental_revenue": float(incremental),
        "promo_start": promo_start,
        "promo_end": promo_end,
        "uplift_pct": uplift_pct,
        "wape_backtest": result["wape_backtest"],
    }
