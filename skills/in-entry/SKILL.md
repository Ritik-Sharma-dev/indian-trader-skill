---
name: in-entry
description: "Entry Timer for NSE intraday. Watches Nifty, Bank Nifty or a stock bar by bar on 5-minute (or 1-minute) bars and says the moment to get in: opening-range breakout either way (long = buy CE / future, short = buy PE / sell future), a close beyond your level, or a VWAP reclaim or loss. Respects the entry window (09:30-14:30 IST by default). Says triggered with time and price, waiting and how far, or expired. Writes workspace/entry.json. Never places an order. Use when the user says \"tell me when to enter\", \"watch Nifty\", \"has it broken out\", \"ORB entry\", \"entry signal\", \"time my entry\", \"is it a buy now\"."
---
# Entry Timer

## Commands

```
python "Indian Trader Skill/it.py" entry check NIFTY                         # ORB, either side, 5-minute bars
python "Indian Trader Skill/it.py" entry check BANKNIFTY --side long --min-volume-x 1.2
python "Indian Trader Skill/it.py" entry check RELIANCE --setup level --level 1205 --side long
python "Indian Trader Skill/it.py" entry check NIFTY --setup vwap --side short
python "Indian Trader Skill/it.py" entry watch NIFTY --until 14:30           # one line per closed bar until it triggers (exit 0) or expires (1)
python "Indian Trader Skill/it.py" entry check NIFTY --now "2026-10-22 10:30"  # replay a past moment
```

`watch` wakes just after each 5-minute bar closes. For long watches in Claude Code, prefer `/loop 5m` with `entry check`.

## How to read it

- The trigger time is the bar's CLOSE (the 10:20 bar closes at 10:25) and the price is that close.
- Long: buy a call (CE) or buy the future. Short: buy a put (PE) or sell the future.
- Window: `no_entries_before` (09:30) and `no_entries_after` (14:30) in config.

Next: `/in-plan` right after a trigger.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (`E:\Orbantis Technologies Projects\Trading`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
