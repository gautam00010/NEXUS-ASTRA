"""Academic papers and bibliography for the Overnight Drift anomaly."""

from __future__ import annotations
from typing import Any, Dict, List

ANOMALY_PAPERS: List[Dict[str, Any]] = [
    {
        "id": "knuteson_2020",
        "title": "Strikingly Suspicious Overnight and Intraday Returns",
        "authors": "Bruce Knuteson",
        "year": 2020,
        "citation": "arXiv:2010.01727 [q-fin.TR]",
        "url": "https://arxiv.org/abs/2010.01727",
        "affiliation": "Former MIT Physicist / D.E. Shaw quantitative researcher",
        "abstract": (
            "Over the past three decades across 21 leading global equity indices (US, India, Germany, Canada, Japan), "
            "essentially all cumulative market returns were generated while the market was closed overnight, while "
            "intraday returns were flat or persistently negative. The paper hypothesizes systematic algorithmic "
            "ramping into the open and sagging intraday by large quantitative firms."
        ),
        "key_takeaway": (
            "Documents the staggering cumulative divergence between holding overnight versus intraday, "
            "establishing empirical return decomposition across 21 nations."
        ),
    },
    {
        "id": "knuteson_2021",
        "title": "How to Increase the Value of Your Stock Overnight",
        "authors": "Bruce Knuteson",
        "year": 2021,
        "citation": "arXiv:2104.14987 [q-fin.TR]",
        "url": "https://arxiv.org/abs/2104.14987",
        "affiliation": "Independent Quantitative Research",
        "abstract": (
            "Extends the return decomposition analysis to individual high-profile stocks including Micron Technology (MU), "
            "demonstrating an overnight return of +138M% compared to an intraday return of -99.92%, arguing that market "
            "microstructure allows off-hours price discovery to disproportionately dictate total capital appreciation."
        ),
        "key_takeaway": (
            "Micron Technology represents the extreme archetypal specimen of compounding asymmetry and off-hours drift."
        ),
    },
    {
        "id": "haghani_white_2022",
        "title": "Night Moves: Is the Overnight Drift Anomaly Real?",
        "authors": "Victor Haghani and Richard Dewey White",
        "year": 2022,
        "citation": "Elm Partners Research / SSRN",
        "url": "https://elmfunds.com/night-moves/",
        "affiliation": "Elm Partners Wealth Management",
        "abstract": (
            "An investigation into SPY showing that $1 invested from 1993 to 2020 grew to $17.50 overnight and only $0.87 intraday. "
            "Examines whether the phenomenon can be commercially monetized, concluding that transaction costs and tax friction "
            "obliterate naive retail trading, but high-beta tech equities (NVDA, TSLA) exhibit persistent attention-driven overnight biases."
        ),
        "key_takeaway": (
            "Empirically validates the statistical reality of overnight drift while demonstrating that high friction prevents direct retail arbitrage."
        ),
    },
    {
        "id": "lou_polk_skouras_2019",
        "title": "A Tug of War: Overnight Versus Intraday Expected Returns",
        "authors": "Dong Lou, Christopher Polk, and Spyros Skouras",
        "year": 2019,
        "citation": "Journal of Financial Economics, Vol. 134, Issue 1, pp. 192-213",
        "url": "https://doi.org/10.1016/j.jfineco.2019.03.011",
        "affiliation": "London School of Economics / Athens University of Economics and Business",
        "abstract": (
            "Examines the overnight versus intraday distribution of anomaly profits. Shows that momentum profits are earned entirely "
            "overnight and reverse intraday, driven by client-driven institutional trading and individual investor liquidity demand."
        ),
        "key_takeaway": (
            "Peer-reviewed academic confirmation that retail flows at the open drive prices, whereas institutional rebalancing pulls them back intraday."
        ),
    },
    {
        "id": "wigglesworth_2021",
        "title": "The Overnight Trading Mystery",
        "authors": "Robin Wigglesworth",
        "year": 2021,
        "citation": "Financial Times (FT Alphaville)",
        "url": "https://www.ft.com/content/38072046-24ee-48c0-8d54-a62c5b369db4",
        "affiliation": "Financial Times Editor & Author of 'Trillions'",
        "abstract": (
            "Journalistic and market practitioner dissection of Knuteson's claims versus standard quant market microstructure models. "
            "Presents critiques from leading quantitative funds who explain the anomaly through earnings calendar timing, "
            "pre-market illiquidity, and time-zone capital shifts rather than coordinated foul play."
        ),
        "key_takeaway": (
            "Balanced industry overview comparing the conspiratorial manipulation narrative with standard microstructure realities."
        ),
    },
]


def get_papers_bibliography() -> List[Dict[str, Any]]:
    """Return all papers with metadata."""
    return ANOMALY_PAPERS
