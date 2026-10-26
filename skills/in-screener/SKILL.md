---
name: in-screener
description: "Stock Screener. Checks NSE stocks against the user's own rules or a preset (momentum, value, delivery, near-high) using NSE data (P/E, P/E vs sector, delivery %, 52-week range, volatility, market cap, margin) and daily technicals (5/20/60-day returns, RSI, distance from the 50 and 200-day averages). Explains every pass and fail with the number and the threshold and ranks what passes. Use when the user says \"screen stocks\", \"find stocks that\", \"filter Nifty 100\", \"momentum stocks\", \"undervalued vs sector\", \"high delivery stocks\", \"near 52-week high\", \"shortlist\", or \"which F&O stocks are trending\"."
---
# Stock Screener

A screen turns "strong stocks that are not overbought" into rules a computer can check, and shows its work.

## Commands

```
python "Indian Trader Skill/it.py" screen --preset momentum --list nifty100
python "Indian Trader Skill/it.py" screen --preset value --list nifty200 --top 15
python "Indian Trader Skill/it.py" screen --preset delivery --list fo
python "Indian Trader Skill/it.py" screen --preset near-high --symbols RELIANCE,TCS,INFY,HDFCBANK
python "Indian Trader Skill/it.py" screen --rules "Indian Trader Skill/skills/in-screener/rules.example.json" --list nifty50
```

Exit code 1 means nothing passed: say so and show the closest misses. Saves `workspace/shortlist.json`.

## Metrics

| metric | meaning |
| --- | --- |
| `price`, `change_pct` | NSE last price and today's change |
| `pe`, `sector_pe`, `pe_vs_sector` | NSE trailing P/E, the sector's, and the ratio (under 1 = cheaper than the sector) |
| `delivery_pct` | delivered / traded quantity today (high = real buying or selling, low = intraday churn) |
| `pct_from_high`, `pct_from_low` | distance from the 52-week high / low, % |
| `volatility`, `margin_pct` | NSE annualised volatility, applicable margin % |
| `mcap_cr`, `traded_value_cr`, `sector`, `industry`, `fo` | size, liquidity, classification, in F&O |
| `rsi`, `ret_5d`, `ret_20d`, `ret_60d` | daily RSI(14) and returns, % |
| `vs_ema50`, `vs_ema200` | % above (+) or below (-) the 50 / 200-day EMA |

## A rules file

```json
{"name": "Liquid F&O leaders",
 "rules": [{"metric": "fo", "op": "==", "value": true},
           {"metric": "traded_value_cr", "op": ">=", "value": 200},
           {"metric": "vs_ema50", "op": ">", "value": 0},
           {"metric": "sector", "op": "not in", "value": ["Financial Services"]}],
 "rank":  [{"metric": "ret_20d", "order": "desc", "weight": 2}, {"metric": "delivery_pct", "order": "desc", "weight": 1}],
 "missing": "fail"}
```

Ops: `>`, `>=`, `<`, `<=`, `==`, `!=`, `between` ([low, high]), `in`, `not in`. `"missing": "skip"` ignores a rule when a stock has no value for it (banks have no sector P/E on some days) and says so. Turn the user's words into rules and ask when a threshold is vague ("cheap" means what P/E?). Save them as `workspace/rules.json` to make them the default.

## Rules for the answer

- Report the shortlist with the numbers, the closest misses with what failed, and the time of the data.
- A screen is a filter, not a buy list. Suggest `/in-chart`, `/in-holdings` and `/in-insiders` on the top names before anything else.
- P/E is trailing (last four quarters); the delivery share is today's and changes daily.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/`.
- There is **no broker connection**. Nothing here can place a real order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice.
