"""
OEE (Overall Equipment Effectiveness) simulation with Monte Carlo.

For each line and each replication we sample the stochastic disruptions that
affect real production, then compute OEE via the Six Big Losses waterfall:

    Planned Production Time
      - Scheduled breaks                          (planned, not a loss)
      = Operating Time
      - Breakdowns         (Availability #1)     MTBF/MTTR
      - Changeovers        (Availability #2)     from schedule (deterministic)
      = Run Time
      - Reduced speed      (Performance #3)     normal distribution around ideal rate
      - Minor stops        (Performance #4)     Poisson process
      = Net Run Time
      - Production rejects (Quality #5)          3% baseline
      - Startup rejects    (Quality #6)          15% during first 5 min after changeover
      = Fully Productive Time

OEE = Fully Productive / Planned = Availability × Performance × Quality

50 Monte Carlo replications produce distributions over each loss so the
dashboard can show confidence intervals and per-line drill-downs.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_PROC = ROOT / "data" / "processed"

MTBF_MIN = 150.0       # mean minutes between breakdowns
MTTR_LOG_MEAN = np.log(15.0)   # log-normal repair time ~15 min median
MTTR_LOG_SIGMA = 0.4
MINOR_STOP_LAMBDA = 1 / 30.0   # ~1 minor stop per 30 min of run time
MINOR_STOP_MEAN_DUR = 2.0       # average 2 min per minor stop
REDUCED_SPEED_MEAN = 0.93       # actual rate = 93% of nameplate (average)
REDUCED_SPEED_SIGMA = 0.04
BASELINE_REJECT = 0.03
STARTUP_REJECT = 0.15
STARTUP_WINDOW_MIN = 5
SCHEDULED_BREAK_MIN = 60        # 1 hour per shift for breaks


def load_schedule(mode: str = "optimized") -> pd.DataFrame:
    return pd.read_parquet(DATA_PROC / "schedule.parquet").query("mode == @mode").copy()


def _line_deterministic(grp: pd.DataFrame, horizon_min: int) -> dict:
    """Deterministic quantities from the schedule (no randomness)."""
    grp = grp.sort_values("start_min").reset_index(drop=True)
    last_end = int(grp["end_min"].max())
    scheduled_idle = max(0, horizon_min - last_end)
    # Changeovers = gaps BETWEEN consecutive ops (excluding the initial warmup,
    # which counts as startup setup loss, and excluding trailing idle which
    # counts as scheduled_idle).
    gaps = []
    prev_end = int(grp["end_min"].iloc[0])
    for _, row in grp.iloc[1:].iterrows():
        gap = int(row["start_min"]) - prev_end
        gaps.append(max(0, gap))
        prev_end = int(row["end_min"])
    initial_setup = int(grp["start_min"].iloc[0])
    changeover_min = sum(gaps) + initial_setup
    total_run_min = int(grp["duration_min"].sum())
    total_units = float(grp["qty"].sum())
    # Number of SKU starts = number of startup windows
    n_starts = len(grp)
    return {
        "horizon_min": horizon_min,
        "last_end_min": last_end,
        "scheduled_idle_min": scheduled_idle,
        "changeover_min": changeover_min,
        "total_run_min": total_run_min,
        "total_units": total_units,
        "n_starts": n_starts,
    }


def simulate_line(line: str, grp: pd.DataFrame, horizon_min: int, rng: np.random.Generator) -> dict:
    d = _line_deterministic(grp, horizon_min)
    planned = d["horizon_min"]
    # Scale break proportionally to line's scheduled time (up to 60 min for full day)
    break_frac = min(1.0, planned / 480)
    break_min = int(SCHEDULED_BREAK_MIN * break_frac)
    operating = max(1, planned - break_min)

    # Breakdowns: number ~ Poisson(operating / MTBF), duration ~ lognormal
    n_bd = rng.poisson(operating / MTBF_MIN)
    breakdown_min = float(rng.lognormal(MTTR_LOG_MEAN, MTTR_LOG_SIGMA, size=n_bd).sum()) if n_bd > 0 else 0.0
    # Clip breakdowns to not exceed (operating - changeovers - idle)
    avail_budget = operating - d["changeover_min"] - d["scheduled_idle_min"]
    breakdown_min = min(breakdown_min, max(0, avail_budget))

    run_time = max(0, operating - breakdown_min - d["changeover_min"] - d["scheduled_idle_min"])

    # Reduced speed: uniform scaling
    speed_factor = float(rng.normal(REDUCED_SPEED_MEAN, REDUCED_SPEED_SIGMA))
    speed_factor = min(1.0, max(0.6, speed_factor))
    reduced_speed_min = run_time * (1 - speed_factor)

    # Minor stops
    n_minor = rng.poisson(run_time * MINOR_STOP_LAMBDA)
    minor_stop_min = float(rng.exponential(MINOR_STOP_MEAN_DUR, size=n_minor).sum()) if n_minor > 0 else 0.0
    minor_stop_min = min(minor_stop_min, max(0, run_time - reduced_speed_min))

    net_run = max(0, run_time - reduced_speed_min - minor_stop_min)

    # Quality
    total_units = d["total_units"]
    # Startup rejects: during first STARTUP_WINDOW_MIN of each run
    # Fraction of production in startup windows:
    # For each op with duration dur_i, startup fraction = min(STARTUP_WINDOW, dur_i) / dur_i
    startup_units = 0.0
    for _, row in grp.iterrows():
        dur = int(row["duration_min"])
        qty = float(row["qty"])
        fraction = min(STARTUP_WINDOW_MIN, dur) / max(1, dur)
        startup_units += qty * fraction
    startup_units_lost = startup_units * STARTUP_REJECT
    normal_units = total_units - startup_units
    normal_units_lost = normal_units * BASELINE_REJECT
    total_rejects = startup_units_lost + normal_units_lost
    good_units = max(0, total_units - total_rejects)

    avg_rate = total_units / max(1, d["total_run_min"])
    reject_min = total_rejects / max(1e-6, avg_rate)
    fully_productive = max(0, net_run - reject_min)

    availability = run_time / operating if operating > 0 else 0
    performance = net_run / run_time if run_time > 0 else 0
    quality = good_units / total_units if total_units > 0 else 1.0
    oee = availability * performance * quality

    return {
        "line": line,
        "planned_min": planned,
        "operating_min": operating,
        "break_min": break_min,
        "scheduled_idle_min": d["scheduled_idle_min"],
        "changeover_min": d["changeover_min"],
        "breakdown_min": breakdown_min,
        "run_min": run_time,
        "reduced_speed_min": reduced_speed_min,
        "minor_stop_min": minor_stop_min,
        "net_run_min": net_run,
        "startup_reject_units": startup_units_lost,
        "normal_reject_units": normal_units_lost,
        "reject_min": reject_min,
        "fully_productive_min": fully_productive,
        "total_units": total_units,
        "good_units": good_units,
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": oee,
        "n_breakdowns": n_bd,
        "n_minor_stops": n_minor,
        "speed_factor": speed_factor,
    }


def simulate_one_run(schedule: pd.DataFrame, seed: int) -> list[dict]:
    """Each line uses its OWN last-end-min as planned time.

    This measures how well the line uses its scheduled production window.
    """
    rng = np.random.default_rng(seed)
    out = []
    for line, grp in schedule.groupby("line"):
        # Planned per line = last_end_min on that line (the time we committed to)
        line_horizon = int(grp["end_min"].max())
        out.append(simulate_line(line, grp, line_horizon, rng))
    return out


def monte_carlo(schedule: pd.DataFrame, n_runs: int = 50, seed0: int = 42) -> pd.DataFrame:
    rows = []
    for k in range(n_runs):
        for m in simulate_one_run(schedule, seed=seed0 + k):
            m["run_id"] = k
            rows.append(m)
    return pd.DataFrame(rows)


def build_waterfall(agg: pd.DataFrame) -> pd.DataFrame:
    mean_by_line = agg.groupby("line").mean(numeric_only=True).reset_index()
    planned = mean_by_line["planned_min"].sum()
    break_loss = mean_by_line["break_min"].sum() if "break_min" in mean_by_line.columns else SCHEDULED_BREAK_MIN * len(mean_by_line)
    operating = planned - break_loss
    breakdowns = mean_by_line["breakdown_min"].sum()
    changeovers = mean_by_line["changeover_min"].sum()
    scheduled_idle = mean_by_line["scheduled_idle_min"].sum()
    run_time = operating - breakdowns - changeovers - scheduled_idle
    reduced_speed = mean_by_line["reduced_speed_min"].sum()
    minor_stops = mean_by_line["minor_stop_min"].sum()
    net_run = run_time - reduced_speed - minor_stops
    reject_min = mean_by_line["reject_min"].sum()
    fully_productive = net_run - reject_min

    steps_raw = [
        ("Planned Production Time", planned, "total"),
        ("Scheduled breaks", -break_loss, "planned_loss"),
        ("Operating Time", operating, "subtotal"),
        ("Breakdowns", -breakdowns, "availability_loss"),
        ("Changeovers", -changeovers, "availability_loss"),
        ("Scheduled idle", -scheduled_idle, "availability_loss"),
        ("Run Time", run_time, "subtotal"),
        ("Reduced speed", -reduced_speed, "performance_loss"),
        ("Minor stops", -minor_stops, "performance_loss"),
        ("Net Run Time", net_run, "subtotal"),
        ("Production rejects", -reject_min * 0.6, "quality_loss"),
        ("Startup rejects", -reject_min * 0.4, "quality_loss"),
        ("Fully Productive", fully_productive, "final"),
    ]
    # Drop negligible (<1 min absolute) losses to de-clutter the waterfall
    cleaned = []
    for step, val, kind in steps_raw:
        if kind in ("total", "subtotal", "final"):
            cleaned.append((step, val, kind))
            continue
        if abs(val) < 1.0:
            continue
        cleaned.append((step, val, kind))
    wf = pd.DataFrame(cleaned, columns=["step", "minutes", "kind"])
    return wf


def build_six_big_losses(agg: pd.DataFrame) -> pd.DataFrame:
    """Aggregate six big losses (mean across runs, sum across lines)."""
    per_run = agg.groupby("run_id").sum(numeric_only=True)
    means = per_run.mean()
    # Convert reject units into minutes via line-averaged rate
    overall_rate = agg["total_units"].sum() / max(1, agg["run_min"].sum())
    startup_min = agg.groupby("run_id")["startup_reject_units"].sum().mean() / max(1e-6, overall_rate)
    normal_min = agg.groupby("run_id")["normal_reject_units"].sum().mean() / max(1e-6, overall_rate)
    rows = [
        {"loss": "1. Breakdowns", "category": "Availability", "minutes": float(means["breakdown_min"])},
        {"loss": "2. Changeovers", "category": "Availability", "minutes": float(means["changeover_min"])},
        {"loss": "3. Reduced speed", "category": "Performance", "minutes": float(means["reduced_speed_min"])},
        {"loss": "4. Minor stops", "category": "Performance", "minutes": float(means["minor_stop_min"])},
        {"loss": "5. Production rejects", "category": "Quality", "minutes": normal_min},
        {"loss": "6. Startup rejects", "category": "Quality", "minutes": startup_min},
    ]
    df = pd.DataFrame(rows)
    df["cost_rub"] = df["minutes"] * 3500   # assumption: 3500 rub/min of lost capacity
    return df


def main():
    print("Loading OPTIMIZED schedule...")
    sched_opt = load_schedule("optimized")
    if sched_opt.empty:
        raise RuntimeError("run scheduling first")
    print(f"  {len(sched_opt)} jobs across {sched_opt['line'].nunique()} lines")

    print("Monte Carlo: 50 replications for OPTIMIZED...")
    agg_opt = monte_carlo(sched_opt, n_runs=50)
    agg_opt["mode"] = "optimized"

    print("Monte Carlo: 50 replications for NAIVE...")
    sched_naive = load_schedule("naive")
    agg_naive = monte_carlo(sched_naive, n_runs=50) if not sched_naive.empty else pd.DataFrame()
    if not agg_naive.empty:
        agg_naive["mode"] = "naive"

    agg = pd.concat([agg_opt, agg_naive], ignore_index=True) if not agg_naive.empty else agg_opt
    agg.to_parquet(DATA_PROC / "oee_results.parquet", index=False)

    wf = build_waterfall(agg_opt)
    wf.to_parquet(DATA_PROC / "oee_waterfall.parquet", index=False)
    six = build_six_big_losses(agg_opt)
    six.to_parquet(DATA_PROC / "six_big_losses.parquet", index=False)

    # Also build waterfall for naive for comparison
    if not agg_naive.empty:
        wf_n = build_waterfall(agg_naive).rename(columns={"minutes": "minutes_naive"})
        wf_merged = wf.merge(wf_n[["step", "minutes_naive"]], on="step", how="left")
        wf_merged.to_parquet(DATA_PROC / "oee_waterfall_comparison.parquet", index=False)

    print("\nMean OEE by line & mode:")
    print(agg.groupby(["mode", "line"])["oee"].agg(["mean", "std"]).round(3).to_string())
    print("\nOverall OEE:")
    for mode in agg["mode"].unique():
        s = agg[agg["mode"] == mode]
        overall = (s["fully_productive_min"].sum() / s["planned_min"].sum())
        print(f"  {mode}: {overall:.3f} ({overall*100:.1f}%)")
    print("\nSix big losses (optimized):")
    print(six.round(1).to_string(index=False))
    print("Done.")


if __name__ == "__main__":
    main()
