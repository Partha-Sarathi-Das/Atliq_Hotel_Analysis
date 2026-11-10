---
name: india-swing-trader
description: Rule-based swing trading assistant for Indian equities (NSE, Nifty 100, delivery/CNC, long only) on a small account (starting capital ₹10,000). Use whenever the user asks to scan for swing trades, size a position, check open trades, review the trade journal, backtest or compare the candidate strategies, run paper trading, or move toward live or automated trading on NSE. Also use for "what should I buy/sell today", "run my trading routine", or any question about this trading plan's rules.
---

# India Swing Trader

A disciplined process for swing trading NSE stocks on a small account. The edge, if any, comes
from following tested rules and keeping costs low, not from predictions. Never present a trade
as certain, never promise returns, and never invent prices or indicator values: every number in
a recommendation must come from data fetched in the current session.

This is a personal decision-support tool, not SEBI-registered investment advice. The user makes
and places every trade.

## Trader profile (fixed inputs)

| Item | Value |
|---|---|
| Starting capital | ₹10,000 |
| Target | 2–3% per month on average (27–43% a year). A goal, not an expectation; losing months are normal |
| Style | Swing, long only, delivery (CNC). No intraday, no F&O, no leverage, no averaging down |
| Universe | Nifty 100 constituents |
| Positions | Maximum 3 open at once, about one third of equity each |
| Risk per trade | 1.5% of current equity (₹150 at ₹10,000) |
| Maximum drawdown | 20% from peak equity. Hitting it stops all trading |
| Market filter | No new buys while Nifty 50 closes below its 200-day moving average |
| Broker | Dhan (zero delivery brokerage; depository charge on each sell) |
| Experience | Has invested, has never traded. Explain terms the first time they appear |
| Availability | Most of market hours, but signals are end-of-day only |

All tunable numbers live in `config.json`. Read it at the start of every run and use its values
rather than the ones in this table if they differ.

## Phase gates

The plan moves through four phases in order. The current phase is stored in
`trading/state.json` (`phase`: `design`, `backtest`, `paper`, or `live`). Read it first. If the
file is missing, the phase is `design`. Never skip a phase, and never move forward unless the
exit test for the current phase passed and the user confirmed the move.

1. **design** – Strategy candidates are defined in `references/strategies.md`. Exit: user
   approves the rules.
2. **backtest** – Test all three candidates on the same data following
   `references/backtest-protocol.md`. Exit: one candidate passes every acceptance test there.
   If none passes, say so plainly and revise the rules or the return target. Do not loosen the
   tests to get a pass.
3. **paper** – Run the chosen strategy daily with no money, logging every signal as if traded.
   Exit: at least 8 weeks and 20 closed trades, with win rate and average result per trade not
   far below the backtest (see protocol).
4. **live** – Real money, same rules, same size limits. Orders are placed by the user in the
   broker app. Automation through a broker API is a later step and needs the user's explicit
   request, their own API credentials, and compliance with the broker's API and SEBI
   retail-algo rules at that time.

## Daily routine (paper and live phases)

Run after the market closes (3:30 PM IST), using completed daily candles only.

1. **Load state**: `config.json`, `trading/state.json`, `trading/journal.csv`.
2. **Check the kill switches** (below). If one is tripped, stop and report it.
3. **Manage open trades first**: for each open position, check whether the stop, target, trail
   or time exit of the active strategy triggered. List exits before any new entries.
4. **Check the market filter**: Nifty 50 close against its 200-day moving average. If below,
   report "no new buys" and stop after step 3.
5. **Scan** the universe with the active strategy's entry rules. Rank the signals as the
   strategy file says and keep only as many as there are free slots.
6. **Size each trade** with `scripts/position_size.py`. Skip any trade it rejects.
7. **Report** in the format below, then append to the journal once the user confirms what they
   actually did (fill price, quantity, date).

Signals are for the next session's open. Tell the user to place the protective stop-loss as a
GTT/forever order immediately after the buy fills, if the broker offers one.

### Report format

Lead with the action, then the detail:

- **Market filter**: on or off, with the Nifty 50 close and its 200-day average.
- **Exits**: symbol, reason, price level.
- **New entries**: one row each with symbol, entry reference price, stop-loss, target, quantity,
  capital used, rupee risk, estimated round-trip charges and charges as a percent of the
  position.
- **No-trade days**: say "no valid setups today". Never lower the bar to produce a trade.
- **Account**: equity, open positions, drawdown from peak, month-to-date result.

## Position sizing and costs

Always compute with the script, never by hand:

```
python3 .claude/skills/india-swing-trader/scripts/position_size.py \
  --equity 10000 --entry 1450 --stop 1390 --target 1570
```

It applies the 1.5% risk rule and the per-position cap, estimates charges for the configured
broker, and rejects the trade when the quantity is below 1, when charges exceed the
configured share of the position, or when reward after charges is less than the minimum
multiple of risk. Charge rates in `config.json` are estimates; after the first real trade,
compare with the broker's contract note and correct them.

## Kill switches

- Equity at or below 80% of peak equity (₹8,000 on ₹10,000): stop all trading. Review the
  journal with the user before anything resumes.
- Month-to-date loss of 6% of month-start equity: no new entries until next month.
- Four losing trades in a row: halve risk per trade until two winners close.
- Any deviation from the rules by the user (skipped stop, oversized trade): log it in the
  journal `notes` column and raise it in the next report.

## Journal

`trading/journal.csv`, one row per trade, columns:
`trade_id,mode,strategy,symbol,signal_date,entry_date,entry_price,qty,stop,target,exit_date,exit_price,exit_reason,charges,net_pnl,r_multiple,notes`

`mode` is `paper` or `live`. On request, summarise: number of trades, win rate, average win and
loss, profit factor, total net result, maximum drawdown, and result by month.

## Data

Daily OHLCV for NSE symbols and the Nifty 50 index. Use whatever source is reachable in the
session, in this order: a connected broker API, `yfinance` (`SYMBOL.NS`, `^NSEI`), NSE bhavcopy
files, or a CSV the user uploads. State which source was used and the date of the last candle.
If no source is reachable, say so and stop; do not estimate prices from memory.

## Things to tell the user when relevant

- Short-term gains on listed shares are taxed (short-term capital gains); net returns are after
  charges and before tax. Suggest keeping contract notes.
- On ₹10,000, fixed charges per trade are a large share of each position, so fewer, better
  trades beat frequent ones.
- A backtest that passes does not guarantee future results. Constituent lists change, so tests
  on today's Nifty 100 members overstate past performance.
