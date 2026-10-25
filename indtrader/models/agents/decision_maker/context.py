"""The day's context: the market research that sets the confidence of a decision.

Each source votes +1 (bullish), -1 (bearish) or 0 and says why:

* overnight global markets (the global agent's mood score)
* the daily trend (close vs a rising / falling 20-day EMA)
* timeframe alignment: the 15-minute, hourly and daily charts (chart analyst)
* the open: a gap up or down of at least the rules' minimum
* the option chain: put-call ratio (put writers below the market are support)
* FII positioning in index futures (participant open interest)
* the tone of the last 12 hours of Indian market headlines

India VIX, the expiry day, policy / macro headlines and high-impact
economic events during the session are notes, not votes. None of
the votes were part of the backtest (no history of option chains or global
moods is kept), so they set the confidence of a decision, never the
decision itself. Every source fails on its own and leaves a note.
"""

import datetime as dt
import logging
from typing import List, Optional, Tuple

from indtrader.core import clock
from indtrader.core.errors import IndianTraderError
from indtrader.models.agents.chart_analyst.mtf import TIMEFRAMES, MultiTimeframeAnalyzer
from indtrader.models.agents.global_news.snapshot import GlobalSnapshot, mood
from indtrader.models.agents.global_news.sources import GlobalNewsSources
from indtrader.models.agents.india_news.desk import NewsDesk, NewsQuery
from indtrader.models.analytics.flows import MoneyFlows, participant_view
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService

log = logging.getLogger(__name__)


def _vote(name: str, value: int, detail: str) -> dict:
    return {"name": name, "vote": value, "detail": detail}


def near_walls(walls: Optional[List[dict]], spot: float, above: bool, within_pct: float = 3.0, count: int = 2) -> List[float]:
    """The biggest open-interest strikes on one side of the price and within reach today (far walls do not matter intraday)."""
    reach = spot * within_pct / 100
    picked = [w for w in walls or [] if (spot <= w["strike"] <= spot + reach if above else spot - reach <= w["strike"] <= spot)]
    return [w["strike"] for w in sorted(picked, key=lambda w: -(w["oi"] or 0))[:count]]


RISK_TAGS = ("rbi-rates", "macro", "macro-data", "fno-rules", "ban-surveillance", "tax-fiscal", "trade-policy")


def news_view(items: List[dict], min_scored: int = 5, threshold: float = 0.2) -> Tuple[dict, List[str], List[str]]:
    """(the news vote, the top headlines, warnings) from the last hours of market headlines.

    The tone is the average word-list sentiment of the headlines that have
    one; it needs at least ``min_scored`` of them to vote. Headlines tagged
    with policy or macro themes become warnings: they can move the index
    against any chart signal.
    """
    scored = [it["sentiment"] for it in items if it.get("sentiment")]
    tone = sum(scored) / len(scored) if scored else 0.0
    sign = (1 if tone >= threshold else -1 if tone <= -threshold else 0) if len(scored) >= min_scored else 0
    vote = _vote("news", sign, "news tone %+.2f over %d scored headlines (%d in 12h)" % (tone, len(scored), len(items)))
    headlines = ["%s (%s)" % (it["title"][:110], it.get("source", "")) for it in items[:5]]
    risky = [it for it in items if set(it.get("tags") or []) & set(RISK_TAGS)]
    warnings = ["policy / macro headline: %s" % it["title"][:110] for it in risky[:2]]
    return vote, headlines, warnings


def event_warnings(calendar: List[dict], now: dt.datetime) -> List[str]:
    """High-impact economic events due during today's session (IST)."""
    start, end = clock.at(now.date(), clock.OPEN), clock.at(now.date(), clock.CLOSE)
    return ["HIGH-impact event at %s IST: %s %s. Avoid a new entry in the 15 minutes before it" % (
        e["time"].strftime("%H:%M"), e["country"], e["event"]) for e in calendar if e["impact"] == "High" and start <= e["time"] <= end]


def lean(votes: List[dict]) -> dict:
    """The sum of the votes as a direction: +2 or more bullish, -2 or less bearish, otherwise mixed."""
    total = sum(v["vote"] for v in votes)
    label = "BULLISH" if total >= 2 else "BEARISH" if total <= -2 else "MIXED"
    return {"score": total, "label": label, "for": sum(1 for v in votes if v["vote"] > 0), "against": sum(1 for v in votes if v["vote"] < 0)}


def confidence(votes: List[dict], side: str) -> str:
    """HIGH when the context agrees with the side by two votes or more, LOW when it disagrees, else MEDIUM."""
    sign = 1 if side == "long" else -1
    net = sum(v["vote"] for v in votes) * sign
    return "HIGH" if net >= 2 else "LOW" if net < 0 else "MEDIUM"


class DayContext:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.market = ctx.market

    def collect(self, symbol: str, now: dt.datetime, regime: Optional[str], gap: Optional[float], min_gap: float) -> dict:
        votes: List[dict] = []
        notes: List[str] = []
        errors: List[str] = []
        levels: dict = {}

        try:
            overnight = mood(GlobalSnapshot(self.market).collect())
            sign = 1 if overnight["score"] > 0 else -1 if overnight["score"] < 0 else 0
            votes.append(_vote("global", sign, "overnight markets %s (%+d): %s" % (overnight["label"], overnight["score"],
                                                                                 ", ".join(overnight["notes"][:3]) or "small moves")))
        except IndianTraderError as exc:
            errors.append("global markets: %s" % exc)

        if regime in ("up", "down"):
            votes.append(_vote("daily trend", 1 if regime == "up" else -1,
                               "daily trend %s (close vs the 20-day EMA)" % regime.upper()))
        else:
            votes.append(_vote("daily trend", 0, "daily trend mixed"))

        try:
            frames = MultiTimeframeAnalyzer(self.market).analyze_symbol(symbol, now, TIMEFRAMES[1:])
            label = frames["alignment"]["label"]
            sign = 1 if label.endswith("UP") else -1 if label.endswith("DOWN") else 0
            votes.append(_vote("timeframes", sign, "15m / 1h / daily charts %s (%s)" % (
                label, ", ".join("%s %s" % (r["interval"], r["trend"]) for r in frames["rows"]))))
        except IndianTraderError as exc:
            errors.append("timeframes: %s" % exc)

        if gap is None:
            notes.append("the open is not known yet: the day is tradeable only with a gap of %.1f%% or more" % min_gap)
        elif abs(gap) >= min_gap:
            votes.append(_vote("open", 1 if gap > 0 else -1, "gap %s %+.2f%%" % ("up" if gap > 0 else "down", gap)))
        else:
            votes.append(_vote("open", 0, "flat open %+.2f%%" % gap))

        try:
            chain = OptionChainService(self.market).fetch(symbol, now, "near")
            analysis = OptionChainAnalyzer(self.ctx.cfg).analyze(chain, now, self.market.lot_size(symbol))
            pcr = analysis.get("pcr")
            sign = 1 if pcr and pcr >= 1.2 else -1 if pcr and pcr <= 0.8 else 0
            votes.append(_vote("option chain", sign, "PCR %.2f (%s)" % (pcr or 0, "put writers support" if sign > 0 else
                                                                         "call writers cap" if sign < 0 else "balanced")))
            levels.update(max_pain=analysis.get("max_pain"), expected_move=analysis.get("expected_move"), expiry=str(chain["expiry"]),
                          resistance=near_walls(analysis.get("resistance"), chain["spot"], above=True),
                          support=near_walls(analysis.get("support"), chain["spot"], above=False))
            if chain["expiry"] == now.date():
                notes.append("expiry day: premiums decay fast after midday; no entries after %s" % self.ctx.cfg["expiry_day_no_entries_after"])
        except IndianTraderError as exc:
            errors.append("option chain: %s" % exc)

        try:
            view, _ = participant_view(MoneyFlows(self.market).participants(now))
            fii = view.get("FII") or {}
            share = fii.get("fut_long_pct")
            if share is not None:
                sign = -1 if share < 35 else 1 if share > 65 else 0
                votes.append(_vote("FII futures", sign, "FIIs %.0f%% long in index futures" % share))
        except IndianTraderError as exc:
            errors.append("FII positioning: %s" % exc)

        try:
            vote, headlines, warnings = news_view(NewsDesk(self.market, self.ctx.cfg).news(
                NewsQuery(hours=12, show_seen=True, mark_seen=False, stocks=False, filings=False, limit=0, with_moves=False), now)["items"])
            votes.append(vote)
            levels["headlines"] = headlines
            notes.extend(warnings)
        except IndianTraderError as exc:
            errors.append("news: %s" % exc)

        try:
            notes.extend(event_warnings(GlobalNewsSources(self.market.http).calendar(now), now))
        except IndianTraderError as exc:
            errors.append("economic calendar: %s" % exc)

        try:
            vix = self.market.quote("INDIAVIX")["price"]
            levels["vix"] = vix
            if vix and vix >= self.ctx.cfg["warn_vix_above"]:
                notes.append("India VIX %.1f is high: wider swings, stops get hit more; one lot only" % vix)
        except (IndianTraderError, KeyError, TypeError) as exc:
            errors.append("India VIX: %s" % exc)

        return {"time": now.isoformat(timespec="minutes"), "votes": votes, "lean": lean(votes), "levels": levels,
                "notes": notes, "errors": errors, "status": clock.market_status(now)["state"]}
