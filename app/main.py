"""Retail Intelligence для сети кофеен — дашборд из 5 модулей.

Источник — анонимизированные транзакции specialty-сети (3 региона РФ, 6 мес 2023).

Модули:
  1. EDA — 8 графиков с выводами по транзакционным данным
  2. Forecast — прогноз выручки на 30/60/90 дней (ансамбль StatsForecast) +
     drill-down по точкам + coherence-check
  3. Закупки — ABC/XYZ классификация, safety stock, точка заказа
  4. Смены — почасовой профиль спроса → рекомендованное число бариста на слот
  5. What-If — симуляция промо-акций поверх baseline-прогноза

Stack: pandas · Plotly · Streamlit · Nixtla StatsForecast.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tabs import eda as tab_eda  # noqa: E402
from app.tabs import maven_forecast as tab_forecast  # noqa: E402
from app.tabs import purchasing as tab_purchasing  # noqa: E402
from app.tabs import shifts as tab_shifts  # noqa: E402
from app.tabs import whatif as tab_whatif  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Retail Intelligence — сеть кофеен",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ─────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────
st.markdown("# ☕ Retail Intelligence — сеть кофеен")
st.markdown(
    "<div style='color:#94a3b8;font-size:15px;margin-top:-12px;margin-bottom:4px;'>"
    "Прогноз спроса, закупки, смены и сценарный анализ на транзакционных данных "
    "сети из 3 регионов РФ."
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
# Tabs: 5 модулей Retail Intelligence
# ─────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 EDA — анализ данных",
    "🔮 Forecast — прогноз выручки",
    "📦 Закупки — ABC/XYZ + safety stock",
    "👥 Смены — штат бариста",
    "🎯 What-If — сценарии промо",
])

with tab1:
    tab_eda.render()

with tab2:
    tab_forecast.render()

with tab3:
    tab_purchasing.render()

with tab4:
    tab_shifts.render()

with tab5:
    tab_whatif.render()


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
