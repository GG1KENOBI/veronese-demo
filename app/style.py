"""Design tokens — single source of truth for colors, fonts, spacing.

Before: colors were scattered across main.py and charts.py with drift
(3 different blues for forecast, 2 different donut palettes, waterfall
total #1e40af vs #2563eb).

After: import from here. Any chart or layout uses the same tokens.

Usage:
    from app.style import COLORS, FONT, CATEGORY_COLORS, PLOTLY_LAYOUT

    fig.update_layout(**PLOTLY_LAYOUT)
    fig.add_trace(go.Bar(marker_color=COLORS["brand_primary"], ...))
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────
# Brand + semantic palette
# ─────────────────────────────────────────────────────────────────────
COLORS = {
    # Brand (consistent blue family)
    "brand_primary": "#1e40af",     # Dominant brand blue — hero KPI bar, forecast history
    "brand_accent": "#60a5fa",      # Lighter blue for forecast/future, hover
    "brand_deep": "#1e3a8a",        # Darker variant for borders/ink

    # Product categories (roast types, package forms)
    "roast_dark": "#78350f",
    "roast_medium": "#b45309",
    "roast_light": "#fbbf24",
    "capsules": "#0284c7",
    "flavored": "#ec4899",
    "decaf": "#6b7280",
    "three_in_one": "#ca8a04",

    # Semantic (good/bad/info/warning)
    "good": "#22c55e",
    "bad": "#ef4444",
    "warning": "#f59e0b",
    "info": "#3b82f6",
    "neutral": "#64748b",

    # Ink (text + backgrounds on dark theme)
    "ink_bright": "#e5e7eb",        # primary text on dark bg
    "ink_muted": "#94a3b8",         # secondary text, captions, axis labels
    "ink_dim": "#64748b",           # tertiary, gridlines
    "ink_dark": "#0f172a",          # text on light surfaces

    # Backgrounds
    "bg_panel": "rgba(30, 41, 59, 0.4)",  # subtle container tint
    "bg_card": "rgba(30, 41, 59, 0.6)",   # button/card tint
    "bg_transparent": "rgba(0, 0, 0, 0)",
    "border": "#334155",
}


# Category colors for Gantt blocks, keyed by product category label
CATEGORY_COLORS = {
    "Тёмная обжарка": COLORS["roast_dark"],
    "Средняя обжарка": COLORS["roast_medium"],
    "Светлая обжарка": COLORS["roast_light"],
    "Ароматизированный": COLORS["flavored"],
    "Без кофеина": COLORS["decaf"],
    "Капсулы": COLORS["capsules"],
    "3-в-1": COLORS["three_in_one"],
    "Прочее": COLORS["neutral"],
}


# OEE loss category colors (Six Big Losses)
LOSS_COLORS = {
    "Availability": COLORS["bad"],
    "Performance": COLORS["warning"],
    "Quality": "#a855f7",  # purple — distinct from warning orange
}


# Cost-breakdown donut (production, setup, holding, backorder)
COST_COLORS = [
    COLORS["brand_primary"],     # Production
    COLORS["warning"],           # Setup
    COLORS["good"],              # Holding
    COLORS["bad"],               # Backorder
]


# Typography scale (Plotly font sizes)
FONT = {
    "xs": 9,     # dense tick labels
    "sm": 11,    # standard axis labels, captions
    "md": 13,    # body text, legend
    "lg": 15,    # chart titles
    "xl": 20,    # section headers
    "hero": 48,  # main hero number in markdown/HTML
}


# Shared Plotly layout defaults. Apply via `fig.update_layout(**PLOTLY_LAYOUT)`.
PLOTLY_LAYOUT = {
    "plot_bgcolor": COLORS["bg_transparent"],
    "paper_bgcolor": COLORS["bg_transparent"],
    "font": {"color": COLORS["ink_bright"], "size": FONT["md"]},
    "hoverlabel": {
        "bgcolor": COLORS["ink_dark"],
        "bordercolor": COLORS["border"],
        "font": {"color": COLORS["ink_bright"], "size": FONT["sm"]},
    },
    "xaxis": {
        "gridcolor": "rgba(148, 163, 184, 0.15)",
        "tickfont": {"size": FONT["sm"]},
    },
    "yaxis": {
        "gridcolor": "rgba(148, 163, 184, 0.15)",
        "tickfont": {"size": FONT["sm"]},
    },
}


# Waterfall marker colors — referenced by charts.py
WATERFALL_COLORS = {
    "increasing": COLORS["good"],
    "decreasing": COLORS["bad"],
    "total": COLORS["brand_primary"],
    "connector": COLORS["ink_muted"],
}
