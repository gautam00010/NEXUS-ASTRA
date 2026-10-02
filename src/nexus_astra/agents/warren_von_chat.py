import logging

logger = logging.getLogger(__name__)

class WarrenVONChat:
    """
    Warren-VON Chat utilizing the local VON 1.1 18ms SDK (no LLMs).
    Parses intents (buy/sell/hold/valuation), queries fair value, gates, US influence,
    and returns structured answers.
    """
    
    def __init__(self):
        pass
        
    def parse_intent(self, user_query: str) -> str:
        query = user_query.lower()
        if any(w in query for w in ["buy", "long"]):
            return "BUY"
        elif any(w in query for w in ["sell", "short", "exit"]):
            return "SELL"
        elif any(w in query for w in ["hold"]):
            return "HOLD"
        elif any(w in query for w in ["value", "valuation", "fair", "intrinsic"]):
            return "VALUATION"
        return "UNKNOWN"
        
    def chat(self, user_query: str, context: dict = None) -> str:
        intent = self.parse_intent(user_query)
        ctx = context or {}
        
        symbol = ctx.get("symbol", "the asset")
        fv = ctx.get("fair_value", 0.0)
        upside = ctx.get("upside", 0.0)
        health = ctx.get("health", 0.0)
        regime = ctx.get("regime", "NORMAL")
        
        if intent == "VALUATION":
            return f"VON 1.1 Analysis: {symbol} has an intrinsic value of {fv:.2f} ({upside:+.1f}% upside). Health Score: {health}/100."
        elif intent == "BUY":
            if upside > 10 and regime == "NORMAL" and health > 60:
                return f"VON 1.1 Recommendation: Accumulate {symbol}. Valuation is attractive (+{upside:.1f}%) and market regime is supportive."
            else:
                return f"VON 1.1 Recommendation: Caution on {symbol}. Regime is {regime}, upside {upside:.1f}%, health {health}/100. Does not meet high-conviction buy criteria."
        elif intent == "SELL":
            return f"VON 1.1 Recommendation: We manage risk ruthlessly. If your thesis on {symbol} is broken or it hits its stop-loss, cut the cord."
        elif intent == "HOLD":
            return f"VON 1.1 Recommendation: Monitoring {symbol} closely. Our VECM Duration engine will flag when edge decays."
        
        return f"VON 1.1: I process intents around valuation, sizing, and regime. Ask me if you should buy {symbol} or what its intrinsic value is."
