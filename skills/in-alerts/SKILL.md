---
name: in-alerts
description: "Price Alerts for Indian markets. Turns the trade plan into five alerts at once (underlying stop and target, option premium stop and target, and a square-off reminder at 15:15), plus above/below price levels, percent moves from the previous close, any IST time, and the NSE opening bell. Each rings once. Use when the user says \"alert me when\", \"tell me if Nifty hits\", \"watch my stop\", \"remind me to square off\", \"alert on premium\", \"watch my trade\", or after /in-plan or /in-paper."
---
# Price Alerts

## Commands

```
python "Indian Trader Skill/it.py" alerts add --from-plan                 # 5 alerts from workspace/plan.json (today only)
python "Indian Trader Skill/it.py" alerts add --symbol NIFTY --below 22600
python "Indian Trader Skill/it.py" alerts add --symbol RELIANCE --pct 2
python "Indian Trader Skill/it.py" alerts add --at 15:15 --label "square off"
python "Indian Trader Skill/it.py" alerts add --opening-bell
python "Indian Trader Skill/it.py" alerts check                           # rings what hit (exit 0) or says nothing rang (exit 1)
python "Indian Trader Skill/it.py" alerts list
python "Indian Trader Skill/it.py" alerts reset nifty-stop
python "Indian Trader Skill/it.py" alerts clear
```

For continuous watching in Claude Code: `/loop 1m python "Indian Trader Skill/it.py" alerts check --quiet`, and run `paper mark` when one rings.

Quotes are free and delayed (Yahoo for prices, NSE chain for premiums): good for alerts, not for exact fills.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
