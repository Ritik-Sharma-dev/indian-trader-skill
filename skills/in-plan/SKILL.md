---
name: in-plan
description: "Trade Planner. Sets the stop and target on the underlying BEFORE entry (opening-range middle or opposite side, ATR, percent, points or a price; target as a multiple of risk like 1.5R or 2R), then picks the instrument: the option strike (ATM/ITM/OTM) with premium entry, premium stop and premium target estimated by Black-Scholes including time decay, or futures with risk per lot and estimated margin, or intraday equity. Square-off by 15:15. Writes workspace/plan.json. Use when the user says \"plan the trade\", \"where's my stop\", \"set stop and target\", \"which strike should I buy\", \"premium stop loss\", \"risk reward\", \"what's my R\", or right after /in-entry triggers."
---
# Trade Planner

## Commands

```
python "Indian Trader Skill/it.py" plan make                                     # from entry.json: or-mid stop, 2R target, ATM option for indices
python "Indian Trader Skill/it.py" plan make --target 1.5R --strike itm1
python "Indian Trader Skill/it.py" plan make --stop or-opposite --instrument future
python "Indian Trader Skill/it.py" plan make --symbol RELIANCE --side long --entry 1205 --stop pct:0.8 --instrument equity
python "Indian Trader Skill/it.py" plan make --symbol NIFTY --side short --entry 22650 --stop points:60 --target 2R --expiry next
python "Indian Trader Skill/it.py" plan show
```

## How it works

- Levels live on the underlying. For options, the premium at the underlying stop and target is Black-Scholes at the current IV, `--hold` (30) minutes later, anchored to the live premium. It is an estimate: IV can collapse or spike.
- Refuses a stop on the wrong side, a risk under 0.05% of price, or an entry that has not triggered.
- Futures levels are on spot; tell the user to shift them by the futures premium (basis).

Next: `/in-timemachine` (odds), then `/in-budget` (size).

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
