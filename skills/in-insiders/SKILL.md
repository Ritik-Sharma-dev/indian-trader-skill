---
name: in-insiders
description: "Insider Tracker, the Indian version of the Pelosi tracker. Reads SEBI insider-trading disclosures (PIT Reg 7(2), from BSE) and takeover-code filings (SAST Reg 29, from NSE): promoters, directors and KMP buying or selling in the open market, clusters of insiders on the same side, pledges created or enforced by lenders, and funds crossing 5% of a company. Alerts once per new filing. Use when the user says \"insider buying\", \"promoter buying\", \"promoter selling\", \"who is buying this stock\", \"insider trades\", \"SAST\", \"pledge\", \"promoter pledge\", \"stake increase\", \"fund bought 5%\", or wants a watch on company insiders."
---
# Insider Tracker

India's version of following the people closest to a company. Insiders must disclose trades within two trading days; this skill reads those public filings and separates the signal from the paperwork.

## Commands

```
python "Indian Trader Skill/it.py" insiders                          # last 7 days, every company: buys, sells, pledges, SAST
python "Indian Trader Skill/it.py" insiders --days 30 --min-value 2500000
python "Indian Trader Skill/it.py" insiders RELIANCE TCS --days 30   # only these stocks
python "Indian Trader Skill/it.py" insiders --new                    # only filings not shown before (for a schedule)
python "Indian Trader Skill/it.py" insiders --all --peek             # include ESOP, gifts, allotments; do not mark as seen
```

Saves `workspace/insiders.json`. Seen filings are remembered for 30 days in `workspace/state/insiders.json`.

## What matters and what does not

- **Signal: open-market buys by promoters, directors or KMP** with their own money, most of all a **cluster** (several insiders buying the same stock in the window). Report the value, average price and trade date.
- **Open-market sells by promoters** matter more than sells by designated employees (who often sell to pay tax on ESOPs).
- **Pledge created** by a promoter: risk if the price falls (margin calls). **Pledge enforced** (the exchanges call it "invocation"): a lender has taken or sold the shares, which is a red flag. **Pledge released** is neutral to good.
- **Noise (hidden unless `--all`)**: ESOP allotments, gifts, inter-se transfers between family members, off-market moves.
- **SAST**: a fund or person crossing 5%, or changing by 2% after that. A fund building a stake is context; a promoter group raising its holding through the open market is a stronger statement.

## Rules for the answer

- Say the dates every time: the trade date and the filing date. Filings arrive up to two trading days after the trade, so the price may already have moved.
- Name the person and their category exactly as filed. Never guess why they traded.
- A symbol shown as `BSE:<code>` could not be matched to an NSE symbol; say so rather than guessing the company.
- Never call an insider buy a trade signal. It is one input next to the chart, flows and news.
- The tool removes the filer's PAN, address and phone number on arrival; never ask for or repeat personal details beyond the name in the filing.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/`.
- There is **no broker connection**. Nothing here can place a real order.
- Data is free and unofficial (NSE and BSE website APIs). It can lag or fail; say so when it does and never invent numbers.
- This is analysis, not advice.
