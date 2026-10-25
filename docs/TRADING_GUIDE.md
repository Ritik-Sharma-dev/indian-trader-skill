# Trading Guide

How Indian Trader reads the market, how it decides between a CALL and a PUT, and exactly when it tells you to buy and when to sell. It is written for the trader, not the programmer. All commands run from the folder that contains `Indian Trader Skill`.

> Indian Trader never places an order. It tells you what its rules say; you confirm on your broker's chart and place the order yourself. Most F&O traders lose money. Read [Limits](#11-limits-read-this) before trading real money.

## Contents

1. [The idea in one minute](#1-the-idea-in-one-minute)
2. [How the live chart is read](#2-how-the-live-chart-is-read)
3. [The indicators and what each one says](#3-the-indicators-and-what-each-one-says)
4. [CALL or PUT: the entry signals](#4-call-or-put-the-entry-signals)
5. [When to sell: stop, target, trailing, square-off](#5-when-to-sell-stop-target-trailing-square-off)
6. [The decision rules: which signals to take](#6-the-decision-rules-which-signals-to-take)
7. [Your trading day, minute by minute](#7-your-trading-day-minute-by-minute)
8. [A real day: 23 October 2026](#8-a-real-day-23-october-2026)
9. [Options or futures, and how much to trade](#9-options-or-futures-and-how-much-to-trade)
10. [What every agent tells you](#10-what-every-agent-tells-you)
11. [Limits (read this)](#11-limits-read-this)
12. [Checklist and common mistakes](#12-checklist-and-common-mistakes)

---

## 1. The idea in one minute

- The first 15 minutes (09:15-09:30) set the **opening range**: the day's first high and low.
- When a 5-minute candle **closes** outside that range, the market has chosen a direction. Below the range means **buy a PUT**; above it means **buy a CALL**.
- The trade gets a **stop** (where the idea is wrong) and a **target** at twice the risk.
- The stop moves to your entry price once the trade is 1R in profit. After that it trails behind the price. Everything is closed by **15:15**.
- Five filters decide which signals to take: NIFTY only, the day's first signal only, before 12:00, only on a gap day, and only if one lot fits your loss limit. They were measured on 58 real sessions.

## 2. How the live chart is read

| Step | What happens |
|---|---|
| Data | NIFTY 5-minute candles from Yahoo Finance; the live price from NSE's own index feed |
| Closed candles only | A candle counts only after it closes (the 09:50 candle counts at 09:55). An unfinished candle is never used, so a signal cannot vanish when the candle finishes |
| How often | Run `decide now NIFTY` every 3 to 5 minutes. Each run processes every candle that closed since the last run |
| Memory | The engine keeps the day's state in `workspace/state/` (opening range, the trade, the stop). Restarting loses nothing |
| Between candles | The live NSE price is checked against the stop and target, so a touch is reported at once instead of at the next close |
| Late signals | A signal more than one candle old is reported as **missed** and never chased |
| Replays | `live replay NIFTY --date YYYY-MM-DD` runs any past session candle by candle with exactly the same code |

Yahoo's candles can arrive a minute or two late. Always look at the same candle on your broker's chart before you act.

## 3. The indicators and what each one says

All indicators are computed on the 5-minute candles, from the day's closed bars plus the two previous sessions.

| Indicator | Reads | Bullish | Bearish |
|---|---|---|---|
| **Opening range** (OR) | High and low of 09:15-09:30 | Close above the OR high | Close below the OR low |
| **VWAP** (time-weighted for the index) | The day's average price | Price above VWAP | Price below VWAP |
| **SuperTrend** (10, 3) | Trend direction with an ATR buffer | UP | DOWN |
| **EMA 9 vs EMA 21** | Short-term momentum | EMA 9 above EMA 21 | EMA 9 below EMA 21 |
| **Previous day high / low** (PDH / PDL) | Yesterday's extremes | Close above PDH | Close below PDL |
| **ATR (14)** | Typical candle size | Sets stop distance and filters | |
| **RSI (14)** | Shown for context | | |

**The bias.** VWAP, SuperTrend and the EMA pair each give one vote, +1 bullish or −1 bearish, so the bias runs from **−3** (all bearish) to **+3** (all bullish). Every status line shows it:

```
10:05 IST  NIFTY 22522.65  bias STRONG BEARISH (-3): below VWAP 22604.20, SuperTrend DOWN, EMA9 < EMA21
```

The bias does not create trades. It stops you trading against the chart: a CALL setup needs the bias at 0 or above, a PUT setup needs it at 0 or below. The stronger setups need more votes (see below).

## 4. CALL or PUT: the entry signals

Entries are allowed from **09:30**, after the opening range has formed, and only on a candle **close**.

| Setup | BUY CALL when | BUY PUT when |
|---|---|---|
| **ORB** (opening-range break) | The first 5-minute close **above the OR high**, bias 0 or higher | The first 5-minute close **below the OR low**, bias 0 or lower |
| **Pullback** | The range broke up, price dips back to VWAP or the OR high, and the candle **closes back above** it (green candle), bias +1 or higher | The range broke down, price bounces to VWAP or the OR low, and the candle **closes back below** it (red candle), bias −1 or lower |
| **Level** | A close **above the previous day's high**, the candle before it still below, bias +2 or higher | A close **below the previous day's low**, the candle before it still above, bias −2 or lower |

A setup is skipped when:

- price is more than 2.5 ATR from VWAP (too stretched to chase)
- the stop would be wider than 3 ATR
- a trade is already open
- two candles have not yet passed since the last exit

**In one line:** the market tells you the side (above the range: CALL; below: PUT), and the bias confirms that the chart agrees. If price closes outside the range while the bias still points the other way, the signal waits until the bias turns. On 23 October that wait lasted from 09:35 to 09:55 (see [section 8](#8-a-real-day-23-october-2026)).

## 5. When to sell: stop, target, trailing, square-off

| Exit | Rule |
|---|---|
| **Stop** (initial) | ORB: the middle of the opening range. Pullback and level: just beyond the last three candles' extreme plus 0.1 ATR. Never closer than 0.6 ATR |
| **Target** | 2 × the risk from entry (2R). Risk 50 points means target 100 points away |
| **Breakeven** | When the trade has moved 1R in your favour **since entry**, the stop moves to the entry price: from then on the trade cannot lose |
| **Trailing** | Beyond 1.5R, the stop follows 1 ATR behind each candle's close and only tightens |
| **Trend turned** | A PUT exits if a candle closes above VWAP with SuperTrend turned up (a CALL: below VWAP with SuperTrend down) |
| **Square-off** | Everything is closed by **15:15** |

The stop and target are **NIFTY index levels**. When you enter, the tool converts them into option premiums: the premium stop and premium target, re-priced with Black-Scholes at the option's live implied volatility, 30 minutes after entry so that time decay is included. Set your stop-loss order on the premium, and watch the index level.

## 6. The decision rules: which signals to take

The live engine produces every signal. The decision maker takes only those that pass these rules. The rules come from testing the engine on 58 NIFTY sessions (July to October 2026):

| Rule | Why (what the test showed) |
|---|---|
| NIFTY only | BANKNIFTY lost money on every split of the test (−9.7R) |
| The day's **first** signal only | First signals: +8.7R. Second signals: −5.5R |
| Entries **until 12:00** | Before 12:00: +7.0R. After: −3.8R |
| Only on a **gap day** (open 0.2% or more from the previous close) | Gap days: +8.4R. Flat opens: −5.1R |
| One lot's risk must fit `max_loss_per_trade` | Your own limit, checked with charges included |
| No new trade after the daily loss or trade limit | Your own limit (the kill switch) |

Result: of 81 signals (+3.3R in total), the rules took 27: 59% won, **+11.0R**, worst losing run −3R. R is the amount risked on one trade, so +11.0R means eleven times the risk.

These results are **in-sample**: the rules were chosen by looking at the same 58 days. Real results will be worse. The decision journal (`decide journal`) records every live decision so the rules can be judged on new days.

**Confidence.** The research (global mood, daily trend, the gap direction, option-chain PCR, FII positioning, news tone and the 15m / 1h / daily chart alignment) votes on each signal:

- **HIGH:** the research agrees with the trade.
- **MEDIUM:** the research is mixed.
- **LOW:** the research disagrees.

Confidence never changes the action, because none of these inputs could be backtested. A LOW-confidence BUY is still what the tested rules say; skipping it is your choice.

## 7. Your trading day, minute by minute

| Time (IST) | Do this | Command |
|---|---|---|
| **Before 09:10** | Run the whole team: news, global cues, smart money, charts, options, risk and the day plan. Note the two gap levels and the research lean | `python "Indian Trader Skill/it.py" agent run trading-desk --print` |
| **09:15** | Market opens. If NIFTY opens between the two gap levels, the plan says **no trade today**: stop here | |
| **09:15-09:30** | Do nothing. The opening range is forming | |
| **09:25 onwards** | Ask for the decision every 3-5 minutes. You will see **WAIT** with the exact triggers | `python "Indian Trader Skill/it.py" decide now NIFTY` |
| **On BUY CALL / BUY PUT** | Check the candle close on your broker's chart. Place a **LIMIT** buy order for the named option, 1 lot, at about the shown premium. Set the stop-loss order at the premium stop | |
| **In the trade** | Keep running `decide now`. **HOLD** shows profit, the current stop and the target; move your stop-loss order when it says the stop moved | |
| **On EXIT** | Sell the option at once with a LIMIT order at the bid | |
| **12:00** | No signal yet means **NO TRADE today**. Close the screen | |
| **15:15** | Anything still open is closed | |
| **Weekend** | Review the week's trades | `python "Indian Trader Skill/it.py" agent run performance-coach --print` |

In Claude Code, you can type `/in-desk` before the open and `/loop 3m` with "run the decide now command for NIFTY and report the DECISION" during the session.

**The seven answers `decide now` can give**

| Answer | Meaning | Your action |
|---|---|---|
| `WAIT` | No signal yet | Nothing. Watch the triggers it prints |
| `BUY CALL` / `BUY PUT` | The day's signal passed every rule | Confirm the candle, then buy the named option (LIMIT, 1 lot) |
| `HOLD` | You are in the trade | Keep the stop-loss order at the level it shows |
| `EXIT` | Stop, target, trend turned or 15:15 | Sell now |
| `NO TRADE` | Flat open, the signal came after 12:00, or the risk is over your limit | Stand aside today |
| `DONE` | Today's trade is finished, or its signal was missed | Stop for the day |

## 8. A real day: 23 October 2026

| Time | What the chart did | What the tool said |
|---|---|---|
| 09:15 | Opened 22,742.20, previous close 22,687.65: a **+0.24% gap** | Tradeable day (needed 0.2%) |
| 09:15-09:30 | Opening range: high **22,786.95**, low **22,699.80** | WAIT. Triggers: CALL above 22,786.95, PUT below 22,699.80 |
| 09:35-09:50 | Candles closed **below** the OR low (22,681.60, 22,687.60, 22,689.00, 22,661.70), but SuperTrend was still UP and EMA 9 above EMA 21: bias **+1** | WAIT. A PUT needs the bias at 0 or below; the chart had not turned yet |
| **09:55** | The 09:50-09:55 candle **closed at 22,638.00**, below the OR low and below VWAP (22,699.87); SuperTrend flipped DOWN: bias **−1** | **BUY PUT** (NIFTY 27 Oct 22650 PE). NIFTY stop 22,743.40 (middle of the range), target 22,427.25 (2R), risk 105.4 points |
| 10:00 | Next candle: EMA 9 crossed below EMA 21, bias **−3** (all three votes bearish) | HOLD |
| 10:10 | Trade 1R in profit | HOLD, stop moved to **22,638.00** (breakeven) |
| 10:20 | Trade beyond 1.5R, low near 22,490 | HOLD, stop trailed to **22,533.50** |
| **10:30** | Price bounced back up to 22,533.50 | **EXIT**: +104.5 NIFTY points (+0.99R) |
| After | The day's one trade is done | DONE |

One lot (65 units) of the 22650 PE would have made about Rs 3,600-3,700 after charges. This is an estimate: NSE does not publish past intraday option prices, so the premium was modelled.

A TradingView 30-minute chart of the same day matches the tool's candles. The trade sits inside the long red 09:45-10:15 candle.

## 9. Options or futures, and how much to trade

The decision maker names an **option** (the at-the-money strike of the nearest expiry). The same signal can be traded in **futures**:

| | Bullish signal | Bearish signal | One-lot risk at a typical 51-point stop | Capital needed |
|---|---|---|---|---|
| **Options** | Buy CALL (CE) | Buy PUT (PE) | About Rs 1,830 (delta about 0.5, charges included) | The premium, about Rs 8,600-9,000 a lot |
| **Futures** | Buy NIFTY future | Sell NIFTY future | About Rs 3,300 (65 × 51 points) plus charges | Margin, roughly Rs 1.7-1.8 lakh a lot |

To plan the same trade in futures: `python "Indian Trader Skill/it.py" plan make --instrument future` (see `plan -h`). Futures move point for point with the index, so both the risk and the reward are about twice an ATM option's.

**Which strike.** The options strategist scores the ITM2, ITM1, ATM and OTM1 strikes. It prefers a delta of 0.45-0.70, a tight bid-ask spread, high open interest and the smallest move needed to cover the spread and time decay. On expiry day and the day before, prefer ITM1 over ATM, because time value collapses.

**How many lots.** The risk manager decides. With the default `max_loss_per_trade` of Rs 1,000 it answers **BLOCKED**, because one NIFTY lot needs about Rs 1,830. Set the limit in `Indian Trader Skill/workspace/config.json` to an amount you can afford to lose on one trade:

```json
{ "max_loss_per_trade": 2000, "max_daily_loss": 4000 }
```

Start with **1 lot**. The rules allow one trade a day, so the daily loss limit should be at least one trade's risk.

## 10. What every agent tells you

| Agent | Ask it | It tells you |
|---|---|---|
| `india-news` | What happened in India? | Headlines, RBI / SEBI / NSE policy, filings moving stocks, results today |
| `global-news` | How will the world affect the open? | US futures, Asia, crude, dollar, yields as one mood score; events in IST |
| `smart-money` | What are big players doing? | FII / DII flows, FII long / short in index futures, big one-sided deals, insider trades |
| `market-analyst` | Where are the levels? | Option chain (PCR, max pain, OI walls), key levels, bullish / bearish / range scenarios |
| `chart-analyst` | Do the charts agree? | NIFTY, BANKNIFTY, FINNIFTY, SENSEX on 5m / 15m / 1h / daily: ALIGNED, LEANING or MIXED |
| `options-strategist` | Which strike? | Are options cheap or expensive, the expected move, the best CALL and PUT |
| `stock-picker` | Which stocks? | F&O long and short watchlists (relative strength, the day's move, OI buildup) |
| `live-monitor` | What is the chart doing now? | The bias, levels and raw signals, every candle |
| `risk-manager` | Can I trade, how big? | STOP / BLOCKED / CAUTION / CLEAR and the lots allowed |
| `decision-maker` | What do I do now? | One instruction with the option, limit price, stop and target |
| `performance-coach` | How am I doing? | Win rate by hour, weekday and setup; your mistakes; advice |
| `trading-desk` | Everything, please | All of the above in order, ending with the decision |

Run any one with `python "Indian Trader Skill/it.py" agent run <name> --print`.

**Reading the research quickly**

| Signal | Usually means |
|---|---|
| Global mood negative, crude up sharply | Weak or gap-down open; PUT setups more likely |
| PCR below 0.8 | Call writers dominate: rallies get sold |
| PCR above 1.2 | Put writers dominate: dips get bought |
| FIIs under 25% long in index futures | Heavily short: bearish, but a gap up can trigger a sharp short-covering rally |
| Timeframes ALIGNED in one direction | Breakouts that way are more trustworthy |
| Timeframes MIXED | Smaller moves; take profits sooner |
| India VIX in the top 20% of its year | Wide swings, expensive premiums, stops hit more often |

## 11. Limits (read this)

- **No guarantee.** The rules made money on 58 past sessions they were chosen from. That is the most optimistic possible test. Judge them only after 20 or more live trades in the journal.
- **Index points are not rupees.** The backtest counts NIFTY points before option decay, the spread and charges. Option results are smaller.
- **Free data.** Yahoo candles can lag; NSE pages can fail. The tool says when a source fails and never invents a number. Always confirm on your broker's chart.
- **One trade a day, by design.** Most days end with WAIT, NO TRADE or one small result. That is the strategy working, not failing.
- **Gaps and fast markets** can fill past a stop. A stop is a plan, not a promise.
- **Not advice.** This is a tool for your own decisions. SEBI's studies found that about nine in ten individual F&O traders lose money.

## 12. Checklist and common mistakes

**Before every trade**

- [ ] The tool says `BUY CALL` or `BUY PUT` (not WAIT, not LOW-confidence without thinking).
- [ ] The candle has **closed** beyond the level on your broker's chart.
- [ ] The time is before 12:00, and this is the day's first signal.
- [ ] The risk manager is not STOP or BLOCKED.
- [ ] A **LIMIT** order for 1 lot, with the stop-loss order at the premium stop.

**Common mistakes the tool is built to prevent**

| Mistake | What the tool does |
|---|---|
| Buying before the candle closes | Uses closed candles only |
| Chasing a move you missed | Reports it as missed; DONE for the day |
| Taking a second trade to win back a loss | One trade a day |
| Trading at lunch or in the afternoon | No entries after 12:00 |
| Trading a flat, directionless day | Needs a 0.2% gap |
| Moving the stop further away | Stops only tighten |
| Trading too big | The risk manager caps lots by your loss limit |
| Holding into the close | Square-off at 15:15 |
