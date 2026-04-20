"""ROI wizard — client enters 3 numbers, hero is recomputed under their data.

Goal: turn a generic VERONESE demo ("+185 млн ₽/год") into the client's own
number ("+127 млн ₽/год для вашего завода"). Psychologically the cifra
becomes "mine", not "theirs".
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from app.constants import CLIENT, annual_savings_mrub


@dataclass
class ClientInputs:
    """User-overridden parameters. All 3 affect annual savings calculation."""

    lines_count: int
    working_days_per_year: int
    rub_per_production_minute: float


def _session_defaults() -> ClientInputs:
    """Seed wizard fields from config/client.yaml on first render."""
    return ClientInputs(
        lines_count=CLIENT.lines_count,
        working_days_per_year=CLIENT.working_days_per_year,
        rub_per_production_minute=CLIENT.rub_per_production_minute,
    )


def get_inputs() -> ClientInputs:
    """Read current wizard state from session. Seeds defaults if empty."""
    if "wizard_inputs" not in st.session_state:
        st.session_state.wizard_inputs = _session_defaults()
    return st.session_state.wizard_inputs


def render_compact(hours_saved_per_day: float) -> ClientInputs:
    """3-column compact wizard. Returns the currently-entered inputs.

    Call this ABOVE the hero KPI so the user can enter their numbers
    and see them reflect immediately in `headline_savings_mrub()`.
    """
    defaults = get_inputs()

    st.markdown(
        "<div style='color:#94a3b8;font-size:13px;margin-bottom:8px;'>"
        "Введите 3 цифры вашего завода — пересчитаем экономию под вас"
        "</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        lines = st.number_input(
            "Количество линий",
            min_value=1, max_value=50,
            value=int(defaults.lines_count),
            step=1,
            help="Сколько фасовочных линий на вашем заводе?",
        )
    with c2:
        days = st.number_input(
            "Рабочих дней в году",
            min_value=100, max_value=365,
            value=int(defaults.working_days_per_year),
            step=1,
            help="Сколько дней в году завод реально производит (обычно 220).",
        )
    with c3:
        rub_min = st.number_input(
            "Выручка на минуту производства, ₽",
            min_value=100, max_value=100_000,
            value=int(defaults.rub_per_production_minute),
            step=100,
            help=(
                "Средняя валовая выручка с минуты полезной работы линии. "
                "Типично для FMCG-кофе: 3000–5000 ₽/мин. Если не уверены — "
                "оставьте 3500."
            ),
        )

    new_inputs = ClientInputs(
        lines_count=int(lines),
        working_days_per_year=int(days),
        rub_per_production_minute=float(rub_min),
    )
    st.session_state.wizard_inputs = new_inputs
    return new_inputs


def compute_savings_mrub(hours_saved_per_day: float, inputs: ClientInputs) -> float:
    """Apply the wizard inputs to compute annual savings in millions ₽.

    Scales linearly with `lines_count` vs `CLIENT.lines_count` — assumption
    that more lines multiply the per-day savings.
    """
    line_multiplier = inputs.lines_count / max(CLIENT.lines_count, 1)
    effective_hours = hours_saved_per_day * line_multiplier
    return (
        effective_hours
        * 60
        * inputs.working_days_per_year
        * inputs.rub_per_production_minute
    ) / 1_000_000
