"""Unit tests for Quant Papers Sharpe Worm education module."""

import pytest
import numpy as np
import pandas as pd
import matplotlib.animation as animation

from nexus_astra.education.sharpe_worm import (
    animate_sharpe_worm,
    create_plotly_sharpe_worm,
    get_sharpe_worm_metrics,
    render_sharpe_worm_canvas_html,
    render_3_worms_comparison_html,
)
from nexus_astra.analytics.quantstats_engine import QuantStatsEngine
from nexus_astra.portfolio.riskfolio_engine import optimize_portfolio_with_worms


def test_sharpe_worm_metrics_skill_classification():
    """Verify that Sharpe >= 1.5 is classified as SKILL with green color."""
    m = get_sharpe_worm_metrics(excess_return=0.18, volatility=0.10)
    assert m["category"] == "SKILL"
    assert m["color"] == "#00C853"
    assert m["sharpe"] == pytest.approx(1.8, abs=0.01)
    assert "straight and fast" in m["behavior"]


def test_sharpe_worm_metrics_luck_classification():
    """Verify that 0.5 <= Sharpe < 1.5 is classified as LUCK with amber color."""
    m = get_sharpe_worm_metrics(excess_return=0.08, volatility=0.10)
    assert m["category"] == "LUCK"
    assert m["color"] == "#FFA500"
    assert m["sharpe"] == pytest.approx(0.8, abs=0.01)
    assert "moderate wiggle" in m["behavior"]


def test_sharpe_worm_metrics_gambling_classification():
    """Verify that Sharpe < 0.5 is classified as GAMBLING with red color."""
    m = get_sharpe_worm_metrics(excess_return=0.02, volatility=0.15)
    assert m["category"] == "GAMBLING"
    assert m["color"] == "#FF2D2D"
    assert m["sharpe"] < 0.5
    assert "sideways" in m["behavior"]


def test_animate_sharpe_worm_funcanimation():
    """Verify that animate_sharpe_worm returns a valid FuncAnimation instance."""
    ani = animate_sharpe_worm(excess_return=0.12, volatility=0.08, frames=10)
    assert isinstance(ani, animation.FuncAnimation)


def test_plotly_sharpe_worm():
    """Verify that create_plotly_sharpe_worm produces an animated Plotly figure."""
    fig = create_plotly_sharpe_worm(excess_return=0.10, volatility=0.05)
    assert fig is not None
    assert len(fig.frames) > 0


def test_render_3_worms_html():
    """Verify HTML5 canvas 3-worm comparison output."""
    html = render_3_worms_comparison_html()
    assert "worm_current_trade" in html
    assert "worm_nifty_benchmark" in html
    assert "worm_nexus_astra_target" in html
    assert "QUANT PAPERS" in html.upper()


def test_quantstats_sharpe_worm_integration():
    """Verify QuantStats integration with Sharpe worm metrics."""
    rets = pd.Series(np.random.normal(0.001, 0.01, 50), index=pd.date_range("2026-01-01", periods=50))
    worm_data = QuantStatsEngine.get_sharpe_worm(rets)
    assert "sharpe" in worm_data
    assert "category" in worm_data
    assert "telegram_text" in worm_data


def test_riskfolio_sharpe_worms_integration():
    """Verify Riskfolio optimization returns asset-level Sharpe worms."""
    res = optimize_portfolio_with_worms()
    assert "weights" in res
    assert "sharpe_worms" in res
    worms = res["sharpe_worms"]
    assert "TCS" in worms or "RELIANCE" in worms
    for k, v in worms.items():
        assert "sharpe" in v
        assert "worm_summary" in v
