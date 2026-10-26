---
name: in-optionchain
description: "Option Chain Analyst for NSE F&O (Nifty, Bank Nifty, Fin Nifty, Midcap Select, stock options). Reads NSE's live option chain and works out PCR (total, near ATM, and of today's change), max pain, call and put OI walls (resistance and support), where calls and puts were written today, ATM IV, the straddle's priced-in move to expiry, delta/gamma/theta/vega for every strike near the money (Black-Scholes), a positioning bias with reasons, and picks a strike (ATM/ITM/OTM) with its premium, spread and lot cost. Use when the user says \"option chain\", \"PCR\", \"max pain\", \"OI data\", \"support resistance from OI\", \"which strike\", \"Nifty CE PE\", \"IV\", \"Greeks\", \"theta\", \"expected move\", \"expiry\"."
---
# Option Chain Analyst

## Commands

```
python "Indian Trader Skill/it.py" chain NIFTY                          # nearest expiry
python "Indian Trader Skill/it.py" chain BANKNIFTY --expiry monthly     # near, next, monthly, or YYYY-MM-DD
python "Indian Trader Skill/it.py" chain NIFTY --pick CE:atm            # also pick a strike: CE/PE with atm, itm1, itm2, otm1, otm2 or a strike
python "Indian Trader Skill/it.py" chain RELIANCE --rows 8              # stock options (monthly)
```

Saves `workspace/optionchain-<SYMBOL>.json`.

## Facts the user should know

- Lot sizes come from NSE's file every day (NIFTY 65, BANKNIFTY 30 as of October 2026). Never quote them from memory.
- SEBI allows one weekly expiry per exchange: NIFTY weekly on NSE (Tuesday, moved earlier on holidays), SENSEX weekly on BSE. Bank Nifty, Fin Nifty, Midcap Select and stocks are monthly.
- SENSEX / BANKEX options are on BSE; NSE's chain does not cover them (use the index for analysis only).
- OI is in contracts. IV comes from NSE, or is solved from the last price when NSE shows 0.

## How to read it

- PCR over 1.2: put writers dominate (support). Under 0.8: call writers dominate (supply). Positioning, not a forecast.
- Biggest call OI above spot = resistance wall; biggest put OI below = support wall.
- Straddle price = the market's priced-in move to expiry. A plan whose target is beyond it needs a reason.
- For buying: delta 0.4-0.6 (ATM / 1 ITM), spread under 1-2%, healthy OI. Deep OTM (delta under 0.25) is blocked by `/in-risk`.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
