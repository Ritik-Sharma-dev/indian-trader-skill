---
name: in-live
description: "Live Market Monitor. Re-checks Nifty (or Bank Nifty) every 2-5 minutes during market hours on the latest closed 5-minute candles and says exactly when to ENTER (buy CE or PE, with the ATM strike, premium, stop and target) and when to EXIT (stop, target, breakeven and trailing stop, trend reversal, 15:15 square-off). Runs as a Claude loop with the live-market-monitor agent, or as a free terminal loop with a beep. Replays and backtests the same rules on past days. Use when the user says \"monitor the market\", \"live analysis\", \"watch Nifty every 3 minutes\", \"tell me when to enter and exit\", \"live signals\", \"start the live agent\", \"stop monitoring\"."
---
# Live Market Monitor

The engine (`it.py live`) does the analysis in code, so every check is fast and consistent; Claude or the terminal just calls it on a timer.

## Start it (two ways)

**1. In Claude (with explanations):** run the loop skill:

```
/loop 3m use the live-market-monitor agent to run one live tick for NIFTY and report any ACTION
```

Each iteration the agent runs `live tick NIFTY`, reports ENTRY / EXIT actions word for word, and otherwise a 3-line status. Stop with "stop the loop".

**2. In a terminal (free, no Claude needed, beeps on every action):**

```
python "Indian Trader Skill/it.py" live run NIFTY --every 120 --until 15:20
```

Open a second VS Code terminal for it and leave it running.

## Other commands

```
python "Indian Trader Skill/it.py" live tick NIFTY          # one check now
python "Indian Trader Skill/it.py" live status NIFTY        # today's state and last events
python "Indian Trader Skill/it.py" live reset NIFTY         # forget today's state (start fresh)
python "Indian Trader Skill/it.py" live replay NIFTY --date 2026-10-22   # how the rules traded a past day
python "Indian Trader Skill/it.py" live backtest NIFTY --sessions 57     # the rules' record on the last ~57 sessions
```

Log of every tick: `Indian Trader Skill/workspace/live/<SYMBOL>-<date>.log`.

## What it does each tick

1. Processes every 5-minute candle that closed since the last tick (only closed candles: the replay test proves batch and tick-by-tick give the same trades).
2. Bias: price vs VWAP, SuperTrend, EMA 9 vs 21 (-3 to +3).
3. Entries between 09:30 and 14:30, at most `live_max_trades` (2) a day, one at a time: opening-range break, pullback rejected at VWAP / range edge, close beyond the previous day's high / low. Not more than 2.5 ATR from VWAP.
4. Stop beyond the last 3 candles (the range middle for an opening-range entry), target 2R; at +1R the stop moves to the entry, beyond +1.5R it trails 1 ATR; exits when the trend turns (close across VWAP with SuperTrend flipped) and at 15:15.
5. On an entry: the ATM option of the nearest expiry (CE for long, PE for short) with live premium, premium stop and target.

## Honest record

On 57 Nifty sessions (Jul-Oct 2026) the rules made about 0R in total (33% winners at 2R targets), before option decay and charges; Bank Nifty was negative; filtering by the daily trend made it worse. Use the monitor for timing and discipline (it says when the setup appears and when to get out), not as a profit guarantee. Re-run `live backtest` every week.

## Rules

- A signal more than one candle old is reported as "missed" and never chased.
- Before acting on an ENTRY: confirm the candle close in the broker app, size with `/in-budget`, check `/in-risk`, LIMIT order, square off by 15:15.
- Not investment advice.
