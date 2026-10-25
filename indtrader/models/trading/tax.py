"""Indian tax arithmetic for traders: F&O and intraday income, capital-gain lots.

Not tax advice. The rules applied (Income-tax Act, as amended to Budget 2026;
rates live in ``config.json`` under ``tax`` so a new budget is a config edit):

* **F&O** is non-speculative business income, taxed at the slab rate.
  Turnover follows the ICAI Guidance Note on Tax Audit: the sum of the
  absolute profit or loss of every closed trade (premium is not added).
  Charges, STT included (s.36(1)(xv)), are business expenses.
* **Intraday equity** is speculative business income (s.43(5)).
  Speculative losses offset only speculative income.
* **Delivery equity** (listed, STT paid): held more than 12 months is
  long-term, 12.5 % on gains above Rs 1.25 lakh a year (s.112A); otherwise
  short-term at 20 % (s.111A). Shares in demat are sold first-in first-out
  (CBDT Circular 768/2003). India has no wash-sale rule.

The tool never says what anyone owes: slab rates, surcharge, cess, other
income and deductions decide that. It shows the numbers a CA asks for.
"""

import calendar
import csv
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from indtrader.core import settings
from indtrader.core.errors import ConfigError, ValidationError
from indtrader.core.formatting import num
from indtrader.core.storage import read_json, write_json

log = logging.getLogger(__name__)

def tax_settings(cfg: dict) -> dict:
    return dict(settings.DEFAULTS["tax"], **(cfg.get("tax") or {}))


def financial_year(day: dt.date) -> str:
    """1 Apr 2026 - 31 Mar 2027 -> '2026-27'."""
    start = day.year if day.month >= 4 else day.year - 1
    return "%d-%02d" % (start, (start + 1) % 100)


def fy_bounds(fy: str) -> Tuple[dt.date, dt.date]:
    try:
        start = int(fy.split("-")[0])
    except (ValueError, IndexError) as exc:
        raise ValidationError("financial year looks like 2026-27, got %r" % fy) from exc
    return dt.date(start, 4, 1), dt.date(start + 1, 3, 31)


def long_term_from(bought: dt.date, months: int = 12) -> dt.date:
    """The first day a lot counts as long-term: more than ``months`` after purchase."""
    years, month_index = divmod(bought.month - 1 + months, 12)
    year, month = bought.year + years, month_index + 1
    day = min(bought.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day) + dt.timedelta(days=1)


# --- business income: F&O and intraday ----------------------------------------------------------

@dataclass
class ClosedTrade:
    day: dt.date
    symbol: str
    segment: str            # fno / intraday
    gross: float            # profit (+) or loss (-) before charges
    charges: float


def trades_from_journal(journal: List[dict]) -> List[ClosedTrade]:
    out = []
    for trade in journal:
        if trade.get("status") != "closed":
            continue
        segment = "fno" if trade.get("type") in ("option", "future") else "intraday"
        out.append(ClosedTrade(dt.date.fromisoformat(trade["closed"][:10]), trade.get("symbol") or "-", segment,
                               float(trade.get("gross") or 0), float(trade.get("charges") or 0)))
    return out


def trades_from_csv(path: str) -> List[ClosedTrade]:
    """A broker P&L export reduced to: date (YYYY-MM-DD), symbol, segment (fno/intraday), pnl, charges."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc)) from exc
    out = []
    for number, row in enumerate(rows, 2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            segment = row["segment"].lower()
            if segment not in ("fno", "intraday"):
                raise ValueError("segment must be fno or intraday")
            out.append(ClosedTrade(dt.date.fromisoformat(row["date"]), row.get("symbol") or "-", segment,
                                   float(row["pnl"].replace(",", "")), float((row.get("charges") or "0").replace(",", ""))))
        except (KeyError, ValueError) as exc:
            raise ValidationError("%s line %d: %s (columns: date, symbol, segment, pnl, charges)" % (path, number, exc)) from exc
    return out


def business_income(trades: List[ClosedTrade], fy: str, tax: dict) -> Dict[str, dict]:
    start, end = fy_bounds(fy)
    out = {}
    for segment in ("fno", "intraday"):
        rows = [t for t in trades if t.segment == segment and start <= t.day <= end]
        gross = sum(t.gross for t in rows)
        charges = sum(t.charges for t in rows)
        turnover = sum(abs(t.gross) for t in rows)
        out[segment] = {"trades": len(rows), "turnover": round(turnover, 2), "gross": round(gross, 2), "charges": round(charges, 2),
                        "net": round(gross - charges, 2), "profitable": sum(1 for t in rows if t.gross > 0)}
    fno = out["fno"]
    fno["audit_likely"] = fno["turnover"] > tax["audit_turnover_digital"]
    fno["net_pct_of_turnover"] = round(fno["net"] / fno["turnover"] * 100, 2) if fno["turnover"] else None
    return out


# --- capital gains: delivery lots ------------------------------------------------------------------

class Portfolio:
    """Delivery holdings with tax lots (``workspace/portfolio.json``) and the realised log (``state/tax.json``).

    ``portfolio.json``: ``{"positions": {"INFY": {"lots": [{"id": "INFY-1", "date": "2025-06-02",
    "qty": 10, "cost": 15230.5}]}}}`` with ``cost`` the total paid for the lot, charges included.
    """

    def __init__(self, tax: dict) -> None:
        self.tax = tax
        self.path = settings.path("portfolio.json")
        self.state_path = settings.path("state", "tax.json")
        self.data = read_json(self.path, {"positions": {}}) or {"positions": {}}
        self.state = read_json(self.state_path, {"realised": []}) or {"realised": []}
        self._validate()

    def _validate(self) -> None:
        for symbol, position in (self.data.get("positions") or {}).items():
            for lot in position.get("lots") or []:
                missing = [k for k in ("date", "qty", "cost") if lot.get(k) in (None, "")]
                if missing:
                    raise ConfigError("portfolio.json %s lot %s is missing %s" % (symbol, lot.get("id", "?"), ", ".join(missing)))
                if float(lot["qty"]) <= 0:
                    raise ConfigError("portfolio.json %s lot %s has qty <= 0" % (symbol, lot.get("id", "?")))

    def lots(self, symbol: str) -> List[dict]:
        position = (self.data.get("positions") or {}).get(symbol.upper())
        if not position or not position.get("lots"):
            raise ValidationError("no lots for %s in %s" % (symbol.upper(), self.path))
        return sorted(position["lots"], key=lambda lot: lot["date"])          # FIFO order

    def symbols(self) -> List[str]:
        return sorted(s for s, p in (self.data.get("positions") or {}).items() if p.get("lots"))

    def lot_view(self, lot: dict, price: Optional[float], today: dt.date) -> dict:
        bought = dt.date.fromisoformat(lot["date"])
        long_from = long_term_from(bought, self.tax["long_term_months"])
        value = price * float(lot["qty"]) if price is not None else None
        return {"id": lot.get("id"), "date": lot["date"], "qty": float(lot["qty"]), "cost": float(lot["cost"]),
                "value": round(value, 2) if value is not None else None,
                "gain": round(value - float(lot["cost"]), 2) if value is not None else None,
                "term": "long" if today >= long_from else "short", "long_term_from": long_from.isoformat()}

    def sell_preview(self, symbol: str, qty: float, price: float, day: dt.date, charges: float = 0.0) -> dict:
        """What selling ``qty`` at ``price`` would realise, lot by lot, first in first out."""
        if qty <= 0 or price <= 0:
            raise ValidationError("quantity and price must be above zero")
        lots = self.lots(symbol)
        held = sum(float(lot["qty"]) for lot in lots)
        if qty > held + 1e-9:
            raise ValidationError("selling %s but only %s %s are held" % (num(qty, 0), num(held, 0), symbol.upper()))
        left, parts = qty, []
        for lot in lots:
            if left <= 1e-9:
                break
            take = min(left, float(lot["qty"]))
            share = take / float(lot["qty"])
            cost = float(lot["cost"]) * share
            proceeds = take * price - charges * (take / qty)
            view = self.lot_view(lot, price, day)
            parts.append({"lot": lot.get("id"), "date": lot["date"], "qty": take, "cost": round(cost, 2),
                          "proceeds": round(proceeds, 2), "gain": round(proceeds - cost, 2), "term": view["term"]})
            left -= take
        short = round(sum(p["gain"] for p in parts if p["term"] == "short"), 2)
        long_ = round(sum(p["gain"] for p in parts if p["term"] == "long"), 2)
        return {"symbol": symbol.upper(), "qty": qty, "price": price, "date": day.isoformat(), "fy": financial_year(day),
                "parts": parts, "short_term": short, "long_term": long_}

    def record_sale(self, preview: dict) -> None:
        """Apply a sale that has filled: shrink the lots (FIFO) and log the realised gains."""
        symbol = preview["symbol"]
        lots = self.data["positions"][symbol]["lots"]
        by_id = {lot.get("id"): lot for lot in lots}
        for part in preview["parts"]:
            lot = by_id[part["lot"]]
            remaining = float(lot["qty"]) - part["qty"]
            lot["cost"] = round(float(lot["cost"]) * remaining / float(lot["qty"]), 2) if remaining > 1e-9 else 0
            lot["qty"] = round(remaining, 6)
        self.data["positions"][symbol]["lots"] = [lot for lot in lots if float(lot["qty"]) > 1e-9]
        self.state.setdefault("realised", []).append({k: preview[k] for k in ("symbol", "qty", "price", "date", "fy", "short_term", "long_term")})
        write_json(self.path, self.data)
        write_json(self.state_path, self.state)
        log.info("recorded sale %s x%s at %s", symbol, preview["qty"], preview["price"])

    def realised(self, fy: str) -> dict:
        rows = [r for r in self.state.get("realised", []) if r.get("fy") == fy]
        return {"sales": len(rows), "short_term": round(sum(r["short_term"] for r in rows), 2),
                "long_term": round(sum(r["long_term"] for r in rows), 2)}


def capital_gains_estimate(realised: dict, tax: dict) -> dict:
    """Short-term losses offset short then long gains; long-term losses offset only long gains (s.70, s.74)."""
    short, long_ = realised["short_term"], realised["long_term"]
    if short < 0 < long_:                       # a net short-term loss is set off against long-term gains
        absorbed = min(-short, long_)
        short, long_ = short + absorbed, long_ - absorbed
    exemption_used = min(max(long_, 0.0), tax["ltcg_exemption"])
    taxable_long = max(0.0, long_ - tax["ltcg_exemption"])
    return {"net_short_term": round(short, 2), "net_long_term": round(long_, 2), "exemption_used": round(exemption_used, 2),
            "taxable_long_term": round(taxable_long, 2),
            "tax_at_listed_rates": round(max(short, 0.0) * tax["stcg_pct"] / 100 + taxable_long * tax["ltcg_pct"] / 100, 2),
            "carry_forward_loss": round(max(-short, 0.0) + max(-long_, 0.0), 2)}


def harvest(portfolio: Portfolio, prices: Dict[str, float], today: dt.date, min_loss: float = 0) -> dict:
    """Lots worth selling for tax: losses to book, and long-term gains that fit in this year's exemption."""
    fy = financial_year(today)
    used = max(0.0, portfolio.realised(fy)["long_term"])
    room = max(0.0, portfolio.tax["ltcg_exemption"] - used)
    losses, gains = [], []
    for symbol in portfolio.symbols():
        price = prices.get(symbol)
        if price is None:
            continue
        for lot in portfolio.lots(symbol):
            view = dict(portfolio.lot_view(lot, price, today), symbol=symbol, price=price)
            if view["gain"] is None:
                continue
            if view["gain"] < 0 and -view["gain"] >= abs(min_loss):
                losses.append(view)
            elif view["gain"] > 0 and view["term"] == "long":
                gains.append(view)
    losses.sort(key=lambda v: v["gain"])
    gains.sort(key=lambda v: v["gain"])
    fits, total = [], 0.0
    for view in gains:
        if total + view["gain"] <= room:
            fits.append(view)
            total += view["gain"]
    return {"fy": fy, "exemption_room": round(room, 2), "losses": losses, "exempt_gains": fits, "exempt_total": round(total, 2)}


# --- rendering ------------------------------------------------------------------------------------
