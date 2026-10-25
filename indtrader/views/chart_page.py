"""A self-contained HTML candlestick chart (inline SVG): works offline,
follows the system's light / dark theme, shows each candle on hover."""

import html
import json
from typing import List, Tuple

from indtrader.core.formatting import num
from indtrader.models.data import bars as barlib

WIDTH, HEIGHT = 1100, 560
PAD_LEFT, PAD_RIGHT, PAD_TOP = 10, 70, 20

OVERLAYS = {   # series key -> (css colour class, legend name)
    "vwap": ("c1", "VWAP"), "ema9": ("c2", "EMA 9"), "ema21": ("c3", "EMA 21"), "st": ("c4", "SuperTrend"),
    "ema20": ("c2", "EMA 20"), "ema50": ("c3", "EMA 50"), "ema200": ("c4", "EMA 200"),
}

STYLE = """
:root{--bg:#ffffff;--fg:#1d1d1f;--muted:#6e6e73;--grid:#e5e5ea;--up:#1a7f37;--dn:#cf222e;--vol:#c7c7cc;--lvl:#8250df;
--c1:#0969da;--c2:#bf8700;--c3:#8250df;--c4:#d1242f;--c5:#57606a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--grid:#21262d;--up:#3fb950;--dn:#f85149;--vol:#30363d;--lvl:#d2a8ff;
--c1:#58a6ff;--c2:#d29922;--c3:#bc8cff;--c4:#ff7b72;--c5:#8b949e}}
:root[data-theme="dark"]{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--grid:#21262d;--up:#3fb950;--dn:#f85149;--vol:#30363d;--lvl:#d2a8ff;
--c1:#58a6ff;--c2:#d29922;--c3:#bc8cff;--c4:#ff7b72;--c5:#8b949e}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;padding:16px;max-width:1140px;margin-inline:auto}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 12px}
svg{width:100%;height:auto;display:block}.grid{stroke:var(--grid);stroke-width:1}.ax{fill:var(--muted);font-size:11px}
.up{stroke:var(--up);fill:var(--up)}.dn{stroke:var(--dn);fill:var(--dn)}.vol{fill:var(--vol)}
.lvl{stroke:var(--lvl);stroke-dasharray:4 4;stroke-width:1}.lvlt{fill:var(--lvl);font-size:11px}
.ln{fill:none;stroke-width:1.6}.c5{stroke:var(--c5)}
.c1{stroke:var(--c1);color:var(--c1)}.c2{stroke:var(--c2);color:var(--c2)}.c3{stroke:var(--c3);color:var(--c3)}.c4{stroke:var(--c4);color:var(--c4)}
.hov{fill:var(--fg);opacity:.08}.lg{margin-right:14px;font-weight:600}#tip{color:var(--muted);min-height:20px;font-variant-numeric:tabular-nums}
ul{padding-left:18px}.note{color:var(--muted);font-size:12px}
"""

SCRIPT = """
const bars=__BARS__;const svg=document.querySelector('svg');const hov=document.getElementById('hover');const tip=document.getElementById('tip');
svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect();const x=(e.clientX-r.left)/r.width*1100;
const cw=(1100-80)/bars.length;const i=Math.max(0,Math.min(bars.length-1,Math.floor((x-10)/cw)));const b=bars[i];
hov.setAttribute('x',10+cw*i);hov.setAttribute('visibility','visible');
tip.textContent=b.t+'  O '+b.o.toFixed(2)+'  H '+b.h.toFixed(2)+'  L '+b.l.toFixed(2)+'  C '+b.c.toFixed(2)+(b.v?'  V '+b.v.toLocaleString('en-IN'):'');});
svg.addEventListener('mouseleave',()=>hov.setAttribute('visibility','hidden'));
"""


class ChartPage:
    """Renders a :class:`ChartAnalyzer` result as an HTML page."""

    def __init__(self, analysis: dict) -> None:
        self.analysis = analysis
        self.series = analysis["series"]
        self.bars: List[dict] = self.series["bars"]
        self.overlays = [k for k in OVERLAYS if k in self.series]
        self.price_h, self.vol_h, self.rsi_h, self.gap = int(HEIGHT * 0.62), int(HEIGHT * 0.12), int(HEIGHT * 0.16), 14
        self.candle_w = (WIDTH - PAD_LEFT - PAD_RIGHT) / max(len(self.bars), 1)
        self.levels = self._levels()
        self.low, self.high = self._price_range()

    # -- geometry -----------------------------------------------------------------------

    def _levels(self) -> List[Tuple[float, str]]:
        found = []
        levels = self.analysis.get("levels", {})
        for key, label in (("or_high", "OR high"), ("or_low", "OR low"), ("pdh", "PDH"), ("pdl", "PDL"), ("pdc", "PDC")):
            if levels.get(key):
                found.append((levels[key], label))
        if self.analysis.get("pivots"):
            found += [(self.analysis["pivots"][k], k) for k in ("R1", "S1", "TC", "BC")]
        found += [(x["level"], "%s x%d" % (x["kind"], x["touches"])) for x in levels.get("swing", [])[:4]]
        return found

    def _price_range(self) -> Tuple[float, float]:
        values = [b["h"] for b in self.bars] + [b["l"] for b in self.bars]
        for key in self.overlays:
            values += [v for v in self.series[key] if v is not None]
        low, high = min(values), max(values)
        margin = (high - low) * 0.15
        self.levels = [(v, label) for v, label in self.levels if low - margin <= v <= high + margin]
        for value, _ in self.levels:
            low, high = min(low, value), max(high, value)
        span = (high - low) or 1
        return low - span * 0.03, high + span * 0.03

    def x(self, i: int) -> float:
        return PAD_LEFT + self.candle_w * (i + 0.5)

    def y(self, value: float) -> float:
        return PAD_TOP + (self.high - value) / (self.high - self.low) * self.price_h

    # -- drawing --------------------------------------------------------------------------

    def svg(self) -> str:
        parts = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" role="img">' % (WIDTH, HEIGHT)]
        parts += self._grid() + self._level_lines() + self._candles() + self._overlay_lines()
        volume_top = PAD_TOP + self.price_h + self.gap
        parts += self._volume(volume_top) + self._rsi(volume_top + self.vol_h + self.gap) + self._time_axis()
        parts.append('<rect id="hover" class="hov" x="0" y="%d" width="%.1f" height="%d" visibility="hidden"/>'
                     % (PAD_TOP, self.candle_w, self.price_h))
        parts.append("</svg>")
        return "\n".join(parts)

    def _grid(self) -> List[str]:
        out = []
        for step in range(5):
            value = self.low + (self.high - self.low) * step / 4
            out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (PAD_LEFT, WIDTH - PAD_RIGHT, self.y(value), self.y(value)))
            out.append('<text class="ax" x="%d" y="%.1f">%s</text>' % (WIDTH - PAD_RIGHT + 6, self.y(value) + 4, num(value)))
        return out

    def _level_lines(self) -> List[str]:
        out = []
        for value, label in self.levels:
            out.append('<line class="lvl" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (PAD_LEFT, WIDTH - PAD_RIGHT, self.y(value), self.y(value)))
            out.append('<text class="lvlt" x="%d" y="%.1f">%s %s</text>' % (PAD_LEFT + 4, self.y(value) - 3, html.escape(label), num(value)))
        return out

    def _candles(self) -> List[str]:
        out = []
        for i, bar in enumerate(self.bars):
            css = "up" if bar["c"] >= bar["o"] else "dn"
            x = self.x(i)
            out.append('<line class="%s" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>' % (css, x, x, self.y(bar["h"]), self.y(bar["l"])))
            top, bottom = self.y(max(bar["o"], bar["c"])), self.y(min(bar["o"], bar["c"]))
            out.append('<rect class="%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                       % (css, x - self.candle_w * 0.35, top, max(self.candle_w * 0.7, 1), max(bottom - top, 0.8)))
        return out

    def _overlay_lines(self) -> List[str]:
        out = []
        for key in self.overlays:
            points = ["%.1f,%.1f" % (self.x(i), self.y(v)) for i, v in enumerate(self.series[key]) if v is not None]
            if len(points) > 1:
                out.append('<polyline class="ln %s" points="%s"/>' % (OVERLAYS[key][0], " ".join(points)))
        return out

    def _volume(self, top: float) -> List[str]:
        peak = max((b["v"] for b in self.bars), default=0)
        if not peak:
            return []
        out = []
        for i, bar in enumerate(self.bars):
            height = bar["v"] / peak * self.vol_h
            out.append('<rect class="vol" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                       % (self.x(i) - self.candle_w * 0.35, top + self.vol_h - height, max(self.candle_w * 0.7, 1), height))
        out.append('<text class="ax" x="%d" y="%d">volume</text>' % (WIDTH - PAD_RIGHT + 6, top + 12))
        return out

    def _rsi(self, top: float) -> List[str]:
        def ry(value: float) -> float:
            return top + (100 - value) / 100 * self.rsi_h

        out = []
        for value in (30, 50, 70):
            out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (PAD_LEFT, WIDTH - PAD_RIGHT, ry(value), ry(value)))
            out.append('<text class="ax" x="%d" y="%.1f">%d</text>' % (WIDTH - PAD_RIGHT + 6, ry(value) + 4, value))
        points = ["%.1f,%.1f" % (self.x(i), ry(v)) for i, v in enumerate(self.series["rsi"]) if v is not None]
        if len(points) > 1:
            out.append('<polyline class="ln c5" points="%s"/>' % " ".join(points))
        out.append('<text class="ax" x="%d" y="%d">RSI 14</text>' % (PAD_LEFT + 4, top + 12))
        return out

    def _time_axis(self) -> List[str]:
        intraday = barlib.interval_minutes(self.analysis["interval"]) is not None
        step = max(1, len(self.bars) // 8)
        out = []
        for i in range(0, len(self.bars), step):
            stamp = self.bars[i]["t"]
            label = stamp.strftime("%H:%M") if intraday else stamp.strftime("%d %b")
            out.append('<text class="ax" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (self.x(i), HEIGHT - 2, label))
        return out

    # -- page ------------------------------------------------------------------------------------

    def html(self) -> str:
        a = self.analysis
        title = html.escape("%s %s chart" % (a["symbol"], a["interval"]))
        legend = " ".join('<span class="lg %s">%s</span>' % OVERLAYS[k] for k in self.overlays)
        signals = "".join("<li>%s</li>" % html.escape(s) for s in a["signals"])
        candles = [{"t": b["t"].strftime("%Y-%m-%d %H:%M"), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
                   for b in self.bars]
        return "\n".join([
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            "<title>%s</title><style>%s</style></head><body>" % (title, STYLE),
            '<h1>%s</h1><p class="sub">As of %s IST &middot; trend %s &middot; %s</p>'
            % (title, html.escape(a["as_of"].replace("T", " ")), a["trend"], legend),
            '<div id="tip">Move over the chart to see each candle.</div>',
            '<div id="chart">%s</div>' % self.svg(),
            "<ul>%s</ul>" % signals,
            '<p class="note">Made by Indian Trader from free, unofficial data. It describes the chart; it does not predict it.</p>',
            "<script>%s</script></body></html>" % SCRIPT.replace("__BARS__", json.dumps(candles)),
        ]) + "\n"
