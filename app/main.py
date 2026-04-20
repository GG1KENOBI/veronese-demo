"""Аналитика сети кофеен — простая 2-секционная страница.

Секция 1: EDA — 8 графиков с выводами по транзакционным данным
Секция 2: Forecast — прогноз выручки на 30/60/90 дней через ансамбль моделей

Данные: анонимизированная выборка транзакций специализированной сети
кофеен (3 региона РФ, 6 месяцев). Клиент под NDA.
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
    page_title="Аналитика сети кофеен — EDA + Forecast",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ─────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────
st.markdown("# ☕ Аналитика сети кофеен — EDA + Forecast")
st.markdown(
    "<div style='color:#94a3b8;font-size:15px;margin-top:-12px;margin-bottom:4px;'>"
    "Разбор транзакционных данных сети из 3 регионов РФ: EDA + прогноз выручки на 30–90 дней."
    "</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<div style='color:#64748b;font-size:13px;margin-bottom:24px;'>"
    "🔒 <b>Данные анонимизированы</b> (клиент под NDA). "
    "149 116 транзакций · 6 месяцев · 3 точки (Москва, СПб, Екатеринбург) · 80 SKU. "
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
    "Разбор выполнен на анонимизированной выборке. Имя клиента, география точек и "
    "конкретные цифры заменены на соразмерные. "
    "Стек: pandas · Plotly · Streamlit · Nixtla StatsForecast. "
    "Готовы повторить на ваших данных за 2 недели discovery."
)
