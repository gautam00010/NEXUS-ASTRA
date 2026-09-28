"""Position sizing and risk overlays for NEXUS-ASTRA."""

from __future__ import annotations


def calculate_fractional_kelly_allocation(
    historical_win_rate: float,
    average_win_pct: float,
    average_loss_pct: float,
) -> float:
    """Return the capital allocation percentage using a 0.25x Fractional Kelly Criterion.

    The Kelly fraction is computed as:

        Kelly = win_rate - ((1 - win_rate) / payoff_ratio)

    where payoff_ratio = average_win_pct / average_loss_pct.

    The final allocation is clipped to the range [0, 100].
    """

    _validate_probability(historical_win_rate)
    _validate_positive("average_win_pct", average_win_pct)
    _validate_positive("average_loss_pct", average_loss_pct)

    payoff_ratio = average_win_pct / average_loss_pct
    if payoff_ratio <= 0:
        raise ValueError("Payoff ratio must be positive.")

    kelly_fraction = historical_win_rate - ((1.0 - historical_win_rate) / payoff_ratio)
    fractional_kelly = max(0.0, kelly_fraction * 0.25)
    return _clip_percentage(fractional_kelly * 100.0)


def apply_volatility_targeting(
    kelly_allocation_pct: float,
    current_vix: float,
) -> float:
    """Apply a 50% reduction to the Kelly allocation when VIX is above 25."""

    _validate_percentage("kelly_allocation_pct", kelly_allocation_pct)
    _validate_non_negative("current_vix", current_vix)

    adjusted_allocation = kelly_allocation_pct * 0.5 if current_vix > 25.0 else kelly_allocation_pct
    return _clip_percentage(adjusted_allocation)


def calculate_final_capital_allocation_pct(
    historical_win_rate: float,
    average_win_pct: float,
    average_loss_pct: float,
    current_vix: float,
) -> float:
    """Return the final capital allocation percentage after Kelly sizing and VIX targeting."""

    base_allocation = calculate_fractional_kelly_allocation(
        historical_win_rate=historical_win_rate,
        average_win_pct=average_win_pct,
        average_loss_pct=average_loss_pct,
    )
    return apply_volatility_targeting(base_allocation, current_vix)


def apply_position_caps(
    raw_allocation_pct: float,
    sector_current_pct: float = 0.0,
    sector_cap_pct: float = 30.0,
    max_position_pct: float = 15.0,
) -> tuple[float, str]:
    """
    Enforce hard position caps:
      1. Max single position: 15% of portfolio
      2. Max sector concentration: 30% of portfolio
    Returns (final_allocation_pct, reason_str).
    """
    reasons: list[str] = []
    alloc = raw_allocation_pct

    if alloc > max_position_pct:
        reasons.append(f"capped_position_{max_position_pct}pct")
        alloc = max_position_pct

    remaining_sector_capacity = max(0.0, sector_cap_pct - sector_current_pct)
    if alloc > remaining_sector_capacity:
        reasons.append(f"capped_sector_concentration_{sector_cap_pct}pct")
        alloc = remaining_sector_capacity

    return _clip_percentage(alloc), "|".join(reasons) if reasons else "OK"


def compute_position_size(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    current_vix: float,
    sector_current_pct: float = 0.0,
) -> dict[str, float | str]:
    """
    Single entry-point for position sizing.
    Returns dict with: kelly_raw, kelly_fractional, after_vix, final, cap_reason.
    
    Formula: f* = [W*(R+1)-1]/R * 0.20  (20% fractional Kelly)
    where R = avg_win/avg_loss, W = win_rate
    """
    _validate_probability(win_rate)
    _validate_positive("avg_win_pct", avg_win_pct)
    _validate_positive("avg_loss_pct", avg_loss_pct)

    R = avg_win_pct / avg_loss_pct
    kelly_raw = (win_rate * (R + 1.0) - 1.0) / R  # full Kelly fraction
    kelly_frac = max(0.0, kelly_raw * 0.20)         # 20% fractional Kelly
    kelly_pct = _clip_percentage(kelly_frac * 100.0)

    # VIX targeting: halve when VIX > 25
    after_vix = kelly_pct * 0.5 if current_vix > 25.0 else kelly_pct

    final, cap_reason = apply_position_caps(
        raw_allocation_pct=after_vix,
        sector_current_pct=sector_current_pct,
    )

    return {
        "kelly_raw": round(kelly_raw * 100, 4),
        "kelly_fractional_20pct": round(kelly_pct, 4),
        "after_vix_targeting": round(after_vix, 4),
        "final_pct": round(final, 4),
        "cap_reason": cap_reason,
    }


def _validate_probability(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError("historical_win_rate must be between 0 and 1.")


def _validate_positive(name: str, value: float) -> None:
    if value <= 0.0:
        raise ValueError(f"{name} must be greater than 0.")


def _validate_non_negative(name: str, value: float) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be greater than or equal to 0.")


def _validate_percentage(name: str, value: float) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be greater than or equal to 0.")


def _clip_percentage(value: float) -> float:
    return max(0.0, min(100.0, value))
