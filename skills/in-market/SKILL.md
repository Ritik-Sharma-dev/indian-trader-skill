---
name: in-market
description: "Market Pulse. Shows whether NSE is open (IST clock, holidays, next open), live Indian indices (Nifty 50, Sensex, Bank Nifty, Fin Nifty, Midcap Select, Next 50, midcap and smallcap), India VIX with Nifty's typical daily move, sector strength ranking, market breadth, and global cues (US indices and futures, Nikkei, Hang Seng, Brent and WTI crude, gold, USD/INR, dollar index). Also quotes any NSE/BSE symbol. Use when the user says \"is the market open\", \"how is the market\", \"Nifty today\", \"market pulse\", \"global cues\", \"which sectors are strong\", \"India VIX\", \"quote RELIANCE\", \"price of\", or at the start of any trading session."
---
# Market Pulse

## Commands

```
python "Indian Trader Skill/it.py" clock                       # NSE open/closed, minutes to close, next open, next holidays
python "Indian Trader Skill/it.py" pulse                       # indices, VIX, sectors, breadth, global cues -> workspace/pulse.json
python "Indian Trader Skill/it.py" pulse --no-global
python "Indian Trader Skill/it.py" quote NIFTY BANKNIFTY RELIANCE TCS --write   # -> workspace/prices.json
python "Indian Trader Skill/it.py" refresh                     # refresh NSE holiday list + F&O lot sizes (run weekly)
python "Indian Trader Skill/it.py" global snapshot             # overnight: US, futures, VIX, 10Y, dollar, crude, Asia, Europe, Indian ADRs + global mood
python "Indian Trader Skill/it.py" global calendar             # this week's Fed / US data / China events in IST
```

Symbols: NSE stocks by their NSE code (RELIANCE, HDFCBANK, M&M), BSE stocks with `.BO`, indices as NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, INDIAVIX.

## How to read it

- India VIX is annualised: Nifty's typical one-day move is about VIX / 19 percent. Under 13 = calm, 13-18 normal, 18-25 elevated, over 25 fear.
- Breadth from NSE is summed over all indices (stocks repeat), so read it as a ratio, not a count.
- Previous closes are taken from the previous NSE trading day's bars (Yahoo's own field can skip holidays).
- Global cues stand in for GIFT Nifty, which has no free feed. `global snapshot` adds Indian ADRs (INFY, WIT, HDB, IBN, RDY in New York): their overnight move is an early read on those stocks.
- For a full research run with the three agents (India news, global news, market data), use `/in-research`.

Next: `/in-news` for what is moving things, `/in-flows` for FII/DII, `/in-brief` for everything in one page.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (`E:\Orbantis Technologies Projects\Trading`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
