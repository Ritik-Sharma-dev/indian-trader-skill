---
name: in-budget
description: "Budget Manager. Sizes the trade in lots from your capital and your max loss per trade (loss at the stop including all charges), the per-trade capital cap, free cash after a buffer and open paper trades, and a max-lots limit; says which limit decided it; refuses when even one lot is too risky. Includes the full Indian cost model: brokerage, STT (Budget 2026 rates: options 0.15% on the sell premium, futures 0.05%), NSE exchange charges, SEBI fee, stamp duty, GST and breakeven. Writes one proposed order to workspace/orders.json (never sent anywhere). Use when the user says \"how many lots\", \"size this trade\", \"how much to buy\", \"I have 1 lakh\", \"I only want to risk 1000\", \"charges\", \"brokerage calculator\", \"STT\", \"breakeven\", or after /in-plan."
---
# Budget Manager

## Commands

```
python "Indian Trader Skill/it.py" budget size                      # size workspace/plan.json
python "Indian Trader Skill/it.py" budget size --write              # write workspace/orders.json for /in-risk
python "Indian Trader Skill/it.py" budget charges --type option --buy 160.30 --sell 190 --qty 65
python "Indian Trader Skill/it.py" budget charges --type future --buy 22700 --sell 22800 --qty 65
python "Indian Trader Skill/it.py" budget charges --type equity_intraday --buy 1200 --sell 1212 --qty 100
python "Indian Trader Skill/it.py" budget target --profit 3500              # for a profit goal: the move needed and the loss at the stop with 1, 2, 3, 5, 10, 20, 40 lots
python "Indian Trader Skill/it.py" config init                      # create workspace/config.json, then edit it
```

## Your rules (workspace/config.json)

`capital`, `cash_buffer_pct`, `max_capital_per_trade_pct`, `max_loss_per_trade`, `max_daily_loss`, `max_trades_per_day`, `max_lots_per_trade`, `min_reward_risk`, and the `charges` block (match it to your broker's contract note). Ask the user for capital and max loss before the first real sizing; never raise a limit to make a trade fit unless the user explicitly decides to.

## How to read it

- When the user names a profit goal or a number of lots, run `budget target --profit <goal>` and show the table: more lots shrink the move needed but multiply the loss at the stop. Never promise a profit.
- "NO TRADE" is the tool working: one lot risks more than the user allows. Offer a nearer stop, a cheaper strike, or skipping the trade.
- Futures margin is an estimate (`futures_margin_pct`); the broker's SPAN + exposure margin is the real number.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
