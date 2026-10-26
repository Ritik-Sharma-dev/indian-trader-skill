---
name: in-tax
description: "Tax Helper for Indian traders. Not tax advice. Works out F&O (non-speculative business) and intraday (speculative) turnover, gross P&L, charges and net for a financial year from the paper journal or a broker P&L CSV, flags when a tax audit is likely, tracks delivery lots first-in first-out with short or long term and the date each lot turns long-term, previews what a sale would realise, and finds lots to sell for losses or to use the yearly long-term exemption. Use when the user says \"F&O tax\", \"trading turnover\", \"tax audit\", \"how is F&O taxed\", \"STCG\", \"LTCG\", \"capital gains\", \"tax on selling\", \"tax harvesting\", \"1.25 lakh exemption\", \"carry forward loss\", or before selling a delivery holding."
---
# Tax Helper

The arithmetic a chartered accountant asks for, done on the user's own trades. **Not tax advice**: say that once, early, in every answer that uses this skill. The tool never says what anyone owes.

## Commands

```
python "Indian Trader Skill/it.py" tax report                                 # this financial year, from the paper journal
python "Indian Trader Skill/it.py" tax report --fy 2026-27 --trades pnl.csv   # a broker P&L CSV instead
python "Indian Trader Skill/it.py" tax lots                                   # delivery lots: gain, short / long term, long-term date
python "Indian Trader Skill/it.py" tax sell INFY --qty 12 --price 1450        # what a sale would realise (FIFO), preview
python "Indian Trader Skill/it.py" tax sell INFY --qty 12 --price 1450 --charges 35 --record   # after it fills
python "Indian Trader Skill/it.py" tax harvest --min-loss 2000
```

Files: `workspace/portfolio.json` holds delivery lots (shape: `portfolio.example.json` in this folder; `cost` is the total paid for the lot, charges included). `workspace/state/tax.json` logs sales recorded with `--record`. A broker CSV needs the columns `date, symbol, segment, pnl, charges` (segment `fno` or `intraday`, pnl before charges). Never invent a purchase date or cost: ask the user, or use their broker's tax P&L.

## The rules applied (rates in `config.json` under `tax`)

- **F&O**: non-speculative business income at the slab rate. **Turnover** = sum of each trade's absolute profit or loss (ICAI Guidance Note on Tax Audit; premium is not added). Charges including STT are expenses. Audit (s.44AB) above Rs 10 crore turnover when dealings are digital; with a loss or low profit an audit can still apply under s.44AD rules, so tell the user to ask a CA.
- **F&O loss**: offsets other income except salary in the same year, then carries forward 8 years against business income, only if the ITR is filed by the due date.
- **Intraday equity**: speculative business income; losses offset only speculative income, carried forward 4 years.
- **Delivery (listed, STT paid)**: held more than 12 months is long-term, 12.5% above Rs 1.25 lakh of gains a year (s.112A); otherwise short-term at 20% (s.111A). Short-term losses offset short and long gains; long-term losses offset only long-term gains; 8-year carry forward.
- **FIFO**: shares in demat are treated as sold oldest first. The broker cannot sell "specific lots".
- **No wash-sale rule** in India, but a sale must be genuine. For exemption harvesting, buy back on the next trading day: a same-day sell and buy can be treated as intraday.

## Steps

1. `tax report`: show the turnover, gross, charges and net per segment, and any audit or loss notes.
2. Before selling a delivery holding: `tax sell` with the planned quantity and price; show the short and long-term gain.
3. Year-end (Feb-March): `tax harvest`. Losses to book against gains; long-term gains that fit in the remaining exemption.
4. After a sale fills: `tax sell ... --record`.

## Never

Never file anything, never give a final tax bill or a slab-rate figure, never tell the user what they owe, never place an order. Rates change with each budget: if the user's year differs, say which rates the tool used.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- Output files go to `Indian Trader Skill/workspace/`.
- There is **no broker connection**. Nothing here can place a real order.
- This is arithmetic, not tax or financial advice. Check with a chartered accountant.
