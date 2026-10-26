---
name: in-decide
description: "Trade Decision Maker for intraday NIFTY options. Gives ONE instruction: BUY CALL or BUY PUT now (with the option, limit price, stop and target), HOLD, EXIT now, WAIT (with the exact candle triggers), NO TRADE today, or DONE. Combines the live 5-minute chart engine with the day's research (global markets, option chain PCR and OI walls, FII positioning, daily trend, the open) and rules measured on real sessions (first signal only, before 12:00, only on a gap day, NIFTY only). Before the open it gives the day plan. Use when the user asks \"what should I do now\", \"should I buy call or put\", \"when to buy\", \"when to sell\", \"entry and exit time\", \"take decision for me\", \"day plan\", \"plan for tomorrow\", or wants a decision every few minutes."
---
# Trade Decision Maker

One clear instruction for intraday NIFTY options, built from the live chart and the day's research. It decides; you confirm in your broker app and place the order yourself.

## Commands

```
python "Indian Trader Skill/it.py" decide plan NIFTY        # before 09:15: which open makes today tradeable, the lean, levels, triggers
python "Indian Trader Skill/it.py" decide now NIFTY         # during the session: the decision now (exit code 0 = act now)
python "Indian Trader Skill/it.py" decide backtest NIFTY    # the rules' record on the last ~58 sessions (in-sample)
python "Indian Trader Skill/it.py" decide journal           # the live, forward record of real decisions
python "Indian Trader Skill/it.py" decide now NIFTY --json
```

For a live session, loop it from 09:25 to 15:20 with `/loop 3m` and the instruction "run the decide now command for NIFTY and report the DECISION" (or ask the `trade-decision-maker` agent).

## The actions

| Action | What to do |
|---|---|
| `BUY PUT` / `BUY CALL` | Buy the named option now: LIMIT at about the shown premium, 1 lot. Confirm in the broker app that the candle closed beyond the level first. |
| `HOLD` | Keep the trade. The stop and target are shown; the stop moves to breakeven at +1R and trails after +1.5R. |
| `EXIT` | Sell the option now at the bid (stop, target, trend turned, or 15:15). |
| `WAIT` | No signal yet: the triggers say exactly which 5-minute close starts a trade. |
| `NO TRADE` | Stand aside today (flat open, the signal came after 12:00, or the first signal was skipped). |
| `DONE` | Today's one trade is finished, or its signal was missed. Never chase a missed signal. |

## The rules and why (NIFTY, 58 sessions, Jul-Oct 2026, index points)

- Every engine signal: 81 trades, +3.3R (close to break-even). The decision rules took 27 of them: **59% won, +11.0R**.
- **First signal only** (the second signal lost 5.5R). **Entries until 12:00** (entries after 12:00 lost 3.8R). **Only on a gap day**, at least 0.2% from the previous close (flat days lost 2.6R in what the other rules left). **NIFTY only** (BANKNIFTY lost on every split).
- The rules were chosen on the same sessions they were measured on, so the future will be worse. `decide backtest` re-measures them; if TAKEN stops beating "every signal", say so.
- Confidence (HIGH / MEDIUM / LOW) comes from global markets, the option chain, FII positioning, the trend, the open and the news tone. These were not backtested: they never change the action, only the confidence. Policy / macro headlines and high-impact events during the session appear as warnings.
- **Risk check**: a BUY becomes NO TRADE when one lot's loss at the premium stop (charges included) is over `max_loss_per_trade` in `workspace/config.json`. A NIFTY ATM option usually risks Rs 2,500-3,500 a lot with these stops, so the default Rs 1,000 blocks it: tell the user to set the limit they can afford.
- **Journal**: every real-time decision (never a replay) is logged in `workspace/journal/decisions.json`. After 20+ trades, `decide journal` shows whether the rules hold up live and whether HIGH confidence beats LOW.

## Rules for the answer

- Lead with the action and copy the numbers exactly (option, limit, stop, target). Never invent a price.
- On BUY, remind once: confirm the candle close, LIMIT order, 1 lot, square off by 15:15. Check the cost with `/in-budget` if the user trades more than 1 lot.
- On WAIT, give the triggers in plain words ("if a 5-minute candle closes below 22,699.80, buy the PUT").
- Say "decision support, not a guarantee" once per session; most F&O traders lose money.

## Ground rules (all Indian Trader skills)

- Run commands from the project folder (the one that contains `Indian Trader Skill`): `python "Indian Trader Skill/it.py" ...`. Python 3.8+, nothing to install.
- All times are IST. Output files go to `Indian Trader Skill/workspace/`.
- There is **no broker connection**. Nothing here can place a real order.
- Data is free and unofficial (NSE, BSE, Yahoo). It can lag; confirm prices in the broker app.
- This is analysis, not advice.
