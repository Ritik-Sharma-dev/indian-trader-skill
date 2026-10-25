---
name: in-risk
description: "Risk Manager. PASS or BLOCK for the proposed order before anything else happens: stop required and on the right side, net loss within your max per trade, today's losses plus open risk within the daily limit, trades per day, reward:risk after charges, entry window and market hours, no fresh option buying late on expiry day, no option selling or futures unless allowed, no lottery strikes (low delta), liquidity (bid-ask spread, OI), lot and capital caps, blocked tickers and duplicates; warns on high India VIX and on results or board meetings today or tomorrow. Records verdicts so the paper journal only opens an order that passed. Use when the user says \"check my trade\", \"is this safe\", \"risk check\", \"can I take this\", \"does this break my rules\", \"how much have I lost today\", and always before /in-paper."
---
# Risk Manager

## Commands

```
python "Indian Trader Skill/it.py" risk                    # checks workspace/orders.json, records verdicts in state/risk.json
python "Indian Trader Skill/it.py" risk --no-write         # check only
python "Indian Trader Skill/it.py" risk --no-events --no-vix
```

Exit code 0 = every order PASSED, 1 = something was blocked.

## Rules

Every BLOCK reason names the rule and the numbers. Report each one plainly. Do not suggest editing config limits to get a PASS; the limits exist for the bad day. Warnings (VIX, results day) are shown but do not block unless `block_on_results_day` is true.

Next on PASS: show the user the exact order and ask for an explicit yes, then `/in-paper`.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (`E:\Orbantis Technologies Projects\Trading`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
