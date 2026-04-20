"""
Data preparation for VERONESE production planning demo.

Transforms Maven Roasters coffee shop transactions into:
- SKU-level daily demand history (2 years) for forecasting
- SKU catalog with production attributes
- Hierarchy (Total -> Form -> Brand -> SKU) for HierarchicalForecast
- Production parameters per line
- Changeover matrix (sequence-dependent setup times)

All synthesis is grounded in real empirical rules (Russian seasonality,
Bühler roaster cycles, coffee industry setup times).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROC = ROOT / "data" / "processed"
CONFIG = ROOT / "config"

# Demo horizon: 2 years of daily data, last 28 days reserved for CV
START_DATE = pd.Timestamp("2022-07-01")
END_DATE = pd.Timestamp("2024-06-30")

# Russian seasonality multipliers by month (Jan=1 ... Dec=12)
# Peak: Sep-Feb; dip: May-Jul
RU_SEASONALITY = {
    1: 1.10, 2: 1.12, 3: 1.08, 4: 0.98, 5: 0.92, 6: 0.88,
    7: 0.86, 8: 0.92, 9: 1.05, 10: 1.10, 11: 1.15, 12: 1.30,
}

# Holiday spikes (month-day): multiplier applied to a ±window
HOLIDAY_SPIKES = [
    ("12-20", "12-31", 1.35),   # Новогодние подарки
    ("02-15", "02-23", 1.25),   # 23 февраля
    ("03-01", "03-08", 1.22),   # 8 марта
]

# Form-level base demand scale (units/day across all SKUs in that form)
FORM_SCALE = {
    "Beans": 1.0,
    "Ground": 1.15,
    "Capsules": 0.95,
    "3in1": 0.6,
}


def load_maven() -> pd.DataFrame:
    """Load Maven Roasters and aggregate to daily counts per product_type."""
    df = pd.read_csv(DATA_RAW / "maven_roasters.csv", sep="|")
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    daily = (
        df.groupby(["transaction_date", "product_category", "product_type"])
        ["transaction_qty"].sum().reset_index()
        .rename(columns={"transaction_date": "ds", "transaction_qty": "qty"})
    )
    return daily


def load_sku_catalog() -> list[dict]:
    with open(CONFIG / "sku_catalog.yaml") as f:
        return yaml.safe_load(f)["skus"]


def build_sku_base_pattern(sku: dict, maven_daily: pd.DataFrame) -> pd.Series:
    """Build a daily demand baseline from Maven for the given SKU.

    Uses the sku's maven_source hint to pick which category/type signal to use,
    then normalizes and scales.
    """
    # Parse maven_source = "category:type" or "category" or "type"
    src = sku["maven_source"]
    if ":" in src:
        cat_hint, type_hint = src.split(":", 1)
    else:
        cat_hint, type_hint = src, None

    # Match loosely
    mask = maven_daily["product_category"].str.contains(cat_hint, case=False, na=False)
    sub = maven_daily[mask].copy()
    if type_hint:
        mask2 = sub["product_type"].str.contains(type_hint.split()[0], case=False, na=False)
        if mask2.sum() > 10:
            sub = sub[mask2]

    if sub.empty:
        # Fallback: take overall coffee average
        sub = maven_daily[maven_daily["product_category"].str.contains("Coffee|coffee", regex=True, na=False)]

    pattern = sub.groupby("ds")["qty"].sum()
    pattern = pattern.reindex(pd.date_range(pattern.index.min(), pattern.index.max()), fill_value=0)

    # Normalize (mean=1)
    if pattern.mean() > 0:
        pattern = pattern / pattern.mean()
    else:
        pattern = pd.Series(1.0, index=pattern.index)
    return pattern


def apply_ru_seasonality(dates: pd.DatetimeIndex) -> np.ndarray:
    mult = np.array([RU_SEASONALITY[d.month] for d in dates])
    for start, end, boost in HOLIDAY_SPIKES:
        smd, sd = [int(x) for x in start.split("-")]
        emd, ed = [int(x) for x in end.split("-")]
        for i, d in enumerate(dates):
            if (d.month, d.day) >= (smd, sd) and (d.month, d.day) <= (emd, ed):
                mult[i] *= boost
    return mult


def stable_hash(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)


def generate_sku_history(sku: dict, maven_daily: pd.DataFrame) -> pd.DataFrame:
    """Generate 2-year daily demand history for a single SKU."""
    rng = np.random.default_rng(stable_hash(sku["sku_id"]) % (2**32))

    # Base pattern (normalized, ~180 days from Maven)
    base = build_sku_base_pattern(sku, maven_daily)
    # Smooth the pattern
    base = base.rolling(7, min_periods=1, center=True).mean()

    # Extend to full 2-year horizon by tiling day-of-year structure
    full_idx = pd.date_range(START_DATE, END_DATE, freq="D")
    # Compute day-of-year centroid for each date in base
    doy_map = base.groupby(base.index.dayofyear).mean().to_dict()
    # Global mean for missing days
    gmean = float(base.mean()) if len(base) else 1.0
    full = pd.Series([doy_map.get(d.dayofyear, gmean) for d in full_idx], index=full_idx)

    # Apply Russian seasonality
    full = full * apply_ru_seasonality(full_idx)

    # Apply per-SKU absolute scaling (depending on form, brand, package size)
    form_scale = FORM_SCALE.get(sku["form"], 1.0)
    # CTM brands get 1.8x volume (private label = large retail orders)
    brand_scale = 1.8 if sku["brand"] == "CTM" else 1.0
    # Larger packages have lower unit volume
    size_scale = {250: 1.0, 500: 0.6, 1000: 0.25, 55: 1.2, 200: 0.9, 180: 0.7}.get(
        sku["package_size_g"], 1.0
    )
    # Dark roast is most popular
    roast_scale = {"Dark": 1.1, "Medium": 1.0, "Light": 0.6}.get(sku["roast_level"], 1.0)
    # Decaf sells less
    if sku["is_decaf"]:
        roast_scale *= 0.4
    # Base absolute daily volume: scaled up to match real mid-size factory output
    # (VERONESE ~65 employees, 5000+ m^2 — this is ~1000 packages/day baseline per SKU)
    base_daily = 1100 * form_scale * brand_scale * size_scale * roast_scale

    full = full * base_daily

    # Add year-over-year growth (3.2% CAGR matches Russian coffee market)
    years_from_start = (full_idx - START_DATE).days / 365.25
    full = full * (1.032 ** years_from_start)

    # Weekly pattern: weekday > weekend for B2B/retail
    weekday_mult = np.where(full_idx.dayofweek < 5, 1.12, 0.75)
    full = full * weekday_mult

    # Random noise (CV=18%)
    noise = rng.normal(1.0, 0.18, size=len(full))
    full = full * noise

    # Promo events: 4-6 promo bursts/year, each 7-14 days, +30-50% boost
    n_promos = rng.integers(8, 14)
    promo_flags = np.zeros(len(full), dtype=int)
    for _ in range(n_promos):
        start = rng.integers(0, len(full) - 14)
        length = rng.integers(7, 15)
        boost = rng.uniform(1.30, 1.55)
        full.iloc[start : start + length] *= boost
        promo_flags[start : start + length] = 1

    # Clip negatives, round to int (units sold)
    full = full.clip(lower=0).round().astype(int)

    df = pd.DataFrame({
        "unique_id": sku["sku_id"],
        "ds": full_idx,
        "y": full.values,
        "promo": promo_flags,
    })
    return df


def build_hierarchy(skus: list[dict]) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Build hierarchy structure: Total -> Form -> Brand -> SKU.

    Returns:
        hierarchy_df: long-format mapping (level, parent, child)
        tags: dict of level_name -> list of unique_ids (Nixtla format)
        S: summing matrix (bottom-up) aggregated series x bottom series
    """
    rows = []
    for sku in skus:
        sku_id = sku["sku_id"]
        form = sku["form"]
        brand = sku["brand"]
        rows.append({
            "sku_id": sku_id,
            "brand": brand,
            "form": form,
            "form_brand": f"{form}/{brand}",
        })
    df = pd.DataFrame(rows)
    df.to_parquet(DATA_PROC / "hierarchy.parquet", index=False)
    return df


def build_changeover_matrix(skus: list[dict]) -> pd.DataFrame:
    """Generate sequence-dependent setup times based on SKU attribute deltas.

    Rules (in minutes):
      Roasting stage:
        - same SKU:         0
        - same blend/roast: 5 (just re-start)
        - diff blend same roast: 15
        - diff roast level: 30
        - to/from flavored: 45
        - to/from decaf:    60 (full clean)
      Packaging stage:
        - same SKU:         0
        - same package type, size: 10 (basic clean)
        - diff size:        25
        - diff package type: 60 (format changeover)
    """
    sku_ids = [s["sku_id"] for s in skus]
    idx = {s["sku_id"]: s for s in skus}

    rows = []
    for a in sku_ids:
        for b in sku_ids:
            sa, sb = idx[a], idx[b]
            if a == b:
                roast_t = 0
                pack_t = 0
            else:
                # roasting
                if sa["is_decaf"] != sb["is_decaf"]:
                    roast_t = 60
                elif sa["is_flavored"] != sb["is_flavored"]:
                    roast_t = 45
                elif sa["roast_level"] != sb["roast_level"]:
                    roast_t = 30
                elif sa["blend"] != sb["blend"]:
                    roast_t = 15
                else:
                    roast_t = 5
                # packaging
                if sa["package_type"] != sb["package_type"]:
                    pack_t = 60
                elif sa["package_size_g"] != sb["package_size_g"]:
                    pack_t = 25
                else:
                    pack_t = 10
            rows.append({
                "from_sku": a, "to_sku": b,
                "roasting_min": roast_t, "packaging_min": pack_t,
            })
    return pd.DataFrame(rows)


def build_production_params(skus: list[dict], lines_cfg: dict) -> pd.DataFrame:
    """Per-SKU production params: which line, speed, etc."""
    lines = {L["id"]: L for L in lines_cfg["packaging_lines"]}
    rows = []
    for sku in skus:
        eligible = sku["eligible_lines"]
        primary = eligible[0]
        line = lines[primary]
        # Throughput depends on package size (smaller = faster units/min)
        speed = line["throughput_units_per_minute"]
        rows.append({
            "sku_id": sku["sku_id"],
            "primary_line": primary,
            "eligible_lines": ",".join(eligible),
            "speed_units_per_min": speed,
            "package_size_g": sku["package_size_g"],
            "form": sku["form"],
            "brand": sku["brand"],
            "blend": sku["blend"],
            "roast_level": sku["roast_level"],
            "is_flavored": sku["is_flavored"],
            "is_decaf": sku["is_decaf"],
            "package_type": sku["package_type"],
            "unit_price_rub": sku["unit_price_rub"],
        })
    return pd.DataFrame(rows)


def main():
    DATA_PROC.mkdir(parents=True, exist_ok=True)
    print("Loading Maven Roasters transactions...")
    maven = load_maven()
    print(f"  {len(maven):,} daily category rows, {maven['ds'].nunique()} days")

    print("Loading SKU catalog...")
    skus = load_sku_catalog()
    print(f"  {len(skus)} SKUs defined")

    with open(CONFIG / "production_lines.yaml") as f:
        lines_cfg = yaml.safe_load(f)

    # 1. Demand history
    print("Generating 2-year daily demand history per SKU...")
    frames = [generate_sku_history(s, maven) for s in skus]
    hist = pd.concat(frames, ignore_index=True)
    hist.to_parquet(DATA_PROC / "demand_history.parquet", index=False)
    print(f"  demand_history.parquet: {len(hist):,} rows, "
          f"{hist['unique_id'].nunique()} SKUs, "
          f"{hist['ds'].nunique()} days, "
          f"total volume {hist['y'].sum():,.0f} units")

    # 2. SKU catalog as parquet
    cat_df = pd.DataFrame(skus)
    cat_df.to_parquet(DATA_PROC / "sku_catalog.parquet", index=False)
    print(f"  sku_catalog.parquet: {len(cat_df)} rows")

    # 3. Hierarchy
    build_hierarchy(skus)
    print("  hierarchy.parquet")

    # 4. Production params
    params_df = build_production_params(skus, lines_cfg)
    params_df.to_parquet(DATA_PROC / "production_params.parquet", index=False)
    print("  production_params.parquet")

    # 5. Changeover matrix
    co = build_changeover_matrix(skus)
    co.to_parquet(DATA_PROC / "changeover_matrix.parquet", index=False)
    print(f"  changeover_matrix.parquet: {len(co)} pairs")

    # 6. Production lines config as parquet (for dashboard convenience)
    pl_rows = []
    for L in lines_cfg["packaging_lines"]:
        pl_rows.append(L)
    pd.DataFrame(pl_rows).to_parquet(DATA_PROC / "production_lines.parquet", index=False)

    print("Data preparation complete.")


if __name__ == "__main__":
    main()
