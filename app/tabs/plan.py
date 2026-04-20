"""Production plan tab — inside an expander on the main page.

Shows SKU × week heatmap, shadow prices, and cost breakdown donut.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app.constants import CLIENT
from app.data import DemoData
from app.style import COLORS, COST_COLORS
from src.visualization.charts import _short_sku_label


def render(data: DemoData) -> None:
    # ---- KPIs
    if not data.cost.empty:
        total = data.cost["rub"].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Стоимость плана, 12 недель",
            f"{total/1e6:.1f} млн ₽",
            help="Суммарные затраты: сырьё + переналадки + хранение + штрафы.",
        )
        labels = [
            ("Setup", "Переналадки", "~25 000 ₽ за каждую"),
            ("Holding", "Хранение", "12 ₽ за упаковку в неделю"),
            ("Backorder", "Штрафы за дефицит", "800 ₽ за недопоставленную"),
        ]
        for col, (cat_name, label, help_text) in zip([c2, c3, c4], labels):
            if cat_name in data.cost["category"].values:
                val = data.cost[data.cost["category"] == cat_name]["rub"].iloc[0]
                col.metric(label, f"{val/1e6:.2f} млн ₽", help=help_text)

    # ---- Bottleneck narrative
    bottleneck = None
    if not data.sp.empty and "binding" in data.sp.columns:
        bind = data.sp[data.sp["binding"]].sort_values("shadow_price_rub_per_min", ascending=False)
        if not bind.empty:
            top = bind.iloc[0]
            bottleneck = {"line": top["line"], "week": int(top["week"]) + 1, "price": float(top["shadow_price_rub_per_min"])}

    if bottleneck:
        st.info(
            f"📍 **Самое слабое звено:** линия **{bottleneck['line']}** на неделе **{bottleneck['week']}**. "
            f"Добавить час работы там = экономия **{bottleneck['price']*60:,.0f} ₽**.".replace(",", " ")
        )
    else:
        st.info(
            "✅ **Узких мест нет** — мощностей хватает. "
            "Чтобы посмотреть, что происходит при перегрузке, выберите в сайдбаре "
            "«Поломка линии −35%» и нажмите «Применить»."
        )

    # ---- Heatmap SKU × week + shadow prices side-by-side
    left, right = st.columns([2, 1])

    with left:
        st.markdown("##### Что производить каждую неделю")
        st.caption("Строки — SKU, столбцы — недели. Чем темнее — больше штук. Пустые = не планируется.")
        if not data.plan.empty:
            pivot = data.plan.pivot_table(
                index="sku_id", columns="week", values="production_units", aggfunc="sum",
            ).fillna(0)
            if len(pivot) > 0:
                pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]

            cat_map = data.cat.set_index("sku_id").to_dict(orient="index") if not data.cat.empty else {}
            y_labels = [_short_sku_label(s, cat_map.get(s, {})) for s in pivot.index]

            fig = go.Figure(data=go.Heatmap(
                z=pivot.values,
                x=[f"Нед {c+1}" for c in pivot.columns],
                y=y_labels,
                colorscale="Blues",
                colorbar=dict(title="шт"),
                hovertemplate="%{y}<br>%{x}<br>%{z:,.0f} шт<extra></extra>",
            ))
            fig.update_layout(
                height=500,
                margin=dict(l=180, r=20, t=10, b=30),
                yaxis=dict(tickfont=dict(size=10)),
            )
            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("##### Ценность +1 мин мощности")
        st.caption("Где на линиях больнее всего не хватает времени. Тёплее = дороже.")
        if not data.sp.empty:
            sp_pivot = data.sp.pivot(
                index="line", columns="week", values="shadow_price_rub_per_min",
            ).fillna(0)
            fig = go.Figure(data=go.Heatmap(
                z=sp_pivot.values,
                x=[f"Нед {c+1}" for c in sp_pivot.columns],
                y=sp_pivot.index,
                colorscale="Reds",
                colorbar=dict(title=f"{CLIENT.currency_symbol}/мин"),
                hovertemplate="%{y}<br>%{x}<br>%{z:,.0f} ₽/мин<extra></extra>",
            ))
            fig.update_layout(height=230, margin=dict(l=80, r=20, t=10, b=20))
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("##### Структура затрат")
        if not data.cost.empty:
            fig = go.Figure(go.Pie(
                labels=data.cost["category"],
                values=data.cost["rub"],
                hole=0.55,
                marker=dict(colors=COST_COLORS),
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:,.0f} ₽<extra></extra>",
            ))
            total = data.cost["rub"].sum()
            fig.update_layout(
                height=230,
                margin=dict(l=10, r=10, t=10, b=10),
                showlegend=False,
                annotations=[dict(
                    text=f"<b>{total/1e6:.1f} М₽</b>",
                    x=0.5, y=0.5,
                    font_size=15,
                    showarrow=False,
                )],
            )
            st.plotly_chart(fig, use_container_width=True)

    # ---- Raw data expander
    with st.expander("🗄 Детальный план (таблица)"):
        if not data.plan.empty:
            plan_view = data.plan.copy()
            plan_view["week"] = plan_view["week"] + 1
            plan_view = plan_view.rename(columns={
                "sku_id": "Товар", "line": "Линия", "week": "Неделя",
                "production_units": "Произвести, шт.", "setup": "Переналадка?",
            })
            plan_view["Произвести, шт."] = plan_view["Произвести, шт."].round(0).astype(int)
            st.dataframe(plan_view, use_container_width=True, hide_index=True, height=320)
