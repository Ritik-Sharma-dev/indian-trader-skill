#!/usr/bin/env python3
"""Cross-check Indian Trader's numbers for a session against independent sources.

Compares the tool's quotes with NSE's and BSE's official figures and with
Yahoo's 5-minute bars, recomputes PCR and max pain from the raw chain, checks
the Black-Scholes IVs against NSE's own and checks put-call parity. Writes a
Markdown report you can compare with any broker app.

Usage (from the project folder)::

    python "Indian Trader Skill/tools/verify_data.py"                       # today, live
    python "Indian Trader Skill/tools/verify_data.py" --out report.md
"""

import argparse
import math
import os
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from indtrader.core import clock, settings  # noqa: E402
from indtrader.core.context import AppContext  # noqa: E402
from indtrader.core.errors import IndianTraderError  # noqa: E402
from indtrader.models.analytics import blackscholes as bs  # noqa: E402
from indtrader.models.analytics.option_chain import OptionChainAnalyzer, OptionChainService, chain_time  # noqa: E402
from indtrader.models.data import bars as barlib  # noqa: E402

INDICES = (("NIFTY 50", "NIFTY", "NSE"), ("NIFTY BANK", "BANKNIFTY", "NSE"), ("SENSEX", "SENSEX", "BSE"), ("INDIA VIX", "INDIAVIX", "NSE"))


def _fmt(value: Optional[float]) -> str:
    return "-" if value is None else "{:,.2f}".format(value)


class DataVerifier:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.market = ctx.market
        self.lines: List[str] = []
        self.checks: List[Tuple[str, object, object, bool]] = []

    def check(self, name: str, ours, reference, tolerance: float) -> bool:
        ok = ours is not None and reference is not None and abs(ours - reference) <= tolerance
        self.checks.append((name, ours, reference, ok))
        return ok

    def row(self, *cells) -> None:
        self.lines.append("| " + " | ".join(str(c) for c in cells) + " |")

    def official(self) -> dict:
        nse = {r["index"]: r for r in self.market.nse.all_indices()["data"]}
        sensex = self.market.bse.sensex()

        def number(value):
            return float(str(value).replace(",", ""))

        out = {}
        for name, _, source in INDICES:
            if source == "BSE":
                out[name] = {"src": "BSE official", "last": number(sensex["ltp"]), "prev": number(sensex["Prev_Close"]),
                             "open": number(sensex["I_open"]), "high": number(sensex["High"]), "low": number(sensex["Low"])}
            else:
                record = nse[name]
                out[name] = {"src": "NSE allIndices", "last": record["last"], "prev": record["previousClose"],
                             "open": record["open"], "high": record["high"], "low": record["low"]}
        return out

    def indices(self) -> None:
        official = self.official()
        self.lines.append("## 1. Index levels: compare these with your broker app\n")
        self.row("Index", "Close (LTP)", "Change", "Change %", "Open", "High", "Low", "Prev close", "Official source")
        self.row(*["---"] * 9)
        for name, o in official.items():
            change = o["last"] - o["prev"]
            self.row(name, _fmt(o["last"]), "%+.2f" % change, "%+.2f%%" % (change / o["prev"] * 100), _fmt(o["open"]),
                     _fmt(o["high"]), _fmt(o["low"]), _fmt(o["prev"]), o["src"])
        self.lines.append("\n## 2. Indian Trader vs the official numbers\n")
        self.row("Index", "Field", "Official", "Indian Trader quote", "Yahoo 5-min bars", "Match")
        self.row(*["---"] * 6)
        for name, symbol, _ in INDICES:
            o = official[name]
            quote = self.market.quote(symbol)
            try:
                _, bars = self.market.candles(symbol, "5m", "1d")
            except IndianTraderError:
                bars = []                                  # the bar column shows "-"
            session = [b for b in bars if b["t"].date() == self.ctx.now.date()]
            aggregate = barlib.aggregate(session) if session else {}
            tolerance = 0.015 if name == "INDIA VIX" else 0.06
            for field, ours in (("last", quote["price"]), ("prev", quote["prev_close"]), ("high", quote["day_high"]), ("low", quote["day_low"])):
                ok = self.check("%s %s" % (name, field), ours, o[field], tolerance)
                bar_value = {"last": aggregate.get("c"), "high": aggregate.get("h"), "low": aggregate.get("l")}.get(field)
                bar_note = "" if bar_value is None else (" ok" if abs(bar_value - o[field]) <= max(tolerance, o[field] * 0.0003) else " (differs)")
                self.row(name, field, _fmt(o[field]), _fmt(ours), _fmt(bar_value) + bar_note, "yes" if ok else "**NO**")

    def options(self, symbol: str, each_side: int) -> None:
        cfg, now = self.ctx.cfg, self.ctx.now
        chain = OptionChainService(self.market).fetch(symbol, now)
        lot = self.market.lot_size(symbol)
        analysis = OptionChainAnalyzer(cfg).analyze(chain, now, lot)
        self.lines.append("### %s, expiry %s, spot %s, lot %d, NSE time %s\n" % (
            symbol, analysis["expiry"], _fmt(analysis["spot"]), lot, analysis["timestamp"]))
        self.lines.append("PCR %.2f, max pain %s, ATM %s, ATM IV %.1f%%, ATM straddle %s (priced-in move to expiry)\n" % (
            analysis["pcr"], _fmt(analysis["max_pain"]), _fmt(analysis["atm"]), analysis["atm_iv"] * 100, _fmt(analysis["straddle"])))
        self.row("Strike", "CE LTP", "CE OI", "CE IV (NSE)", "CE IV (ours)", "PE LTP", "PE OI", "PE IV (NSE)", "PE IV (ours)")
        self.row(*["---"] * 9)
        years = clock.years_to(clock.expiry_close(chain["expiry"]), chain_time(chain, now))
        rate = cfg["risk_free_rate_pct"] / 100
        atm = next(i for i, r in enumerate(chain["rows"]) if r["strike"] == analysis["atm"])
        gaps = []
        for row in chain["rows"][atm - each_side: atm + each_side + 1]:
            cells = [_fmt(row["strike"]).replace(".00", "")]
            for kind, key in (("CE", "ce"), ("PE", "pe")):
                leg = row[key]
                ours = bs.implied_vol(kind, leg["ltp"], chain["spot"], row["strike"], years, rate) if leg["ltp"] else None
                if ours and leg["iv"]:
                    gaps.append(abs(ours * 100 - leg["iv"]))
                cells += [_fmt(leg["ltp"]), "{:,}".format(leg["oi"]), "%.1f" % leg["iv"] if leg["iv"] else "-", "%.1f" % (ours * 100) if ours else "-"]
            self.row(*cells)
        median_gap = sorted(gaps)[len(gaps) // 2] if gaps else None
        self.lines.append("\nBlack-Scholes IV vs NSE's IV near the money: median gap %.2f vol points (%d options)\n" % (median_gap or 0, len(gaps)))
        self.checks.append(("%s IV model vs NSE (median gap < 0.3 pts)" % symbol, median_gap, 0.3, median_gap is not None and median_gap < 0.3))
        rows = chain["rows"]

        def payout(strike):
            return sum(max(0, strike - r["strike"]) * (r["ce"] or {}).get("oi", 0) + max(0, r["strike"] - strike) * (r["pe"] or {}).get("oi", 0)
                       for r in rows)

        self.check("%s max pain recomputed" % symbol, analysis["max_pain"], min((r["strike"] for r in rows), key=payout), 0)
        pcr = sum((r["pe"] or {}).get("oi", 0) for r in rows) / sum((r["ce"] or {}).get("oi", 0) for r in rows)
        self.check("%s PCR recomputed" % symbol, analysis["pcr"], pcr, 1e-9)
        forwards = [r["ce"]["ltp"] - r["pe"]["ltp"] + r["strike"] * math.exp(-rate * years)
                    for r in rows[atm - 3: atm + 4] if r["ce"] and r["pe"] and r["ce"]["ltp"] and r["pe"]["ltp"]]
        spread = max(forwards) - min(forwards)
        self.checks.append(("%s parity: implied forwards agree within 0.1%%" % symbol, spread, chain["spot"] * 0.001, spread < chain["spot"] * 0.001))

    def run(self) -> str:
        now = self.ctx.now
        self.lines.append("# Data check, session of %s (checked %s IST)\n" % (now.date(), now.strftime("%H:%M")))
        self.indices()
        self.lines.append("\n## 3. Nifty and Bank Nifty options (NSE)\n")
        self.options("NIFTY", 5)
        self.options("BANKNIFTY", 3)
        lots = self.market.lot_sizes()
        self.lines.append("## 4. Lot sizes (NSE fo_mktlots.csv)\n")
        self.lines.append(", ".join("%s %d" % (k, lots[k]["lot"]) for k in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50") if k in lots))
        self.lines.append("\n## 5. Automatic checks\n")
        self.row("Check", "Indian Trader", "Reference", "Result")
        self.row(*["---"] * 4)
        for name, ours, reference, ok in self.checks:
            show = lambda v: "-" if v is None else ("%.4f" % v if isinstance(v, float) else v)   # noqa: E731
            self.row(name, show(ours), show(reference), "PASS" if ok else "**FAIL**")
        self.lines.append("\n%d of %d checks passed." % (sum(1 for c in self.checks if c[3]), len(self.checks)))
        return "\n".join(self.lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-check Indian Trader against NSE / BSE official data")
    parser.add_argument("--out", help="report path (default workspace/verification-<date>.md)")
    parser.add_argument("--offline", help="a recorded snapshot folder")
    parser.add_argument("--now", help="pin the IST clock")
    args = parser.parse_args()
    try:
        ctx = AppContext.create(now=args.now, offline=args.offline)
        report = DataVerifier(ctx).run()
    except IndianTraderError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    path = args.out or settings.path("verification-%s.md" % ctx.now.date().isoformat())
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    print("Saved %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
