"""
Multi-item Capacitated Lot-Sizing Problem (CLSP) for coffee production planning.

Formulation (minimize total cost):
  min sum_{j,l,t} c_prod_jl * x_jlt
    + sum_{j,l,t} c_setup * y_jlt
    + sum_{j,t}   c_hold_j * I_jt
    + sum_{j,t}   c_back * B_jt

Subject to:
  Inventory balance:   I_{j,t-1} + sum_l x_jlt - I_jt + B_jt - B_{j,t-1} = d_jt
  Line capacity:       sum_j (a_jl * x_jlt + st_jl * y_jlt) <= C_lt
  Setup-production:    x_jlt <= M_jl * y_jlt
  Eligibility:         x_jlt = 0 for (j,l) not in E
  Safety stock:        I_jt >= SS_j          (soft via backorder)
  Min lot size:        x_jlt >= q_min_j * y_jlt (currently disabled for feasibility)

Solver: HiGHS via Pyomo appsi.

Outputs:
  - data/processed/production_plan.parquet (x_jlt, I_jt, B_jt, y_jlt)
  - data/processed/shadow_prices.parquet   (line×week dual values)
  - data/processed/cost_breakdown.parquet  (production/setup/holding/backorder)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyomo.environ as pyo
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA_PROC = ROOT / "data" / "processed"
CONFIG = ROOT / "config"


def load_inputs(horizon_weeks: int = 12, forecast_col: str = "Ensemble"):
    """Load forecasts and production params, aggregate to weekly demand."""
    forecasts = pd.read_parquet(DATA_PROC / "forecasts.parquet")
    hier = pd.read_parquet(DATA_PROC / "hier_tags.parquet")
    params = pd.read_parquet(DATA_PROC / "production_params.parquet")

    # Filter to bottom level (SKU) only; unique_id format: form/brand/sku
    sku_mask = forecasts["unique_id"].str.count("/") == 2
    fc = forecasts[sku_mask].copy()
    fc["sku_id"] = fc["unique_id"].str.split("/").str[-1]
    fc["ds"] = pd.to_datetime(fc["ds"])

    # Pick forecast column: prefer MinTrace reconciled, fallback to raw model
    available = [c for c in fc.columns if forecast_col in c]
    if available:
        col = available[0]
    else:
        # Find best reconciled column for any model
        cand = [c for c in fc.columns if "MinTrace_method-mint_shrink" in c and "-lo-" not in c and "-hi-" not in c]
        col = cand[0] if cand else "AutoETS"

    fc["y_hat"] = fc[col].clip(lower=0)
    # Forecasts are already WEEKLY; each unique_id × ds is one week
    fc["week"] = (fc.groupby("sku_id")["ds"].rank(method="dense") - 1).astype(int)

    weekly = fc.groupby(["sku_id", "week"])["y_hat"].sum().reset_index()
    weekly = weekly[weekly["week"] < horizon_weeks].copy()
    return weekly, params, col


def load_cost_params():
    with open(CONFIG / "production_lines.yaml") as f:
        cfg = yaml.safe_load(f)
    return cfg


def compute_capacities(params: pd.DataFrame, cfg: dict, horizon_weeks: int) -> dict:
    """Weekly capacity in units/week per line.

    Capacity = throughput_upm * shift_minutes * shifts_per_week * availability_base
    """
    caps = {}
    for L in cfg["packaging_lines"]:
        units_per_week = (
            L["throughput_units_per_minute"]
            * L["shift_minutes"]
            * L["shifts_per_week"]
            * L["availability_base"]
        )
        for t in range(horizon_weeks):
            caps[(L["id"], t)] = float(units_per_week)
    return caps


def compute_safety_stock(weekly_demand: pd.DataFrame, cfg: dict) -> dict:
    """SS_j = z * sigma_d * sqrt(L)."""
    z = cfg["service_level"]["z_value"]
    L = cfg["service_level"]["lead_time_weeks"]
    ss = {}
    for sku_id, g in weekly_demand.groupby("sku_id"):
        sigma = g["y_hat"].std()
        if np.isnan(sigma) or sigma < 1:
            sigma = g["y_hat"].mean() * 0.15
        ss[sku_id] = float(z * sigma * np.sqrt(L))
    return ss


def build_model(
    weekly: pd.DataFrame,
    params: pd.DataFrame,
    cfg: dict,
    horizon_weeks: int = 12,
    service_level: float = 0.95,
    capacity_multiplier: float = 1.0,
    setup_cost_multiplier: float = 1.0,
):
    """Construct Pyomo ConcreteModel."""
    m = pyo.ConcreteModel(name="CLSP")

    skus = sorted(weekly["sku_id"].unique())
    lines = [L["id"] for L in cfg["packaging_lines"]]
    periods = list(range(horizon_weeks))

    m.J = pyo.Set(initialize=skus)
    m.L = pyo.Set(initialize=lines)
    m.T = pyo.Set(initialize=periods)

    # --- Parameters ---
    demand = {(r.sku_id, r.week): float(r.y_hat) for r in weekly.itertuples()}
    # Fill missing (sku, week) with 0
    for j in skus:
        for t in periods:
            demand.setdefault((j, t), 0.0)
    m.d = pyo.Param(m.J, m.T, initialize=demand, default=0.0)

    caps = compute_capacities(params, cfg, horizon_weeks)
    # Apply capacity multiplier (for what-if)
    caps = {k: v * capacity_multiplier for k, v in caps.items()}
    m.C = pyo.Param(m.L, m.T, initialize=caps)

    # Cost parameters
    prod_cost = cfg["costs"]["production_cost_per_unit"]
    setup_cost = cfg["costs"]["setup_cost_rub"] * setup_cost_multiplier
    hold_cost = cfg["costs"]["holding_cost_per_unit_per_week"]
    back_cost = cfg["costs"]["backorder_cost_per_unit"]

    m.c_prod = pyo.Param(initialize=prod_cost)
    m.c_setup = pyo.Param(initialize=setup_cost)
    m.c_hold = pyo.Param(initialize=hold_cost)
    m.c_back = pyo.Param(initialize=back_cost)

    # Eligibility: (sku, line) -> 1 if eligible
    eligibility = {}
    line_speed = {}
    for r in params.itertuples():
        elig = r.eligible_lines.split(",")
        for L in lines:
            eligibility[(r.sku_id, L)] = 1 if L in elig else 0
        line_speed[r.sku_id] = r.speed_units_per_min

    # Production time coefficient a_jl: minutes per unit
    # We'll assume same speed for all eligible lines per SKU; ineligible set to very large
    def a_jl_init(m, j, l):
        if eligibility.get((j, l), 0) == 1:
            return 1.0 / line_speed[j]
        else:
            return 1e6  # effectively blocks
    m.a = pyo.Param(m.J, m.L, initialize=a_jl_init)

    # Setup time per line (in minutes) — use average changeover; conservative
    m.st = pyo.Param(m.J, m.L, initialize=30.0, mutable=False)

    # Capacity in minutes (convert units capacity to minutes)
    # Line capacity in minutes = shift_minutes * shifts_per_week * availability
    cap_mins = {}
    for L in cfg["packaging_lines"]:
        mins = L["shift_minutes"] * L["shifts_per_week"] * L["availability_base"]
        for t in periods:
            cap_mins[(L["id"], t)] = mins * capacity_multiplier
    m.CapMin = pyo.Param(m.L, m.T, initialize=cap_mins)

    # Safety stock
    ss = compute_safety_stock(weekly, cfg)
    m.SS = pyo.Param(m.J, initialize=ss, default=0.0)

    # Big-M per (SKU, line, period) — take the MIN of:
    #   (a) demand from t onward + safety stock (can't benefit from more)
    #   (b) line capacity in units that period (can't produce more physically)
    # This is the facility-location-style tight bound that dramatically speeds
    # up the MIP vs a loose global constant.
    bigM = {}
    for j in skus:
        for l in lines:
            for t in periods:
                remaining = sum(demand.get((j, s), 0) for s in periods if s >= t)
                demand_bound = remaining + ss.get(j, 0) + 1.0
                # Capacity bound: cap minutes / minutes per unit on this line
                if eligibility.get((j, l), 0) == 1:
                    cap_units = cap_mins[(l, t)] / max(1e-6, 1.0 / line_speed[j])
                    bigM[(j, l, t)] = min(demand_bound, cap_units)
                else:
                    bigM[(j, l, t)] = 0.0
    m.BigM = pyo.Param(m.J, m.L, m.T, initialize=bigM, mutable=False)

    # --- Variables ---
    m.x = pyo.Var(m.J, m.L, m.T, within=pyo.NonNegativeReals)
    m.I = pyo.Var(m.J, m.T, within=pyo.NonNegativeReals)
    m.y = pyo.Var(m.J, m.L, m.T, within=pyo.Binary)
    m.B = pyo.Var(m.J, m.T, within=pyo.NonNegativeReals)

    # --- Constraints ---
    # Eligibility
    def eligibility_rule(m, j, l, t):
        if eligibility.get((j, l), 0) == 0:
            return m.x[j, l, t] == 0
        return pyo.Constraint.Skip
    m.eligibility_con = pyo.Constraint(m.J, m.L, m.T, rule=eligibility_rule)

    # Inventory balance: I[t-1] + sum_l x - I[t] + B[t] - B[t-1] = d[t]
    def balance_rule(m, j, t):
        I_prev = 0 if t == 0 else m.I[j, t - 1]
        B_prev = 0 if t == 0 else m.B[j, t - 1]
        return I_prev + sum(m.x[j, l, t] for l in m.L) - m.I[j, t] + m.B[j, t] - B_prev == m.d[j, t]
    m.balance_con = pyo.Constraint(m.J, m.T, rule=balance_rule)

    # Capacity (minutes)
    def capacity_rule(m, l, t):
        return sum(m.a[j, l] * m.x[j, l, t] + m.st[j, l] * m.y[j, l, t] for j in m.J) <= m.CapMin[l, t]
    m.capacity_con = pyo.Constraint(m.L, m.T, rule=capacity_rule)

    # Setup-production link (tight per-(j,l,t) big-M)
    def setup_link_rule(m, j, l, t):
        return m.x[j, l, t] <= m.BigM[j, l, t] * m.y[j, l, t]
    m.setup_link_con = pyo.Constraint(m.J, m.L, m.T, rule=setup_link_rule)

    # Safety stock: I[j,t] >= SS_j (soft: backorder absorbs deficit)
    # We don't enforce hardly; SS influences effective demand via holding penalty
    # Instead: encourage holding SS via higher backorder penalty and low holding cost
    # As soft constraint, we add to balance by requiring ending inventory >= SS if feasible

    # Final-period safety stock (end of horizon planning buffer)
    def final_ss_rule(m, j):
        return m.I[j, max(periods)] >= m.SS[j]
    m.final_ss_con = pyo.Constraint(m.J, rule=final_ss_rule)

    # --- Objective ---
    def obj_rule(m):
        prod = sum(m.c_prod * m.x[j, l, t] for j in m.J for l in m.L for t in m.T)
        setup = sum(m.c_setup * m.y[j, l, t] for j in m.J for l in m.L for t in m.T)
        hold = sum(m.c_hold * m.I[j, t] for j in m.J for t in m.T)
        back = sum(m.c_back * m.B[j, t] for j in m.J for t in m.T)
        return prod + setup + hold + back
    m.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

    # Dual suffix is added later for LP resolve (not for MIP — HiGHS can't return MIP duals)
    return m


def solve(model, time_limit_sec: int = 25, mip_gap: float = 0.08, extract_duals: bool = True):
    """Solve MILP with HiGHS, then (optionally) fix binaries and resolve LP for duals.

    Two-stage: MIP gives the integer plan; LP relaxation with fixed y-vars
    produces valid shadow prices for the capacity constraints.

    Defaults: 25s time limit + 8% MIP gap — accepts near-feasible integer
    solutions quickly. For demo this produces a realistic plan within ~25s.
    """
    # Legacy interface: more reliable time-limit handling than appsi wrapper
    solver = pyo.SolverFactory("highs")
    result = solver.solve(
        model, tee=False,
        options={"time_limit": time_limit_sec, "mip_rel_gap": mip_gap},
    )

    if not extract_duals:
        return result

    # Store MIP y values, then relax integrality + fix at those values for LP resolve
    y_vals = {}
    for (j, l, t), var in model.y.items():
        v = pyo.value(var)
        y_vals[(j, l, t)] = 0 if v is None else int(round(v))

    # Relax binary domain to continuous, then fix to MIP value
    for (j, l, t), var in model.y.items():
        var.domain = pyo.NonNegativeReals
        var.setub(1.0)
        var.fix(y_vals[(j, l, t)])

    # Add dual suffix (LP problem now)
    model.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)

    lp_solver = pyo.SolverFactory("highs")
    try:
        lp_result = lp_solver.solve(
            model, tee=False, options={"time_limit": 20},
        )
    except Exception as exc:  # noqa: BLE001
        # Non-fatal — keep MIP solution, skip duals
        print(f"  [LP resolve skipped: {exc}]")
        lp_result = None

    # Restore domain for reuse
    for var in model.y.values():
        var.unfix()
        var.domain = pyo.Binary
    for (j, l, t), var in model.y.items():
        var.value = y_vals[(j, l, t)]

    return lp_result


def extract_solution(model):
    """Extract solution as DataFrames."""
    J = list(model.J)
    L = list(model.L)
    T = list(model.T)

    plan_rows = []
    for j in J:
        for l in L:
            for t in T:
                x_val = pyo.value(model.x[j, l, t])
                y_val = pyo.value(model.y[j, l, t])
                if x_val is not None and x_val > 1e-3:
                    plan_rows.append({
                        "sku_id": j, "line": l, "week": t,
                        "production_units": round(x_val, 2),
                        "setup": int(round(y_val or 0)),
                    })

    inv_rows = []
    for j in J:
        for t in T:
            I_val = pyo.value(model.I[j, t])
            B_val = pyo.value(model.B[j, t])
            inv_rows.append({
                "sku_id": j, "week": t,
                "inventory_end": round(I_val, 2),
                "backorder": round(B_val, 2),
                "safety_stock": round(pyo.value(model.SS[j]), 2),
            })

    plan_df = pd.DataFrame(plan_rows)
    inv_df = pd.DataFrame(inv_rows)

    # Shadow prices for capacity constraints (per line × week)
    # For <= constraints, a negative dual means "relaxing the RHS (more capacity)
    # would reduce cost"; we report absolute value as "rub saved per +1 min capacity"
    sp_rows = []
    if hasattr(model, "dual"):
        for l in L:
            for t in T:
                try:
                    con = model.capacity_con[l, t]
                    dual = model.dual.get(con, None)
                    if dual is not None:
                        dual_val = float(dual)
                        sp_rows.append({
                            "line": l, "week": t,
                            "dual_raw": dual_val,
                            "shadow_price_rub_per_min": abs(dual_val),
                            "capacity_min": pyo.value(model.CapMin[l, t]),
                            "binding": abs(dual_val) > 1e-4,
                        })
                except KeyError:
                    pass
    sp_df = pd.DataFrame(sp_rows)

    # Cost breakdown
    prod_total = sum(pyo.value(model.c_prod) * pyo.value(model.x[j, l, t])
                     for j in J for l in L for t in T)
    setup_total = sum(pyo.value(model.c_setup) * pyo.value(model.y[j, l, t])
                      for j in J for l in L for t in T)
    hold_total = sum(pyo.value(model.c_hold) * pyo.value(model.I[j, t])
                     for j in J for t in T)
    back_total = sum(pyo.value(model.c_back) * pyo.value(model.B[j, t])
                     for j in J for t in T)
    total = prod_total + setup_total + hold_total + back_total
    cost_df = pd.DataFrame([
        {"category": "Production", "rub": prod_total, "share": prod_total / total},
        {"category": "Setup", "rub": setup_total, "share": setup_total / total},
        {"category": "Holding", "rub": hold_total, "share": hold_total / total},
        {"category": "Backorder", "rub": back_total, "share": back_total / total},
    ])

    return plan_df, inv_df, sp_df, cost_df, total


def main(horizon_weeks: int = 12):
    print(f"Loading forecasts + params for horizon={horizon_weeks} weeks...")
    weekly, params, col = load_inputs(horizon_weeks=horizon_weeks)
    cfg = load_cost_params()
    print(f"  forecast column: {col}")
    print(f"  {weekly['sku_id'].nunique()} SKUs, {weekly['week'].max()+1} weeks")
    print(f"  total forecast demand: {weekly['y_hat'].sum():,.0f} units")

    print("Building CLSP model...")
    m = build_model(weekly, params, cfg, horizon_weeks=horizon_weeks)
    n_bin = sum(1 for v in m.y.values())
    n_cont = sum(1 for v in m.x.values()) + sum(1 for v in m.I.values()) + sum(1 for v in m.B.values())
    print(f"  variables: {n_bin} binary, {n_cont} continuous")

    print("Solving with HiGHS...")
    result = solve(m, time_limit_sec=60)
    print(f"  solver status: {result.solver.status}, termination: {result.solver.termination_condition}")
    print(f"  objective (total cost): {pyo.value(m.obj):,.0f} rub")

    print("Extracting solution...")
    plan_df, inv_df, sp_df, cost_df, total = extract_solution(m)
    plan_df.to_parquet(DATA_PROC / "production_plan.parquet", index=False)
    inv_df.to_parquet(DATA_PROC / "inventory_trajectory.parquet", index=False)
    sp_df.to_parquet(DATA_PROC / "shadow_prices.parquet", index=False)
    cost_df.to_parquet(DATA_PROC / "cost_breakdown.parquet", index=False)

    print(f"  plan rows: {len(plan_df)}")
    print(f"  total cost: {total:,.0f} rub")
    print(cost_df.to_string(index=False))
    print(f"\nTop bottleneck weeks (binding capacity):")
    bind = sp_df[sp_df["binding"]].sort_values("shadow_price_rub_per_min", ascending=False)
    if bind.empty:
        print("  (no binding capacity constraints — plenty of slack)")
    else:
        print(bind.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
