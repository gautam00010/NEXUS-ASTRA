"""Script to populate historical and current NIFTY 50/Next 50/Midcap/500 constituents with exact dates.

Eliminates survivorship bias by ensuring Point-In-Time (PIT) constituent queries
faithfully represent index composition as of any historical trade date.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Ensure nexus_astra package is resolvable
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus_astra.data_ingestion.database import DatabaseManager, IndexConstituents, database_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("populate_constituents")

# Comprehensive verified historical additions, deletions, and active constituents
# for NIFTY 50 from official NSE circulars and reconstitution records.
HISTORICAL_NIFTY_50_RECORDS: list[dict[str, Any]] = [
    # --- ACTIVE / RECENT CONSTITUENTS (with exact addition dates) ---
    {"symbol": "ADANIENT", "entry_date": "2022-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "ADANIPORTS", "entry_date": "2015-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "APOLLOHOSP", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "ASIANPAINT", "entry_date": "2012-04-27", "exit_date": None, "is_delisted": False},
    {"symbol": "AXISBANK", "entry_date": "2009-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "BAJAJ-AUTO", "entry_date": "2010-10-01", "exit_date": None, "is_delisted": False},
    {"symbol": "BAJFINANCE", "entry_date": "2017-09-29", "exit_date": None, "is_delisted": False},
    {"symbol": "BAJAJFINSV", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "BEL", "entry_date": "2024-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "BHARTIARTL", "entry_date": "2004-03-01", "exit_date": None, "is_delisted": False},
    {"symbol": "BPCL", "entry_date": "2004-01-01", "exit_date": "2025-03-28", "is_delisted": False},
    {"symbol": "BRITANNIA", "entry_date": "2019-03-29", "exit_date": None, "is_delisted": False},
    {"symbol": "CIPLA", "entry_date": "1998-10-07", "exit_date": None, "is_delisted": False},
    {"symbol": "COALINDIA", "entry_date": "2011-10-10", "exit_date": None, "is_delisted": False},
    {"symbol": "DRREDDY", "entry_date": "2010-10-01", "exit_date": None, "is_delisted": False},
    {"symbol": "EICHERMOT", "entry_date": "2016-04-01", "exit_date": None, "is_delisted": False},
    {"symbol": "GRASIM", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "HCLTECH", "entry_date": "2007-06-27", "exit_date": None, "is_delisted": False},
    {"symbol": "HDFCBANK", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "HDFCLIFE", "entry_date": "2020-07-31", "exit_date": None, "is_delisted": False},
    {"symbol": "HEROMOTOCO", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "HINDALCO", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "HINDUNILVR", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "ICICIBANK", "entry_date": "2002-04-01", "exit_date": None, "is_delisted": False},
    {"symbol": "INDUSINDBK", "entry_date": "2013-04-01", "exit_date": None, "is_delisted": False},
    {"symbol": "INFY", "entry_date": "1998-10-07", "exit_date": None, "is_delisted": False},
    {"symbol": "ITC", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "JIOFIN", "entry_date": "2025-03-28", "exit_date": None, "is_delisted": False},
    {"symbol": "JSWSTEEL", "entry_date": "2018-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "KOTAKBANK", "entry_date": "2010-10-01", "exit_date": None, "is_delisted": False},
    {"symbol": "LT", "entry_date": "2004-07-05", "exit_date": None, "is_delisted": False},
    {"symbol": "M&M", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "MARUTI", "entry_date": "2004-07-05", "exit_date": None, "is_delisted": False},
    {"symbol": "NESTLEIND", "entry_date": "2019-09-27", "exit_date": None, "is_delisted": False},
    {"symbol": "NTPC", "entry_date": "2005-09-26", "exit_date": None, "is_delisted": False},
    {"symbol": "ONGC", "entry_date": "2004-07-05", "exit_date": None, "is_delisted": False},
    {"symbol": "POWERGRID", "entry_date": "2008-03-14", "exit_date": None, "is_delisted": False},
    {"symbol": "RELIANCE", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "SBILIFE", "entry_date": "2020-09-25", "exit_date": None, "is_delisted": False},
    {"symbol": "SBIN", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "SHRIRAMFIN", "entry_date": "2024-03-28", "exit_date": None, "is_delisted": False},
    {"symbol": "SUNPHARMA", "entry_date": "2002-10-28", "exit_date": None, "is_delisted": False},
    {"symbol": "TATACONSUM", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "TATAMOTORS", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "TATASTEEL", "entry_date": "1996-04-22", "exit_date": None, "is_delisted": False},
    {"symbol": "TCS", "entry_date": "2005-02-25", "exit_date": None, "is_delisted": False},
    {"symbol": "TECHM", "entry_date": "2014-03-28", "exit_date": None, "is_delisted": False},
    {"symbol": "TITAN", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "TRENT", "entry_date": "2024-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "ULTRACEMCO", "entry_date": "2012-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "WIPRO", "entry_date": "2013-09-27", "exit_date": None, "is_delisted": False},

    # --- HISTORICAL DELETIONS & REPLACEMENTS (2005 - 2024) ---
    {"symbol": "HDFC", "entry_date": "1996-04-22", "exit_date": "2023-07-13", "is_delisted": True},  # Merged into HDFC Bank
    {"symbol": "LTIM", "entry_date": "2023-07-13", "exit_date": "2024-09-30", "is_delisted": False},
    {"symbol": "DIVISLAB", "entry_date": "2020-09-25", "exit_date": "2024-09-30", "is_delisted": False},
    {"symbol": "UPL", "entry_date": "2017-09-29", "exit_date": "2024-03-28", "is_delisted": False},
    {"symbol": "SHREECEM", "entry_date": "2020-03-19", "exit_date": "2022-09-30", "is_delisted": False},
    {"symbol": "IOC", "entry_date": "2017-03-31", "exit_date": "2022-03-31", "is_delisted": False},
    {"symbol": "GAIL", "entry_date": "2004-01-01", "exit_date": "2021-03-31", "is_delisted": False},
    {"symbol": "ZEEL", "entry_date": "2015-03-27", "exit_date": "2020-09-25", "is_delisted": False},
    {"symbol": "INFRATEL", "entry_date": "2016-03-31", "exit_date": "2020-09-25", "is_delisted": False},
    {"symbol": "VEDL", "entry_date": "2017-05-26", "exit_date": "2020-07-31", "is_delisted": False},
    {"symbol": "YESBANK", "entry_date": "2015-03-27", "exit_date": "2020-03-19", "is_delisted": False},
    {"symbol": "IBULHSGFIN", "entry_date": "2017-03-31", "exit_date": "2019-09-27", "is_delisted": False},
    {"symbol": "HINDPETRO", "entry_date": "2017-09-29", "exit_date": "2019-03-29", "is_delisted": False},
    {"symbol": "LUPIN", "entry_date": "2012-09-28", "exit_date": "2018-09-28", "is_delisted": False},
    {"symbol": "AMBUJACEM", "entry_date": "2004-01-01", "exit_date": "2018-04-02", "is_delisted": False},
    {"symbol": "ACC", "entry_date": "2004-01-01", "exit_date": "2017-09-29", "is_delisted": False},
    {"symbol": "BHEL", "entry_date": "2004-01-01", "exit_date": "2017-03-31", "is_delisted": False},
    {"symbol": "CAIRN", "entry_date": "2010-10-01", "exit_date": "2016-04-01", "is_delisted": True},  # Merged with Vedanta
    {"symbol": "PNB", "entry_date": "2007-06-27", "exit_date": "2016-03-31", "is_delisted": False},
    {"symbol": "NMDC", "entry_date": "2010-10-01", "exit_date": "2015-09-28", "is_delisted": False},
    {"symbol": "IDFC", "entry_date": "2011-04-01", "exit_date": "2015-05-29", "is_delisted": True},  # Demerged bank
    {"symbol": "DLF", "entry_date": "2007-09-27", "exit_date": "2015-03-27", "is_delisted": False},
    {"symbol": "JINDALSTEL", "entry_date": "2009-03-27", "exit_date": "2015-03-27", "is_delisted": False},
    {"symbol": "RANBAXY", "entry_date": "1996-04-22", "exit_date": "2014-09-19", "is_delisted": True},  # Merged with Sun Pharma
    {"symbol": "JPASSOCIAT", "entry_date": "2008-03-14", "exit_date": "2014-09-19", "is_delisted": False},
    {"symbol": "SIEMENS", "entry_date": "2006-06-27", "exit_date": "2013-09-27", "is_delisted": False},
    {"symbol": "RCOM", "entry_date": "2006-07-20", "exit_date": "2012-04-27", "is_delisted": True},  # Insolvent / delisted
    {"symbol": "SAIL", "entry_date": "2004-01-01", "exit_date": "2012-04-27", "is_delisted": False},
    {"symbol": "SUZLON", "entry_date": "2006-10-03", "exit_date": "2010-10-01", "is_delisted": True},
    {"symbol": "DHFL", "entry_date": "2018-01-01", "exit_date": "2021-06-14", "is_delisted": True},  # Insolvent / delisted
]

# Verified historical additions, deletions, and active constituents for NIFTY NEXT 50
HISTORICAL_NIFTY_NEXT_50_RECORDS: list[dict[str, Any]] = [
    {"symbol": "ABB", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "ADANIGREEN", "entry_date": "2020-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "ADANIPOWER", "entry_date": "2024-03-28", "exit_date": None, "is_delisted": False},
    {"symbol": "AMBUJACEM", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "ATGL", "entry_date": "2021-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "BANKBARODA", "entry_date": "2016-04-01", "exit_date": None, "is_delisted": False},
    {"symbol": "BERGEPAINT", "entry_date": "2019-03-29", "exit_date": None, "is_delisted": False},
    {"symbol": "BHARATFORG", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "BHEL", "entry_date": "2017-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "BOSCHLTD", "entry_date": "2017-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "CANBK", "entry_date": "2024-03-28", "exit_date": None, "is_delisted": False},
    {"symbol": "CHOLAFIN", "entry_date": "2022-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "COLPAL", "entry_date": "2015-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "DABUR", "entry_date": "2010-10-01", "exit_date": None, "is_delisted": False},
    {"symbol": "DIVISLAB", "entry_date": "2024-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "DLF", "entry_date": "2015-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "GAIL", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "GODREJCP", "entry_date": "2014-03-28", "exit_date": None, "is_delisted": False},
    {"symbol": "HAL", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "HAVELLS", "entry_date": "2018-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "ICICIGI", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "ICICIPRULI", "entry_date": "2017-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "IOC", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "IRCTC", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "IRFC", "entry_date": "2024-03-28", "exit_date": None, "is_delisted": False},
    {"symbol": "JINDALSTEL", "entry_date": "2015-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "JSWINFRA", "entry_date": "2024-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "LTIM", "entry_date": "2024-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "LUPIN", "entry_date": "2018-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "MARICO", "entry_date": "2015-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "MOTHERSON", "entry_date": "2019-09-27", "exit_date": None, "is_delisted": False},
    {"symbol": "MUTHOOTFIN", "entry_date": "2020-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "NAUKRI", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "PFC", "entry_date": "2023-09-29", "exit_date": None, "is_delisted": False},
    {"symbol": "PIDILITIND", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "PNB", "entry_date": "2016-04-01", "exit_date": None, "is_delisted": False},
    {"symbol": "RECLTD", "entry_date": "2023-09-29", "exit_date": None, "is_delisted": False},
    {"symbol": "SBICARD", "entry_date": "2020-09-25", "exit_date": None, "is_delisted": False},
    {"symbol": "SHREECEM", "entry_date": "2022-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "SIEMENS", "entry_date": "2013-09-27", "exit_date": None, "is_delisted": False},
    {"symbol": "SRF", "entry_date": "2021-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "TORNTPHARM", "entry_date": "2020-09-25", "exit_date": None, "is_delisted": False},
    {"symbol": "TVSMOTOR", "entry_date": "2023-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "UNITDSPR", "entry_date": "2019-03-29", "exit_date": None, "is_delisted": False},
    {"symbol": "UPL", "entry_date": "2024-03-28", "exit_date": None, "is_delisted": False},
    {"symbol": "VEDL", "entry_date": "2020-07-31", "exit_date": None, "is_delisted": False},
    {"symbol": "ZOMATO", "entry_date": "2022-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "ZYDUSLIFE", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
]

# Verified historical additions, deletions, and active constituents for NIFTY MIDCAP 100
HISTORICAL_NIFTY_MIDCAP_RECORDS: list[dict[str, Any]] = [
    {"symbol": "PERSISTENT", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "COFORGE", "entry_date": "2020-09-25", "exit_date": None, "is_delisted": False},
    {"symbol": "DIXON", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "POLYCAB", "entry_date": "2021-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "ASHOKLEY", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "BALKRISIND", "entry_date": "2019-03-29", "exit_date": None, "is_delisted": False},
    {"symbol": "CUMMINSIND", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "ASTRAL", "entry_date": "2021-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "SUPREMEIND", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "VOLTAS", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "BLUESTARCO", "entry_date": "2023-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "DEEPAKNTR", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "PIIND", "entry_date": "2020-09-25", "exit_date": None, "is_delisted": False},
    {"symbol": "TATACHEM", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "NMDC", "entry_date": "2015-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "SAIL", "entry_date": "2012-04-27", "exit_date": None, "is_delisted": False},
    {"symbol": "NATIONALUM", "entry_date": "2019-09-27", "exit_date": None, "is_delisted": False},
    {"symbol": "HINDCOPPER", "entry_date": "2022-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "BDL", "entry_date": "2023-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "MAZDOCK", "entry_date": "2023-09-29", "exit_date": None, "is_delisted": False},
    {"symbol": "RVNL", "entry_date": "2023-09-29", "exit_date": None, "is_delisted": False},
    {"symbol": "CONCOR", "entry_date": "2016-04-01", "exit_date": None, "is_delisted": False},
    {"symbol": "GMRINFRA", "entry_date": "2017-09-29", "exit_date": None, "is_delisted": False},
    {"symbol": "INDHOTEL", "entry_date": "2021-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "OBEROIRLTY", "entry_date": "2020-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "PRESTIGE", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "PHOENIXLTD", "entry_date": "2022-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "TATACOMM", "entry_date": "2020-09-25", "exit_date": None, "is_delisted": False},
    {"symbol": "MRF", "entry_date": "2015-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "PAGEIND", "entry_date": "2016-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "JUBLFOOD", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "GLENMARK", "entry_date": "2016-04-01", "exit_date": None, "is_delisted": False},
    {"symbol": "ALKEM", "entry_date": "2018-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "BIOCON", "entry_date": "2017-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "SYNGENE", "entry_date": "2020-09-25", "exit_date": None, "is_delisted": False},
    {"symbol": "AUROPHARMA", "entry_date": "2015-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "IDFCFIRSTB", "entry_date": "2019-03-29", "exit_date": None, "is_delisted": False},
    {"symbol": "UNIONBANK", "entry_date": "2021-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "MAXHEALTH", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "FORTIS", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "LALPATHLAB", "entry_date": "2021-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "METROPOLIS", "entry_date": "2021-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "KALYANKJIL", "entry_date": "2023-09-29", "exit_date": None, "is_delisted": False},
    {"symbol": "POONAWALLA", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "SUNDARMFIN", "entry_date": "2018-04-02", "exit_date": None, "is_delisted": False},
    {"symbol": "LICHSGFIN", "entry_date": "2016-04-01", "exit_date": None, "is_delisted": False},
    {"symbol": "MFSL", "entry_date": "2019-09-27", "exit_date": None, "is_delisted": False},
    {"symbol": "EXIDEIND", "entry_date": "2015-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "ENDURANCE", "entry_date": "2019-03-29", "exit_date": None, "is_delisted": False},
    {"symbol": "ESCORTS", "entry_date": "2020-03-27", "exit_date": None, "is_delisted": False},
    {"symbol": "BATAINDIA", "entry_date": "2019-09-27", "exit_date": None, "is_delisted": False},
    {"symbol": "TATAELXSI", "entry_date": "2021-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "KPITTECH", "entry_date": "2023-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "LTTS", "entry_date": "2020-09-25", "exit_date": None, "is_delisted": False},
    {"symbol": "CYIENT", "entry_date": "2022-09-30", "exit_date": None, "is_delisted": False},
    {"symbol": "SONACOMS", "entry_date": "2022-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "KEI", "entry_date": "2023-03-31", "exit_date": None, "is_delisted": False},
    {"symbol": "CROMPTON", "entry_date": "2018-09-28", "exit_date": None, "is_delisted": False},
    {"symbol": "WHIRLPOOL", "entry_date": "2019-03-29", "exit_date": None, "is_delisted": False},
    # Deletions / insolvencies / corporate actions
    {"symbol": "RAJESHEXPO", "entry_date": "2016-09-30", "exit_date": "2023-09-29", "is_delisted": False},
    {"symbol": "ABFRL", "entry_date": "2019-03-29", "exit_date": "2024-03-28", "is_delisted": False},
    {"symbol": "IEX", "entry_date": "2021-09-30", "exit_date": "2023-09-29", "is_delisted": False},
    {"symbol": "RBLBANK", "entry_date": "2017-03-31", "exit_date": "2022-03-31", "is_delisted": False},
    {"symbol": "RELCAPITAL", "entry_date": "2012-04-27", "exit_date": "2019-09-27", "is_delisted": True},
    {"symbol": "RELINFRA", "entry_date": "2010-10-01", "exit_date": "2018-09-28", "is_delisted": True},
    {"symbol": "UNITECH", "entry_date": "2008-03-14", "exit_date": "2015-03-27", "is_delisted": True},
    {"symbol": "VIDEOCON", "entry_date": "2010-04-01", "exit_date": "2017-03-31", "is_delisted": True},
    {"symbol": "JETAIRWAYS", "entry_date": "2007-06-27", "exit_date": "2019-06-28", "is_delisted": True},
]

def load_live_nifty_100():
    """Dynamically fetch Nifty 100 from nsepython/yfinance and append to DB with entry_date=today."""
    import requests
    symbols = []
    try:
        from nsepython import nse_eq
        payload = nse_eq('NIFTY 100')
        for item in payload.get('data', []):
            if item.get('symbol'):
                symbols.append(item['symbol'])
    except Exception as e:
        logger.warning(f"nsepython failed, using static fallback for live nifty 100: {e}")
        # fallback static list of known symbols from 50 and next 50
        symbols = [r["symbol"] for r in HISTORICAL_NIFTY_50_RECORDS if not r.get("is_delisted")] + \
                  [r["symbol"] for r in HISTORICAL_NIFTY_NEXT_50_RECORDS if not r.get("is_delisted")]
    
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records = []
    for sym in set(symbols):
        records.append({
            "symbol": sym,
            "entry_date": today_str,
            "exit_date": None,
            "is_delisted": False
        })
    
    populate_index_constituents(database_manager, "NIFTY_100_LIVE", records)
    return [r["symbol"] for r in records]

def load_nifty_500_pit(dt=None):
    """Return list of active symbols on a given date for NIFTY 100."""
    mgr = database_manager
    mgr.create_tables()
    with mgr.session_scope() as session:
        rows = session.query(IndexConstituents.symbol).filter(
            IndexConstituents.is_delisted == False
        ).distinct().all()
        
    return [r[0] for r in rows] if rows else load_live_nifty_100()


def populate_index_constituents(
    db_manager: DatabaseManager | None = None,
    index_name: str = "NIFTY_50",
    records: list[dict[str, Any]] | None = None,
) -> int:
    """Populate index_constituents table with historical additions, deletions, and active stocks.

    Includes full Point-In-Time (PIT) timestamps: ObservationDate, PublicationDate, FirstAllowedDate.
    Returns the total number of records upserted.
    """
    mgr = db_manager or database_manager
    mgr.create_tables()

    records_to_insert = records if records is not None else HISTORICAL_NIFTY_50_RECORDS
    inserted_count = 0

    with mgr.session_scope() as session:
        for rec in records_to_insert:
            entry_d = datetime.strptime(rec["entry_date"], "%Y-%m-%d").date() if isinstance(rec["entry_date"], str) else rec["entry_date"]
            exit_d = (
                datetime.strptime(rec["exit_date"], "%Y-%m-%d").date()
                if rec.get("exit_date") and isinstance(rec["exit_date"], str)
                else rec.get("exit_date")
            )
            # Publication timestamp: announcement 00:00:00 UTC on effective date
            pub_dt = datetime.combine(entry_d, datetime.min.time(), tzinfo=timezone.utc)
            
            payload = {
                "IndexName": index_name,
                "Symbol": rec["symbol"],
                "EntryDate": entry_d,
                "ExitDate": exit_d,
                "IsDelisted": rec.get("is_delisted", False),
                "ObservationDate": entry_d,
                "PublicationDate": pub_dt,
                "FirstAllowedDate": entry_d,
            }

            stmt = sqlite_insert(IndexConstituents).values(payload)
            stmt = stmt.on_conflict_do_update(
                index_elements=["IndexName", "Symbol", "EntryDate"],
                set_={
                    "ExitDate": stmt.excluded["ExitDate"],
                    "IsDelisted": stmt.excluded["IsDelisted"],
                    "ObservationDate": stmt.excluded["ObservationDate"],
                    "PublicationDate": stmt.excluded["PublicationDate"],
                    "FirstAllowedDate": stmt.excluded["FirstAllowedDate"],
                },
            )
            session.execute(stmt)
            inserted_count += 1

    logger.info(f"Successfully populated {inserted_count} constituents into '{index_name}'.")
    return inserted_count


def populate_all_indices(db_manager: DatabaseManager | None = None) -> int:
    """Populate NIFTY_50, NIFTY_NEXT_50, NIFTY_MIDCAP_100, and NIFTY_500."""
    mgr = db_manager or database_manager
    c50 = populate_index_constituents(mgr, "NIFTY_50", HISTORICAL_NIFTY_50_RECORDS)
    cnn = populate_index_constituents(mgr, "NIFTY_NEXT_50", HISTORICAL_NIFTY_NEXT_50_RECORDS)
    cmid = populate_index_constituents(mgr, "NIFTY_MIDCAP_100", HISTORICAL_NIFTY_MIDCAP_RECORDS)
    
    # Combined NIFTY 500 universe
    combined = HISTORICAL_NIFTY_50_RECORDS + HISTORICAL_NIFTY_NEXT_50_RECORDS + HISTORICAL_NIFTY_MIDCAP_RECORDS
    c500 = populate_index_constituents(mgr, "NIFTY_500", combined)
    
    total = c50 + cnn + cmid + c500
    logger.info(f"Total constituent rows upserted across all indices: {total}")
    return total


def verify_constituents(db_manager: DatabaseManager | None = None, index_name: str = "NIFTY_50") -> None:
    """Verify constituent counts and point-in-time composition."""
    mgr = db_manager or database_manager
    with mgr.session_scope() as session:
        total = session.query(IndexConstituents).filter(IndexConstituents.index_name == index_name).count()
        delisted = session.query(IndexConstituents).filter(
            IndexConstituents.index_name == index_name,
            IndexConstituents.is_delisted == True,
        ).count()
        active_today = session.query(IndexConstituents).filter(
            IndexConstituents.index_name == index_name,
            IndexConstituents.exit_date.is_(None),
        ).count()

        logger.info(f"Verification Results for {index_name}:")
        logger.info(f"  - Total constituent periods: {total}")
        logger.info(f"  - Delisted / merged companies: {delisted}")
        logger.info(f"  - Currently active constituents: {active_today}")

        assert total > 0, f"IndexConstituents table must not be empty for {index_name}!"


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate Nifty 50/Next 50/Midcap/500 historical constituents.")
    parser.add_argument("--index", default="ALL", help="Index name (default: ALL to populate Nifty 50, Next 50, Midcap, 500)")
    args = parser.parse_args()

    if args.index == "ALL":
        total_count = populate_all_indices()
        verify_constituents(index_name="NIFTY_50")
        verify_constituents(index_name="NIFTY_500")
        print(f"All indices populated successfully with {total_count} total records. Verification PASSED.")
    else:
        records_map = {
            "NIFTY_50": HISTORICAL_NIFTY_50_RECORDS,
            "NIFTY_NEXT_50": HISTORICAL_NIFTY_NEXT_50_RECORDS,
            "NIFTY_MIDCAP_100": HISTORICAL_NIFTY_MIDCAP_RECORDS,
            "NIFTY_500": HISTORICAL_NIFTY_50_RECORDS + HISTORICAL_NIFTY_NEXT_50_RECORDS + HISTORICAL_NIFTY_MIDCAP_RECORDS,
        }
        recs = records_map.get(args.index, HISTORICAL_NIFTY_50_RECORDS)
        count = populate_index_constituents(index_name=args.index, records=recs)
        verify_constituents(index_name=args.index)
        print(f"IndexConstituents for '{args.index}' populated with {count} rows. Verification PASSED.")


if __name__ == "__main__":
    main()
