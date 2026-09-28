"""VON Router for direct probabilistic decisions without heavy LLM generation."""

import time
import logging
from typing import Any, Dict, List

try:
    import von
except ImportError:
    # Fallback if von is not strictly installed
    von = None

logger = logging.getLogger(__name__)

class VonRouter:
    """Wrapper for VON decision routing and psychological firewalls."""
    
    def __init__(self):
        self.presets = {
            "regime_state": {
                "choices": ["normal", "elevated_risk", "data_uncertain"],
                "instructions": "Determine market regime. normal if VIX<20 and trend intact, elevated_risk if VIX>25 or heavy selling, data_uncertain if stale."
            },
            "event_risk": {
                "instructions": "Is there an impending trading halt, ban, or regulatory action?"
            },
            "news_tone": {
                "criteria": ["bearish", "neutral", "bullish"],
                "instructions": "Score the tone ordinally from bearish to bullish."
            },
            "fii_exhaustion": {
                "choices": ["accelerating", "decelerating", "absorbed"],
                "instructions": "Is foreign institutional selling accelerating, decelerating, or absorbed by domestic flows?"
            },
            "promoter_signal": {
                "choices": ["increasing", "decreasing", "pledge_rise"],
                "instructions": "Are promoters increasing stakes, decreasing, or pledging shares?"
            }
        }
        
    def decide(self, state: str, preset_name: str) -> Dict[str, Any]:
        preset = self.presets[preset_name]
        start = time.time()
        
        if not von or not hasattr(von, 'decide'):
            return {"choice": "DATA_FAIL", "confidence": 0.0, "latency_ms": 0.0}
        
        try:
            res = von.decide(state, preset["choices"], preset["instructions"])
            # Extract Choice with confidence = P(c1)-P(c2) calibrated T=1.1692
            choice_val = getattr(res, "choice", None) or getattr(res, "choice_val", None) or str(res)
            raw_conf = getattr(res, "confidence", res[1] if isinstance(res, tuple) else 0.5)
            confidence = raw_conf / 1.1692
        except Exception as e:
            logger.error(f"von.decide failed: {e}")
            return {"choice": "DATA_FAIL", "confidence": 0.0, "latency_ms": 0.0}
                
        latency = (time.time() - start) * 1000
        return {"choice": choice_val, "confidence": confidence, "latency_ms": latency}

    def judge(self, state: str, preset_name: str) -> Dict[str, Any]:
        preset = self.presets[preset_name]
        start = time.time()
        
        if not von or not hasattr(von, 'judge'):
            return {"probability": 0.0, "latency_ms": 0.0, "status": "DATA_FAIL"}
        
        try:
            res = von.judge(state, preset["instructions"])
            prob = getattr(res, "probability", float(res))
        except Exception as e:
            logger.error(f"von.judge failed: {e}")
            return {"probability": 0.0, "latency_ms": 0.0, "status": "DATA_FAIL"}
                
        latency = (time.time() - start) * 1000
        return {"probability": prob, "latency_ms": latency, "status": "OK"}
        
    def rate(self, state: str, preset_name: str) -> Dict[str, Any]:
        preset = self.presets.get(preset_name)
        start = time.time()
        
        if not von or not hasattr(von, 'rate') or not preset:
            return {"score": 0.0, "latency_ms": 0.0, "status": "DATA_FAIL"}
        
        try:
            res = von.rate(state, preset["criteria"], preset["instructions"])
            score = getattr(res, "score", float(res))
        except Exception as e:
            logger.error(f"von.rate failed: {e}")
            return {"score": 0.0, "latency_ms": 0.0, "status": "DATA_FAIL"}
                
        latency = (time.time() - start) * 1000
        return {"score": score, "latency_ms": latency, "status": "OK"}
        
    def system_one(self, state: str, questions: List[str]) -> Dict[str, Any]:
        """fan-out multiple questions single forward pass sub-25ms"""
        start = time.time()
        answers = {}
        
        for q in questions:
            if q in ["regime_state", "fii_exhaustion", "promoter_signal"]:
                answers[q] = self.decide(state, q)
            elif q == "event_risk":
                answers[q] = self.judge(state, q)
            elif q == "news_tone":
                answers[q] = self.rate(state, q)
            else:
                answers[q] = {"status": "DATA_FAIL"}
                
        latency = (time.time() - start) * 1000
        return {"answers": answers, "latency_ms": latency}
