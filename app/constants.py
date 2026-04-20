"""Client-specific constants loaded from config/client.yaml.

Single source of truth for all hardcoded demo numbers. Reshape the demo
for a new client by editing config/client.yaml, not Python code.

Usage:
    from app.constants import CLIENT, annual_savings_mrub

    st.title(f"+{CLIENT.headline_savings_mrub:.0f} млн ₽/год на линиях {CLIENT.name}")
    savings = annual_savings_mrub(hours_per_day=4.0)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _ROOT / "config" / "client.yaml"


@dataclass(frozen=True)
class ClientConfig:
    """Immutable client profile. Loaded once at module import."""

    name: str
    name_short: str
    brand_style: str
    lines_count: int
    shifts_per_day: int
    hours_per_shift: int
    working_days_per_year: int
    rub_per_production_minute: float
    currency_symbol: str
    headline_savings_mrub: Optional[float]

    # Pricing references
    mvp_price_usd_min: int
    mvp_price_usd_max: int
    full_rollout_price_usd_min: int
    full_rollout_price_usd_max: int
    typical_payback_months_min: int
    typical_payback_months_max: int
    enterprise_comparison_price_usd_5y_min: int
    enterprise_comparison_price_usd_5y_max: int
    enterprise_comparison_name: str

    @property
    def production_minutes_per_year(self) -> int:
        """How many productive minutes a year at nominal schedule."""
        return (
            self.lines_count
            * self.shifts_per_day
            * self.hours_per_shift
            * 60
            * self.working_days_per_year
        )


def _load_config(path: Path = _CONFIG_PATH) -> ClientConfig:
    if not path.exists():
        # Safe VERONESE defaults if yaml missing (dev convenience)
        return ClientConfig(
            name="VERONESE", name_short="VERONESE",
            brand_style="Союз ЛУР / VERONESE",
            lines_count=3, shifts_per_day=1, hours_per_shift=8,
            working_days_per_year=220,
            rub_per_production_minute=3500.0,
            currency_symbol="₽",
            headline_savings_mrub=None,
            mvp_price_usd_min=50_000, mvp_price_usd_max=100_000,
            full_rollout_price_usd_min=150_000, full_rollout_price_usd_max=200_000,
            typical_payback_months_min=2, typical_payback_months_max=4,
            enterprise_comparison_price_usd_5y_min=2_000_000,
            enterprise_comparison_price_usd_5y_max=5_000_000,
            enterprise_comparison_name="SAP IBP / Kinaxis",
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    mvp = data.get("mvp_price_usd", {}) or {}
    full = data.get("full_rollout_price_usd", {}) or {}
    payback = data.get("typical_payback_months", {}) or {}
    enterprise = data.get("enterprise_comparison_price_usd_5y", {}) or {}

    return ClientConfig(
        name=str(data.get("client_name", "VERONESE")),
        name_short=str(data.get("client_name_short", data.get("client_name", "VERONESE"))),
        brand_style=str(data.get("brand_style", "")),
        lines_count=int(data.get("lines_count", 3)),
        shifts_per_day=int(data.get("shifts_per_day", 1)),
        hours_per_shift=int(data.get("hours_per_shift", 8)),
        working_days_per_year=int(data.get("working_days_per_year", 220)),
        rub_per_production_minute=float(data.get("rub_per_production_minute", 3500)),
        currency_symbol=str(data.get("currency_symbol", "₽")),
        headline_savings_mrub=(
            float(data["headline_annual_savings_mrub"])
            if data.get("headline_annual_savings_mrub") is not None
            else None
        ),
        mvp_price_usd_min=int(mvp.get("min", 50_000)),
        mvp_price_usd_max=int(mvp.get("max", 100_000)),
        full_rollout_price_usd_min=int(full.get("min", 150_000)),
        full_rollout_price_usd_max=int(full.get("max", 200_000)),
        typical_payback_months_min=int(payback.get("min", 2)),
        typical_payback_months_max=int(payback.get("max", 4)),
        enterprise_comparison_price_usd_5y_min=int(enterprise.get("min", 2_000_000)),
        enterprise_comparison_price_usd_5y_max=int(enterprise.get("max", 5_000_000)),
        enterprise_comparison_name=str(data.get("enterprise_comparison_name", "SAP IBP / Kinaxis")),
    )


# Loaded once at import. Changing config/client.yaml requires a Streamlit rerun.
CLIENT: ClientConfig = _load_config()


# ─────────────────────────────────────────────────────────────────────
# Pure functions — derive dynamic numbers from hours of savings + client config
# ─────────────────────────────────────────────────────────────────────

def annual_savings_rub(hours_saved_per_day: float, client: ClientConfig = CLIENT) -> float:
    """Annual ₽ saved, given hours-per-day freed up on packaging lines."""
    return hours_saved_per_day * 60 * client.working_days_per_year * client.rub_per_production_minute


def annual_savings_mrub(hours_saved_per_day: float, client: ClientConfig = CLIENT) -> float:
    """Annual savings in millions of ₽."""
    return annual_savings_rub(hours_saved_per_day, client) / 1_000_000


def headline_savings_mrub(hours_saved_per_day: float, client: ClientConfig = CLIENT) -> float:
    """Main hero number — uses override from yaml if set, else computes."""
    if client.headline_savings_mrub is not None:
        return client.headline_savings_mrub
    return annual_savings_mrub(hours_saved_per_day, client)


def format_rub(amount_rub: float) -> str:
    """'1 234 567 ₽' style formatting for Russian UI."""
    return f"{amount_rub:,.0f}".replace(",", " ") + f" {CLIENT.currency_symbol}"


def format_mrub(amount_mrub: float, digits: int = 0) -> str:
    """'185 млн ₽' style."""
    return f"{amount_mrub:,.{digits}f}".replace(",", " ") + f" млн {CLIENT.currency_symbol}"
