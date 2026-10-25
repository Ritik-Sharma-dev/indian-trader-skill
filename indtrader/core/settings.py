"""Settings and workspace locations.

Everything the tools write lives in one workspace folder, by default
``Indian Trader Skill/workspace/`` (``INDTRADER_HOME`` moves it). The
trader's rules live in ``workspace/config.json``; any key left out falls
back to :data:`DEFAULTS`. ``it.py config init`` writes a starter file.

Money is in rupees. Times are IST, ``HH:MM``.
"""

import copy
import logging
import os
from typing import Any, Dict, Optional, Tuple

from indtrader.core.errors import ConfigError
from indtrader.core.storage import read_json, write_json

log = logging.getLogger(__name__)

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

Settings = Dict[str, Any]

DEFAULTS: Settings = {
    # money and limits
    "capital": 100000,                  # trading capital, rupees
    "cash_buffer_pct": 10,              # always left unused
    "max_capital_per_trade_pct": 30,    # premium (or margin) in one trade
    "max_loss_per_trade": 1000,         # loss at the stop, after charges
    "max_daily_loss": 3000,             # realised losses + open risk, per day
    "max_trades_per_day": 3,
    "max_lots_per_trade": 2,
    "min_reward_risk": 1.5,             # after charges
    "require_stop": True,
    # live monitor
    "live_max_trades": 2,               # entries per day
    "live_trend_filter": False,         # only trade with the daily trend (tested: worse on Jul-Oct 2026)
    # decision maker: hard gates measured on the live rules (NIFTY, Jul-Oct 2026, 58 sessions)
    "decision": {
        "symbols": ["NIFTY"],           # BANKNIFTY lost on every split of the same test
        "last_entry": "12:00",          # entries after 12:00: -3.8R on 19 trades
        "min_gap_pct": 0.2,             # flat opens (|gap| < 0.2 %): -5.1R on 38 trades
        "trades_per_day": 1,            # the day's second signal: -5.5R on 28 trades
        "context_refresh_min": 15,      # option chain / flows / global mood re-read at most this often
    },
    # the clock (IST)
    "no_entries_before": "09:30",       # let the opening range form
    "no_entries_after": "14:30",
    "square_off_by": "15:15",           # brokers auto square-off about 15:15-15:25
    "expiry_day_no_entries_after": "13:30",
    # what is allowed
    "allow_option_selling": False,      # naked option writing: unlimited risk
    "allow_futures": True,
    "allow_equity_intraday": True,
    "blocked": [],
    # option quality filters
    "min_option_delta": 0.25,           # below this is a lottery ticket
    "max_option_spread_pct": 3.0,       # bid-ask spread as % of the premium
    "min_option_oi": 500,               # open interest, contracts
    "warn_vix_above": 20,
    "block_on_results_day": False,      # True = block, False = warn only
    # models
    "risk_free_rate_pct": 10.0,         # Black-Scholes rate; NSE's option chain IVs use 10%
    "futures_margin_pct": 12.0,         # estimate only; real SPAN + exposure varies
    "stock_futures_margin_pct": 20.0,
    "equity_intraday_leverage": 5.0,    # MIS: margin = value / leverage
    "tick": 0.05,
    # charges (check against the broker's contract note)
    "charges": {
        "brokerage_per_order": 20.0,    # flat, per executed order
        "brokerage_pct_cap": 0.03,      # futures / equity: the lower of flat or this %
        "stt": {                        # Budget 2026 rates, from 1 Apr 2026
            "option_sell_pct": 0.15,    # on premium, sell side
            "future_sell_pct": 0.05,    # on value, sell side
            "equity_intraday_sell_pct": 0.025,
            "equity_delivery_pct": 0.1,  # both sides
        },
        "exchange_txn": {               # NSE, % of turnover (premium for options)
            "option_pct": 0.03503,
            "future_pct": 0.00173,
            "equity_pct": 0.00297,
        },
        "sebi_per_crore": 10.0,
        "stamp_duty": {                 # buy side only
            "option_buy_pct": 0.003,
            "future_buy_pct": 0.002,
            "equity_intraday_buy_pct": 0.003,
            "equity_delivery_buy_pct": 0.015,
        },
        "gst_pct": 18.0,                # on brokerage + exchange + SEBI fees
    },
    # tax arithmetic (Budget 2026 rates; not advice, update after each budget)
    "tax": {
        "stcg_pct": 20.0,               # s.111A: listed equity held up to 12 months
        "ltcg_pct": 12.5,               # s.112A: held more than 12 months
        "ltcg_exemption": 125000,       # long-term gains exempt per financial year
        "long_term_months": 12,
        "audit_turnover_digital": 100000000,   # s.44AB: Rs 10 crore when cash dealings are under 5 %
    },
    # fallbacks used only when NSE data cannot be fetched
    "fallback_lot_sizes": {
        "NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60, "MIDCPNIFTY": 120,
        "NIFTYNXT50": 25, "SENSEX": 20, "BANKEX": 30,
    },
    "fallback_expiry_weekday": {"NIFTY": 1, "SENSEX": 3},   # 0 = Monday; weekly expiries
    # watchlist for news and alerts when no scan has run
    "watchlist": ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN"],
}

_STARTER_KEYS: Tuple[str, ...] = (
    "capital", "cash_buffer_pct", "max_capital_per_trade_pct", "max_loss_per_trade", "max_daily_loss",
    "max_trades_per_day", "max_lots_per_trade", "min_reward_risk", "no_entries_before", "no_entries_after",
    "square_off_by", "allow_option_selling", "allow_futures", "blocked", "watchlist", "charges",
)
_POSITIVE_NUMBERS = ("capital", "max_loss_per_trade", "max_daily_loss", "max_trades_per_day", "max_lots_per_trade")
_TIMES = ("no_entries_before", "no_entries_after", "square_off_by", "expiry_day_no_entries_after")


def home() -> str:
    """The workspace folder."""
    return os.environ.get("INDTRADER_HOME") or os.path.join(PACKAGE_ROOT, "workspace")


def path(*parts: str) -> str:
    """A path inside the workspace; parent folders are created."""
    full = os.path.join(home(), *parts)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full


def _merge(base: Settings, extra: Optional[Settings]) -> Settings:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def validate(cfg: Settings) -> None:
    """Raise :class:`ConfigError` on values that would make the tools misbehave."""
    for key in _POSITIVE_NUMBERS:
        value = cfg.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ConfigError("config.json: %s must be a positive number (got %r)" % (key, value))
    for key in _TIMES:
        text = cfg.get(key, "")
        parts = text.split(":") if isinstance(text, str) else []
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ConfigError("config.json: %s must be HH:MM (got %r)" % (key, text))
    if not isinstance(cfg.get("blocked", []), list):
        raise ConfigError("config.json: blocked must be a list of symbols")


def load(config_file: Optional[str] = None) -> Settings:
    """The defaults merged with the user's config.json, validated."""
    user = read_json(config_file or path("config.json"), {}) or {}
    if not isinstance(user, dict):
        raise ConfigError("config.json must contain a JSON object")
    cfg = _merge(DEFAULTS, user)
    validate(cfg)
    return cfg


def init(force: bool = False) -> Tuple[str, bool]:
    """Write a starter config.json; returns (path, created)."""
    target = path("config.json")
    if os.path.exists(target) and not force:
        return target, False
    write_json(target, {key: DEFAULTS[key] for key in _STARTER_KEYS})
    log.info("created %s", target)
    return target, True
