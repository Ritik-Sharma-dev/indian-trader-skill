# Indian Trader

Market data, analytics and a team of research and decision agents for intraday trading on the Indian market (NSE / BSE): NIFTY, BANKNIFTY, SENSEX, F&O stocks and their options. It runs as a command-line tool, as an MCP server for Claude, and as a set of Claude Code skills and agents.

It has no broker connection and cannot place an order. Every output is analysis for a human to act on.

- Python 3.8+, standard library only. No dependencies, no API keys.
- Data from free public sources (NSE and BSE website APIs, Yahoo Finance, news RSS), cross-checked against the exchanges' official figures.
- 225 tests that run offline on recorded snapshots of real market sessions.

New to the tool? Start with the **[Trading Guide](docs/TRADING_GUIDE.md)**: how the live chart is read, which indicators decide CALL or PUT, when to buy and when to sell, and a real trading day step by step.

## Contents

- [Trading Guide](docs/TRADING_GUIDE.md)
- [Installation](#installation)
- [Quick start](#quick-start)
- [The agents](#the-agents)
- [Commands](#commands)
- [Claude Code integration](#claude-code-integration)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [Data sources](#data-sources)
- [Testing](#testing)
- [Development](#development)
- [Disclaimer](#disclaimer)

## Installation

```bash
git clone <repository-url> "Indian Trader Skill"
cd "Indian Trader Skill"
python it.py clock
```

There is nothing to install. Optionally, `pip install -e .` adds an `indtrader` console command equivalent to `python it.py`.

The skills and agent definitions call the tool as `python "Indian Trader Skill/it.py" ...` from the folder that contains this repository, so keep the folder name when you clone it into a Claude Code project.

## Quick start

```bash
python it.py config init                 # writes workspace/config.json; set capital and loss limits
python it.py refresh                     # NSE holidays and F&O lot sizes
python it.py agent run trading-desk --print
```

The trading desk runs the whole agent team (research, analysis, risk) and ends with a decision: the day plan before the open, or the instruction for now during the session. During market hours:

```bash
python it.py decide now NIFTY            # BUY CALL / BUY PUT / HOLD / EXIT / WAIT / NO TRADE / DONE
```

Exit code 0 means there is something to do now (a BUY or an EXIT), 1 means there is not, so the command can be polled from a script.

## The agents

Each agent is a model class that collects findings. A view renders them as Markdown, saved to `workspace/research/<date>/<agent>-data.md`.

| Stage | Agent | What it produces |
|---|---|---|
| Research | `india-news` | Indian headlines, RBI / SEBI / NSE policy, company filings ranked by price move, flows, results calendar |
| Research | `global-news` | US futures, Asia, Europe, crude, dollar and yields as a mood score for the Indian open; economic calendar in IST |
| Research | `smart-money` | FII / DII cash flows, FII index-futures positioning, one-sided block and bulk deals, insider trades and pledges |
| Analysis | `market-analyst` | Option chain (PCR, max pain, OI walls), key levels and conditional scenarios for NIFTY and BANKNIFTY |
| Analysis | `chart-analyst` | NIFTY, BANKNIFTY, FINNIFTY and SENSEX on 5m / 15m / 1h / daily charts: trend per chart, alignment, divergence |
| Analysis | `options-strategist` | Implied vs realised volatility, expected move, ITM / ATM / OTM strikes scored, best call and put to buy |
| Analysis | `stock-picker` | F&O long and short watchlists from relative strength, the day's move and futures OI buildup |
| Live | `live-monitor` | The 5-minute signal engine: opening-range breaks, pullbacks, level breaks, with stops and targets |
| Risk | `risk-manager` | STOP / BLOCKED / CAUTION / CLEAR from the daily loss budget, trade limits and one-lot risk |
| Decision | `decision-maker` | One instruction, with the option, limit price, stop and target, and a confidence level |
| Review | `performance-coach` | The paper or decision journal by hour, weekday, setup and confidence; mistakes and advice |
| All | `trading-desk` | Runs the stages above in order and writes one combined report |

### How the decision is made

The decision maker takes the live engine's signals through rules measured on 58 NIFTY sessions (July to October 2026):

1. NIFTY only. BANKNIFTY lost on every split of the test.
2. Only the first signal of the day. The second signal lost 5.5R.
3. Entries until 12:00. Later entries lost.
4. Only on a day that opens at least 0.2% from the previous close. Flat opens lost.
5. One lot's risk at the premium stop, charges included, must fit `max_loss_per_trade`.
6. No new trade once the daily loss limit or trade limit is used up.

Every engine signal: 81 trades, +3.3R. Taken by the rules: 27 trades, 59% won, +11.0R. These figures are in-sample: the rules were chosen on the same sessions. `decide backtest` re-measures them, and every real-time decision is logged to `workspace/journal/decisions.json` (`decide journal`) to track them out of sample.

The research (global mood, daily trend, the open, option-chain PCR, FII positioning, news tone and timeframe alignment) sets the confidence (HIGH / MEDIUM / LOW) and never the action, because none of it could be backtested.

## Commands

`python it.py <command> -h` documents every flag. All commands accept `--json`, `--offline DIR` (read a recorded snapshot) and `--now "YYYY-MM-DD HH:MM"` (pin the IST clock).

| Area | Commands |
|---|---|
| System | `config`, `refresh`, `clock`, `agent run <name>`, `mcp` |
| Market | `pulse`, `quote`, `chart`, `chain`, `history`, `flows`, `global` |
| News | `news`, `movers`, `policy` |
| Trade chain | `scan`, `entry`, `plan`, `tm` (Time Machine), `budget`, `risk`, `paper`, `alerts` |
| Research | `insiders`, `holdings`, `screen`, `tax` |
| Reports | `brief`, `decide`, `live` |

Examples:

```bash
python it.py chain NIFTY --pick PE:atm           # option chain analytics and one strike in detail
python it.py chart NIFTY --interval 15m --html   # indicators and levels, plus an HTML chart
python it.py live replay NIFTY --date 2026-10-23 # replay a session through the live engine
python it.py decide backtest NIFTY               # the decision rules' record
python it.py holdings --find "life insurance" --list nifty50
python it.py screen --preset momentum --list nifty100
python it.py tax report                          # F&O and intraday turnover and P&L (not tax advice)
python it.py news --tickers NCC --since 2026-10-12 --until 2026-10-18   # a past week of company news and NSE filings
python it.py live backtest GROWW                 # a stock's record, before and after intraday charges
```

## Claude Code integration

**MCP server.** `python it.py mcp` serves 23 read-only tools over stdio (JSON-RPC 2.0, protocol 2025-06-18). Register it in the Claude Code project's `.mcp.json`:

```json
{
  "mcpServers": {
    "indian-trader": { "command": "python", "args": ["Indian Trader Skill/it.py", "mcp"] }
  }
}
```

**Skills.** `skills/in-*/SKILL.md` (22 skills, such as `/in-desk`, `/in-decide`, `/in-live` and `/in-optionchain`). Copy the folders into the project's `.claude/skills/`.

**Agents.** `agents/*.md` (11 Claude agent definitions). Copy them into `.claude/agents/`. Each one runs the matching code agent and adds web research or explanation on top.

## Project structure

```
it.py                    entry point: python it.py <command>
indtrader/
  core/                  infrastructure: settings, logging, errors, NSE clock, HTTP with offline replay, storage, AppContext
  models/                data and logic; never prints, never formats a report
    data/                Yahoo, NSE and BSE clients behind MarketData
    analytics/           indicators, Black-Scholes, option chains, charts, history, flows, news, insiders, shareholding
    trading/             scanner, entry timer, planner, Time Machine, sizing, charges, risk, paper journal, alerts, screener, tax
    agents/              one package per agent (see above)
  views/                 plain-text, Markdown and HTML rendering of model results
  controllers/           command handlers and the agent runner
  cli/                   argument parsing and dispatch
  mcp/                   MCP server and tool definitions
skills/                  Claude Code skills
agents/                  Claude Code agent definitions
tests/                   unittest suite and recorded market snapshots
tools/verify_data.py     cross-checks a session against NSE / BSE official data
```

The package follows model-view-controller with one-way dependencies:

```
core  <-  models  <-  views  <-  controllers  <-  cli / mcp
```

A layer imports only from the layers to its left. `tests/test_architecture.py` enforces this on every import statement, and also checks that no model calls `print`. Every command and tool receives an `AppContext` carrying the settings, the clock (real or pinned) and `MarketData` (live or replayed).

**Errors.** Expected problems raise `IndianTraderError` subclasses (`ConfigError`, `ValidationError`, `DataError`, `NetworkError`). The CLI prints the message and exits 1. Anything else is a bug: it is logged with a traceback and exits 2. In multi-source reports, each source fails on its own and leaves a note instead of stopping the run.

**Logging.** Modules log to `indtrader.*`. The CLI and MCP server write `workspace/logs/indtrader.log` (rotating). stdout carries only results, and only protocol messages in MCP mode.

## Configuration

`workspace/config.json` overrides the defaults in `indtrader/core/settings.py`. It is validated on load. The values that matter most:

| Key | Default | Meaning |
|---|---|---|
| `capital` | 100000 | Trading capital, rupees |
| `max_loss_per_trade` | 1000 | Loss at the stop, after charges. One NIFTY ATM lot usually needs Rs 1,800 or more |
| `max_daily_loss` | 3000 | Realised losses plus open risk, per day |
| `max_trades_per_day` | 3 | Paper and risk-check limit |
| `max_lots_per_trade` | 2 | Hard cap on size |
| `no_entries_before` / `no_entries_after` / `square_off_by` | 09:30 / 14:30 / 15:15 | The trading clock, IST |
| `decision` | see settings | Decision-maker rules: symbols, last entry, minimum gap, trades per day |
| `charges` | Budget 2026 rates | Brokerage, STT, exchange, SEBI, stamp duty, GST |
| `tax` | Budget 2026 rates | STCG / LTCG rates and the long-term exemption |

The `workspace/` folder holds everything the tool writes: config, journals, state, caches, logs and reports. It is not tracked by git.

## Data sources

| Data | Source |
|---|---|
| Index quotes | NSE `allIndices`, BSE `GetSensexData`; Yahoo Finance as a fallback |
| Candles, stock quotes, global markets | Yahoo Finance chart and spark endpoints |
| Option chains, expiries, lot sizes, holidays | NSE `option-chain-v3`, `option-chain-contract-info`, `fo_mktlots.csv`, `holiday-master` |
| Flows, deals, OI changes | NSE `fiidiiTradeReact`, participant OI files, `snapshot-capital-market-largedeal`, `live-analysis-oi-spurts-contracts` |
| Filings, ownership, valuation | NSE announcements, `corporate-sast-reg29`, shareholding XBRL, `GetQuoteApi`; BSE insider-trading disclosures |
| News and calendar | Indian and global RSS feeds; Google News India search by company name and date; the Forex Factory economic calendar |
| Official day, symbols | NSE `sec_bhavdata_full` (bhavcopy), `EQUITY_L.csv`, `symbolchange.csv`; BSE quote search |

These APIs are public but unofficial and can change. The data layer applies corrections found by cross-checking against the exchanges: official index quotes first, previous closes from the previous NSE session, missing daily bars rebuilt from 5-minute bars, and option IVs computed the way NSE computes them.

Corrections added after cross-checking stocks (26 Oct 2026):

- **Closing auction.** From 3 Aug 2026, stocks with F&O stop continuous trading at 15:15, an auction sets their official close by 15:35, and equity derivatives trade until 15:40 (options now expire at 15:40). Intraday bars of those stocks and of indices carry `auction: true` from 15:15; charts read indicators at the last continuous bar and report the auction close separately.
- **Option prices vs spot.** The chain checks NSE's spot against the price implied by put-call parity at the strikes nearest ATM. When they differ by more than `max_spot_parity_gap_pct` (0.5 %), as after the auction, ATM, IV and Greeks use the parity price and the view says so.
- **NSE's official day.** For a finished session, charts compare the bars with NSE's bhavcopy (`sec_bhavdata_full`) and flag a gap over 0.2 %; the official close is shown as the last price.
- **Strikes** are printed exactly (152.5, never 152).
- **Stock backtests** size each trade to `max_loss_per_trade` and subtract equity-intraday charges; index backtests are still before option decay and charges.
- **Symbols.** An unknown symbol is explained from NSE's equity list, its symbol-change file and BSE's search (`HDFC`: NSE symbols starting HDFC; `ZOMATO`: renamed ETERNAL; `AMINTAN`: listed only on BSE as `AMINTAN.BO`).
- **Company events.** A chart warns when results, a board outcome or another major filing came after its last bar. BSE insider filings include the filer's PAN, address and phone number. These fields are dropped on arrival and never cached, saved or shown.

## Testing

```bash
python -m unittest discover -s tests
```

The suite runs offline against recorded snapshots of real sessions in `tests/fixtures/` and covers:

- the maths: Black-Scholes, max pain, charges, tax set-offs
- the NSE calendar
- accuracy against official figures
- the trade chain and the live engine (incremental processing gives the same result as batch)
- every agent, the MCP protocol, and every command shown in the skills, the README and the guide
- the layer rules

To record a snapshot of a live session for replay:

```bash
INDTRADER_RECORD=snapshots/today python it.py agent run trading-desk
python it.py agent run trading-desk --offline snapshots/today --now "YYYY-MM-DD HH:MM"
```

CI runs pyflakes and the full suite on Linux and Windows with Python 3.8, 3.10 and 3.12.

## Development

- **Standard library only.** A new dependency needs a strong reason.
- **Adding a command:** model code in `models/`, a renderer in `views/`, a handler in `controllers/`, and a parser entry in `cli/parser.py`. Add an MCP tool in `mcp/tools.py` if Claude should call it.
- **Adding an agent:** a package under `models/agents/` with an `Agent` subclass whose `collect()` returns plain data and an `errors` list. Register it in `models/agents/__init__.py`, add its report to `views/reports.REPORTS`, and add its Claude definition to `agents/`. The architecture tests fail until the report exists.
- **Tests:** new data sources need a recorded fixture so the test runs offline.

## Disclaimer

This software is for analysis and education. It is not investment, trading or tax advice. SEBI's studies found that about nine in ten individual F&O traders lose money. Backtests here are in-sample and use index points before option decay and charges. Free data can be late or wrong, so confirm prices with your broker before acting. You are responsible for your own trades.

## License

MIT. See [LICENSE](LICENSE).
