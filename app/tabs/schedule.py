"""Schedule tab — hero content of the demo.

This is THE killer block: animated Gantt showing naive → optimized
reordering, plus the "X hours saved / Y М₽/year" headline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.constants import CLIENT, format_mrub
from app.data import DemoData
from app.style import COLORS
from app.wizard import ClientInputs, compute_savings_mrub
from src.visualization.charts import animated_compare_gantt, gantt_chart


def _utilization_strip(sched_df: pd.DataFrame, title: str) -> go.Figure:
    """Thin heatmap strip: per-line utilization by 30-min buckets."""
    if sched_df.empty:
        return go.Figure()
    max_end = int(sched_df["end_min"].max()) + 60
    hours = list(range(0, max_end, 30))
    lines = sorted(sched_df["line"].unique())
    util = np.zeros((len(lines), len(hours)))
    for li, L in enumerate(lines):
        sub = sched_df[sched_df["line"] == L]
        for _, row in sub.iterrows():
            for hi, h in enumerate(hours):
                overlap = max(0, min(row["end_min"], h + 30) - max(row["start_min"], h))
                util[li, hi] += overlap / 30
        util[li] = np.clip(util[li], 0, 1)
    fig = go.Figure(go.Heatmap(
        z=util * 100,
        x=[f"{h//60:02d}:{h%60:02d}" for h in hours],
        y=lines,
        colorscale=[[0, "#1e293b"], [0.5, COLORS["info"]], [1, COLORS["good"]]],
        zmin=0, zmax=100,
        showscale=False,
        hovertemplate="%{y}<br>%{x}<br>Загрузка: %{z:.0f}%<extra></extra>",
    ))
    for shift_end in (480, 960, 1440):
        if shift_end < max_end:
            fig.add_vline(
                x=(shift_end // 30),
                line_dash="dot",
                line_color=COLORS["roast_light"],
                line_width=1,
            )
    fig.update_layout(
        height=130,
        margin=dict(l=40, r=20, t=8, b=20),
        title=dict(text=title, font=dict(size=12), x=0, y=0.95),
        xaxis=dict(showgrid=False, tickfont=dict(size=9)),
        yaxis=dict(tickfont=dict(size=10)),
    )
    return fig


def render(data: DemoData, inputs: ClientInputs) -> None:
    """Main Schedule content block. Always visible (not in expander)."""
    if data.sched.empty:
        st.warning(
            "Расписание ещё не посчитано. "
            "Запустите `./run_demo.sh` или `python -m scripts.build_scenarios`."
        )
        return

    # ---- Top: big savings headline derived from scheduled data + wizard
    if not data.sched_sum.empty:
        row = data.sched_sum.iloc[0].to_dict()
        hours_saved = float(row["setup_savings_h"])
        savings_pct = float(row["setup_savings_pct"])
        annual_mrub = compute_savings_mrub(hours_saved, inputs)

        st.markdown(
            f"""
            <div style='background:rgba(34,197,94,0.08);border-left:4px solid #22c55e;
                        padding:16px 20px;border-radius:8px;margin-bottom:16px;'>
              <div style='font-size:24px;font-weight:700;color:#e5e7eb;line-height:1.2;'>
                −{hours_saved:.1f} ч/день на переналадках = +{format_mrub(annual_mrub)}/год
              </div>
              <div style='font-size:14px;color:#cbd5e1;margin-top:6px;'>
                То же оборудование, тот же штат. Только правильный порядок SKU.
                Сокращение на {savings_pct:.0f}% лишних переналадок за счёт CP-SAT оптимизатора.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ---- Animated Gantt (the killer visualization)
    st.markdown("#### Как SKU идут по линиям в течение смены")
    st.caption(
        "🎬 **Нажмите ▶ Оптимизировать** — блоки товаров переедут из алфавитного порядка "
        "в CP-SAT-оптимальный. Наведите курсор на блок для деталей."
    )

    sched_naive = data.sched[data.sched["mode"] == "naive"]
    sched_opt = data.sched[data.sched["mode"] == "optimized"]

    st.plotly_chart(
        animated_compare_gantt(sched_naive, sched_opt, height=620),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    # ---- Compact KPI row UNDER the animation
    if not data.sched_sum.empty:
        row = data.sched_sum.iloc[0].to_dict()
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Смена сейчас",
            f"{row['naive_makespan_h']:.1f} ч",
            help="Как сейчас расписывает планировщик (по алфавиту). Производство + переналадки + простои.",
        )
        c2.metric(
            "Смена с оптимизацией",
            f"{row['optimized_makespan_h']:.1f} ч",
            f"{row['optimized_makespan_h'] - row['naive_makespan_h']:+.1f} ч",
            help="Тот же объём производства, умный порядок SKU. Освободившиеся часы = запасная мощность.",
        )
        c3.metric(
            "Переналадки/день",
            f"{row['optimized_setup_h']:.1f} ч",
            f"−{row['setup_savings_h']:.1f} ч",
            delta_color="inverse",
            help="Сколько часов в сутки уходит на чистку линий + смену упаковки + прогрев.",
        )

    # ---- Changeover breakdown (optional drill-down inside own expander)
    if not data.bd.empty:
        with st.expander("🧩 Разбивка переналадок по причинам"):
            agg = data.bd.groupby(["category", "mode"])["minutes"].sum().reset_index()
            fig = px.bar(
                agg, x="mode", y="minutes", color="category",
                text="minutes", barmode="stack",
                color_discrete_sequence=[
                    COLORS["bad"], COLORS["warning"], "#a855f7",
                    COLORS["info"], COLORS["good"], COLORS["neutral"],
                ],
            )
            fig.update_traces(texttemplate="%{text:.0f}", textposition="inside")
            fig.update_layout(
                height=320,
                margin=dict(l=20, r=20, t=10, b=30),
                yaxis_title="Минуты",
                xaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Смена типа упаковки и переходы decaf — самые дорогие. "
                "Оптимизатор ставит SKU в порядок, минимизирующий именно эти категории."
            )

    # ---- Raw schedule table for the detail-oriented
    with st.expander("🗄 Расписание построчно (таблица)"):
        view = data.sched.copy()
        view = view.rename(columns={
            "sku_id": "Товар", "line": "Линия", "mode": "Режим",
            "start_min": "Старт, мин", "end_min": "Конец, мин",
            "duration_min": "Длительность, мин", "qty": "Кол-во, шт.",
            "blend": "Бленд", "roast_level": "Обжарка",
            "package_type": "Упаковка", "is_flavored": "Ароматизация",
            "is_decaf": "Без кофеина",
        })
        keep = [c for c in [
            "Товар", "Линия", "Режим", "Старт, мин", "Конец, мин",
            "Длительность, мин", "Кол-во, шт.", "Бленд", "Обжарка", "Упаковка",
        ] if c in view.columns]
        st.dataframe(view[keep], use_container_width=True, hide_index=True, height=320)
