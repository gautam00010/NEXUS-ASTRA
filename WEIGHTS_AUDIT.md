# Weighting and Gate Audit

## Removed hard gates

- Composite score <= 75 blocked signals.
- Requiring at least 3 of 4 layer directions to agree blocked signals.
- The six verification gates failed fast and returned `NO_TRADE`.
- Johansen, Z-Score, GARCH, evidence-count, and maths-layer checks could act as implicit eligibility blocks.

The old score was mixed-scale (for example 7.5 versus 75) and returned no outcome after one low-confidence sleeve. It could suppress a whole system for several days despite usable directional evidence.

## Static weight failure

The old composite used fixed weights: macro 30%, microstructure 22%, alternative quant 28%, cross-market 20%, with smaller fixed 15/15 FII and 20/15 etc. Momentum, mean reversion, macro, FII/DII, sentiment, fundamentals, and technical datasets were not adapted to current regime or predictive performance.

Static weights fail because:

1. A regime change alters which datasets have information.
2. Dataset accuracy and Sharpe are time-varying.
3. High-volatility datasets should receive less weight when realized volatility rises.
4. The same thesis should emphasize FII, Z-Score, GARCH, macro/PCR, pairs, or filings contextually.

## Soft probability rules

- `P < 0.50`: HOLD
- `0.50 <= P < 0.65`: WATCH
- `0.65 <= P <= 0.80`: TRADE
- `P > 0.80`: STRONG_TRADE

Johansen failure subtracts 0.10, Z-Score failure subtracts 0.05, evidence below 12 subtracts 0.05, and other weak checks become small penalties. No soft gate returns `NO_TRADE`.

## Dynamic formula

`weight_i(t) = base_i * regime_multiplier_i(t) * max(0.2, recent_sharpe_i) / realized_vol_i`, then normalized to one. Exponential recency decay is 0.94. Negative Sharpe retains a 0.05 weight floor so the dataset can recover.
