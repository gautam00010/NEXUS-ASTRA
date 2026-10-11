"""Quant Papers Education Module - Animated Worm Sharpe Ratio Explainer.

Core Concept:
Sharpe Ratio = (Rp - Rf) / σp = Excess Return / Volatility
Measures risk-adjusted returns by dividing excess return by volatility so investors compare skill over luck.

The Animated Worm Model:
- Worm body length = Excess Return (Rp - Rf) -> Longer worm = more return
- Worm wiggle amplitude = Volatility σp -> More wiggle = more risk
- Worm speed / propagation = Sharpe Ratio -> High Sharpe moves straight & fast (skill),
  low Sharpe wiggles sideways slowly (luck / gambling)
- Color classification:
  * Green  (#00C853): Sharpe >= 1.5 -> SKILL (Institutional Alpha)
  * Amber  (#FFA500): 0.5 <= Sharpe < 1.5 -> LUCK (Market Beta)
  * Red    (#FF2D2D): Sharpe < 0.5 -> GAMBLING (Uncompensated Risk)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


def get_sharpe_worm_metrics(
    excess_return: float,
    volatility: float,
    sharpe: float | None = None,
) -> Dict[str, Any]:
    """Calculate Sharpe ratio, classification, and educational worm description."""
    safe_vol = max(abs(volatility), 0.0001)
    if sharpe is None:
        computed_sharpe = excess_return / safe_vol
    else:
        computed_sharpe = float(sharpe)

    # Classification
    if computed_sharpe >= 1.5:
        category = "SKILL"
        color = "#00C853"
        verdict = "Skill Over Luck (Institutional Alpha)"
        behavior = "Green worm moving straight and fast"
    elif computed_sharpe >= 0.5:
        category = "LUCK"
        color = "#FFA500"
        verdict = "Market Beta / Moderate Luck"
        behavior = "Amber worm with moderate wiggle and pace"
    else:
        category = "GAMBLING"
        color = "#FF2D2D"
        verdict = "Gambling / Uncompensated Risk"
        behavior = "Red worm wiggling sideways slowly"

    ret_pct = excess_return if abs(excess_return) > 1.0 else excess_return * 100.0
    vol_pct = volatility if abs(volatility) > 1.0 else volatility * 100.0

    summary_text = (
        f"Sharpe {computed_sharpe:.2f} | Length {ret_pct:.1f}% return / "
        f"Wiggle {vol_pct:.1f}% vol = {category} - {behavior}"
    )

    telegram_text = (
        f"🪱 Sharpe {computed_sharpe:.2f} | Length {ret_pct:.1f}% return / "
        f"Wiggle {vol_pct:.1f}% vol = {category} - {behavior} - {verdict}"
    )

    return {
        "excess_return": excess_return,
        "excess_return_pct": ret_pct,
        "volatility": volatility,
        "volatility_pct": vol_pct,
        "sharpe": computed_sharpe,
        "category": category,
        "color": color,
        "verdict": verdict,
        "behavior": behavior,
        "summary_text": summary_text,
        "telegram_text": telegram_text,
    }


def animate_sharpe_worm(
    excess_return: float,
    volatility: float,
    sharpe: float | None = None,
    frames: int = 100,
    interval: int = 50,
) -> animation.FuncAnimation:
    """
    Generate an animated worm visualizing the Sharpe Ratio using matplotlib.animation.FuncAnimation.
    
    Worm dynamics:
    - Worm body length = excess return (Rp - Rf)
    - Worm wiggle amplitude = volatility σp
    - Worm speed = Sharpe Ratio (frequency / phase shift)
    - Color = Green (Sharpe > 1.5), Orange (0.5 - 1.5), Red (< 0.5)
    """
    metrics = get_sharpe_worm_metrics(excess_return, volatility, sharpe)
    s = metrics["sharpe"]
    vol = max(0.05, abs(volatility))
    ret_len = max(0.5, abs(excess_return))

    fig, ax = plt.subplots(figsize=(8, 3.5), facecolor="#000000")
    ax.set_facecolor("#000000")

    # Domain for the worm body
    x_base = np.linspace(0, ret_len, 100)
    
    # Speed and wiggle frequency scale with Sharpe
    speed_factor = max(0.2, abs(s)) * 0.15
    freq = max(1.0, 5.0 - min(4.0, max(0.0, s)))  # lower Sharpe wiggles more frequently sideways

    color = "green" if s >= 1.5 else ("orange" if s >= 0.5 else "red")
    line, = ax.plot([], [], lw=4, color=color, solid_capstyle="round")
    head_dot, = ax.plot([], [], "o", color=color, markersize=8)

    ax.set_xlim(-0.2, ret_len + 0.5)
    ax.set_ylim(-vol * 1.8 - 0.1, vol * 1.8 + 0.1)
    
    # Bloomberg minimalist styling
    ax.spines["bottom"].set_color("#333333")
    ax.spines["left"].set_color("#333333")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors="#888888", labelsize=9)
    ax.grid(True, color="#1A1A1A", linestyle="--", alpha=0.7)
    
    title_str = f"Sharpe: {s:.2f} ({metrics['category']}) | Length={ret_len:.1f} | Wiggle={vol:.2f}"
    ax.set_title(title_str, color="#EAEAEA", fontsize=11, fontweight="bold", pad=10)

    def init():
        line.set_data([], [])
        head_dot.set_data([], [])
        return line, head_dot

    def update(frame: int):
        phase = frame * speed_factor
        # Wiggle = volatility * sin(x * freq - phase)
        worm_y = vol * np.sin(x_base * freq - phase)
        line.set_data(x_base, worm_y)
        head_dot.set_data([x_base[-1]], [worm_y[-1]])
        return line, head_dot

    ani = animation.FuncAnimation(
        fig,
        update,
        init_func=init,
        frames=frames,
        interval=interval,
        blit=True,
    )
    
    # Attach fig to ani for convenience
    ani._fig = fig
    return ani


def create_plotly_sharpe_worm(
    excess_return: float,
    volatility: float,
    sharpe: float | None = None,
    title: str = "Sharpe Ratio Animated Worm",
) -> go.Figure:
    """
    Generate an interactive Plotly animated figure with play controls.
    """
    metrics = get_sharpe_worm_metrics(excess_return, volatility, sharpe)
    s = metrics["sharpe"]
    vol = max(0.05, abs(volatility))
    ret_len = max(0.5, abs(excess_return))
    
    color = "#00C853" if s >= 1.5 else ("#FFA500" if s >= 0.5 else "#FF2D2D")
    speed_factor = max(0.2, abs(s)) * 0.18
    freq = max(1.0, 5.0 - min(4.0, max(0.0, s)))

    x = np.linspace(0, ret_len, 80)
    
    # Create base trace
    y_init = vol * np.sin(x * freq)
    fig = go.Figure(
        data=[
            go.Scatter(
                x=x,
                y=y_init,
                mode="lines+markers",
                line=dict(color=color, width=5),
                marker=dict(size=[0]*(len(x)-1) + [12], color=color),
                name=f"Sharpe {s:.2f}",
            )
        ],
        layout=go.Layout(
            title=dict(
                text=f"{title} // Sharpe: {s:.2f} [{metrics['category']}]",
                font=dict(color="#EAEAEA", family="IBM Plex Mono", size=13),
            ),
            paper_bgcolor="#000000",
            plot_bgcolor="#0A0A0A",
            xaxis=dict(
                title=dict(text="Excess Return (Length)", font=dict(color="#888888", size=11)),
                range=[-0.1, ret_len + 0.2],
                color="#888888",
                gridcolor="#1F1F1F",
            ),
            yaxis=dict(
                title=dict(text="Volatility (Wiggle)", font=dict(color="#888888", size=11)),
                range=[-vol * 2.0, vol * 2.0],
                color="#888888",
                gridcolor="#1F1F1F",
            ),
            margin=dict(l=40, r=40, t=50, b=40),
            showlegend=False,
            height=280,
            updatemenus=[
                dict(
                    type="buttons",
                    showactive=False,
                    x=1.05,
                    y=1.15,
                    buttons=[
                        dict(
                            label="▶ Animate",
                            method="animate",
                            args=[
                                None,
                                dict(
                                    frame=dict(duration=50, redraw=False),
                                    fromcurrent=True,
                                    mode="immediate",
                                    loop=True,
                                ),
                            ],
                        )
                    ],
                    font=dict(color="#FFA500", family="IBM Plex Mono", size=10),
                    bgcolor="#1A1A1A",
                    bordercolor="#333333",
                )
            ],
        ),
    )

    # 40 animated frames
    frames = []
    for k in range(40):
        phase = k * speed_factor
        y_k = vol * np.sin(x * freq - phase)
        frames.append(
            go.Frame(
                data=[
                    go.Scatter(
                        x=x,
                        y=y_k,
                        mode="lines+markers",
                        line=dict(color=color, width=5),
                        marker=dict(size=[0]*(len(x)-1) + [12], color=color),
                    )
                ],
                name=f"frame_{k}",
            )
        )
    fig.frames = frames
    return fig


def render_sharpe_worm_canvas_html(
    excess_return: float,
    volatility: float,
    sharpe: float | None = None,
    canvas_id: str = "sharpeWormCanvas",
    label: str = "Trade Sharpe Worm",
    width: int = 280,
    height: int = 180,
) -> str:
    """Generate self-contained HTML5 Canvas snippet rendering a smooth 60fps Sharpe worm."""
    m = get_sharpe_worm_metrics(excess_return, volatility, sharpe)
    s = m["sharpe"]
    vol = max(0.04, abs(volatility))
    ret = max(0.02, abs(excess_return))
    color = m["color"]
    category = m["category"]

    return f"""
    <div style="background:#0F0F0F; border:1px solid #2A2A2A; border-radius:6px; padding:12px; margin-bottom:10px; font-family:'IBM Plex Mono',monospace;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span style="color:#EAEAEA; font-weight:700; font-size:12px;">{label}</span>
            <span style="background:{color}22; color:{color}; border:1px solid {color}55; padding:2px 6px; border-radius:3px; font-size:10px; font-weight:700;">
                {category} // {s:.2f}
            </span>
        </div>
        <canvas id="{canvas_id}" width="{width}" height="{height}" style="width:100%; height:{height}px; background:#000000; border-radius:4px; display:block;"></canvas>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:8px; font-size:10px; color:#888888;">
            <div>LENGTH (Return): <span style="color:#EAEAEA;">{m['excess_return_pct']:.1f}%</span></div>
            <div>WIGGLE (Risk): <span style="color:#EAEAEA;">{m['volatility_pct']:.1f}%</span></div>
            <div>SPEED: <span style="color:{color}; font-weight:600;">{max(0.1, abs(s)):.2f}x</span></div>
            <div>VERDICT: <span style="color:{color}; font-weight:600;">{m['category']}</span></div>
        </div>
    </div>
    <script>
    (function() {{
        const canvas = document.getElementById('{canvas_id}');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const W = canvas.width;
        const H = canvas.height;
        const sharpe = {s};
        const vol = {vol};
        const ret = {ret};
        const color = '{color}';

        let phase = 0;
        const segments = 45;
        // Worm length proportional to return
        const wormLength = Math.min(W * 0.75, Math.max(W * 0.25, ret * W * 2.5));
        // Wiggle amplitude proportional to volatility
        const amplitude = Math.min(H * 0.38, Math.max(6, vol * H * 1.5));
        // High Sharpe moves straight & fast; low Sharpe wiggles frantically sideways & slow progress
        const speed = Math.max(0.04, Math.abs(sharpe) * 0.08);
        const freq = Math.max(1.5, 6.0 - Math.min(4.5, Math.max(0.0, sharpe) * 1.5));

        function draw() {{
            ctx.clearRect(0, 0, W, H);

            // Subtle guideline
            ctx.strokeStyle = '#1A1A1A';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(20, H / 2);
            ctx.lineTo(W - 20, H / 2);
            ctx.stroke();
            ctx.setLineDash([]);

            // Draw worm body
            const startX = 25;
            ctx.beginPath();
            ctx.lineWidth = 6;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.strokeStyle = color;

            let headX = startX;
            let headY = H / 2;

            for (let i = 0; i <= segments; i++) {{
                const t = i / segments;
                const x = startX + t * wormLength;
                // sinusoidal undulation
                const y = (H / 2) + Math.sin(t * freq * Math.PI * 2 - phase) * amplitude;
                if (i === 0) {{
                    ctx.moveTo(x, y);
                }} else {{
                    ctx.lineTo(x, y);
                }}
                if (i === segments) {{
                    headX = x;
                    headY = y;
                }}
            }}
            ctx.stroke();

            // Worm eye / head
            ctx.fillStyle = '#FFFFFF';
            ctx.beginPath();
            ctx.arc(headX, headY, 5, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#000000';
            ctx.beginPath();
            ctx.arc(headX + 1, headY, 2, 0, Math.PI * 2);
            ctx.fill();

            phase += speed;
            requestAnimationFrame(draw);
        }}
        requestAnimationFrame(draw);
    }})();
    </script>
    """


def render_3_worms_comparison_html() -> str:
    """
    Renders the 3 canonical worms side-by-side:
    1. Current Trade: Sharpe -0.71 (Red worm, wiggling sideways slowly - luck/gambling)
    2. Nifty 100 Benchmark: Sharpe 0.80 (Amber worm, moderate wiggle - luck)
    3. NEXUS-ASTRA Target: Sharpe 1.58+ (Green worm, straight fast - skill over luck)
    """
    w1 = render_sharpe_worm_canvas_html(
        excess_return=0.028,
        volatility=0.176,
        sharpe=-0.71,
        canvas_id="worm_current_trade",
        label="WORM 1: CURRENT TRADE (VectorBT)",
        width=300,
        height=140,
    )

    w2 = render_sharpe_worm_canvas_html(
        excess_return=0.095,
        volatility=0.120,
        sharpe=0.80,
        canvas_id="worm_nifty_benchmark",
        label="WORM 2: NIFTY 100 BENCHMARK",
        width=300,
        height=140,
    )

    w3 = render_sharpe_worm_canvas_html(
        excess_return=0.182,
        volatility=0.115,
        sharpe=1.58,
        canvas_id="worm_nexus_astra_target",
        label="WORM 3: NEXUS-ASTRA TARGET (Riskfolio+Kelly)",
        width=300,
        height=140,
    )

    return f"""
    <div style="font-family:'IBM Plex Mono',monospace; color:#EAEAEA;">
        <div style="background:#0F0F0F; border:1px solid #2A2A2A; border-radius:6px; padding:14px; margin-bottom:14px;">
            <div style="color:#FFA500; font-size:13px; font-weight:700; margin-bottom:6px;">
                ⚡ QUANT PAPERS: SHARPE RATIO = SKILL OVER LUCK
            </div>
            <div style="color:#A0A0A0; font-size:11px; line-height:1.6;">
                <span style="color:#EAEAEA; font-weight:600;">Excess Return / Volatility</span> = How much compensation you harvest per unit of market risk.<br/>
                • <b style="color:#EAEAEA;">Worm Length:</b> Excess Return (Rp - Rf) — longer body = higher net returns.<br/>
                • <b style="color:#EAEAEA;">Worm Wiggle:</b> Volatility (σp) — frantic sideways undulation = higher risk.<br/>
                • <b style="color:#EAEAEA;">Worm Speed:</b> Sharpe Ratio — sprint forward in a straight line = <span style="color:#00C853; font-weight:700;">TRUE SKILL</span>. Wiggle sideways slowly = <span style="color:#FF2D2D; font-weight:700;">LUCK / GAMBLING</span>.
            </div>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:12px;">
            <div>{w1}</div>
            <div>{w2}</div>
            <div>{w3}</div>
        </div>
    </div>
    """


__all__ = [
    "get_sharpe_worm_metrics",
    "animate_sharpe_worm",
    "create_plotly_sharpe_worm",
    "render_sharpe_worm_canvas_html",
    "render_3_worms_comparison_html",
]
