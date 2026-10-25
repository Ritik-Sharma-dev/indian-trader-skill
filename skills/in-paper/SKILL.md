---
name: in-paper
description: "Paper Trading Journal: real prices, no real orders (there is no broker connection yet). Opens the proposed order only if /in-risk passed it today and the user said yes to that exact order; fills options at the live ask from NSE's chain and closes at the bid; marks open trades and auto-closes them at stop, target or square-off; reports win rate, average R, gross, charges, net, drawdown and results by setup. Use when the user says \"take the trade\", \"paper trade it\", \"buy it\" (paper), \"close my trade\", \"how are my trades doing\", \"P&L\", \"journal\", \"my results\", \"win rate\"."
---
# Paper Trading Journal

## Commands

```
python "Indian Trader Skill/it.py" paper open --yes                  # only after /in-risk PASS and the user's explicit yes
python "Indian Trader Skill/it.py" paper open --yes --price 160.30   # record a fill price instead of the live ask
python "Indian Trader Skill/it.py" paper mark                        # live prices; auto-close at stop / target / square-off
python "Indian Trader Skill/it.py" paper close --id 20261022-1       # close now at the live bid (or --price)
python "Indian Trader Skill/it.py" paper status
python "Indian Trader Skill/it.py" paper report --days 30
```

## The yes

Before `paper open`, show the order in plain words (instrument, lots and quantity, limit price, stop, target, net loss at the stop, net reward, R:R, charges). Ask the user to confirm THAT order. Only a clear yes to that order counts: not "ok", "sure" or "yes to all". Then run `paper open --yes`.

## Notes

- Ledger: `workspace/paper.json`. Charges are deducted from every closed trade.
- Run 2-4 weeks of paper trades before any real money; `paper report` is the evidence.
- `mark` uses the current price only; between marks a level could have been touched and recovered. Use `/in-alerts` with `/loop 1m` to watch closely.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (`E:\Orbantis Technologies Projects\Trading`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
