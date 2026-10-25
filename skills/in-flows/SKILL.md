---
name: in-flows
description: "Money Flows. FII/FPI and DII cash-market buying and selling (rupees crore) with a day-by-day history, NSE participant-wise open interest in index futures and options (are FIIs net long or short, how are clients and pros positioned), and today's bulk, block and short-selling deals. Use when the user says \"FII data\", \"DII buying\", \"what are FIIs doing\", \"FII long short ratio\", \"participant OI\", \"bulk deals\", \"block deals\", \"smart money\", \"institutional activity\"."
---
# Money Flows

## Commands

```
python "Indian Trader Skill/it.py" flows                      # all three
python "Indian Trader Skill/it.py" flows fiidii               # FII / DII cash: buy, sell, net (crore); history builds in state/flows.json
python "Indian Trader Skill/it.py" flows participants         # FII / DII / Pro / Client index futures long %, net calls, net puts
python "Indian Trader Skill/it.py" flows deals --symbols RELIANCE TCS --limit 20
```

## How to read it

- FII index futures long % under 25 = heavily short: bearish positioning, but also fuel for sharp short-covering rallies. Over 75 = heavily long.
- Participant OI is published after the close (about 19:00 IST); before that the tool uses the previous day's file and says which date.
- Bulk and block deals show who traded size; a promoter or fund buying is context, not a signal.
- Flows lag. Never time an intraday entry on flows alone.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (`E:\Orbantis Technologies Projects\Trading`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
