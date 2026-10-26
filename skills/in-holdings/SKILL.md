---
name: in-holdings
description: "Shareholding Tracker, the Indian version of the 13F copycat. Reads each company's quarterly shareholding pattern (SEBI LODR Reg 31 XBRL): promoters, foreign institutions, domestic institutions, mutual funds, insurance, retail and HNIs, every named holder over 1%, and what changed since the last quarter. Can also search a list of stocks for one investor or fund by name (for example LIC, a mutual fund, or a well-known individual investor). Use when the user says \"who owns this stock\", \"shareholding pattern\", \"FII holding\", \"DII holding\", \"mutual fund holding\", \"promoter holding\", \"did FIIs increase stake\", \"what does LIC own\", \"stocks held by <investor>\", \"copy this investor\", or \"superstar portfolio\"."
---
# Shareholding Tracker

The US 13F shows what a fund owns. In India the filing comes from the company side: every quarter each listed company publishes who owns it. This skill reads those filings and can also turn them round to find one investor across many stocks.

## Commands

```
python "Indian Trader Skill/it.py" holdings RELIANCE                         # categories, named holders, change vs last quarter
python "Indian Trader Skill/it.py" holdings TCS INFY HCLTECH --limit 10
python "Indian Trader Skill/it.py" holdings --find "life insurance" --list nifty50
python "Indian Trader Skill/it.py" holdings --find "kacholia" --list nifty500   # one investor across 500 stocks (slow the first time, then cached)
python "Indian Trader Skill/it.py" holdings --find "mirae" RELIANCE TCS INFY     # only these stocks
```

Saves `workspace/holdings-<SYMBOL>.json` and `workspace/holdings-find.json`. Filings are cached (they never change), so a second search is fast.

## How to read it

- **Promoter trend**: steady or rising is normal; a steady fall over several quarters, or a sudden drop, deserves a look at the insider and pledge filings (`/in-insiders`).
- **FII vs DII**: in recent years domestic funds have often bought what foreign funds sold. A rising mutual-fund share with a falling FII share is a rotation, not a verdict.
- **Named holders over 1%**: "new" means the holder crossed 1% this quarter; "gone" means they fell under 1% or sold out (the filing cannot tell which).
- Retail share rising while institutions sell is a classic late-stage pattern; say it as context, not a forecast.

## Rules for the answer

- **Say how old the data is, every time**: "holdings as of 30 Sep 2026, filed 21 Oct 2026". It is a quarter-end snapshot filed up to 21 days later.
- **Only holdings over 1% are named.** A search that finds nothing means "not over 1% in these stocks", not "does not own it".
- Changes are between two quarter ends, not trades: say "held 0.2 points more at 30 Sep than at 30 Jun", never "bought on" a day.
- Never claim copying a holder copies their results. Their cost, timing and exit are invisible.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/`.
- There is **no broker connection**. Nothing here can place a real order.
- Data is free and unofficial (NSE website APIs and archives). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice.
