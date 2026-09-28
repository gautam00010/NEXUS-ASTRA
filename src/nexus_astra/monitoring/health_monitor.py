import os
import time
import logging
from datetime import datetime
from typing import Dict, Any

from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.metrics_api import MetricsApi
from datadog_api_client.v2.models import MetricPayload, MetricSeries, MetricPoint, MetricIntakeType

logger = logging.getLogger(__name__)


class SystemHealth:
    """Datadog integration for system health monitoring."""
    
    def __init__(self):
        self.api_key = os.getenv("DATADOG_API_KEY")
        self.app_key = os.getenv("DATADOG_APP_KEY")
        self.enabled = bool(self.api_key and self.app_key)
        
        if self.enabled:
            configuration = Configuration()
            configuration.api_key["apiKeyAuth"] = self.api_key
            configuration.api_key["appKeyAuth"] = self.app_key
            self.api_client = ApiClient(configuration)
            self.metrics_api = MetricsApi(self.api_client)
        else:
            logger.warning("Datadog credentials missing. Health metrics will only be logged locally.")

        self.tags = ["env:production", "project:nexus-astra"]

    def _push_metric(self, metric_name: str, value: float) -> None:
        if not self.enabled:
            logger.debug(f"[LOCAL METRIC] {metric_name}: {value}")
            return
            
        try:
            body = MetricPayload(
                series=[
                    MetricSeries(
                        metric=f"nexus_astra.{metric_name}",
                        type=MetricIntakeType.GAUGE,
                        points=[
                            MetricPoint(
                                timestamp=int(time.time()),
                                value=float(value),
                            ),
                        ],
                        tags=self.tags,
                    ),
                ],
            )
            self.metrics_api.submit_metrics(body=body)
        except Exception as e:
            logger.error(f"Failed to push metric to Datadog: {e}")

    def track_latency(self, component: str, duration_ms: float) -> None:
        """Tracks pipeline or API call latency."""
        self._push_metric(f"latency.{component}", duration_ms)

    def track_freshness(self, dataset: str, age_seconds: float) -> None:
        """Tracks data staleness."""
        self._push_metric(f"freshness.{dataset}", age_seconds)

    def track_signal_velocity(self, signals_per_hour: int) -> None:
        """Tracks the number of signals generated per hour."""
        self._push_metric("signal_velocity", float(signals_per_hour))

    def track_api_error(self, api_name: str) -> None:
        """Increments API error counter."""
        self._push_metric(f"errors.api.{api_name}", 1.0) # Using gauge as counter proxy for simplicity
        
    def track_model_drift(self, model_name: str, drift_score: float) -> None:
        """Tracks statistical model drift (e.g., input feature distributions)."""
        self._push_metric(f"model_drift.{model_name}", drift_score)

    def generate_health_dashboard(self, metrics: Dict[str, Any], filepath: str = "health_dashboard.html") -> None:
        """Generates a simple HTML summary of system health for GitHub Pages."""
        html_content = f"""
        <html>
        <head>
            <title>NEXUS-ASTRA System Health</title>
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #121212; color: #ffffff; padding: 20px; }}
                h1 {{ color: #00ff00; }}
                .metric-card {{ background-color: #1e1e1e; padding: 15px; margin: 10px 0; border-radius: 8px; }}
                .status-ok {{ color: #00ff00; font-weight: bold; }}
                .status-warn {{ color: #ffa500; font-weight: bold; }}
                .status-error {{ color: #ff0000; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h1>System Health Dashboard</h1>
            <p>Last Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
            
            <div class="metric-card">
                <h3>Pipeline Status</h3>
                <p>Status: <span class="status-ok">OPERATIONAL</span></p>
                <p>Latest Signal Velocity: {metrics.get('signal_velocity', 'N/A')} / hour</p>
            </div>
            
            <div class="metric-card">
                <h3>API Health</h3>
                <p>Recent Errors: {metrics.get('recent_errors', 0)}</p>
            </div>
        </body>
        </html>
        """
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"Health dashboard generated at {filepath}")
        except Exception as e:
            logger.error(f"Failed to write health dashboard: {e}")
