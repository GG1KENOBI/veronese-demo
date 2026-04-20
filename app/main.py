"""Maven Roasters Analytics — простая 2-секционная страница.

Секция 1: EDA — 8 графиков с выводами про датасет
Секция 2: Forecast — прогноз выручки на 30/60/90 дней через ансамбль моделей

Решение стандартной Kaggle-задачи на открытом датасете Maven Roasters.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tabs import eda as tab_eda  # noqa: E402
from app.tabs import maven_forecast as tab_forecast  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Maven Roasters — Analytics & Forecast",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ─────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────
st.markdown("# ☕ Maven Roasters — Analytics & Forecast")
st.markdown(
    "<div style='color:#94a3b8;font-size:15px;margin-top:-12px;margin-bottom:4px;'>"
    "Разбор кофейного датасета с Kaggle: EDA + прогноз выручки на 30–90 дней."
    "</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div style='color:#64748b;font-size:13px;margin-bottom:24px;'>"
    "📊 Датасет: "
    "<a href='https://www.kaggle.com/datasets/agungpambudi/trends-product-coffee-shop-sales-revenue-dataset' "
    "target='_blank' style='color:#60a5fa;'>Maven Roasters Coffee Shop Sales (Kaggle)</a>. "
    "149 116 транзакций, 6 месяцев, 3 магазина в Нью-Йорке, 80 SKU. "
    "Стек: pandas · Plotly · Streamlit · Nixtla StatsForecast."
    "</div>",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────
# Tabs: EDA + Forecast
# ─────────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📈 EDA — анализ данных", "🔮 Forecast — прогноз выручки"])

with tab1:
    tab_eda.render()

with tab2:
    tab_forecast.render()


# ─────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Открытый разбор Kaggle-датасета. "
    "[Исходный код на GitHub](https://github.com/GG1KENOBI/veronese-demo) · "
    "[Датасет на Kaggle](https://www.kaggle.com/datasets/agungpambudi/trends-product-coffee-shop-sales-revenue-dataset) · "
    "Построено на открытом стеке: pandas, Plotly, Streamlit, Nixtla StatsForecast."
)
