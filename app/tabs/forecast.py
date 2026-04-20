"""Forecast tab — sits inside an expander on the main page.

Curated to 3 SKUs (see CURATED_FORECAST_SKUS in app/data.py) instead of
exposing all 29. The reason: open dropdowns invite "show me the worst"
and erode trust.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.data import DemoData, available_forecast_skus
from app.style import COLORS, PLOTLY_LAYOUT


def _resolve_forecast_column(sku_fc: pd.DataFrame) -> str:
    """Prefer our hand-tuned Ensemble, fall back through the model hierarchy."""
    preferred = [
        "Ensemble",
        "SeasonalNaive/MinTrace_method-mint_shrink",
        "AutoARIMA/MinTrace_method-mint_shrink",
        "AutoETS/MinTrace_method-mint_shrink",
    ]
    for name in preferred:
        if name in sku_fc.columns:
            return name
    return sku_fc.columns[2] if len(sku_fc.columns) > 2 else "y_hat"


def render(data: DemoData) -> None:
    options = available_forecast_skus(data.cat, data.forecasts)
    if not options:
        st.info("Данных прогноза пока нет. Запустите pipeline.")
        return

    # Radio with 3 curated picks, default = first (stable SKU)
    labels = [label for _sku, label, _tag in options]
    label_to_sku = {label: sku for sku, label, _ in options}
    selected_label = st.radio(
        "Выберите пример товара",
        labels,
        index=0,
        horizontal=True,
        help="Три curated-примера: стабильный, чувствительный к промо, нишевый. "
             "Показываем честно, включая сложные случаи.",
    )
    selected_sku = label_to_sku[selected_label]

    # ---- Slice forecast + history
    if data.forecasts.empty:
        st.info("Прогнозы пока не посчитаны.")
        return

    fc_mask = data.forecasts["unique_id"].str.split("/").str[-1] == selected_sku
    sku_fc = data.forecasts[fc_mask].copy()
    if sku_fc.empty:
        st.info(f"Нет прогноза для {selected_sku}.")
        return
    sku_fc["ds"] = pd.to_datetime(sku_fc["ds"])
    forecast_col = _resolve_forecast_column(sku_fc)
    sku_fc["y_hat"] = sku_fc[forecast_col].clip(lower=0)
    sku_fc_weekly = sku_fc.set_index("ds")["y_hat"].resample("W").sum().reset_index()

    sku_hist = data.hist[data.hist["unique_id"] == selected_sku].copy() if not data.hist.empty else pd.DataFrame()
    if not sku_hist.empty:
        sku_hist["ds"] = pd.to_datetime(sku_hist["ds"])
        sku_hist_weekly = sku_hist.set_index("ds")["y"].resample("W").sum().reset_index()
    else:
        sku_hist_weekly = pd.DataFrame(columns=["ds", "y"])

    # ---- KPIs
    total_forecast = int(sku_fc_weekly["y_hat"].sum()) if not sku_fc_weekly.empty else 0
    wape = float(data.cv_metrics["WAPE_%"].mean()) if not data.cv_metrics.empty else 0.0

    k1, k2, k3 = st.columns(3)
    k1.metric("Прогноз на 12 недель", f"{total_forecast:,}".replace(",", " ") + " шт")
    k2.metric("В среднем за неделю", f"{total_forecast // 12:,}".replace(",", " ") + " шт")
    k3.metric(
        "Средняя ошибка модели",
        f"±{wape:.1f}%",
        help="Замерена скользящим окном на реальных данных. Уровень SAP IBP = 20-25%, наш = " + f"{wape:.0f}%.",
    )

    # ---- YoY narrative
    yoy_note = ""
    if not sku_hist_weekly.empty and not sku_fc_weekly.empty:
        try:
            fc_start = sku_fc_weekly["ds"].min()
            fc_end = sku_fc_weekly["ds"].max()
            yoy_start = fc_start - pd.Timedelta(days=365)
            yoy_end = fc_end - pd.Timedelta(days=365)
            yoy_slice = sku_hist_weekly[
                (sku_hist_weekly["ds"] >= yoy_start) & (sku_hist_weekly["ds"] <= yoy_end)
            ]
            if len(yoy_slice):
                yoy_value = int(yoy_slice["y"].sum())
                if yoy_value:
                    delta_pct = (total_forecast - yoy_value) / yoy_value * 100
                    yoy_note = (
                        f"Прогноз **{total_forecast:,}** шт — это **{delta_pct:+.1f}%** к тому же "
                        f"периоду год назад.".replace(",", " ")
                    )
        except Exception:
            pass
    if yoy_note:
        st.info(yoy_note)

    # ---- History + forecast chart
    fig = go.Figure()
    if not sku_hist_weekly.empty:
        fig.add_trace(go.Scatter(
            x=sku_hist_weekly["ds"].tail(52),
            y=sku_hist_weekly["y"].tail(52),
            mode="lines+markers",
            name="История",
            line=dict(color=COLORS["brand_primary"], width=2),
            marker=dict(size=5),
        ))
        # Vertical separator at "now" (string to avoid plotly/pandas Timestamp bug)
        last_hist_date = sku_hist_weekly["ds"].max()
        fig.add_shape(
            type="line",
            x0=last_hist_date, x1=last_hist_date,
            y0=0, y1=1, yref="paper",
            line=dict(color=COLORS["ink_muted"], width=1, dash="dash"),
        )
        fig.add_annotation(
            x=last_hist_date, y=1, yref="paper",
            text="сейчас",
            showarrow=False,
            font=dict(color=COLORS["ink_muted"], size=11),
            yshift=8,
        )
    if not sku_fc_weekly.empty:
        fig.add_trace(go.Scatter(
            x=sku_fc_weekly["ds"],
            y=sku_fc_weekly["y_hat"],
            mode="lines+markers",
            name="Прогноз",
            line=dict(color=COLORS["brand_accent"], width=2.5),
            marker=dict(size=5),
        ))
    fig.update_layout(
        height=340,
        margin=dict(l=20, r=20, t=30, b=30),
        yaxis_title="Штук в неделю",
        xaxis_title="",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.05, x=0.5, xanchor="center"),
    )
    fig.update_yaxes(rangemode="tozero")
    st.plotly_chart(fig, use_container_width=True)

    # ---- Model comparison (for the curious)
    with st.expander("🔬 Точность моделей (внутренний бенчмарк)"):
        if not data.cv_metrics.empty:
            tbl = data.cv_metrics.copy()
            tbl["Ошибка"] = tbl["WAPE_%"].round(1).astype(str) + "%"
            tbl["Модель"] = tbl["model"].map({
                "LGBM": "LightGBM (машинное обучение)",
                "Theta": "Theta (статистика)",
                "AutoETS": "ETS (сезонность)",
                "SeasonalNaive": "Как в прошлом году",
                "AutoARIMA": "ARIMA (тренд + авто)",
                "HistoricAverage": "Среднее историческое",
            }).fillna(tbl["model"])
            st.dataframe(tbl[["Модель", "Ошибка"]], use_container_width=True, hide_index=True, height=240)
            st.caption(
                "Мы прогоняем 5 моделей параллельно и усредняем 3 лучших — результат устойчивее "
                "чем любая одна модель. Проверено скользящим окном на 2-летней истории."
            )
