"""What-If промо — симуляция uplift категории поверх baseline-прогноза.

Отвечает на вопрос коммерческого директора:
  - Если запустить промо +X% на категорию Y на N дней, сколько это даст
    прироста выручки?

Логика: честно не переобучаем модель на промо (для этого нужна история
промо-акций с флагами, которой в датасете нет). Показываем мультипликативный
uplift к baseline-прогнозу — прямой ответ на «а что если», без подмены
модели.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.style import COLORS
from src import maven_analysis as M


def _fmt_rub(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f} млн ₽".replace(".", ",")
    if abs(v) >= 1_000:
        return f"{v/1_000:.0f} тыс ₽"
    return f"{v:.0f} ₽"


def render() -> None:
    st.markdown("### What-If — промо и сценарный анализ")
    st.caption(
        "Прогноз — наш baseline. Мы накладываем на окно промо мультипликативный "
        "uplift и считаем **инкрементальную выручку** = (прогноз с промо) − (baseline). "
        "Честно: модель не учит промо-флаги — этому нужно научить после pilot-недели "
        "с реальными акциями. Здесь демонстрируется механика сценария: двигаем слайдер, "
        "числа пересчитываются за секунды."
    )

    # ─── Controls ────────────────────────────────────────────────────
    c1, c2 = st.columns([2, 1])
    with c1:
        target = st.selectbox(
            "На какую категорию / точку делаем промо",
            list(M.FORECAST_TARGETS.keys()),
            index=1,  # coffee_revenue по умолчанию — самая интересная
            format_func=lambda k: M.FORECAST_TARGETS[k],
        )
    with c2:
        horizon = st.selectbox("Горизонт прогноза, дней", [30, 60, 90], index=1)

    c3, c4, c5 = st.columns(3)
    with c3:
        uplift = st.slider(
            "Uplift спроса, %",
            min_value=0, max_value=80, value=30, step=5,
            help="Ожидаемое увеличение спроса в окне промо относительно baseline.",
        )
    with c4:
        duration = st.slider(
            "Длительность промо, дней",
            min_value=3, max_value=30, value=14, step=1,
        )
    with c5:
        offset = st.slider(
            "Старт промо через, дней от сегодня",
            min_value=0, max_value=max(0, horizon - duration), value=7, step=1,
            help="Задержка между сейчас и началом акции.",
        )

    with st.spinner("Считаем базовый прогноз и накладываем uplift..."):
        result = M.promo_simulation(
            target=target,
            horizon_days=int(horizon),
            uplift_pct=float(uplift),
            promo_duration_days=int(duration),
            promo_start_offset_days=int(offset),
        )

    if "error" in result:
        st.error(result["error"])
        return

    history = result["history"]
    base = result["base_forecast"]
    promo = result["promo_forecast"]
    incremental = result["incremental_revenue"]
    promo_start = result["promo_start"]
    promo_end = result["promo_end"]

    # ─── KPIs ────────────────────────────────────────────────────────
    base_window = base[(base["ds"] >= promo_start) & (base["ds"] <= promo_end)]
    promo_window = promo[(promo["ds"] >= promo_start) & (promo["ds"] <= promo_end)]
    base_sum = float(base_window["y_hat"].sum())
    promo_sum = float(promo_window["y_hat"].sum())
    roi_like = incremental / max(1.0, base_sum) * 100

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Baseline в окне",
        _fmt_rub(base_sum),
        help="Ожидаемая выручка за дни промо без акции.",
    )
    k2.metric(
        "С промо",
        _fmt_rub(promo_sum),
        help="Ожидаемая выручка за дни промо при uplift +{}%.".format(uplift),
    )
    k3.metric(
        "Инкрементальная выручка",
        _fmt_rub(incremental),
        delta=f"+{roi_like:.1f}% к baseline",
    )
    k4.metric(
        "Точность baseline",
        f"±{result['wape_backtest']:.1f}%",
        help="WAPE модели на backtest 14 дней. Учитывайте этот коридор при интерпретации.",
    )

    # ─── Main chart: history + base + promo ──────────────────────────
    st.markdown("#### Прогноз: baseline vs с промо")
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=history["ds"], y=history["y"],
        mode="lines", name="История (факт)",
        line=dict(color=COLORS["brand_primary"], width=1.5),
    ))
    fig.add_trace(go.Scatter(
        x=base["ds"], y=base["y_hat"],
        mode="lines", name="Baseline (без промо)",
        line=dict(color=COLORS["brand_accent"], width=2),
    ))
    fig.add_trace(go.Scatter(
        x=promo["ds"], y=promo["y_hat"],
        mode="lines", name=f"С промо +{uplift:.0f}%",
        line=dict(color=COLORS["warning"], width=2.5),
    ))

    # Highlight promo window
    fig.add_vrect(
        x0=promo_start, x1=promo_end,
        fillcolor=COLORS["warning"], opacity=0.12, line_width=0,
        annotation_text=f"окно промо ({duration} дней)",
        annotation_position="top left",
        annotation_font=dict(color=COLORS["warning"], size=11),
    )

    # Vertical "now" separator
    last_date = history["ds"].max()
    fig.add_shape(
        type="line",
        x0=last_date, x1=last_date, y0=0, y1=1, yref="paper",
        line=dict(color=COLORS["ink_muted"], width=1, dash="dash"),
    )
    fig.add_annotation(
        x=last_date, y=1, yref="paper",
        text="конец истории →", showarrow=False,
        font=dict(color=COLORS["ink_muted"], size=11), yshift=8,
    )

    fig.update_layout(
        height=420,
        margin=dict(l=60, r=20, t=40, b=40),
        xaxis_title="",
        yaxis_title="Выручка, ₽",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
        plot_bgcolor=COLORS["bg_transparent"],
        paper_bgcolor=COLORS["bg_transparent"],
    )
    fig.update_yaxes(rangemode="tozero")
    st.plotly_chart(fig, use_container_width=True)

    # ─── Daily detail table ──────────────────────────────────────────
    with st.expander("📊 Детализация по дням в окне промо"):
        detail = promo_window[["ds", "y_hat"]].rename(columns={"ds": "Дата", "y_hat": "С промо, ₽"})
        detail["Baseline, ₽"] = base_window["y_hat"].values
        detail["Δ, ₽"] = detail["С промо, ₽"] - detail["Baseline, ₽"]
        detail["Дата"] = pd.to_datetime(detail["Дата"]).dt.strftime("%Y-%m-%d")
        for col in ["С промо, ₽", "Baseline, ₽", "Δ, ₽"]:
            detail[col] = detail[col].round(0).astype(int)
        st.dataframe(detail, use_container_width=True, hide_index=True, height=300)

    st.markdown(
        """
        <div style="color:#94a3b8;font-size:13px;margin-top:8px;">
        <b>Как использовать на встрече с клиентом:</b> на звонке коммерческий
        директор говорит «хотим промо на Кофе +30% на две недели» — двигаем
        слайдеры, получаем оценку инкрементальной выручки и видим, попадает ли
        цифра в доверительный коридор ±WAPE. Это даёт разумный ответ за 30 секунд,
        а не за неделю расчётов в Excel.
        </div>
        """,
        unsafe_allow_html=True,
    )
