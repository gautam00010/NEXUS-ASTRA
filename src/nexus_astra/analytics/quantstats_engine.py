"""QuantStats Analytics Engine for automated tear sheets with Sharpe Worm integration."""
import quantstats as qs
import pandas as pd
import numpy as np
import logging
from pathlib import Path
from nexus_astra.education.sharpe_worm import (
    get_sharpe_worm_metrics,
    render_sharpe_worm_canvas_html,
)

logger = logging.getLogger(__name__)


class QuantStatsEngine:
    @staticmethod
    def get_sharpe_worm(returns: pd.Series, rf: float = 0.0) -> dict:
        """Calculate Sharpe Ratio and corresponding Sharpe Worm animation metrics."""
        clean_rets = returns.dropna()
        if clean_rets.empty:
            return get_sharpe_worm_metrics(excess_return=0.0, volatility=0.0, sharpe=0.0)

        mean_daily = float(clean_rets.mean())
        std_daily = float(clean_rets.std()) if len(clean_rets) > 1 else 1e-4

        ann_return = mean_daily * 252.0 - rf
        ann_vol = std_daily * np.sqrt(252.0)
        sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0

        worm_data = get_sharpe_worm_metrics(
            excess_return=ann_return,
            volatility=ann_vol,
            sharpe=sharpe,
        )
        return worm_data

    @staticmethod
    def generate_tear_sheet(returns: pd.Series, output_path: str = "logs/quantstats_tearsheet.html"):
        """
        Generates a comprehensive QuantStats tear sheet (HTML report).
        Includes Sharpe (after costs), DD, and performance metrics alongside the Sharpe Worm animation.
        """
        try:
            # Ensure index is datetime for quantstats
            if not isinstance(returns.index, pd.DatetimeIndex):
                returns.index = pd.to_datetime(returns.index)

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            qs.reports.html(returns, output=output_path, title="NEXUS-ASTRA Live Tear Sheet")
            logger.info(f"QuantStats tear sheet generated at {output_path}")

            # Embed Sharpe worm explainer alongside tear sheet
            worm_info = QuantStatsEngine.get_sharpe_worm(returns)
            worm_html = render_sharpe_worm_canvas_html(
                excess_return=worm_info["excess_return"],
                volatility=worm_info["volatility"],
                sharpe=worm_info["sharpe"],
                canvas_id="qs_tear_sheet_worm",
                label=f"NEXUS-ASTRA SHARPE WORM [{worm_info['category']}]",
                width=600,
                height=180,
            )

            # Append Sharpe Worm section to the generated HTML report
            if Path(output_path).exists():
                with open(output_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                worm_injection = f"""
                <div style="max-width:960px; margin:24px auto; padding:16px; background:#0F0F0F; border:1px solid #333; border-radius:6px; color:#EAEAEA; font-family:monospace;">
                    <h3 style="color:#FFA500; margin-top:0;">⚡ Quant Papers: Sharpe Ratio = Skill Over Luck</h3>
                    <p style="color:#A0A0A0; font-size:12px;">{worm_info['summary_text']}</p>
                    {worm_html}
                </div>
                """
                if "</body>" in content:
                    content = content.replace("</body>", f"{worm_injection}</body>")
                    with open(output_path, "w", encoding="utf-8") as f:
                        f.write(content)
        except Exception as e:
            logger.warning(f"QuantStats generation failed: {e}")
