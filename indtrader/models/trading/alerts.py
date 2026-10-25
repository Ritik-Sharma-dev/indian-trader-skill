"""Price alerts that ring once.

Rule types (``workspace/alerts.json``):

* ``above`` / ``below``: the underlying price (official for indices)
* ``premium_above`` / ``premium_below``: an option's premium (NSE chain)
* ``pct``: moved ``pct`` percent or more from the previous close
* ``time``: the IST clock passed ``at`` on a trading day
* ``opening_bell``: NSE opened today

A level rule rings once until reset; ``pct``, ``time`` and ``opening_bell``
ring once per day. ``from_plan`` makes five rules: the underlying stop and
target, the premium stop and target, and the square-off reminder.
"""

import datetime as dt
import logging
from typing import Dict, List, Optional, Tuple

from indtrader.core import clock, settings
from indtrader.core.errors import IndianTraderError, ValidationError
from indtrader.core.formatting import num, pct
from indtrader.core.storage import read_json, write_json
from indtrader.models.analytics.option_chain import OptionChainService, premium_of

log = logging.getLogger(__name__)

DAILY_TYPES = ("pct", "time", "opening_bell")


def rules_from_plan(plan: dict) -> List[dict]:
    base_id = plan["symbol"].lower()
    underlying, instrument = plan["underlying"], plan["instrument"]
    long = plan["side"] == "long"
    symbol = plan["symbol"]
    rules = [
        {"id": "%s-stop" % base_id, "type": "below" if long else "above", "symbol": symbol, "price": underlying["stop"],
         "label": "underlying stop"},
        {"id": "%s-target" % base_id, "type": "above" if long else "below", "symbol": symbol, "price": underlying["target"],
         "label": "underlying target"},
        {"id": "%s-squareoff" % base_id, "type": "time", "at": plan["square_off_by"], "label": "square off %s now" % symbol},
    ]
    if instrument.get("type") == "option":
        option = {"symbol": plan["symbol"], "strike": instrument["strike"], "kind": instrument["kind"], "expiry": instrument["expiry"]}
        rules += [dict(option, id="%s-prem-stop" % base_id, type="premium_below", price=instrument["premium"]["stop"], label="premium stop"),
                  dict(option, id="%s-prem-target" % base_id, type="premium_above", price=instrument["premium"]["target"], label="premium target")]
    for rule in rules:
        rule["date"] = plan["date"]
    return rules


def evaluate(rule: dict, now: dt.datetime, quotes: Dict[str, dict], premiums: Dict[str, float], rang: Dict[str, str]) -> Optional[str]:
    """The alert message when ``rule`` fires now, else ``None``."""
    if rule.get("date") and rule["date"] != now.date().isoformat():
        return None
    kind = rule["type"]
    if kind in DAILY_TYPES:
        if rang.get(rule["id"]) == now.date().isoformat():
            return None
    elif rang.get(rule["id"]):
        return None
    if kind in ("time", "opening_bell"):
        if not clock.is_trading_day(now.date()):
            return None
        at = clock.OPEN if kind == "opening_bell" else clock.parse_hhmm(rule["at"])
        if at <= now.time() < clock.CLOSE:
            return "%s: %s IST" % (rule.get("label") or ("NSE is open" if kind == "opening_bell" else "time"), clock.hm(at))
        return None
    if kind in ("premium_above", "premium_below"):
        premium = premiums.get(rule["id"])
        if premium is None:
            return None
        if (kind == "premium_above" and premium >= rule["price"]) or (kind == "premium_below" and premium <= rule["price"]):
            return "%s %s %s %s premium %s %s %s (%s)" % (rule["symbol"], num(rule["strike"], 0), rule["kind"], rule["expiry"], num(premium),
                                                       ">=" if kind == "premium_above" else "<=", num(rule["price"]), rule.get("label", ""))
        return None
    quote = quotes.get(rule["symbol"].upper())
    if not quote or quote.get("price") is None:
        return None
    price = quote["price"]
    if kind == "above" and price >= rule["price"]:
        return "%s %s >= %s (%s)" % (rule["symbol"], num(price), num(rule["price"]), rule.get("label", "above"))
    if kind == "below" and price <= rule["price"]:
        return "%s %s <= %s (%s)" % (rule["symbol"], num(price), num(rule["price"]), rule.get("label", "below"))
    if kind == "pct" and quote.get("change_pct") is not None and abs(quote["change_pct"]) >= rule["pct"]:
        direction = rule.get("direction")
        if (direction == "up" and quote["change_pct"] < 0) or (direction == "down" and quote["change_pct"] > 0):
            return None
        return "%s moved %s today (alert at %s%%)" % (rule["symbol"], pct(quote["change_pct"]), rule["pct"])
    return None


def describe(rule: dict) -> str:
    kind = rule["type"]
    if kind in ("above", "below"):
        return "%s %s %s" % (rule["symbol"], kind, num(rule["price"]))
    if kind.startswith("premium"):
        return "%s %s %s %s premium %s %s" % (rule["symbol"], num(rule["strike"], 0), rule["kind"], rule["expiry"], kind.split("_")[1], num(rule["price"]))
    if kind == "pct":
        return "%s moves %s%% from the previous close" % (rule["symbol"], rule["pct"])
    if kind == "time":
        return "at %s IST (%s)" % (rule["at"], rule.get("label", ""))
    return "NSE opening bell"


class AlertBook:
    def __init__(self, market=None) -> None:
        self.market = market
        self.rules_path = settings.path("alerts.json")
        self.state_path = settings.path("state", "alerts.json")
        self.rules: List[dict] = (read_json(self.rules_path, {"rules": []}) or {"rules": []})["rules"]
        self.rang: Dict[str, str] = read_json(self.state_path, {}) or {}

    def save(self) -> None:
        write_json(self.rules_path, {"rules": self.rules})
        write_json(self.state_path, self.rang)

    def unique_id(self, base: str) -> str:
        taken = {r["id"] for r in self.rules}
        candidate, n = base, 1
        while candidate in taken:
            n += 1
            candidate = "%s-%d" % (base, n)
        return candidate

    def add(self, new_rules: List[dict], replace_same_id: bool = False) -> List[dict]:
        if replace_same_id:
            ids = {r["id"] for r in new_rules}
            self.rules = [r for r in self.rules if r["id"] not in ids]
        self.rules += new_rules
        self.save()
        log.info("added %d alert(s)", len(new_rules))
        return new_rules

    def level_rules(self, symbol: str, above: Optional[float], below: Optional[float], pct_move: Optional[float],
                    label: Optional[str]) -> List[dict]:
        upper = symbol.upper()
        rules = []
        if above is not None:
            rules.append({"id": self.unique_id(upper.lower() + "-above"), "type": "above", "symbol": upper, "price": above, "label": label or "above"})
        if below is not None:
            rules.append({"id": self.unique_id(upper.lower() + "-below"), "type": "below", "symbol": upper, "price": below, "label": label or "below"})
        if pct_move is not None:
            rules.append({"id": self.unique_id(upper.lower() + "-pct"), "type": "pct", "symbol": upper, "pct": pct_move, "label": label or "move"})
        if not rules:
            raise ValidationError("give --above, --below or --pct")
        return rules

    def reset(self, rule_id: str) -> None:
        self.rang.pop(rule_id, None)
        self.save()

    def clear(self) -> None:
        self.rules, self.rang = [], {}
        self.save()

    def check(self, now: dt.datetime) -> Tuple[List[str], List[str]]:
        """(messages that rang, notes about data problems)."""
        notes: List[str] = []
        quotes = self._quotes(notes)
        premiums = self._premiums(now, notes)
        messages = []
        for rule in self.rules:
            message = evaluate(rule, now, quotes, premiums, self.rang)
            if message:
                messages.append(message)
                self.rang[rule["id"]] = now.date().isoformat() if rule["type"] in DAILY_TYPES else now.isoformat(timespec="minutes")
                log.info("alert %s rang: %s", rule["id"], message)
        write_json(self.state_path, self.rang)
        return messages, notes

    def _quotes(self, notes: List[str]) -> Dict[str, dict]:
        quotes = {}
        for symbol in {r["symbol"].upper() for r in self.rules if r["type"] in ("above", "below", "pct")}:
            try:
                quotes[symbol] = self.market.quote(symbol)
            except IndianTraderError as exc:
                notes.append("%s: %s" % (symbol, exc))
        return quotes

    def _premiums(self, now: dt.datetime, notes: List[str]) -> Dict[str, float]:
        premiums: Dict[str, float] = {}
        chains: Dict[tuple, dict] = {}
        service = OptionChainService(self.market)
        for rule in self.rules:
            if not rule["type"].startswith("premium") or self.rang.get(rule["id"]):
                continue
            if rule.get("date") and rule["date"] != now.date().isoformat():
                continue
            key = (rule["symbol"], rule["expiry"])
            try:
                if key not in chains:
                    chains[key] = service.fetch(rule["symbol"], now, rule["expiry"])
                row = next((r for r in chains[key]["rows"] if abs(r["strike"] - rule["strike"]) < 1e-6), None)
                leg = row and row[rule["kind"].lower()]
                if leg:
                    premiums[rule["id"]] = premium_of(leg)
            except IndianTraderError as exc:
                notes.append("%s: %s" % (rule["id"], exc))
        return premiums
