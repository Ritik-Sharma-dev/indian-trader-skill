---
name: in-desk
description: "Trading Desk: the full agent team in one run. Stage 1 research (Indian market news, policy and filings; US / global markets, geopolitics, the economic calendar), stage 2 analysis (charts, option chains, flows, levels and scenarios), stage 3 the decision (the day plan before the open, BUY / HOLD / EXIT / WAIT / NO TRADE during the session), with the risk check and the decision journal. Use when the user says \"run the desk\", \"full analysis and decision\", \"research and tell me what to trade\", \"morning routine\", \"run all agents\", \"prepare for tomorrow\", or wants research, chart analysis and a decision together."
---
# Trading Desk

The agent team, in order: research, then analysis, then one decision.

| Stage | Agent (Claude, `.claude/agents/`) | Code agent | Job |
|---|---|---|---|
| 1 research | `india-market-news` | `india-news` | Indian headlines, RBI / SEBI / NSE policy, filings, flows, results |
| 1 research | `global-market-news` | `global-news` | US futures, Asia, Europe, crude, dollar, yields, geopolitics, calendar in IST |
| 1 research | `smart-money` | `smart-money` | FII / DII flows, FII positioning, one-sided block deals, insiders |
| 2 analysis | `market-data-analyst` | `market-analyst` | Charts (5-min, daily), option chain, flows, history: levels and scenarios |
| 2 analysis | `chart-analyst` | `chart-analyst` | NIFTY, BANKNIFTY, FINNIFTY, SENSEX on 5m / 15m / 1h / daily: alignment, divergence |
| 2 analysis | `options-strategist` | `options-strategist` | IV vs realised volatility, expected move, the best call and put to buy |
| 2 analysis | `stock-picker` | `stock-picker` | F&O long / short watchlists: relative strength, today's move, OI buildup |
| 2 analysis | `live-market-monitor` | `live-monitor` | The live 5-minute engine (used by the decision maker) |
| 3 risk | `risk-manager` | `risk-manager` | STOP / BLOCKED / CAUTION / CLEAR, loss budget, lots allowed |
| 4 decision | `trade-decision-maker` | `decision-maker` | One instruction, the risk check against your max loss, the journal |
| review | `performance-coach` | `performance-coach` | The journals reviewed: by hour, weekday, setup, confidence; mistakes, advice |

## Quick run (data only, about two minutes)

```
python "Indian Trader Skill/it.py" agent run trading-desk --print
```

Saves `workspace/research/<date>/trading-desk-data.md` and each stage's own report next to it.

## Full run (with web research)

1. In ONE message, launch the research and analysis agents in parallel with the Agent tool: `india-market-news`, `global-market-news`, `smart-money`, `market-data-analyst`, `chart-analyst`, `options-strategist` (and `stock-picker` if the user trades stocks). Ask each for its findings in at most 12 bullet points with sources and the likely effect on NIFTY.
2. When they are back, launch `risk-manager`, then `trade-decision-maker` (or run the decide command yourself): before 09:15 IST the day plan, during the session the decision now. Give the decision maker the summaries so it can say where the research agrees or disagrees with the signal. If the risk manager says STOP or BLOCKED, that is the answer for today.
3. Write `Indian Trader Skill/workspace/research/<date>/desk.md`: the decision first, then research (5 bullets), analysis (levels and scenarios), and where the agents disagree.
4. Reply with the decision and the triggers. During market hours, offer a `/loop 3m` on the decide command.

## Rules

- The decision maker's action comes from its tested rules; research and analysis set the confidence and the warnings, never the action. If the research strongly disagrees (for example a high-impact event in the next 30 minutes), say so plainly next to the action.
- Copy numbers from the tools; never invent a level, premium or time.
- Check the record now and then: `decide backtest NIFTY` (in-sample) and `decide journal` (the live, forward record).

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (`E:\Orbantis Technologies Projects\Trading`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. There is **no broker connection**: nothing here can place a real order.
- Data is free and unofficial; confirm prices in the broker app. This is analysis, not advice.
