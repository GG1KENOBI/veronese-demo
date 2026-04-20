"""Hero strip — the first thing the user sees.

Design:
- Big number (+XXX млн ₽/год) dominates the fold
- 3 supporting KPIs under it (hours saved, coverage, OEE)
- Short 1-sentence narrative

Everything here is pure render, no side effects. Takes DemoData + wizard
inputs, computes, renders. Test without Streamlit by not calling render_*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import streamlit as st

from app.constants import CLIENT, format_mrub
from app.data import DemoData
from app.wizard import ClientInputs, compute_savings_mrub


@dataclass
class HeroKPIs:
    """Snapshot of the numbers that drive the hero strip."""

    hours_saved_per_day: float          # from sched_summary
    annual_savings_mrub: float          # derived from hours × client params
    coverage_pct: float                 # % of demand covered (0-100)
    oee_pct: float                      # optimized OEE (0-100)
    plan_cost_mrub: float               # total 12-week plan cost
    bottleneck: Optional[dict]          # {"line": ..., "week": ..., "price": ...}
    skus_at_risk: int                   # SKUs with backorder > 0


def compute_kpis(data: DemoData, inputs: ClientInputs) -> HeroKPIs:
    """Pure-function: derive the 7 numbers the hero strip displays."""
    hours_saved = 0.0
    if not data.sched_sum.empty:
        hours_saved = float(data.sched_sum.iloc[0]["setup_savings_h"])

    annual_mrub = compute_savings_mrub(hours_saved, inputs)

    plan_cost_mrub = 0.0
    if not data.cost.empty:
        plan_cost_mrub = data.cost["rub"].sum() / 1e6

    coverage = 100.0
    if not data.plan.empty and not data.inv.empty:
        total_planned = data.plan["production_units"].sum()
        total_shortage = data.inv["backorder"].sum()
        total_demand = max(1.0, total_planned + total_shortage)
        if total_planned > 0:
            coverage = 100 * (1 - total_shortage / total_demand)

    oee_pct = 0.0
    if not data.oee_res.empty:
        opt = data.oee_res[data.oee_res["mode"] == "optimized"] if "mode" in data.oee_res.columns else data.oee_res
        if not opt.empty:
            per_run = opt.groupby("run_id").apply(
                lambda g: g["fully_productive_min"].sum() / max(1e-6, g["planned_min"].sum()),
                include_groups=False,
            )
            oee_pct = float(per_run.mean()) * 100

    bottleneck = None
    if not data.sp.empty and "binding" in data.sp.columns:
        bind = data.sp[data.sp["binding"]].sort_values("shadow_price_rub_per_min", ascending=False)
        if not bind.empty:
            top = bind.iloc[0]
            bottleneck = {
                "line": top["line"],
                "week": int(top["week"]) + 1,
                "price": float(top["shadow_price_rub_per_min"]),
                "total": len(bind),
            }

    skus_at_risk = 0
    if not data.inv.empty:
        skus_at_risk = int((data.inv.groupby("sku_id")["backorder"].sum() > 0).sum())

    return HeroKPIs(
        hours_saved_per_day=hours_saved,
        annual_savings_mrub=annual_mrub,
        coverage_pct=coverage,
        oee_pct=oee_pct,
        plan_cost_mrub=plan_cost_mrub,
        bottleneck=bottleneck,
        skus_at_risk=skus_at_risk,
    )


# ─────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────

def render_big_number(kpis: HeroKPIs) -> None:
    """Giant +XXX млн ₽/год on one line. The sales moment."""
    amount = format_mrub(kpis.annual_savings_mrub)
    st.markdown(
        f"""
        <div style='text-align:left;padding:12px 0 4px 0;'>
          <div style='font-size:64px;font-weight:800;line-height:1.05;
                      color:#22c55e;letter-spacing:-1.5px;'>
            +{amount}/год
          </div>
          <div style='font-size:18px;color:#cbd5e1;margin-top:4px;'>
            на существующих линиях · без капитальных затрат · окупаемость {CLIENT.typical_payback_months_min}–{CLIENT.typical_payback_months_max} месяца
          </div>
          <div style='font-size:12px;color:#64748b;margin-top:6px;font-style:italic;'>
            Расчёт по вводным выше. Точная цифра — после discovery на реальных SKU.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_support_kpis(kpis: HeroKPIs) -> None:
    """3 supporting KPIs under the big number."""
    k1, k2, k3 = st.columns(3)
    k1.metric(
        "Освобождено часов производства в день",
        f"{kpis.hours_saved_per_day:.1f} ч",
        help="Столько часов в день сейчас уходит на лишние переналадки. Наш алгоритм их убирает.",
    )
    k2.metric(
        "Покрытие заказов",
        f"{kpis.coverage_pct:.1f}%",
        help="Какая доля заказов клиентов выполняется по плану. 100% = нет дефицита.",
    )
    k3.metric(
        "Эффективность линий (OEE)",
        f"{kpis.oee_pct:.1f}%",
        help="Overall Equipment Effectiveness: какая доля времени идёт на полезное производство. World-class 85%, FMCG-норма 60–75%.",
    )


def render_narrative(kpis: HeroKPIs) -> None:
    """Short context sentence. One emoji max, one line, real numbers."""
    bl = kpis.bottleneck
    parts: list[str] = []

    if kpis.skus_at_risk > 0:
        parts.append(
            f"⚠️ **{kpis.skus_at_risk} товаров в дефиците** — добавьте смену или аутсорс."
        )
    elif bl:
        parts.append(
            f"📍 Самое слабое звено: **линия {bl['line']}** на неделе **{bl['week']}**. "
            f"Час работы там = **{bl['price']*60:,.0f} ₽ экономии**.".replace(",", " ")
        )
    else:
        parts.append("✅ План сбалансирован, дефицита нет.")

    st.markdown("  \n".join(parts))
