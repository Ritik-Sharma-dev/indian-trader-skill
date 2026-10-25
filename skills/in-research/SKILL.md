---
name: in-research
description: "Market Research Team. Runs three research agents in parallel: india-market-news (Indian news, company filings and results, RBI / SEBI / NSE / government rule changes, economy), global-market-news (overnight US markets, Fed and US data, earnings, crude, dollar, yields, China, Asia, geopolitics, Indian ADRs, with the effect on India) and market-data-analyst (Nifty / Bank Nifty levels, option-chain positioning, VIX, sectors, flows, scanner, scenarios). Then merges their reports into one market outlook with an impact table by sector and stock. Use when the user says \"research the market\", \"full market analysis\", \"what will the market do today\", \"Indian and US news\", \"morning research\", \"run the agents\", \"market outlook\", or before planning the day's trades."
---
# Market Research Team

Three specialist agents work at the same time, each writes its own report, and you merge them into one outlook.

| Agent | Covers | Report |
|---|---|---|
| `india-market-news` | Indian market news, company filings and results, RBI / SEBI / NSE / government rules and new implementations, economy data, FII/DII | `research/<date>/india-news.md` |
| `global-market-news` | US close and futures, Fed, US data, US earnings, crude, dollar, yields, China / Asia / Europe, geopolitics, tariffs, Indian ADRs, and their effect on India | `research/<date>/global-news.md` |
| `market-data-analyst` | Nifty and Bank Nifty trend and levels, option chain (PCR, max pain, OI walls, IV, priced-in move), VIX, sectors, breadth, flows, scanner, scenarios | `research/<date>/market-analytics.md` |

All paths are under `Indian Trader Skill/workspace/`. `<date>` is today in IST (`python "Indian Trader Skill/it.py" clock`).

## Steps

1. Get the IST date and market state: `python "Indian Trader Skill/it.py" clock`.
2. Launch the three agents **in one message, in parallel** with the Agent tool (`subagent_type`: `india-market-news`, `global-market-news`, `market-data-analyst`). Tell each one the IST date and time, whether NSE is open, and any focus the user gave (stocks, sectors, a question). If the user asked for only one area ("just US news"), launch only that agent.
3. Wait for all three to finish. Do not predict or summarise a report before it arrives. If one fails, say so and continue with the others.
4. Read the three reports. Merge them into `Indian Trader Skill/workspace/research/<date>/outlook.md`:

```
# Market outlook, <date> <time> IST
## The day in five lines          (global mood, India-specific tone, positioning, key levels, event risk)
## Where the agents agree / disagree
## Impact by sector               (table: sector, drivers from India news + global news, direction, key NSE stocks, confidence)
## Stocks in focus                (table: symbol, why (news / filing / setup), direction, source report)
## Nifty and Bank Nifty map       (key levels and the scenarios from the analytics report)
## Event risk today               (IST times: results, data releases, Fed, RBI, expiry)
## What would change the view
## Reports                        (links to the three agent reports)
```

5. Reply to the user with a short summary (at most 15 lines): the overall tone and why, the 3 most important drivers, the sectors and stocks in focus, the key Nifty / Bank Nifty levels, and today's event risk. Give the outlook file path.
6. Offer next steps: `/in-scanner` or `/in-entry` on the stocks in focus, `/in-optionchain` for a strike, and the plan → Time Machine → budget → risk chain.

## Rules

- The agents report; they never place orders. Nothing in this pack can.
- Keep facts (with sources) separate from interpretation. When the news and the data disagree (for example bullish news but call writing and FII shorts), say so plainly.
- Times in IST. Not investment advice: about 9 in 10 individual F&O traders lose money (SEBI's studies).

## Scheduling

To have this ready every trading morning, the user can schedule it (for example 08:30 IST, Monday to Friday) with `/schedule`, or run it with `/loop` during the day. Ask before setting up a schedule.
