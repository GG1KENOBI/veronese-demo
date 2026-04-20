"""Смены бариста — почасовая нагрузка → расчёт штата и расписания.

Отвечает на вопросы операционного менеджера:
  - Сколько бариста нужно в каждый час на каждой точке?
  - Где в расписании overstaffing, а где — очереди?
  - Сколько бариста-часов в неделю и как они распределены по точкам?
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from app.style import COLORS, PLOTLY_LAYOUT
from src import maven_analysis as M


def render() -> None:
    st.markdown("### Смены бариста — расчёт штата по почасовой нагрузке")
    st.caption(
        "Из транзакций собираем средний поток клиентов в каждый час × день недели × точка. "
        "Делим на пропускную способность одного бариста — получаем рекомендуемое число "
        "сотрудников в каждый слот. Подход стандартный для QSR и сетей кофеен: "
        "**baristas = ⌈tx_per_hour / throughput⌉**, с минимумом в открытые часы."
    )

    stores = sorted(M.load_raw()["store_location"].unique().tolist())

    # ─── Controls ────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([1.4, 1, 1])
    with c1:
        store = st.selectbox("Точка", stores, index=0)
    with c2:
        throughput = st.slider(
            "Транзакций на бариста в час",
            min_value=15, max_value=60, value=30, step=5,
            help="Сколько чеков один бариста успевает обработать за час. "
                 "Типично для specialty-кофе: 25–35 tx/час в пик.",
        )
    with c3:
        min_open = st.slider(
            "Минимум в открытые часы",
            min_value=1, max_value=3, value=1, step=1,
            help="Нижняя граница штата пока точка работает.",
        )

    matrix_baristas, matrix_tx = M.barista_need_matrix(
        store, throughput_per_hour=float(throughput), min_baristas_open=int(min_open)
    )
    if matrix_baristas is None or matrix_baristas.empty:
        st.warning(f"Нет данных по точке «{store}».")
        return

    stats = M.weekly_barista_hours(store, throughput_per_hour=float(throughput))

    # ─── Headline KPIs ───────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Бариста-часов в неделю",
        f"{stats['barista_hours']}",
        help="Суммарный штат-часы по рекомендации для всех слотов за неделю.",
    )
    k2.metric(
        "Средняя загрузка",
        f"{stats['avg_utilization']:.0f}%",
        help="Фактические транзакции / (число бариста × throughput). "
             "Если <50% — перегружено штатом. Если >90% — очереди.",
    )
    k3.metric(
        "Пиковый час",
        f"{stats['peak_hour']:02d}:00",
        help="Когда больше всего транзакций в среднем по неделе.",
    )
    k4.metric(
        "Пик, tx/час",
        f"{stats['peak_tx']:.0f}",
        help="Среднее число транзакций в пиковый час.",
    )

    # ─── Heatmap: baristas needed ────────────────────────────────────
    st.markdown(f"#### Рекомендуемое число бариста по слотам — {store}")

    hours = list(matrix_baristas.columns)
    days = list(matrix_baristas.index)
    z = matrix_baristas.values
    text = [[str(int(v)) if v > 0 else "" for v in row] for row in z]

    fig = go.Figure(data=go.Heatmap(
        z=z,
        x=[f"{h:02d}" for h in hours],
        y=days,
        text=text, texttemplate="%{text}",
        textfont={"size": 13, "color": COLORS["ink_bright"]},
        colorscale=[
            [0, "#0f172a"],
            [0.25, "#1e3a8a"],
            [0.5, "#2563eb"],
            [0.75, "#60a5fa"],
            [1, "#fbbf24"],
        ],
        colorbar={"title": "Бариста"},
        hovertemplate="%{y}, %{x}:00<br><b>%{z} бариста</b><extra></extra>",
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT,
        height=340,
        xaxis_title="Час",
        yaxis_title="",
        margin=dict(l=40, r=40, t=10, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ─── Hourly load profile (среднее по неделе) ─────────────────────
    st.markdown("#### Почасовой профиль загрузки — будни vs выходные")
    weekday_idx = [d for d in ["Пн", "Вт", "Ср", "Чт", "Пт"] if d in matrix_tx.index]
    weekend_idx = [d for d in ["Сб", "Вс"] if d in matrix_tx.index]

    weekday_avg = matrix_tx.loc[weekday_idx].mean(axis=0) if weekday_idx else None
    weekend_avg = matrix_tx.loc[weekend_idx].mean(axis=0) if weekend_idx else None

    fig2 = go.Figure()
    if weekday_avg is not None:
        fig2.add_trace(go.Scatter(
            x=[f"{h:02d}:00" for h in weekday_avg.index],
            y=weekday_avg.values,
            mode="lines+markers", name="Будни (Пн–Пт)",
            line=dict(color=COLORS["brand_primary"], width=2.5),
        ))
    if weekend_avg is not None:
        fig2.add_trace(go.Scatter(
            x=[f"{h:02d}:00" for h in weekend_avg.index],
            y=weekend_avg.values,
            mode="lines+markers", name="Выходные (Сб–Вс)",
            line=dict(color=COLORS["warning"], width=2.5),
        ))
    # Threshold: сколько tx/час равно 1 бариста в пределе throughput
    fig2.add_hline(
        y=float(throughput), line_dash="dot", line_color=COLORS["good"],
        annotation_text=f"Предел 1 бариста = {throughput} tx/час",
        annotation_position="top right",
    )
    fig2.update_layout(
        **PLOTLY_LAYOUT,
        height=320,
        xaxis_title="Час",
        yaxis_title="Среднее tx/час",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
        margin=dict(l=60, r=20, t=20, b=40),
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ─── Stores comparison ───────────────────────────────────────────
    st.markdown("#### Сравнение точек — бариста-часов в неделю")
    comp = []
    for s in stores:
        st_stats = M.weekly_barista_hours(s, throughput_per_hour=float(throughput))
        comp.append({
            "store": s,
            "barista_hours": st_stats["barista_hours"],
            "utilization": st_stats["avg_utilization"],
            "peak_tx": st_stats["peak_tx"],
        })

    fig3 = go.Figure()
    fig3.add_trace(go.Bar(
        x=[c["store"] for c in comp],
        y=[c["barista_hours"] for c in comp],
        marker_color=[COLORS["brand_accent"] if c["store"] == store else COLORS["brand_deep"] for c in comp],
        text=[f"{c['barista_hours']} ч<br>загрузка {c['utilization']:.0f}%" for c in comp],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Бариста-часов: %{y}<extra></extra>",
    ))
    fig3.update_layout(
        **PLOTLY_LAYOUT,
        height=300,
        yaxis_title="Бариста-часов/неделя",
        margin=dict(l=60, r=20, t=40, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig3, use_container_width=True)

    st.markdown(
        """
        <div style="color:#94a3b8;font-size:13px;margin-top:8px;">
        <b>Что делать с этим графиком:</b> «низкая средняя загрузка + высокие бариста-часы»
        на какой-то точке — кандидат на пересмотр расписания: можно сократить штат в нижние
        часы и добавить в пик. «Загрузка &gt; 90% в пиковый час» — очереди, нужна
        дополнительная смена или экспресс-касса.
        </div>
        """,
        unsafe_allow_html=True,
    )
