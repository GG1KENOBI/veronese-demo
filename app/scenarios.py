"""Scenario definitions + runner. Pure Python — no Streamlit dependency.

This module used to live in app/views/whatif_page.py. Moved here so the
runtime UI can consume precomputed scenario parquet dirs without importing
Streamlit just to fetch paths.

Usage:
    # At build time (scripts/build_scenarios.py):
    from app.scenarios import run_scenario, SCENARIOS
    for key, spec in SCENARIOS.items():
        run_scenario(spec["id"], output_dir=f"data/processed/scenarios/{key}")

    # At runtime (app/main.py):
    from app.scenarios import scenario_dir, SCENARIOS
    parquet_dir = scenario_dir(selected_scenario_key)
    plan_df = pd.read_parquet(parquet_dir / "production_plan.parquet")
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_PROC = ROOT / "data" / "processed"
SCENARIOS_DIR = DATA_PROC / "scenarios"

# All 9 output parquet files a scenario run produces
SCENARIO_OUTPUTS = [
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
]

# Scenario catalog — keys are short slugs, values are spec dicts.
# `id` is the human-readable name used by _run_scenario to branch logic.
SCENARIOS: Dict[str, Dict[str, Any]] = {
    "base": {
        "id": "base",
        "label": "Базовый (ничего не меняем)",
        "short_label": "Базовый",
        "description": "Исходный план без изменений — для сравнения.",
    },
    "promo_dark_30": {
        "id": "Промо на Dark Arabica: +30% на ближайшие 4 недели",
        "label": "Промо на тёмный кофе +30% (4 недели)",
        "short_label": "Промо +30%",
        "description": "Коммерческий отдел пообещал ритейлеру +30% Dark Arabica на декабрь — что с планом?",
    },
    "capacity_loss_35": {
        "id": "Снижение capacity на 35% (серьёзная поломка)",
        "label": "Поломка линии: −35% мощности",
        "short_label": "Поломка −35%",
        "description": "Сломалась линия, осталось 65% мощности — появится ли дефицит?",
    },
    "ctm_growth_40": {
        "id": "Рост СТМ-спроса: +40% на все CTM SKU",
        "label": "Рост СТМ: +40% спроса",
        "short_label": "СТМ +40%",
        "description": "Ритейл заказывает +40% собственной торговой марки — выдержат ли линии?",
    },
    "service_99": {
        "id": "Увеличение service level до 99%",
        "label": "Повысить надёжность до 99%",
        "short_label": "Service 99%",
        "description": "Хотим поднять service level с 95% до 99% — сколько это стоит?",
    },
}


def scenario_dir(key: str) -> Path:
    """Directory where precomputed parquets for a scenario live."""
    return SCENARIOS_DIR / key


def scenario_exists(key: str) -> bool:
    """Whether a scenario has been precomputed (all 10 files present)."""
    d = scenario_dir(key)
    if not d.exists():
        return False
    return all((d / name).exists() for name in SCENARIO_OUTPUTS)


def _save_outputs(target_dir: Path) -> None:
    """Copy all SCENARIO_OUTPUTS from DATA_PROC to target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in SCENARIO_OUTPUTS:
        src = DATA_PROC / name
        if src.exists():
            df = pd.read_parquet(src)
            df.to_parquet(target_dir / name, index=False)


def run_scenario(scenario_id: str, output_dir: Path | None = None) -> None:
    """Run the full pipeline (CLSP → schedule → OEE) for a scenario.

    If output_dir is given, final parquets are copied there. The pipeline
    itself still writes through DATA_PROC (solver side-effects), so don't
    call this concurrently.

    Args:
        scenario_id: One of the scenario id strings (see SCENARIOS[*]['id']).
                     'base' = no modifications.
        output_dir: Where to persist the 10 resulting parquets. If None,
                    they stay in DATA_PROC as side-effect.
    """
    from src.planning.clsp_model import (
        build_model,
        extract_solution,
        load_cost_params,
        load_inputs as clsp_load_inputs,
        solve,
    )
    from src.scheduling.cpsat_model import main as run_sched
    from src.simulation.oee_simulator import (
        build_six_big_losses,
        build_waterfall,
        load_schedule,
        monte_carlo,
    )

    weekly, params, col = clsp_load_inputs(horizon_weeks=12)
    cfg = load_cost_params()
    cap_mult = 1.0
    setup_mult = 1.0
    service = 0.95

    if scenario_id.startswith("Промо"):
        mask = weekly["sku_id"].str.contains("DARK") & (weekly["week"] < 4)
        weekly.loc[mask, "y_hat"] *= 1.30
    elif scenario_id.startswith("Снижение capacity"):
        cap_mult = 0.65
    elif scenario_id.startswith("Рост СТМ"):
        ctm_mask = weekly["sku_id"].str.startswith("CTM_")
        weekly.loc[ctm_mask, "y_hat"] *= 1.40
    elif scenario_id.startswith("Увеличение service"):
        service = 0.99
        cfg["service_level"]["z_value"] = 2.33
    # scenario_id == "base" → no modifications

    m = build_model(
        weekly, params, cfg,
        horizon_weeks=12,
        service_level=service,
        capacity_multiplier=cap_mult,
        setup_cost_multiplier=setup_mult,
    )
    solve(m, time_limit_sec=30)
    plan_df, inv_df, sp_df, cost_df, total = extract_solution(m)
    plan_df.to_parquet(DATA_PROC / "production_plan.parquet", index=False)
    inv_df.to_parquet(DATA_PROC / "inventory_trajectory.parquet", index=False)
    sp_df.to_parquet(DATA_PROC / "shadow_prices.parquet", index=False)
    cost_df.to_parquet(DATA_PROC / "cost_breakdown.parquet", index=False)

    run_sched(week=0)

    opt = monte_carlo(load_schedule("optimized"), n_runs=30)
    opt["mode"] = "optimized"
    nv = monte_carlo(load_schedule("naive"), n_runs=30)
    nv["mode"] = "naive"
    pd.concat([opt, nv], ignore_index=True).to_parquet(
        DATA_PROC / "oee_results.parquet", index=False
    )
    build_waterfall(opt).to_parquet(DATA_PROC / "oee_waterfall.parquet", index=False)
    build_six_big_losses(opt).to_parquet(DATA_PROC / "six_big_losses.parquet", index=False)

    if output_dir is not None:
        _save_outputs(Path(output_dir))


# ─────────────────────────────────────────────────────────────────────
# Legacy baseline-snapshot helpers. Used by main.py's "Apply scenario"
# button while we still do live solves. Will become unused in Sprint 2
# once precomputed scenarios replace live pipeline.
# ─────────────────────────────────────────────────────────────────────
BASELINE_DIR = DATA_PROC / "baseline"


def save_baseline() -> None:
    """Snapshot current DATA_PROC state into BASELINE_DIR so a reset
    button can restore it after a what-if run."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for name in SCENARIO_OUTPUTS:
        src = DATA_PROC / name
        if src.exists():
            df = pd.read_parquet(src)
            df.to_parquet(BASELINE_DIR / name, index=False)


def reset_to_baseline() -> None:
    """Restore DATA_PROC from BASELINE_DIR."""
    if not BASELINE_DIR.exists():
        return
    for f in BASELINE_DIR.glob("*.parquet"):
        pd.read_parquet(f).to_parquet(DATA_PROC / f.name, index=False)


def load_scenario_frame(key: str, filename: str) -> pd.DataFrame:
    """Load a single parquet from a precomputed scenario dir.

    Falls back to DATA_PROC/filename if scenario key == 'base' and the
    scenarios/ dir doesn't exist yet (first run before build_scenarios.py).
    """
    d = scenario_dir(key)
    path = d / filename
    if path.exists():
        return pd.read_parquet(path)
    # Fallback for pre-build-scenarios state: use main DATA_PROC
    fallback = DATA_PROC / filename
    if fallback.exists():
        return pd.read_parquet(fallback)
    return pd.DataFrame()
