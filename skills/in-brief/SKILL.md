---
name: in-brief
description: "Daily Brief for Indian markets: one page with market status, Indian indices, India VIX and sector strength, global cues, FII/DII flows and participant positioning, block deals, the Nifty and Bank Nifty option-chain view (PCR, max pain, support/resistance, priced-in move), F&O stocks with results or board meetings today or next session, the latest market headlines, and the last scan. Saved as Markdown in workspace/briefs/. Use when the user says \"morning brief\", \"pre-market report\", \"daily brief\", \"what should I know today\", \"market summary\", \"end of day report\", or at the start of a trading day."
---
# Daily Brief

## Commands

```
python "Indian Trader Skill/it.py" brief                                  # Nifty + Bank Nifty chains, 14 hours of headlines
python "Indian Trader Skill/it.py" brief --chains NIFTY BANKNIFTY FINNIFTY --hours 18 --headlines 20
```

## Using it

- Run before 09:15 for the day plan; after 15:30 for the wrap-up (participant OI posts around 19:00).
- Summarise for the user in a few lines: overnight mood, positioning, key levels, event risk (results today), then offer `/in-scanner` and `/in-news` on anything interesting.
- Every section is independent; a failing source shows a note instead of stopping the brief.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
