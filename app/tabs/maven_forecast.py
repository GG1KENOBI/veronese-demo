"""Forecast section on Maven Roasters — 30/60/90 day revenue forecast.

Uses ensemble of AutoARIMA + SeasonalNaive + HistoricAverage.
Backtested WAPE on last 14 days of data.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.style import COLORS
from src import maven_analysis as M


def _fmt_rub(v: float) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f} млн ₽".replace(".", ",")
    if v >= 1_000:
        return f"{v/1_000:.0f} тыс ₽"
    return f"{v:.0f} ₽"


def render() -> None:
    st.markdown("### Прогноз выручки на следующий период")
    st.caption(
        "Модели: ансамбль из **AutoARIMA + SeasonalNaive + HistoricAverage**. "
        "Точность замерена backtest'ом на последних 14 днях данных. "
        "Модели обучаются на дневных суммах. Используется библиотека Nixtla StatsForecast."
    )

    # ─── Controls ────────────────────────────────────────────────────
    c1, c2 = st.columns([2, 1])
    with c1:
        target = st.selectbox(
            "Что прогнозируем",
            list(M.FORECAST_TARGETS.keys()),
            index=0,
            format_func=lambda k: M.FORECAST_TARGETS[k],
        )
    with c2:
        horizon = st.selectbox("Горизонт, дней", [30, 60, 90], index=0)

    # ─── Compute forecast ────────────────────────────────────────────
    with st.spinner(f"Обучаем 3 модели на 6 месяцах истории, строим прогноз на {horizon} дней..."):
        result = M.forecast(target, horizon_days=horizon)

    if "error" in result:
        st.error(result["error"])
        return

    history = result["history"]
    forecast = result["forecast"]
    wape = result["wape_backtest"]

    # ─── KPIs ────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Точность (WAPE, backtest 14 дней)",
        f"±{wape:.1f}%",
        help="Взвешенная абсолютная процентная ошибка. Меньше — точнее. Бенчмарк для FMCG: 20-25%.",
    )
    k2.metric(
        "Суммарный прогноз",
        _fmt_rub(forecast["y_hat"].sum()),
        help=f"Суммарная ожидаемая выручка за {horizon} дней по ансамблю.",
    )
    k3.metric(
        "Средний день прогноза",
        _fmt_rub(forecast["y_hat"].mean()),
    )
    last_30_hist = history.tail(30)["y"].sum()
    change = (forecast["y_hat"].head(30).sum() - last_30_hist) / last_30_hist * 100 if last_30_hist else 0
    k4.metric(
        "Δ vs последние 30 дней",
        f"{change:+.1f}%",
        help="Насколько первые 30 дней прогноза отличаются от последних 30 дней истории.",
    )

    # ─── Main chart: history + forecast + CI ─────────────────────────
    st.markdown("#### История + прогноз с доверительным интервалом")
    fig = go.Figure()

    # History
    fig.add_trace(go.Scatter(
        x=history["ds"],
        y=history["y"],
        mode="lines",
        name="История (факт)",
        line=dict(color=COLORS["brand_primary"], width=1.5),
    ))

    # Confidence interval (80%)
    fig.add_trace(go.Scatter(
        x=pd.concat([forecast["ds"], forecast["ds"][::-1]]),
        y=pd.concat([forecast["y_hat_hi_80"], forecast["y_hat_lo_80"][::-1]]),
        fill="toself",
        fillcolor="rgba(96, 165, 250, 0.25)",
        line=dict(color="rgba(0,0,0,0)"),
        name="80% доверительный интервал",
        hoverinfo="skip",
    ))

    # Ensemble forecast
    fig.add_trace(go.Scatter(
        x=forecast["ds"],
        y=forecast["y_hat"],
        mode="lines",
        name="Прогноз (ансамбль)",
        line=dict(color=COLORS["brand_accent"], width=2.5),
    ))

    # Vertical "now" separator
    last_date = history["ds"].max()
    fig.add_shape(
        type="line",
        x0=last_date, x1=last_date,
        y0=0, y1=1, yref="paper",
        line=dict(color=COLORS["ink_muted"], width=1, dash="dash"),
    )
    fig.add_annotation(
        x=last_date, y=1, yref="paper",
        text="конец истории →",
        showarrow=False,
        font=dict(color=COLORS["ink_muted"], size=11),
        yshift=8,
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

    # ─── Comparison: individual models ───────────────────────────────
    with st.expander("🔬 Сравнение моделей — прогнозы каждой по отдельности"):
        model_cols = [c for c in forecast.columns if c in result["models_used"]]
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=history["ds"].tail(60),
            y=history["y"].tail(60),
            mode="lines",
            name="История (последние 60 дней)",
            line=dict(color=COLORS["brand_primary"], width=1.5),
        ))
        palette = {
            "AutoARIMA": COLORS["good"],
            "SeasonalNaive": COLORS["warning"],
            "HistoricAverage": COLORS["neutral"],
        }
        for m in model_cols:
            fig2.add_trace(go.Scatter(
                x=forecast["ds"],
                y=forecast[m],
                mode="lines",
                name=m,
                line=dict(color=palette.get(m, COLORS["info"]), width=2, dash="dot" if m == "HistoricAverage" else "solid"),
            ))
        # Ensemble
        fig2.add_trace(go.Scatter(
            x=forecast["ds"],
            y=forecast["y_hat"],
            mode="lines",
            name="Ансамбль (среднее 3 моделей)",
            line=dict(color=COLORS["brand_accent"], width=3),
        ))
        fig2.update_layout(
            height=380,
            margin=dict(l=60, r=20, t=40, b=40),
            xaxis_title="",
            yaxis_title="Выручка, ₽",
            hovermode="x unified",
            legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
            plot_bgcolor=COLORS["bg_transparent"],
            paper_bgcolor=COLORS["bg_transparent"],
        )
        fig2.update_yaxes(rangemode="tozero")
        st.plotly_chart(fig2, use_container_width=True)

        st.markdown(
            """
            **Почему ансамбль, а не одна модель:**
            - **AutoARIMA** — ловит тренд и сезонность, но нестабилен на коротких сериях
            - **SeasonalNaive** — «в этот день недели было X, значит и будет X». Крепкий baseline
            - **HistoricAverage** — среднее историческое, anchor на случай «модели поехали»

            Среднее трёх даёт устойчивое предсказание: одна модель ошиблась — две другие компенсируют.
            Это стандартный приём в индустрии (Nixtla, Uber Michelangelo, Amazon Forecast).
            """
        )

    # ─── Raw forecast table ──────────────────────────────────────────
    with st.expander("🗄 Таблица прогноза по дням"):
        disp = forecast[["ds", "y_hat", "y_hat_lo_80", "y_hat_hi_80"]].copy()
        disp.columns = ["Дата", "Прогноз, ₽", "Нижн. гран. 80%", "Верхн. гран. 80%"]
        disp["Дата"] = pd.to_datetime(disp["Дата"]).dt.strftime("%Y-%m-%d")
        for col in ["Прогноз, ₽", "Нижн. гран. 80%", "Верхн. гран. 80%"]:
            disp[col] = disp[col].round(0).astype(int)
        st.dataframe(disp, use_container_width=True, hide_index=True, height=300)
