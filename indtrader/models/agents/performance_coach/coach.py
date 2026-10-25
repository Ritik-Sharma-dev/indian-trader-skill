"""The performance coach: what the record says, and what to change.

Sources, best first:

1. the **paper journal** (``workspace/paper.json``): real fills, charges, rupees
2. the **decision journal** (``workspace/journal/decisions.json``): the
   decision maker's live calls and their results in R
3. the **backtest** of the live rules, as a baseline when the journals hold
   fewer than ``MIN_TRADES`` trades (labelled in-sample)

It measures win rate, average win and loss, expectancy, profit factor, the
worst drawdown and losing streak; splits by entry hour, weekday, setup and
confidence; and looks for the usual mistakes: late entries, overtrading,
losses bigger than the planned maximum, letting losers run longer than
winners. Advice comes only from patterns with enough trades behind them.
"""

import datetime as dt
import logging
from typing import Dict, List, Optional, Sequence

from indtrader.core import clock, settings
from indtrader.core.errors import IndianTraderError
from indtrader.core.formatting import num
from indtrader.core.storage import read_json
from indtrader.models.agents.decision_maker.decider import Decider
from indtrader.models.agents.decision_maker.journal import DecisionJournal

log = logging.getLogger(__name__)

MIN_TRADES = 10            # below this a split is noise
MIN_GROUP = 4              # the smallest group a piece of advice may rest on
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def normalise_paper(trades: Sequence[dict]) -> List[dict]:
    out = []
    for t in trades:
        if t.get("status") != "closed":
            continue
        opened, closed = dt.datetime.fromisoformat(t["opened"]), dt.datetime.fromisoformat(t["closed"])
        out.append({"day": opened.date(), "entry_time": opened.strftime("%H:%M"), "minutes": (closed - opened).total_seconds() / 60,
                    "setup": t.get("setup") or "-", "result": float(t.get("net") or 0), "r": t.get("r"), "confidence": None,
                    "max_loss": t.get("max_loss_net"), "reason": t.get("reason")})
    return out


def normalise_decisions(entries: Sequence[dict]) -> List[dict]:
    out = []
    for e in entries:
        o = e.get("outcome") or {}
        if not o.get("taken") or o.get("r") is None:
            continue
        minutes = None
        if o.get("exit_time"):
            minutes = (clock.parse_hhmm(o["exit_time"]).hour * 60 + clock.parse_hhmm(o["exit_time"]).minute) - \
                      (clock.parse_hhmm(o["entry_time"]).hour * 60 + clock.parse_hhmm(o["entry_time"]).minute)
        out.append({"day": dt.date.fromisoformat(e["date"]), "entry_time": o["entry_time"], "minutes": minutes, "setup": o.get("setup") or "-",
                    "result": o["r"], "r": o["r"], "confidence": o.get("confidence"), "max_loss": None, "reason": o.get("exit_reason")})
    return out


def normalise_backtest(trades: Sequence[dict]) -> List[dict]:
    out = []
    for t in trades:
        start = clock.parse_hhmm(t["time"])
        end = clock.parse_hhmm(t["exit_time"]) if t.get("exit_time") else None
        out.append({"day": dt.date.fromisoformat(t["date"]), "entry_time": t["time"], "setup": "%s %s" % (t["setup"], t["side"]),
                    "minutes": (end.hour * 60 + end.minute - start.hour * 60 - start.minute) if end else None,
                    "result": t["r"], "r": t["r"], "confidence": None, "max_loss": None, "reason": t.get("exit_reason")})
    return out


def summary(trades: Sequence[dict]) -> Optional[dict]:
    if not trades:
        return None
    results = [t["result"] for t in trades]
    wins, losses = [r for r in results if r > 0], [r for r in results if r <= 0]
    equity = peak = drawdown = 0.0
    streak = worst_streak = 0
    for t in sorted(trades, key=lambda t: (t["day"], t["entry_time"])):
        equity += t["result"]
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
        streak = streak + 1 if t["result"] <= 0 else 0
        worst_streak = max(worst_streak, streak)
    gross_loss = -sum(losses)
    return {"trades": len(trades), "win_rate": len(wins) / len(trades), "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(losses) / len(losses) if losses else 0.0, "expectancy": sum(results) / len(results), "total": sum(results),
            "profit_factor": round(sum(wins) / gross_loss, 2) if gross_loss else None, "max_drawdown": drawdown, "worst_losing_streak": worst_streak}


def split(trades: Sequence[dict], key) -> Dict[str, dict]:
    groups: Dict[str, List[dict]] = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t)
    return {k: summary(v) for k, v in sorted(groups.items())}


def mistakes(trades: Sequence[dict], cfg: dict) -> List[str]:
    out = []
    late = [t for t in trades if t["entry_time"] > cfg["decision"]["last_entry"]]
    if late:
        out.append("%d trade(s) entered after %s (the test says late entries lose): %s total" % (
            len(late), cfg["decision"]["last_entry"], num(sum(t["result"] for t in late))))
    per_day: Dict[dt.date, int] = {}
    for t in trades:
        per_day[t["day"]] = per_day.get(t["day"], 0) + 1
    busy = [d for d, n in per_day.items() if n > cfg["decision"]["trades_per_day"]]
    if busy:
        extra = [t for t in trades if per_day[t["day"]] > cfg["decision"]["trades_per_day"]]
        out.append("%d day(s) with more than %d trade(s): those days total %s" % (len(busy), cfg["decision"]["trades_per_day"],
                                                                                num(sum(t["result"] for t in extra))))
    oversized = [t for t in trades if t.get("max_loss") and t["result"] < -abs(t["max_loss"]) * 1.1]
    if oversized:
        out.append("%d loss(es) bigger than the planned maximum: the stop was moved or missed" % len(oversized))
    held_win = [t["minutes"] for t in trades if t["result"] > 0 and t.get("minutes") is not None]
    held_loss = [t["minutes"] for t in trades if t["result"] <= 0 and t.get("minutes") is not None]
    if len(held_win) >= MIN_GROUP and len(held_loss) >= MIN_GROUP:
        avg_win, avg_loss = sum(held_win) / len(held_win), sum(held_loss) / len(held_loss)
        if avg_loss > avg_win * 1.5:
            out.append("losers are held %.0f minutes on average, winners %.0f: cut losers at the stop, do not wait for a comeback" % (avg_loss, avg_win))
    return out


def watch_items(by_weekday: Dict[str, dict]) -> List[str]:
    """Weekdays that lose while the rest win: worth watching, never a rule on a few trades."""
    out = []
    for day, s in by_weekday.items():
        others = [o for d, o in by_weekday.items() if d != day and o]
        if s and s["trades"] >= MIN_GROUP and s["total"] < 0 and others and all(o["total"] > 0 for o in others):
            out.append("%s is the only losing weekday (%d trades, %.0f%% won). Watch it; %d trades are too few for a rule" % (
                day, s["trades"], s["win_rate"] * 100, s["trades"]))
    return out


def advice(overall: dict, by_hour: Dict[str, dict], unit: str) -> List[str]:
    out = []
    if overall["trades"] < MIN_TRADES:
        out.append("only %d trades: too few to judge. Keep trading 1 lot and journaling until there are %d+" % (overall["trades"], MIN_TRADES * 2))
        return out
    if overall["expectancy"] <= 0:
        out.append("the average trade loses (%s): stop sizing up; trade 1 lot or paper until the expectancy turns positive" % num(overall["expectancy"]))
    elif overall["win_rate"] < 0.4 and overall["avg_win"] < 1.5 * abs(overall["avg_loss"] or 1):
        out.append("few winners and small wins: let winners reach the 2R target instead of exiting early")
    good = [h for h, s in by_hour.items() if s["trades"] >= MIN_GROUP and s["expectancy"] > 0]
    bad = [h for h, s in by_hour.items() if s["trades"] >= MIN_GROUP and s["expectancy"] < 0]
    if bad:
        out.append("entries in hour(s) %s lose on average; concentrate on %s" % (", ".join(sorted(bad)), ", ".join(sorted(good)) or "the first hour"))
    if overall["worst_losing_streak"] >= 4:
        out.append("worst losing streak %d: plan for it (daily loss limit, 1 lot) so a streak never ends the account" % overall["worst_losing_streak"])
    if not out:
        out.append("nothing stands out: keep following the rules and the risk limits (%s per trade)" % unit)
    return out


class PerformanceCoach:
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    def review(self, with_baseline: bool = True) -> dict:
        cfg = self.ctx.cfg
        paper = normalise_paper((read_json(settings.path("paper.json"), {"trades": []}) or {"trades": []})["trades"])
        decisions = normalise_decisions(DecisionJournal().data.values())
        if len(paper) >= MIN_TRADES or (paper and len(paper) >= len(decisions)):
            source, trades, unit = "paper journal", paper, "rupees"
        elif decisions:
            source, trades, unit = "decision journal", decisions, "R"
        else:
            source, trades, unit = None, [], None
        result: dict = {"source": source, "unit": unit, "paper_trades": len(paper), "decision_trades": len(decisions), "errors": []}
        if len(trades) < MIN_TRADES and with_baseline:
            try:
                baseline = Decider(self.ctx).backtest("NIFTY")
                result["baseline"] = {"sessions": baseline["sessions"], "from": baseline["from"], "to": baseline["to"],
                                      "taken": summary(normalise_backtest(baseline["trades"]))}
                if not trades:
                    source, trades, unit = "backtest of the decision rules (in-sample baseline)", normalise_backtest(baseline["trades"]), "R"
            except IndianTraderError as exc:
                result["errors"].append("baseline backtest: %s" % exc)
        result.update(source=source, unit=unit)
        overall = summary(trades)
        result["overall"] = overall
        if overall:
            result["by_hour"] = split(trades, lambda t: t["entry_time"][:2] + ":00")
            result["by_weekday"] = split(trades, lambda t: WEEKDAYS[t["day"].weekday()])
            result["by_setup"] = split(trades, lambda t: t["setup"])
            result["by_confidence"] = split([t for t in trades if t["confidence"]], lambda t: t["confidence"])
            result["mistakes"] = mistakes(trades, cfg)
            result["advice"] = advice(overall, result["by_hour"], unit)
            result["watch"] = watch_items(result["by_weekday"])
        return result
