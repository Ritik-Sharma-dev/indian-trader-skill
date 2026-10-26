---
name: in-scanner
description: "Chart Scanner for NSE. Scans F&O stocks (about 200) or Nifty 50/100/200/500 for setups: before the open from daily closes (20-day breakout and breakdown, bull and bear flags, reclaimed or lost the 20-day average, RSI oversold/overbought, big moves), and after 09:30 IST for opening-range breakouts both ways on 5-minute bars (long = CE, short = PE). Writes workspace/watchlist.json. Use when the user says \"scan the market\", \"find setups\", \"what is breaking out\", \"opening range breakout\", \"ORB\", \"stocks breaking down\", \"bull flag\", \"oversold stocks\", \"pre-market scan\", \"build my watchlist\", \"what should I trade today\"."
---
# Chart Scanner

## Commands

```
python "Indian Trader Skill/it.py" scan universe --list fo                 # F&O stock list (from NSE lot sizes)
python "Indian Trader Skill/it.py" scan daily                              # before 09:15: daily setups across F&O stocks
python "Indian Trader Skill/it.py" scan daily --list nifty100 --top 40
python "Indian Trader Skill/it.py" scan daily --symbols RELIANCE,TCS,INFY
python "Indian Trader Skill/it.py" scan orb                                # after 09:30: opening-range breakouts so far
python "Indian Trader Skill/it.py" scan orb --at 10:15 --or-minutes 15 --min-volume-x 1.2
python "Indian Trader Skill/it.py" scan orb --date 2026-10-21 --at 11:00   # replay a past session (5-minute data reaches about 60 days)
```

## How to read it

- ORB triggers on a CLOSED 5-minute bar closing beyond the 15-minute range (09:15-09:30). A wick is not a trigger.
- "Lean" on daily hits: long = bullish setups, short = bearish, either = mixed (for example breakdown + oversold).
- Vol x = trigger bar volume vs the range bars' average. The 09:15 bar carries the opening auction, so 1.0 is already decent.
- A full F&O ORB scan makes about 200 requests (about a minute). Daily scans are fast (20 symbols per request).

Next: `/in-news` on the hits, `/in-chart` to look, `/in-entry` to time one.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
