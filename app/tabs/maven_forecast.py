"""Forecast section on Maven Roasters — 30/60/90 day revenue forecast.

Ensemble: SeasonalNaive (amplitude + weekly pattern) + AutoTheta (trend), 50/50.
Level correction: shift so first 14 days of forecast = last 14 days of history.
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
        "**SeasonalNaive** (амплитуда + недельный паттерн) + **AutoTheta** (тренд), "
        "равное среднее. Финальный шаг — **level correction**: сдвиг прогноза так, чтобы "
        "первые 14 дней прогноза были на уровне последних 14 дней истории (без этого "
        "ансамбль стартует ниже истории на растущем ряду). Точность — backtest-WAPE "
        "на последних 14 днях. Библиотека: Nixtla StatsForecast."
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
    with st.spinner(f"Обучаем модели на 6 месяцах истории, строим прогноз на {horizon} дней..."):
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
            "SeasonalNaive": COLORS["warning"],
            "AutoTheta": "#a855f7",  # фиолетовый
        }
        for m in model_cols:
            fig2.add_trace(go.Scatter(
                x=forecast["ds"],
                y=forecast[m],
                mode="lines",
                name=m,
                line=dict(color=palette.get(m, COLORS["info"]), width=1.8),
            ))
        # Ensemble
        fig2.add_trace(go.Scatter(
            x=forecast["ds"],
            y=forecast["y_hat"],
            mode="lines",
            name="Ансамбль (среднее + level correction)",
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

        per_wape = result.get("per_model_wape", {})
        level_shift = result.get("level_shift", 0.0)
        rows = "\n".join(
            f"| {m} | ±{per_wape.get(m, float('nan')):.2f}% |"
            for m in model_cols
        )
        st.markdown(
            f"""
            **Как устроен ансамбль:**

            | Модель | Backtest WAPE |
            |---|---|
            {rows}

            - **SeasonalNaive** — сохраняет амплитуду и недельный паттерн (копирует
              последнюю неделю). «Умные» модели (ARIMA, ETS) дампят дисперсию к
              среднему — sample path истории шумный, а ожидание — гладкое.
            - **AutoTheta** — retail-baseline, уверенно ловит тренд на растущих рядах.
              AutoARIMA с недельной сезонностью часто не видит тренда вовсе.

            Ансамбль = простое среднее 50/50. Затем применяется **level correction**:
            сдвиг **{level_shift:+,.0f} ₽/день**, чтобы первые 14 дней прогноза
            совпадали по среднему с последними 14 днями истории. Без этого ансамбль
            на растущем ряду стартует ниже последнего уровня истории, создавая
            визуальный разрыв на стыке.

            Доверительный интервал берётся от AutoTheta и центрируется на y_hat.
            """
        )

    # ─── Drill-down: forecast per store ──────────────────────────────
    with st.expander("🏬 Разбивка прогноза по точкам (drill-down)"):
        st.caption(
            "Тот же горизонт прогноза, построенный независимо для каждой из 3 точек. "
            "Сумма по трём точкам ≈ прогнозу по сети (± небольшой разрыв, который "
            "в продвинутой версии убирается hierarchical reconciliation)."
        )
        store_keys = [("moscow", "Москва · Центр"), ("spb", "Санкт-Петербург"), ("ekb", "Екатеринбург")]
        store_colors = [COLORS["brand_primary"], COLORS["brand_accent"], COLORS["warning"]]
        fig3 = go.Figure()
        store_forecast_total = 0.0
        for (key, label), color in zip(store_keys, store_colors):
            sr = M.forecast(key, horizon_days=horizon)
            if "error" in sr:
                continue
            hist_s = sr["history"]
            fc_s = sr["forecast"]
            fig3.add_trace(go.Scatter(
                x=hist_s["ds"].tail(60), y=hist_s["y"].tail(60),
                mode="lines", name=f"{label} (история)",
                line=dict(color=color, width=1, dash="dot"),
                showlegend=False,
                hoverinfo="skip",
            ))
            fig3.add_trace(go.Scatter(
                x=fc_s["ds"], y=fc_s["y_hat"],
                mode="lines", name=label,
                line=dict(color=color, width=2),
            ))
            store_forecast_total += float(fc_s["y_hat"].sum())

        fig3.update_layout(
            height=380,
            margin=dict(l=60, r=20, t=20, b=40),
            xaxis_title="",
            yaxis_title="Выручка точки, ₽",
            hovermode="x unified",
            legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
            plot_bgcolor=COLORS["bg_transparent"],
            paper_bgcolor=COLORS["bg_transparent"],
        )
        fig3.update_yaxes(rangemode="tozero")
        st.plotly_chart(fig3, use_container_width=True)

        network_sum = float(forecast["y_hat"].sum())
        gap_pct = (store_forecast_total - network_sum) / max(1.0, network_sum) * 100
        st.markdown(
            f"""
            <div style="color:#94a3b8;font-size:13px;">
            <b>Проверка когерентности:</b> прогноз по сети целиком —
            <b>{network_sum/1_000_000:.2f} млн ₽</b>. Сумма трёх независимых прогнозов
            по точкам — <b>{store_forecast_total/1_000_000:.2f} млн ₽</b>.
            Разрыв: <b>{gap_pct:+.2f}%</b>. Это и есть <i>incoherence</i>, которую
            закрывает hierarchical reconciliation (Nixtla MinTrace) — фича под
            production-внедрение.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ─── Raw forecast table ──────────────────────────────────────────
    with st.expander("🗄 Таблица прогноза по дням"):
        disp = forecast[["ds", "y_hat", "y_hat_lo_80", "y_hat_hi_80"]].copy()
        disp.columns = ["Дата", "Прогноз, ₽", "Нижн. гран. 80%", "Верхн. гран. 80%"]
        disp["Дата"] = pd.to_datetime(disp["Дата"]).dt.strftime("%Y-%m-%d")
        for col in ["Прогноз, ₽", "Нижн. гран. 80%", "Верхн. гран. 80%"]:
            disp[col] = disp[col].round(0).astype(int)
        st.dataframe(disp, use_container_width=True, hide_index=True, height=300)
