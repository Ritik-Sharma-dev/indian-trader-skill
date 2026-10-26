---
name: in-news
description: "News Monitor for Indian stocks. Pulls headlines from Economic Times, Business Standard, Moneycontrol and Google News plus each company's own NSE filings (results, order wins, acquisitions, board meetings, credit ratings), tags every item (results, order-win, deal, rating, corporate-action, fund-raise, stake, management, regulatory, macro, market, concall), scores the mood, matches headlines to your tickers, shows how far each stock moved today, and never repeats an item. \"movers\" ranks today's NSE filings by how much each F&O stock moved. Use when the user says \"any news on\", \"why is X moving\", \"news on my watchlist\", \"what did the company announce\", \"NSE announcements\", \"results news\", \"order win\", \"trade the news\", \"news movers\", or after a scan."
---
# News Monitor

## Commands

```
python "Indian Trader Skill/it.py" news                                   # your tickers: last scan + plan + open paper trades + config watchlist
python "Indian Trader Skill/it.py" news --tickers RELIANCE HDFCBANK --hours 24
python "Indian Trader Skill/it.py" news --market-only --hours 12          # market feeds only
python "Indian Trader Skill/it.py" news --only-mine                       # only items naming your tickers
python "Indian Trader Skill/it.py" news --all --peek                      # include already-seen items, do not mark them
python "Indian Trader Skill/it.py" news --tickers NCC --since 2026-10-12 --until 2026-10-18 --stocks-only   # a past week
python "Indian Trader Skill/it.py" movers --hours 24                      # NSE filings x today's move, F&O stocks (add --any for all)
python "Indian Trader Skill/it.py" policy --hours 24                      # RBI, SEBI, NSE circulars, ET / BS economy: new rules and implementations
python "Indian Trader Skill/it.py" policy --only fno-rules ban-surveillance rbi-rates
python "Indian Trader Skill/it.py" global headlines --hours 18            # US / global headlines with the usual India impact per theme
```

## Trading the news (the workflow)

1. `movers` or `news` finds a stock with a fresh filing or headline AND a real move.
2. Open the link (the NSE filing PDF is the primary source) and say what it actually says. Do not trade a headline alone.
3. `/in-chart SYMBOL` to see if price confirms (above VWAP, breaking the opening range, volume).
4. Check `/in-optionchain SYMBOL` if it is an F&O stock, then `/in-entry`, `/in-plan`.
5. Results day: `/in-risk` warns when results or a board meeting are today or tomorrow (NSE event calendar). Gaps on results can jump any stop.

## Reading it

- `+` / `-` is a word-list mood score, a pointer only. Tags are keyword rules.
- "Searched as" shows the names used for each company: its NSE name, the shortest start of it no other listed company shares, and brand-like symbols, current or former (from NSE's symbol-change file: ETERNAL is also searched as Zomato). Stories about the company's own web pages, its funds, another listed code or a namesake abroad (`NCC Group PLC`) are untagged.
- `(+N similar)`: reworded copies of the same story were merged into one line.
- Every fetched item is kept in `workspace/news/archive.sqlite`; `--since` / `--until` read a past window from the archive and from a dated Google News search.
- State: `workspace/state/news.json` remembers seen items for 30 days. Times are IST.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/` (config, watchlist, entry, plan, orders, paper journal, charts, briefs).
- There is **no broker connection**. Nothing here can place a real order. The paper journal opens a trade only after `/in-risk` passes it AND the user says yes to that exact order.
- Data is free and unofficial (NSE website APIs, Yahoo Finance, RSS). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice. Most F&O traders lose money (SEBI's own studies: about 9 in 10). Say it plainly when a trade looks poor.
