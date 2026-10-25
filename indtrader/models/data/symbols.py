"""Symbols: NSE / BSE codes, Yahoo codes and the indices we know about."""

import re
from typing import Dict, List, Tuple

# Underlyings NSE treats as indices in its option chain API.
NSE_INDICES = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"})
BSE_INDICES = frozenset({"SENSEX", "BANKEX"})

INDEX_YAHOO: Dict[str, str] = {
    "NIFTY": "^NSEI", "NIFTY50": "^NSEI", "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK", "NIFTY BANK": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
    "SENSEX": "^BSESN",
    "INDIAVIX": "^INDIAVIX", "VIX": "^INDIAVIX", "INDIA VIX": "^INDIAVIX",
    "NIFTYIT": "^CNXIT",
}

# Our symbol -> the index name in NSE's allIndices feed.
NSE_INDEX_NAMES: Dict[str, str] = {
    "NIFTY": "NIFTY 50", "NIFTY50": "NIFTY 50", "BANKNIFTY": "NIFTY BANK",
    "FINNIFTY": "NIFTY FINANCIAL SERVICES", "MIDCPNIFTY": "NIFTY MIDCAP SELECT",
    "NIFTYNXT50": "NIFTY NEXT 50", "INDIAVIX": "INDIA VIX", "VIX": "INDIA VIX", "NIFTYIT": "NIFTY IT",
}

GLOBAL_CUES: List[Tuple[str, str]] = [
    ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow Jones", "^DJI"),
    ("S&P fut", "ES=F"), ("Nasdaq fut", "NQ=F"), ("Nikkei", "^N225"),
    ("Hang Seng", "^HSI"), ("Brent crude", "BZ=F"), ("WTI crude", "CL=F"),
    ("Gold", "GC=F"), ("USD/INR", "USDINR=X"), ("Dollar index", "DX-Y.NYB"),
]


def is_index(symbol: str) -> bool:
    upper = symbol.upper()
    return upper in NSE_INDICES or upper in BSE_INDICES or upper in INDEX_YAHOO


def yahoo_symbol(symbol: str) -> str:
    """Our symbol -> Yahoo's: indices by table, plain NSE codes get ``.NS``."""
    upper = symbol.strip().upper()
    if upper in INDEX_YAHOO:
        return INDEX_YAHOO[upper]
    if upper.startswith("^") or "=" in upper or "." in upper or "_" in upper:
        return upper          # already a Yahoo code (index, future, FX, exchange suffix)
    return upper + ".NS"


def is_indian(yahoo_code: str) -> bool:
    return yahoo_code.endswith((".NS", ".BO")) or yahoo_code in INDEX_YAHOO.values()


def safe_name(symbol: str) -> str:
    """A symbol made safe for file names: ``M&M`` -> ``M_M``, ``^NSEI`` -> ``NSEI``."""
    return "".join(c if c.isalnum() else "_" for c in symbol.upper()).strip("_")


_NAME_NOISE = re.compile(r"\b(limited|ltd|the|and|co|company|corporation|corp|india|industries|inds)\b")


def name_key(name: str) -> str:
    """A company or holder name reduced for matching across exchanges and filings:
    'Natco Pharma Ltd.' and 'NATCO PHARMA LIMITED' -> 'natco pharma'."""
    text = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return " ".join(_NAME_NOISE.sub(" ", text).split())
