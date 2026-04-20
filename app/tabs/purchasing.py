"""Закупки и запасы — ABC/XYZ классификация + safety stock + reorder point.

Отвечает на вопросы категорийного менеджера:
  - Что держать в ядре ассортимента, а что — кандидаты на вывод?
  - Сколько буфера держать по каждому SKU, чтобы не было out-of-stock?
  - Когда запускать заказ?
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.style import COLORS, PLOTLY_LAYOUT
from src import maven_analysis as M


# ABC × XYZ матрица: цвет для каждого класса. Зелёный — ядро, красный — кандидат на вывод.
CLASS_COLORS = {
    "AX": "#16a34a", "AY": "#22c55e", "AZ": "#65a30d",
    "BX": "#2563eb", "BY": "#3b82f6", "BZ": "#60a5fa",
    "CX": "#94a3b8", "CY": "#f59e0b", "CZ": "#ef4444",
}


def render() -> None:
    st.markdown("### Закупки и запасы — ABC / XYZ + safety stock")
    st.caption(
        "**ABC** — классификация SKU по доле в выручке (A: до 80%, B: 80–95%, C: хвост). "
        "**XYZ** — по стабильности спроса: коэффициент вариации (X: <0.5, Y: 0.5–1.0, Z: ≥1.0). "
        "Safety stock считается по классической формуле: **z × σ × √L**, "
        "точка заказа = средний спрос × L + safety stock."
    )

    # ─── Controls ────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        service_level = st.selectbox(
            "Уровень обслуживания",
            list(M.SERVICE_LEVEL_Z.keys()),
            index=1,
            format_func=lambda v: f"{v:g}%",
            help="Вероятность того, что спрос в период поставки не превысит запас. "
                 "95% — стандарт для FMCG; 99% — для критичных SKU.",
        )
    with c2:
        lead_time = st.slider(
            "Время поставки, дней",
            min_value=1, max_value=14, value=3, step=1,
            help="Сколько дней проходит от момента заказа до прихода товара.",
        )
    with c3:
        show_category = st.selectbox(
            "Фильтр по категории",
            ["Все категории"] + sorted(M.load_raw()["product_category"].unique().tolist()),
            index=0,
        )

    table = M.safety_stock_table(service_level=float(service_level), lead_time_days=int(lead_time))
    if show_category != "Все категории":
        table = table[table["category"] == show_category]

    # ─── Headline KPIs ───────────────────────────────────────────────
    a_count = (table["abc"] == "A").sum()
    c_count = (table["abc"] == "C").sum()
    z_count = (table["xyz"] == "Z").sum()
    cz_count = (table["class"] == "CZ").sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "A-SKUs (ядро)",
        f"{a_count}",
        help=f"Приносят ~80% выручки. Из {len(table)} SKU в выборке.",
    )
    k2.metric(
        "C-SKUs (хвост)",
        f"{c_count}",
        help="Приносят 5% выручки, но создают 70% операционной нагрузки.",
    )
    k3.metric(
        "Z-SKUs (непредсказуемые)",
        f"{z_count}",
        help="CV ≥ 1.0 — спрос скачет. Требуют повышенного safety stock или выводятся.",
    )
    k4.metric(
        "CZ — кандидаты на вывод",
        f"{cz_count}",
        help="Мало выручки и нестабильный спрос. Прямая экономия оборотного капитала.",
    )

    # ─── ABC × XYZ heatmap ───────────────────────────────────────────
    st.markdown("#### Матрица ABC × XYZ — где деньги и где риск")
    abc_xyz_pivot = (
        table.groupby(["abc", "xyz"])
        .agg(n_sku=("product_detail", "count"), revenue=("revenue", "sum"))
        .reset_index()
    )
    abc_order = ["A", "B", "C"]
    xyz_order = ["X", "Y", "Z"]
    cell_sku = abc_xyz_pivot.pivot(index="abc", columns="xyz", values="n_sku").reindex(index=abc_order, columns=xyz_order).fillna(0)
    cell_rev = abc_xyz_pivot.pivot(index="abc", columns="xyz", values="revenue").reindex(index=abc_order, columns=xyz_order).fillna(0)

    text = [
        [
            f"<b>{int(cell_sku.loc[a, x])} SKU</b><br>{cell_rev.loc[a, x]/1_000_000:.1f} млн ₽"
            if cell_sku.loc[a, x] > 0 else ""
            for x in xyz_order
        ]
        for a in abc_order
    ]
    fig_m = go.Figure(
        data=go.Heatmap(
            z=cell_rev.values / 1_000_000,
            x=[f"<b>{x}</b><br>{'стабильный' if x=='X' else 'умеренный' if x=='Y' else 'скачет'}" for x in xyz_order],
            y=[f"<b>{a}</b><br>{'ядро' if a=='A' else 'середина' if a=='B' else 'хвост'}" for a in abc_order],
            text=text, texttemplate="%{text}",
            textfont={"size": 13, "color": COLORS["ink_bright"]},
            colorscale=[[0, "#1e293b"], [0.5, "#1e3a8a"], [1, "#60a5fa"]],
            showscale=True, colorbar={"title": "Выручка, млн ₽"},
            hovertemplate="ABC=%{y}<br>XYZ=%{x}<br>Выручка: %{z:.2f} млн ₽<extra></extra>",
        )
    )
    fig_m.update_layout(
        **PLOTLY_LAYOUT,
        height=320, margin=dict(l=120, r=40, t=30, b=60),
    )
    st.plotly_chart(fig_m, use_container_width=True)

    # ─── Pareto (cumulative revenue share) ───────────────────────────
    st.markdown("#### Парето — вклад SKU в выручку")
    pareto = table.sort_values("revenue", ascending=False).reset_index(drop=True)
    pareto["rank"] = pareto.index + 1
    fig_p = go.Figure()
    fig_p.add_trace(go.Bar(
        x=pareto["rank"], y=pareto["revenue"] / 1000,
        marker_color=[CLASS_COLORS.get(c, COLORS["neutral"]) for c in pareto["class"]],
        name="Выручка по SKU, тыс ₽",
        hovertemplate="<b>%{customdata[0]}</b><br>Класс: %{customdata[1]}<br>Выручка: %{y:,.0f} тыс ₽<extra></extra>",
        customdata=pareto[["product_detail", "class"]].values,
    ))
    fig_p.add_trace(go.Scatter(
        x=pareto["rank"], y=pareto["cum_share_pct"],
        mode="lines", name="Накопленная доля, %",
        yaxis="y2",
        line=dict(color=COLORS["brand_accent"], width=2),
    ))
    fig_p.add_hline(y=80, line_dash="dot", line_color=COLORS["good"], yref="y2", annotation_text="80% (граница A)", annotation_position="top right")
    fig_p.add_hline(y=95, line_dash="dot", line_color=COLORS["warning"], yref="y2", annotation_text="95% (граница B)", annotation_position="top right")
    fig_p.update_layout(
        **PLOTLY_LAYOUT,
        height=360,
        xaxis_title="Ранг SKU",
        yaxis_title="Выручка, тыс ₽",
        yaxis2=dict(title="Накопленная доля, %", overlaying="y", side="right", range=[0, 105]),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
        margin=dict(l=60, r=60, t=20, b=40),
    )
    st.plotly_chart(fig_p, use_container_width=True)

    # ─── Detailed table ──────────────────────────────────────────────
    st.markdown("#### Таблица SKU с safety stock и рекомендацией")
    disp = table.copy()
    disp["share_pct"] = disp["share_pct"].round(2)
    disp["cum_share_pct"] = disp["cum_share_pct"].round(1)
    disp["mean_daily_qty"] = disp["mean_daily_qty"].round(2)
    disp["std_daily_qty"] = disp["std_daily_qty"].round(2)
    disp["cv"] = disp["cv"].round(2)
    disp["revenue"] = disp["revenue"].round(0).astype(int)
    disp["safety_stock"] = disp["safety_stock"].round(1)
    disp["reorder_point"] = disp["reorder_point"].round(1)

    disp = disp.rename(columns={
        "product_detail": "SKU",
        "category": "Категория",
        "revenue": "Выручка, ₽",
        "share_pct": "Доля, %",
        "cum_share_pct": "Накопл., %",
        "abc": "ABC",
        "xyz": "XYZ",
        "class": "Класс",
        "mean_daily_qty": "Ср. спрос/день, шт",
        "std_daily_qty": "σ спроса, шт",
        "cv": "CV",
        "safety_stock": "Safety stock, шт",
        "reorder_point": "Точка заказа, шт",
        "recommendation": "Рекомендация",
    })[[
        "SKU", "Категория", "Класс", "Выручка, ₽", "Доля, %", "Накопл., %",
        "Ср. спрос/день, шт", "σ спроса, шт", "CV", "Safety stock, шт", "Точка заказа, шт",
        "Рекомендация",
    ]]
    st.dataframe(disp, use_container_width=True, hide_index=True, height=420)

    st.markdown(
        """
        <div style="color:#94a3b8;font-size:13px;margin-top:8px;">
        <b>Как читать:</b> SKU с классом AX — ядро: много выручки, стабильный спрос, держим
        на регулярном пополнении с низким буфером. AZ — «звёзды-сумасброды»: много выручки,
        но спрос скачет, нужен повышенный safety stock. CZ — мало выручки и нестабильный
        спрос, прямой кандидат на вывод из ассортимента.
        </div>
        """,
        unsafe_allow_html=True,
    )
