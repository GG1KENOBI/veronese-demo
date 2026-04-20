"""OEE tab — inside expander. Waterfall + Pareto + per-line scorecard."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app.data import DemoData
from app.style import COLORS, LOSS_COLORS, WATERFALL_COLORS

_STEP_LABELS_RU = {
    "Planned Production Time": "Плановое время",
    "Scheduled breaks": "Перерывы",
    "Operating Time": "Рабочее время",
    "Breakdowns": "Поломки",
    "Changeovers": "Переналадки",
    "Run Time": "Время работы",
    "Reduced speed": "Снижение скорости",
    "Minor stops": "Микростопы",
    "Net Run Time": "Чистое время",
    "Production rejects": "Брак при производстве",
    "Startup rejects": "Брак на старте",
    "Fully Productive": "Полезное время",
}

_LOSS_LABELS_RU = {
    "1. Breakdowns": "Поломки",
    "2. Changeovers": "Переналадки",
    "3. Reduced speed": "Снижение скорости",
    "4. Minor stops": "Микростопы",
    "5. Production rejects": "Брак при производстве",
    "6. Startup rejects": "Брак на старте",
}


def render(data: DemoData) -> None:
    if data.oee_res.empty or data.oee_wf.empty:
        st.info("OEE-симуляция ещё не запускалась.")
        return

    # ---- Aggregate KPIs
    agg = data.oee_res.groupby(["mode", "run_id"]).apply(
        lambda g: g["fully_productive_min"].sum() / max(1e-6, g["planned_min"].sum()),
        include_groups=False,
    ).reset_index(name="oee")
    mean_opt = agg[agg["mode"] == "optimized"]["oee"].mean() if "optimized" in agg["mode"].values else None
    mean_nv = agg[agg["mode"] == "naive"]["oee"].mean() if "naive" in agg["mode"].values else None

    opt_mode = data.oee_res[data.oee_res["mode"] == "optimized"]
    k1, k2, k3, k4 = st.columns(4)
    if mean_opt is not None:
        k1.metric(
            "OEE (с оптимизацией)",
            f"{mean_opt*100:.1f}%",
            f"{(mean_opt - mean_nv)*100:+.1f} п.п." if mean_nv else None,
            help="Overall Equipment Effectiveness = Availability × Performance × Quality. World-class 85%.",
        )
    if not opt_mode.empty:
        k2.metric("Доступность", f"{opt_mode['availability'].mean()*100:.1f}%")
        k3.metric("Производительность", f"{opt_mode['performance'].mean()*100:.1f}%")
        k4.metric("Качество", f"{opt_mode['quality'].mean()*100:.1f}%")

    # ---- Per-line cards
    if not opt_mode.empty:
        per_line = (
            opt_mode.groupby("line")
            .agg(
                OEE=("oee", "mean"),
                Availability=("availability", "mean"),
                Performance=("performance", "mean"),
                Quality=("quality", "mean"),
            )
            .reset_index()
        )
        st.markdown("##### OEE по линиям (оптимизировано)")
        cols = st.columns(len(per_line) or 1)
        for i, (_, row) in enumerate(per_line.iterrows()):
            with cols[i]:
                oee_v = float(row["OEE"]) * 100
                colour = "🟢" if oee_v > 60 else ("🟡" if oee_v > 40 else "🔴")
                st.metric(
                    f"{colour} {row['line']}",
                    f"{oee_v:.1f}%",
                    f"A {row['Availability']*100:.0f} · P {row['Performance']*100:.0f} · Q {row['Quality']*100:.0f}",
                    delta_color="off",
                    help="A = Availability · P = Performance · Q = Quality",
                )

    st.markdown("---")

    # ---- Waterfall
    st.markdown("##### Куда уходит каждая минута")
    st.caption(
        "Слева направо: **синие** — запас времени на каждом этапе; "
        "**красные** — что его съело. Последний столбец — чистое производительное время."
    )
    measures = [
        "absolute" if k == "total" else ("total" if k in ("subtotal", "final") else "relative")
        for k in data.oee_wf["kind"]
    ]
    x_labels = [_STEP_LABELS_RU.get(s, s) for s in data.oee_wf["step"]]
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=measures,
        x=x_labels,
        y=data.oee_wf["minutes"],
        textposition="outside",
        text=[f"{v:+.0f} мин" for v in data.oee_wf["minutes"]],
        textfont=dict(size=12, color=COLORS["ink_bright"]),
        connector={"line": {"color": WATERFALL_COLORS["connector"], "width": 1, "dash": "dot"}},
        increasing={"marker": {"color": WATERFALL_COLORS["increasing"]}},
        decreasing={"marker": {"color": WATERFALL_COLORS["decreasing"]}},
        totals={"marker": {"color": WATERFALL_COLORS["total"]}},
        hovertemplate="<b>%{x}</b><br>%{y:+.0f} мин<extra></extra>",
    ))
    fig.update_layout(
        height=420,
        margin=dict(l=60, r=20, t=20, b=110),
        yaxis=dict(title="Минуты смены", gridcolor="rgba(148,163,184,0.15)"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(tickangle=-25, tickfont=dict(size=11))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("---")

    # ---- Pareto
    st.markdown("##### Парето потерь — куда инвестировать первым")
    st.caption(
        "Столбцы отсортированы от большего к меньшему. "
        "Синяя линия — накопительный процент. Пересечение с 80% показывает 2-3 причины с наибольшим эффектом."
    )
    if not data.six.empty:
        pareto = data.six.sort_values("minutes", ascending=False).reset_index(drop=True).copy()
        total_loss = pareto["minutes"].sum()
        pareto["cum_pct"] = (pareto["minutes"].cumsum() / total_loss * 100).round(1)
        pareto["loss_ru"] = pareto["loss"].map(lambda s: _LOSS_LABELS_RU.get(s, s))

        colors = [LOSS_COLORS.get(c, COLORS["ink_muted"]) for c in pareto["category"]]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=pareto["loss_ru"],
            y=pareto["minutes"],
            marker=dict(color=colors, line=dict(color=COLORS["ink_dark"], width=1)),
            text=[f"<b>{v:.0f} мин</b>" for v in pareto["minutes"]],
            textposition="outside",
            textfont=dict(size=13, color=COLORS["ink_bright"]),
            hovertemplate="%{x}<br>%{y:.0f} мин<br>%{customdata:,.0f} ₽<extra></extra>",
            customdata=pareto["cost_rub"] if "cost_rub" in pareto.columns else [0]*len(pareto),
        ))
        fig.add_trace(go.Scatter(
            x=pareto["loss_ru"],
            y=pareto["cum_pct"],
            yaxis="y2",
            mode="lines+markers+text",
            line=dict(color=COLORS["brand_accent"], width=3),
            marker=dict(size=10, color=COLORS["brand_accent"], line=dict(color=COLORS["ink_dark"], width=1)),
            text=[f"{v:.0f}%" for v in pareto["cum_pct"]],
            textposition="top center",
            textfont=dict(color=COLORS["ink_bright"], size=11),
            hovertemplate="Накопительно: %{y:.0f}%<extra></extra>",
        ))
        fig.add_hline(
            y=80, yref="y2", line_dash="dash", line_color="#fca5a5",
            annotation_text="80% потерь", annotation_position="right",
        )
        fig.update_layout(
            height=420,
            margin=dict(l=60, r=80, t=40, b=110),
            yaxis=dict(title="Минуты потерь", gridcolor="rgba(148,163,184,0.15)"),
            yaxis2=dict(
                title="Накопительно, %",
                overlaying="y", side="right",
                range=[0, 110], showgrid=False, ticksuffix="%",
            ),
            showlegend=False,
            xaxis=dict(tickangle=-15, tickfont=dict(size=12)),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        dominant = pareto[pareto["cum_pct"] <= 80.01]["loss_ru"].tolist()
        if dominant:
            st.info(
                f"📍 **80% всех потерь** = **{', '.join(dominant)}**. "
                "Автоматизация и сокращение — в первую очередь сюда."
            )
