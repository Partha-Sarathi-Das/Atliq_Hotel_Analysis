# Backtest and paper-trading protocol

## Backtest

- Data: daily OHLCV, at least 10 years, adjusted for splits and bonuses. Nifty 50 index for the
  market filter.
- Split: in-sample up to 31 Dec 2022, out-of-sample from 1 Jan 2023. Tune only on in-sample.
- Portfolio simulation, not per-stock: ₹10,000 start, maximum 3 positions, sizing identical to
  `scripts/position_size.py` (import its functions), equity compounding.
- Costs: charges from `config.json` on every trade plus slippage per side.
- Report for each strategy, in-sample and out-of-sample separately: number of trades, win rate,
  average win and loss in R, profit factor, CAGR, maximum drawdown, worst month, percent of
  months positive, average monthly return, time in market, total charges as a share of gross
  profit. Compare against buy-and-hold Nifty 50 over the same period.
- Universe is point-in-time: a stock can only be bought while it was a Nifty 100 member
  (`references/nifty100_history.json`). Members that later merged or delisted may lack price
  data; report how many.

### Acceptance tests (all must pass, out-of-sample)

1. At least 60 trades out-of-sample (and 150 overall).
2. Profit factor at least 1.3 after costs.
3. Maximum drawdown no worse than 20%.
4. CAGR after costs at least 15%, and above Nifty 50 buy-and-hold for the period.
5. Out-of-sample profit factor at least 70% of in-sample.

Report the average monthly return against the 2–3% goal honestly. If the best passing strategy
delivers less (for example 1–1.5% a month), tell the user and let them choose: accept it, or
keep researching. Never raise risk limits to reach the goal.

## Paper trading

- Minimum 8 weeks and 20 closed trades, following the daily routine exactly.
- Fill assumption: next session's open plus slippage; stops at the stop price or the open if
  gapped.
- Pass: win rate within 10 percentage points of the backtest, average R per trade above zero,
  no kill switch tripped, and no unlogged rule deviations.

## Going live

- Same ₹10,000 limits. First month at half risk per trade (0.75%).
- After the first live trade, reconcile estimated charges with the contract note.

## Position-count comparison

Charges are roughly ₹29 per round trip on a ₹3,000 position (about 1%), mostly the fixed
depository charge on the sell. Run every candidate with `max_positions` 2 and 3 and report
both; fewer, larger positions cut the cost share but concentrate risk.
