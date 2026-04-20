"""Precompute all what-if scenarios at build time.

Runs `app.scenarios.run_scenario` for each entry in SCENARIOS and writes
the resulting parquets to `data/processed/scenarios/{key}/`.

Goal: eliminate 60-90 sec spinner at runtime. After this script runs
once, switching scenarios in the UI is an instant parquet-swap via
st.session_state.

Usage (from project root):
    python -m scripts.build_scenarios           # build all 5
    python -m scripts.build_scenarios base promo_dark_30  # build subset
    python -m scripts.build_scenarios --force   # rebuild even if exists

Expected wall time: ~5-7 min total (5 scenarios × ~60-90 sec each).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.scenarios import (  # noqa: E402
    DATA_PROC,
    SCENARIOS,
    SCENARIOS_DIR,
    scenario_dir,
    scenario_exists,
    run_scenario,
)


def _snapshot_base_outputs(output_dir: Path) -> None:
    """Copy the current DATA_PROC/*.parquet into output_dir.

    The 'base' scenario is whatever the main pipeline already produced
    (no modifications). We don't need to re-run solvers — just snapshot.
    """
    from app.scenarios import SCENARIO_OUTPUTS

    output_dir.mkdir(parents=True, exist_ok=True)
    for name in SCENARIO_OUTPUTS:
        src = DATA_PROC / name
        if src.exists():
            shutil.copy2(src, output_dir / name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "keys", nargs="*",
        help=f"Subset of scenario keys to build. Default: all ({', '.join(SCENARIOS.keys())})",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild even if scenario dir exists.")
    args = parser.parse_args(argv)

    keys_to_build = args.keys if args.keys else list(SCENARIOS.keys())
    unknown = [k for k in keys_to_build if k not in SCENARIOS]
    if unknown:
        print(f"Unknown scenario keys: {unknown}", file=sys.stderr)
        print(f"Available: {list(SCENARIOS.keys())}", file=sys.stderr)
        return 2

    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)

    total_start = time.time()
    for key in keys_to_build:
        spec = SCENARIOS[key]
        out_dir = scenario_dir(key)
        if scenario_exists(key) and not args.force:
            print(f"[skip]  {key:20s}  already built at {out_dir}")
            continue

        print(f"[build] {key:20s}  {spec['label']}")
        t0 = time.time()

        if key == "base":
            # No modifications — just snapshot the already-computed base outputs
            # that data/processed/ holds from the main pipeline run.
            _snapshot_base_outputs(out_dir)
        else:
            run_scenario(spec["id"], output_dir=out_dir)

        dt = time.time() - t0
        print(f"[done]  {key:20s}  in {dt:.1f}s → {out_dir}")

    total_dt = time.time() - total_start
    print(f"\nAll done in {total_dt:.1f}s. Scenarios live in {SCENARIOS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
