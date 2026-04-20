"""Thin Streamlit router — the only file Streamlit actually starts with.

Responsibilities (minimal):
1. set_page_config
2. Sidebar scenario picker
3. Top: hero (big savings number + wizard + KPIs)
4. Middle: schedule tab (main content, no tabs anymore)
5. Bottom: 3 expanders (Forecast / Plan / OEE) for drill-down

Logic lives in app/{data,hero,wizard,tabs/*}.
Constants live in config/client.yaml + app/constants.py.
Colors live in app/style.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.constants import CLIENT  # noqa: E402
from app.data import load_all  # noqa: E402
from app.hero import compute_kpis, render_big_number, render_narrative, render_support_kpis  # noqa: E402
from app.scenarios import SCENARIOS  # noqa: E402
from app.tabs import forecast as tab_forecast  # noqa: E402
from app.tabs import oee as tab_oee  # noqa: E402
from app.tabs import plan as tab_plan  # noqa: E402
from app.tabs import schedule as tab_schedule  # noqa: E402
from app.wizard import render_compact as render_wizard  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Оптимизация FMCG-кофе — прототип на открытом стеке",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="auto",
)


# ─────────────────────────────────────────────────────────────────────
# Sidebar — ONLY scenario selection (everything else moved into tabs)
# ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"### Сценарий «что если»")
    st.caption("Выберите — страница мгновенно пересчитается под этот сценарий.")

    scenario_labels = {key: spec["label"] for key, spec in SCENARIOS.items()}
    scenario_key = st.selectbox(
        "Сценарий",
        list(scenario_labels.keys()),
        index=0,
        format_func=lambda k: scenario_labels[k],
        label_visibility="collapsed",
    )
    st.caption(SCENARIOS[scenario_key].get("description", ""))

    st.markdown("---")
    st.markdown("### О прототипе")
    st.caption(
        "Прототип на открытом датасете **Maven Roasters** (Kaggle, 2 года транзакций) "
        "с параметрами производства, масштабированными до типичной FMCG-линии кофе. "
        "Солверы запускаются на реальных данных, не на заглушках."
    )
    st.caption(
        "Чтобы увидеть то же самое на ваших SKU и линиях — "
        "discovery 1-2 недели, далее прототип под ваш завод за 4-6 недель."
    )


# ─────────────────────────────────────────────────────────────────────
# Load data for selected scenario
# ─────────────────────────────────────────────────────────────────────
data = load_all(scenario_key=scenario_key)


# ─────────────────────────────────────────────────────────────────────
# Hero section — WIZARD first (so user's numbers affect the big cifra)
# ─────────────────────────────────────────────────────────────────────
st.markdown("# Оптимизация FMCG-кофейного производства")
st.markdown(
    "<div style='color:#94a3b8;font-size:15px;margin-top:-12px;margin-bottom:8px;'>"
    "Прогноз → план → расписание линий → OEE. Реальные солверы под капотом: "
    "StatsForecast, Pyomo + HiGHS (MILP), OR-Tools CP-SAT, Monte Carlo."
    "</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div style='color:#64748b;font-size:13px;margin-bottom:24px;'>"
    "🧪 <b>Открытый прототип</b> на датасете "
    "<a href='https://www.kaggle.com/datasets/agungpambudi/trends-product-coffee-shop-sales-revenue-dataset' "
    "target='_blank' style='color:#60a5fa;'>Maven Roasters (Kaggle, 2 года транзакций)</a>, "
    "масштабированном до unit-экономики FMCG-кофе. На ваших SKU — за 2 недели discovery."
    "</div>",
    unsafe_allow_html=True,
)

# ROI wizard (3 fields — lines, days, ₽/min)
with st.container(border=True):
    wizard_inputs = render_wizard(hours_saved_per_day=0.0)

# Big savings number + supporting KPIs
kpis = compute_kpis(data, wizard_inputs)
render_big_number(kpis)
render_support_kpis(kpis)
render_narrative(kpis)

st.markdown("---")


# ─────────────────────────────────────────────────────────────────────
# MAIN CONTENT: Schedule (the killer) — full width, always visible
# ─────────────────────────────────────────────────────────────────────
tab_schedule.render(data, wizard_inputs)

st.markdown("---")


# ─────────────────────────────────────────────────────────────────────
# Details below: Forecast / Plan / OEE as expanders
# ─────────────────────────────────────────────────────────────────────
st.markdown("### 🔎 Подробнее — прогноз, план, эффективность")

with st.expander("📈 Прогноз спроса (как мы знаем что сколько производить)"):
    tab_forecast.render(data)

with st.expander("📦 План производства (что и когда на каких линиях)"):
    tab_plan.render(data)

with st.expander("⚙️ Эффективность линий / OEE (для технолога)"):
    tab_oee.render(data)


# ─────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Открытый стек: StatsForecast (прогноз) · Pyomo + HiGHS (MILP-планирование) · "
    "OR-Tools CP-SAT (расписание) · Monte Carlo (OEE-симуляция). "
    f"Построено на данных {CLIENT.brand_style}. "
    "[Код на GitHub](https://github.com/GG1KENOBI/veronese-demo)."
)
