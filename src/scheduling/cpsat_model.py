"""
Detailed production scheduling with OR-Tools CP-SAT.

Focus: PACKAGING sequence optimization with sequence-dependent setup times.
(Roasting is modeled upstream as a batch process; degassing decouples roasting
and packaging. For scheduling demo, we focus on the packaging stage — the
primary source of changeover losses in coffee production.)

For a given week of the CLSP plan we:
  1. Convert weekly production into a one-day production slate (weekly / 5),
     so each SKU becomes one run on its assigned line.
  2. Build a CP-SAT model with three packaging lines as machines.
  3. Apply sequence-dependent setup times from the changeover matrix.
  4. Solve twice: NAIVE (alphabetical SKU order, forced) vs OPTIMIZED
     (CP-SAT picks the minimum-changeover sequence).
  5. Compare: total changeover minutes, makespan, utilization.

Output: schedule.parquet, changeover_breakdown.parquet, schedule_summary.parquet
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import yaml
from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[2]
DATA_PROC = ROOT / "data" / "processed"
CONFIG = ROOT / "config"

DAY_MINUTES = 24 * 60              # modeling horizon = 1 day
WEEK_TO_DAY = 1.0 / 2.0            # campaign day: produce ~1/2 of weekly volume (= realistic 2-day campaign)
MAX_RUN_MIN = 900                  # cap one SKU's run (demo readability)


def load_inputs():
    plan = pd.read_parquet(DATA_PROC / "production_plan.parquet")
    params = pd.read_parquet(DATA_PROC / "production_params.parquet")
    co = pd.read_parquet(DATA_PROC / "changeover_matrix.parquet")
    with open(CONFIG / "production_lines.yaml") as f:
        cfg = yaml.safe_load(f)
    return plan, params, co, cfg


def build_jobs_for_week(plan: pd.DataFrame, params: pd.DataFrame, week: int):
    """One job per SKU produced that week. Duration = weekly_qty / 5 / speed."""
    wp = plan[plan["week"] == week].copy()
    params_map = params.set_index("sku_id").to_dict(orient="index")
    jobs = []
    for _, row in wp.iterrows():
        sku = row["sku_id"]
        qty_day = row["production_units"] * WEEK_TO_DAY
        p = params_map[sku]
        dur = max(5, min(MAX_RUN_MIN, int(math.ceil(qty_day / p["speed_units_per_min"]))))
        jobs.append({
            "sku_id": sku,
            "line": row["line"],
            "qty": qty_day,
            "dur_min": dur,
            "blend": p["blend"],
            "roast_level": p["roast_level"],
            "is_flavored": bool(p["is_flavored"]),
            "is_decaf": bool(p["is_decaf"]),
            "package_type": p["package_type"],
            "package_size_g": p["package_size_g"],
        })
    return jobs


def build_setup_lookup(co_df: pd.DataFrame):
    """(from_sku, to_sku) -> packaging changeover minutes."""
    return {(r.from_sku, r.to_sku): int(r.packaging_min) for r in co_df.itertuples()}


def schedule_cpsat(
    jobs: list[dict],
    setup: dict,
    naive: bool = False,
    time_limit_sec: int = 30,
    horizon_min: int = DAY_MINUTES * 2,
):
    """Build and solve the packaging-only scheduling model.

    - One interval per job on its fixed line.
    - Circuit-based sequencing encodes changeover time as arc weight.
    - If naive=True, force alphabetical SKU order on each line.
    """
    m = cp_model.CpModel()
    lines = sorted({j["line"] for j in jobs})

    # Variables: start/end/interval per job
    start = {}
    end = {}
    interval = {}
    for j in jobs:
        jid = j["sku_id"]
        s = m.NewIntVar(0, horizon_min, f"s_{jid}")
        e = m.NewIntVar(0, horizon_min, f"e_{jid}")
        iv = m.NewIntervalVar(s, j["dur_min"], e, f"iv_{jid}")
        start[jid] = s
        end[jid] = e
        interval[jid] = iv

    # Group jobs by line
    by_line: dict[str, list[dict]] = {l: [] for l in lines}
    for j in jobs:
        by_line[j["line"]].append(j)

    # No-overlap per line
    for l in lines:
        m.AddNoOverlap([interval[j["sku_id"]] for j in by_line[l]])

    # Sequence-dependent setup times via circuit constraint
    changeover_lits = []  # (lit, minutes)

    for l, line_jobs in by_line.items():
        n = len(line_jobs)
        if n == 0:
            continue
        if n == 1:
            continue  # nothing to sequence

        # Nodes 1..n ; node 0 = virtual source/sink
        arcs = []
        # Source -> i : i is first
        for i, ji in enumerate(line_jobs, start=1):
            first = m.NewBoolVar(f"first_{l}_{ji['sku_id']}")
            arcs.append((0, i, first))
            last = m.NewBoolVar(f"last_{l}_{ji['sku_id']}")
            arcs.append((i, 0, last))
        # i -> j transitions
        for i, ji in enumerate(line_jobs, start=1):
            for j_, jj in enumerate(line_jobs, start=1):
                if i == j_:
                    continue
                a = ji["sku_id"]
                b = jj["sku_id"]
                lit = m.NewBoolVar(f"tr_{l}_{a}_{b}")
                arcs.append((i, j_, lit))
                st = setup.get((a, b), 15)
                m.Add(start[b] >= end[a] + st).OnlyEnforceIf(lit)
                changeover_lits.append((lit, st))
        m.AddCircuit(arcs)

    # Naive mode: force alphabetical order on each line
    if naive:
        for l, line_jobs in by_line.items():
            sids = sorted([j["sku_id"] for j in line_jobs])
            for a, b in zip(sids[:-1], sids[1:]):
                st = setup.get((a, b), 15)
                m.Add(start[b] >= end[a] + st)

    # Objective: minimize sum(3*setup) + makespan
    makespan = m.NewIntVar(0, horizon_min, "makespan")
    for j in jobs:
        m.Add(makespan >= end[j["sku_id"]])
    total_setup = sum(lit * st for lit, st in changeover_lits)
    m.Minimize(3 * total_setup + makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_sec
    solver.parameters.num_search_workers = 8
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, solver.StatusName(status)

    # Extract
    rows = []
    for j in jobs:
        jid = j["sku_id"]
        rows.append({
            "sku_id": jid,
            "line": j["line"],
            "start_min": solver.Value(start[jid]),
            "end_min": solver.Value(end[jid]),
            "duration_min": j["dur_min"],
            "qty": j["qty"],
            "blend": j["blend"],
            "roast_level": j["roast_level"],
            "is_flavored": j["is_flavored"],
            "is_decaf": j["is_decaf"],
            "package_type": j["package_type"],
            "package_size_g": j["package_size_g"],
        })
    sched = pd.DataFrame(rows).sort_values(["line", "start_min"]).reset_index(drop=True)

    setup_total = sum(solver.Value(lit) * st for lit, st in changeover_lits)
    return {
        "schedule": sched,
        "makespan_min": solver.Value(makespan),
        "total_setup_min": setup_total,
        "objective": solver.ObjectiveValue(),
        "status": solver.StatusName(status),
        "wall_time_s": solver.WallTime(),
    }, None


def compute_changeover_breakdown(sched: pd.DataFrame, co_df: pd.DataFrame) -> pd.DataFrame:
    """Classify each transition by reason (for stacked-bar breakdown)."""
    sched = sched.sort_values(["line", "start_min"]).reset_index(drop=True)
    rows = []
    for line, grp in sched.groupby("line"):
        prev = None
        for _, row in grp.iterrows():
            if prev is not None:
                pair = co_df[(co_df["from_sku"] == prev["sku_id"]) & (co_df["to_sku"] == row["sku_id"])]
                minutes = int(pair["packaging_min"].iloc[0]) if len(pair) else 0
                if prev["package_type"] != row["package_type"]:
                    cat = "Смена типа упаковки"
                elif prev["is_decaf"] != row["is_decaf"]:
                    cat = "Переход decaf ↔ regular"
                elif prev["is_flavored"] != row["is_flavored"]:
                    cat = "Ароматизация ↔ обычный"
                elif prev["roast_level"] != row["roast_level"]:
                    cat = "Смена уровня обжарки"
                elif prev["blend"] != row["blend"]:
                    cat = "Другой бленд"
                else:
                    cat = "Минимальная очистка"
                rows.append({
                    "line": line,
                    "from_sku": prev["sku_id"],
                    "to_sku": row["sku_id"],
                    "minutes": minutes,
                    "category": cat,
                })
            prev = row
    return pd.DataFrame(rows)


def main(week: int = 0):
    print(f"Loading plan + changeover matrix (week={week})...")
    plan, params, co, cfg = load_inputs()
    jobs = build_jobs_for_week(plan, params, week=week)
    print(f"  {len(jobs)} SKU jobs; lines: {sorted({j['line'] for j in jobs})}")
    setup = build_setup_lookup(co)

    print("Solving OPTIMIZED (CP-SAT, minimize 3*setup + makespan)...")
    opt, err = schedule_cpsat(jobs, setup, naive=False, time_limit_sec=45)
    if err:
        raise RuntimeError(f"Optimized solve failed: {err}")
    print(f"  makespan: {opt['makespan_min']:,} min ({opt['makespan_min']/60:.1f}h)")
    print(f"  total setup: {opt['total_setup_min']:,} min ({opt['total_setup_min']/60:.2f}h)")

    print("Solving NAIVE (alphabetical order on each line)...")
    nv, err = schedule_cpsat(jobs, setup, naive=True, time_limit_sec=30)
    if err:
        print(f"  naive fallback: {err}")
        nv = None
    else:
        print(f"  makespan: {nv['makespan_min']:,} min ({nv['makespan_min']/60:.1f}h)")
        print(f"  total setup: {nv['total_setup_min']:,} min ({nv['total_setup_min']/60:.2f}h)")

    # Save schedule
    opt_df = opt["schedule"].copy()
    opt_df["mode"] = "optimized"
    opt_df["week"] = week
    frames = [opt_df]
    if nv is not None:
        nv_df = nv["schedule"].copy()
        nv_df["mode"] = "naive"
        nv_df["week"] = week
        frames.append(nv_df)
    full = pd.concat(frames, ignore_index=True)
    full.to_parquet(DATA_PROC / "schedule.parquet", index=False)

    # Breakdown
    bd_frames = []
    for label, res in [("optimized", opt), ("naive", nv)]:
        if res is None:
            continue
        bd = compute_changeover_breakdown(res["schedule"], co)
        bd["mode"] = label
        bd_frames.append(bd)
    bd = pd.concat(bd_frames, ignore_index=True) if bd_frames else pd.DataFrame()
    bd.to_parquet(DATA_PROC / "changeover_breakdown.parquet", index=False)

    savings_min = (nv["total_setup_min"] - opt["total_setup_min"]) if nv else 0
    summary = pd.DataFrame([{
        "week": week,
        "optimized_makespan_h": opt["makespan_min"] / 60,
        "optimized_setup_h": opt["total_setup_min"] / 60,
        "naive_makespan_h": nv["makespan_min"] / 60 if nv else None,
        "naive_setup_h": nv["total_setup_min"] / 60 if nv else None,
        "setup_savings_min": savings_min,
        "setup_savings_h": savings_min / 60,
        "setup_savings_pct": (100 * savings_min / nv["total_setup_min"]) if nv and nv["total_setup_min"] > 0 else 0,
    }])
    summary.to_parquet(DATA_PROC / "schedule_summary.parquet", index=False)
    print("Summary:")
    print(summary.to_string(index=False))
    print("Scheduling complete.")


if __name__ == "__main__":
    main()
