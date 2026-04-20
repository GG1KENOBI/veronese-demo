"""Shared Plotly chart helpers for the Streamlit dashboard."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


PALETTE_FORM = {
    "Beans": "#78350f",
    "Ground": "#a16207",
    "Capsules": "#0284c7",
    "3in1": "#ca8a04",
}
COLOR_VRN = "#16a34a"
COLOR_CTM = "#9333ea"


def gantt_chart(schedule: pd.DataFrame, title: str = "", color_by: str = "category") -> go.Figure:
    """Interactive Gantt with rich Russian tooltips.

    Hover shows: SKU, бленд, обжарка, кол-во, время начала/окончания, длительность.
    Color-coded by product category (dark/medium roast, capsules, flavored, decaf).
    """
    if schedule.empty:
        return go.Figure()
    df = schedule.copy()
    base = pd.Timestamp("2024-01-01 06:00")
    df["start_ts"] = df["start_min"].apply(lambda x: base + pd.Timedelta(minutes=int(x)))
    df["end_ts"] = df["end_min"].apply(lambda x: base + pd.Timedelta(minutes=int(x)))

    def _cat(row):
        pt = str(row.get("package_type", ""))
        if "Capsule" in pt:
            return "Капсулы"
        if row.get("is_flavored"):
            return "Ароматизированный"
        if row.get("is_decaf"):
            return "Без кофеина"
        rl = row.get("roast_level", "")
        return {"Dark": "Тёмная обжарка", "Medium": "Средняя обжарка", "Light": "Светлая обжарка"}.get(rl, rl or "Прочее")
    df["Категория"] = df.apply(_cat, axis=1)

    color_map = {
        "Тёмная обжарка": "#78350f",
        "Средняя обжарка": "#b45309",
        "Светлая обжарка": "#fbbf24",
        "Ароматизированный": "#ec4899",
        "Без кофеина": "#6b7280",
        "Капсулы": "#0284c7",
        "Прочее": "#64748b",
    }

    # Human-readable Russian tooltip fields
    df["Время начала"] = df["start_min"].apply(lambda m: f"{int(m)//60:02d}:{int(m)%60:02d}")
    df["Время окончания"] = df["end_min"].apply(lambda m: f"{int(m)//60:02d}:{int(m)%60:02d}")
    df["Длительность, мин"] = df["duration_min"].astype(int)
    df["Количество, шт"] = df["qty"].round(0).astype(int)

    fig = px.timeline(
        df,
        x_start="start_ts",
        x_end="end_ts",
        y="line",
        color="Категория",
        color_discrete_map=color_map,
        hover_data={
            "sku_id": True,
            "blend": True,
            "Время начала": True,
            "Время окончания": True,
            "Длительность, мин": True,
            "Количество, шт": True,
            "start_ts": False, "end_ts": False,
            "line": False,
            "Категория": True,
        },
        labels={"sku_id": "Товар", "blend": "Бленд", "line": "Линия"},
        title=title,
    )
    fig.update_yaxes(categoryorder="category ascending", title="")
    fig.update_xaxes(
        title="Часы от начала смены",
        tickformat="%H:%M",
    )
    fig.update_layout(
        height=380,
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5,
                    title_text=""),
        hovermode="closest",
    )
    return fig


CATEGORY_COLORS = {
    "Тёмная обжарка": "#78350f",
    "Средняя обжарка": "#b45309",
    "Светлая обжарка": "#fbbf24",
    "Ароматизированный": "#ec4899",
    "Без кофеина": "#6b7280",
    "Капсулы": "#0284c7",
    "Прочее": "#64748b",
}


def _row_category(row) -> str:
    pt = str(row.get("package_type", ""))
    if "Capsule" in pt:
        return "Капсулы"
    if row.get("is_flavored"):
        return "Ароматизированный"
    if row.get("is_decaf"):
        return "Без кофеина"
    rl = row.get("roast_level", "")
    return {"Dark": "Тёмная обжарка", "Medium": "Средняя обжарка", "Light": "Светлая обжарка"}.get(rl, rl or "Прочее")


def animated_compare_gantt(sched_naive: pd.DataFrame, sched_opt: pd.DataFrame, height: int = 520) -> go.Figure:
    """Single Gantt that animates SKU blocks sliding from the naive layout into the optimized one.

    Each SKU is plotted as a horizontal bar whose `base` is the start time. The figure has two
    frames (naive, optimized); pressing Play or dragging the slider smoothly interpolates `base`
    and `x` (duration), so blocks visibly slide to their new positions.
    """
    if sched_naive.empty or sched_opt.empty:
        return go.Figure()

    n = sched_naive.copy()
    o = sched_opt.copy()
    n["cat"] = n.apply(_row_category, axis=1)
    o["cat"] = o.apply(_row_category, axis=1)

    merged = n.merge(
        o[["sku_id", "line", "start_min", "end_min", "duration_min"]],
        on=["sku_id", "line"],
        suffixes=("_n", "_o"),
    )
    if merged.empty:
        return go.Figure()

    merged = merged.sort_values(["sku_id", "line"]).reset_index(drop=True)
    merged["_blend"] = merged.get("blend", "").fillna("")
    merged["_qty"] = merged["qty"].round(0).astype(int)

    lines = sorted(merged["line"].unique())
    categories = [c for c in CATEGORY_COLORS if c in set(merged["cat"])]

    def _traces(start_col: str, dur_col: str):
        traces = []
        for c in categories:
            sub = merged[merged["cat"] == c]
            if sub.empty:
                continue
            durs = sub[dur_col].astype(int).tolist()
            starts = sub[start_col].astype(int).tolist()
            ends = [s + d for s, d in zip(starts, durs)]
            customdata = list(zip(
                sub["sku_id"].tolist(),
                sub["_blend"].tolist(),
                sub["_qty"].tolist(),
                durs,
                [f"{s//60:02d}:{s%60:02d}" for s in starts],
                [f"{e//60:02d}:{e%60:02d}" for e in ends],
            ))
            traces.append(go.Bar(
                y=sub["line"].tolist(),
                x=durs,
                base=starts,
                orientation="h",
                name=c,
                marker=dict(color=CATEGORY_COLORS[c], line=dict(color="#0b1220", width=1)),
                customdata=customdata,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Бленд: %{customdata[1]}<br>"
                    "Линия: %{y}<br>"
                    "Старт: %{customdata[4]}  →  %{customdata[5]}<br>"
                    "Длительность: %{customdata[3]} мин<br>"
                    "Кол-во: %{customdata[2]} шт<extra></extra>"
                ),
            ))
        return traces

    max_end = int(max(merged["end_min_n"].max(), merged["end_min_o"].max())) + 30
    tick_step = 120 if max_end > 720 else 60
    tickvals = list(range(0, max_end + 1, tick_step))
    ticktext = [f"{v//60:02d}:{v%60:02d}" for v in tickvals]

    init_data = _traces("start_min_n", "duration_min_n")
    frames = [
        go.Frame(name="naive", data=_traces("start_min_n", "duration_min_n")),
        go.Frame(name="optimized", data=_traces("start_min_o", "duration_min_o")),
    ]

    fig = go.Figure(data=init_data, frames=frames)

    anim_opts = dict(
        frame=dict(duration=1500, redraw=False),
        transition=dict(duration=1500, easing="cubic-in-out"),
        mode="immediate",
    )

    fig.update_layout(
        barmode="overlay",
        bargap=0.35,
        height=height,
        xaxis=dict(
            title="Время от начала смены",
            range=[0, max_end],
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            showgrid=True,
            gridcolor="rgba(148,163,184,0.15)",
        ),
        yaxis=dict(
            title="",
            categoryorder="array",
            categoryarray=lines[::-1],
        ),
        legend=dict(
            orientation="h", y=-0.22, x=0.5, xanchor="center", yanchor="top",
            title_text="", bgcolor="rgba(0,0,0,0)", font=dict(size=11),
        ),
        margin=dict(l=100, r=20, t=70, b=200),
        transition=dict(duration=1500, easing="cubic-in-out"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        updatemenus=[dict(
            type="buttons",
            direction="right",
            x=0.0, y=1.14, xanchor="left", yanchor="bottom",
            pad=dict(r=10, t=0, b=0),
            bgcolor="rgba(30,41,59,0.6)",
            bordercolor="#334155",
            font=dict(color="#e5e7eb", size=13),
            showactive=False,
            buttons=[
                dict(label="▶ Оптимизировать", method="animate",
                     args=[["optimized"], anim_opts]),
                dict(label="⏮ Сбросить", method="animate",
                     args=[["naive"], anim_opts]),
            ],
        )],
        sliders=[dict(
            active=0,
            y=-0.48, x=0.0, xanchor="left", len=1.0,
            pad=dict(t=10, b=20),
            currentvalue=dict(
                prefix="Режим: ",
                font=dict(color="#e5e7eb", size=13),
                visible=True, xanchor="left",
            ),
            bgcolor="rgba(30,41,59,0.4)",
            bordercolor="#334155",
            tickcolor="#94a3b8",
            font=dict(color="#e5e7eb"),
            steps=[
                dict(label="как сейчас", method="animate",
                     args=[["naive"], anim_opts]),
                dict(label="оптимизировано", method="animate",
                     args=[["optimized"], anim_opts]),
            ],
        )],
    )

    # Soft shift-boundary guides (8-hour shifts)
    for shift_end in (480, 960, 1440):
        if shift_end < max_end:
            fig.add_vline(x=shift_end, line_dash="dot", line_color="#fbbf24", line_width=1, opacity=0.5)

    return fig


def waterfall_oee(wf: pd.DataFrame, planned_total: float | None = None, title: str = "OEE Waterfall") -> go.Figure:
    """Waterfall chart: planned → operating → run → net run → fully productive."""
    df = wf.copy()
    # Plotly waterfall expects: measure, x, y (value)
    measures = []
    for kind in df["kind"]:
        if kind in ("total", "subtotal", "final"):
            measures.append("absolute" if kind == "total" else "total")
        else:
            measures.append("relative")
    fig = go.Figure(go.Waterfall(
        name="OEE",
        orientation="v",
        measure=measures,
        x=df["step"],
        y=df["minutes"],
        textposition="outside",
        text=[f"{v:+.0f} мин" for v in df["minutes"]],
        connector={"line": {"color": "#94a3b8"}},
        increasing={"marker": {"color": "#22c55e"}},
        decreasing={"marker": {"color": "#ef4444"}},
        totals={"marker": {"color": "#2563eb"}},
    ))
    fig.update_layout(
        title=title,
        yaxis_title="Минуты",
        height=460,
        margin=dict(l=40, r=20, t=60, b=80),
    )
    fig.update_xaxes(tickangle=-35)
    return fig


def six_big_losses_bar(losses: pd.DataFrame) -> go.Figure:
    color_map = {"Availability": "#ef4444", "Performance": "#f59e0b", "Quality": "#a855f7"}
    fig = px.bar(
        losses.sort_values("minutes", ascending=True),
        x="minutes",
        y="loss",
        color="category",
        color_discrete_map=color_map,
        orientation="h",
        text="minutes",
        hover_data={"cost_rub": ":,.0f"},
    )
    fig.update_traces(texttemplate="%{text:.0f} мин", textposition="outside")
    fig.update_layout(
        title="Six Big Losses — где теряется мощность",
        xaxis_title="Потери, мин (в среднем на запуск расписания)",
        yaxis_title="",
        height=340,
        margin=dict(l=20, r=60, t=60, b=40),
    )
    return fig


def shadow_prices_heatmap(sp: pd.DataFrame) -> go.Figure:
    if sp.empty:
        return go.Figure()
    pivot = sp.pivot(index="line", columns="week", values="shadow_price_rub_per_min").fillna(0)
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=[f"Нед {c+1}" for c in pivot.columns],
        y=pivot.index,
        colorscale="Reds",
        hovertemplate="Линия %{y}<br>Неделя %{x}<br>Shadow price: %{z:,.0f} руб/мин<extra></extra>",
        colorbar=dict(title="руб/мин"),
    ))
    fig.update_layout(
        title="Shadow prices — ценность +1 минуты capacity (бутылочные горлышки выделены красным)",
        height=260,
        margin=dict(l=40, r=20, t=60, b=40),
    )
    return fig


def cost_breakdown_donut(cost: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Pie(
        labels=cost["category"], values=cost["rub"],
        hole=0.55, textinfo="label+percent",
        marker=dict(colors=["#2563eb", "#f59e0b", "#10b981", "#ef4444"]),
        hovertemplate="%{label}<br>%{value:,.0f} руб (%{percent})<extra></extra>",
    ))
    total = cost["rub"].sum()
    fig.update_layout(
        title="Структура затрат плана",
        annotations=[dict(text=f"<b>{total/1e6:.1f} М₽</b>", x=0.5, y=0.5, font_size=18, showarrow=False)],
        height=340,
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


def production_heatmap(plan: pd.DataFrame, catalog: pd.DataFrame | None = None) -> go.Figure:
    """SKU × week production volume with readable human labels."""
    pivot = plan.pivot_table(index="sku_id", columns="week", values="production_units", aggfunc="sum").fillna(0)
    # Sort SKUs by total volume for cleaner visual (top contributors at top)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    # Build human-readable y labels from catalog (brand + form + blend + size)
    y_labels = list(pivot.index)
    if catalog is not None and not catalog.empty:
        cat_map = catalog.set_index("sku_id").to_dict(orient="index")
        y_labels = [_short_sku_label(s, cat_map.get(s, {})) for s in pivot.index]
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=[f"Нед {c+1}" for c in pivot.columns],
        y=y_labels,
        colorscale="Blues",
        colorbar=dict(title="ед."),
        hovertemplate="%{y}<br>Неделя %{x}<br>Производство: %{z:,.0f} ед<extra></extra>",
    ))
    fig.update_layout(
        title="Производственный план: SKU × недели",
        height=640,
        margin=dict(l=180, r=20, t=60, b=40),
        yaxis=dict(tickfont=dict(size=10)),
    )
    return fig


def _short_sku_label(sku_id: str, attrs: dict) -> str:
    """Compact human label, e.g. 'VRN Капсулы Nespresso Dark 10×'."""
    if not attrs:
        return sku_id
    brand_short = "VRN" if attrs.get("brand") == "VERONESE" else attrs.get("brand", "")
    form = {
        "Beans": "Зерно",
        "Ground": "Молотый",
        "Capsules": "Капсулы",
        "3in1": "3-в-1",
    }.get(attrs.get("form", ""), attrs.get("form", ""))
    blend = attrs.get("blend", "") or ""
    blend_short = blend if len(blend) <= 14 else blend[:12] + "…"
    size = attrs.get("package_size_g", 0) or 0
    roast = attrs.get("roast_level", "") or ""
    is_decaf = attrs.get("is_decaf", False)
    is_flav = attrs.get("is_flavored", False)
    # Size hint
    if isinstance(size, (int, float)) and size:
        if size >= 1000:
            size_s = f"{int(size / 1000)}кг"
        elif attrs.get("form") == "Capsules":
            size_s = "10×" if size <= 80 else "16×"
        else:
            size_s = f"{int(size)}г"
    else:
        size_s = ""
    flags = []
    if is_decaf and "decaf" not in blend.lower(): flags.append("Decaf")
    if is_flav and not is_decaf: flags.append("Flav")
    roast_flag = roast[:4] if roast and not flags else ""  # Dark/Medi/Ligh
    tail = " ".join(p for p in (blend_short, roast_flag, " ".join(flags), size_s) if p)
    label = f"{brand_short} · {form} · {tail}" if form else f"{brand_short} · {tail}"
    return label


def stl_decomposition(series: pd.Series, period: int = 7, title: str = "") -> go.Figure:
    from statsmodels.tsa.seasonal import STL
    stl = STL(series, period=period, robust=True).fit()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=series.values, name="Факт", line=dict(color="#1e293b", width=1)))
    fig.add_trace(go.Scatter(x=stl.trend.index, y=stl.trend.values, name="Тренд", line=dict(color="#2563eb", width=2.5)))
    fig.add_trace(go.Scatter(x=stl.seasonal.index, y=stl.seasonal.values + series.mean(), name="Сезонность (сдвинута)", line=dict(color="#f59e0b", dash="dot")))
    fig.update_layout(
        title=title,
        height=320,
        margin=dict(l=20, r=20, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def forecast_chart_with_ci(history: pd.Series, forecast: pd.DataFrame, sku: str) -> go.Figure:
    """Forecast with 80/95% CI fan chart. forecast has columns ds, y_hat, y_hat_lo_80, y_hat_hi_80, y_hat_lo_95, y_hat_hi_95."""
    fig = go.Figure()
    # History
    fig.add_trace(go.Scatter(x=history.index, y=history.values, name="История", line=dict(color="#1e293b", width=1.5)))
    # 95% CI
    if "y_hat_lo_95" in forecast.columns:
        fig.add_trace(go.Scatter(
            x=pd.concat([forecast["ds"], forecast["ds"][::-1]]),
            y=pd.concat([forecast["y_hat_hi_95"], forecast["y_hat_lo_95"][::-1]]),
            fill="toself", fillcolor="rgba(37,99,235,0.12)", line=dict(color="rgba(0,0,0,0)"),
            name="95% CI", hoverinfo="skip",
        ))
    if "y_hat_lo_80" in forecast.columns:
        fig.add_trace(go.Scatter(
            x=pd.concat([forecast["ds"], forecast["ds"][::-1]]),
            y=pd.concat([forecast["y_hat_hi_80"], forecast["y_hat_lo_80"][::-1]]),
            fill="toself", fillcolor="rgba(37,99,235,0.25)", line=dict(color="rgba(0,0,0,0)"),
            name="80% CI", hoverinfo="skip",
        ))
    fig.add_trace(go.Scatter(x=forecast["ds"], y=forecast["y_hat"], name="Прогноз", line=dict(color="#2563eb", width=2.5)))
    fig.update_layout(
        title=f"Прогноз спроса: {sku}",
        height=380, margin=dict(l=20, r=20, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def changeover_breakdown_bar(bd: pd.DataFrame) -> go.Figure:
    if bd.empty:
        return go.Figure()
    agg = bd.groupby(["category", "mode"])["minutes"].sum().reset_index()
    fig = px.bar(agg, x="mode", y="minutes", color="category", barmode="stack",
                 text="minutes",
                 color_discrete_sequence=["#ef4444", "#f59e0b", "#a855f7", "#3b82f6", "#10b981", "#64748b"])
    fig.update_traces(texttemplate="%{text:.0f}", textposition="inside")
    fig.update_layout(
        title="Переналадки: разбивка по причинам (naive vs optimized)",
        xaxis_title="Режим",
        yaxis_title="Минуты",
        height=380,
        margin=dict(l=40, r=20, t=60, b=40),
    )
    return fig


def oee_distribution_chart(results: pd.DataFrame) -> go.Figure:
    """Distribution of OEE across Monte Carlo runs, per mode."""
    fig = go.Figure()
    for mode in results["mode"].unique():
        sub = results[results["mode"] == mode]
        # Per-run aggregate OEE (weighted by planned time)
        agg = sub.groupby("run_id").apply(
            lambda g: (g["fully_productive_min"].sum() / max(1e-6, g["planned_min"].sum()))
        )
        color = "#16a34a" if mode == "optimized" else "#ef4444"
        fig.add_trace(go.Histogram(
            x=agg.values * 100,
            name=mode,
            opacity=0.7,
            marker=dict(color=color),
            nbinsx=25,
        ))
    fig.update_layout(
        title="Распределение OEE (50 Monte Carlo запусков)",
        barmode="overlay",
        xaxis_title="OEE, %",
        yaxis_title="Количество запусков",
        height=300,
        margin=dict(l=40, r=20, t=60, b=40),
    )
    return fig


def inventory_trajectory_chart(inv: pd.DataFrame, sku: str) -> go.Figure:
    sub = inv[inv["sku_id"] == sku].sort_values("week")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=sub["week"].apply(lambda x: f"Нед {x+1}"), y=sub["inventory_end"], name="Запас", marker_color="#3b82f6"))
    fig.add_trace(go.Scatter(x=sub["week"].apply(lambda x: f"Нед {x+1}"), y=sub["safety_stock"], name="Safety stock", mode="lines", line=dict(color="#ef4444", dash="dash")))
    if (sub["backorder"] > 0).any():
        fig.add_trace(go.Bar(x=sub["week"].apply(lambda x: f"Нед {x+1}"), y=-sub["backorder"], name="Дефицит", marker_color="#ef4444"))
    fig.update_layout(
        title=f"Траектория запасов: {sku}",
        xaxis_title="",
        yaxis_title="Единицы",
        height=300, margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig
