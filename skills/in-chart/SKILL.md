---
name: in-chart
description: "Chart Analyst. Technical analysis of any NSE/BSE stock or index on 1m/5m/15m/1h/daily bars: VWAP, EMA 9/21 (intraday) or 20/50/200 (daily), SuperTrend, RSI, MACD, Bollinger, ATR, opening range, previous day high/low/close, CPR and floor pivots, swing support and resistance, a trend verdict, and an HTML candlestick chart that works offline in light and dark mode. Use when the user says \"analyze the chart\", \"chart of\", \"technical analysis\", \"support and resistance\", \"pivot levels\", \"CPR\", \"VWAP\", \"is it trending\", \"show me the chart\", \"levels for Nifty today\"."
---
# Chart Analyst

## Commands

```
python "Indian Trader Skill/it.py" chart NIFTY                         # today's 5-minute session with levels
python "Indian Trader Skill/it.py" chart BANKNIFTY --interval 15m --html
python "Indian Trader Skill/it.py" chart RELIANCE --interval 1d        # daily: EMAs, RSI, MACD, 52-week range, swing levels
python "Indian Trader Skill/it.py" chart NIFTY --range 60d --date 2026-10-21 --html   # a past session
python "Indian Trader Skill/it.py" history NIFTY BANKNIFTY                  # the last month: up/down days, ranges, gaps, day types, opening-range behaviour, when highs/lows happen
python "Indian Trader Skill/it.py" history RELIANCE HDFCBANK --sessions 44  # two months, any symbols
```

After the close, `chart` also prints "Levels for the NEXT session" (pivots and CPR from the day's official high, low and close): use those for tomorrow's plan.

`--html` writes `workspace/charts/<SYMBOL>-<interval>-<date>.html`: candles, VWAP / EMAs / SuperTrend, volume, RSI, the opening range, PDH / PDL / PDC, CPR and pivots. Give the user the full path to open it in a browser.

## How to read it

- Index candles have no volume, so VWAP is a time-weighted average (TWAP) for indices; it says so.
- CPR width under 0.25% hints at a trending day; over 0.6% at a range day.
- Trend: intraday = price vs VWAP + EMA 9/21 + SuperTrend; daily = price vs EMA 20/50/200.
- It describes the chart; it does not predict. Pair it with `/in-optionchain` for index trades.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (`E:\Orbantis Technologies Projects\Trading`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
