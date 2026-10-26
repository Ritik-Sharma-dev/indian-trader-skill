---
name: in-timemachine
description: "Time Machine. Replays the planned trade 10,000 times before risking a rupee: rebuilds the rest of the session from the underlying's own 5-minute bars over the last 60 days (time-of-day aware), prices the option at every exit with Black-Scholes so theta is included, and re-runs the same opening-range rule on every past session. Gives the odds of target first, stop first or neither by square-off, P&L per lot after charges, the path of the underlying, history, and an honest verdict. Use when the user says \"run the time machine\", \"what are the odds\", \"simulate this trade\", \"backtest this\", \"monte carlo\", \"is this a coin flip\", \"how often does this work\", or after /in-plan."
---
# Time Machine

## Commands

```
python "Indian Trader Skill/it.py" tm                         # workspace/plan.json, 10,000 replays, seed 19
python "Indian Trader Skill/it.py" tm --write                 # also save workspace/timemachine.json
python "Indian Trader Skill/it.py" tm --replays 20000 --seed 7 --until 15:00
```

## How to read it

- Target first / stop first / neither: the core odds. Compare the share of decided replays that hit the target with the break-even win rate 1/(1+R:R).
- History: the same rule on the last ~57 real sessions. If simulation and history disagree, say so.
- P&L per lot includes theta for options and round-trip charges.
- It mirrors the last 60 days. If those days trended down, long breakouts will score badly. That is information, not a bug.
- Not a forecast: results days, RBI policy, the budget, expiry days and global shocks behave differently.

Next: `/in-budget`.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
