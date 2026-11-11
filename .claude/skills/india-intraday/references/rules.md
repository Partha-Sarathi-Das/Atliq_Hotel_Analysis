# Opening-range breakout rules (pre-registered 10 Nov 2026, before any test was run)

Adapted from the opening-range breakout in the US day-trader-skill pack (scanner, entry timer,
exit planner, time machine, budget and risk managers) for NSE, IST, and Dhan intraday charges.
Long only, no leverage, no overnight positions.

## Setups

| | ORB15 | ORB60 |
|---|---|---|
| Bars | 5-minute | 60-minute |
| Opening range | 09:15–09:30 (first 3 bars) | 09:15–10:15 (first bar) |
| Trigger | first bar that **closes** above the range high, bar starting no later than 11:00 | same, bar starting no later than 12:15 |
| Entry | open of the next bar, plus slippage | same |
| Data available | last 60 sessions only | about 3 years (from Nov 2023) |

Shared rules:

- Universe: Nifty 100 or Nifty Midcap 150, point-in-time membership.
- Stop: opening-range midpoint. Skip if the stop is less than 0.4% below entry (too tight for
  costs) or at/above entry.
- Target: entry + 2R (R = entry − stop).
- Exit: stop or target, whichever the bar reaches first; if a bar touches both, assume the stop.
  A bar that opens beyond a level fills at its open. Anything still open is sold at the 15:15
  bar's open (before Dhan's auto square-off).
- Sizing: risk 1% of start-of-day equity per trade, position value capped at equity ÷ 3, whole
  shares, no margin.
- Limits: at most 3 trades and 3 open positions per day; no new entries once the day's realised
  loss reaches 3% of equity.
- Ranking when several stocks trigger on the same bar: highest traded value (price × volume)
  of the trigger bar first.
- Costs: Dhan intraday charges from `config.json` on every trade; slippage 0.05% per side on
  Nifty 100, 0.10% on Midcap 150.

## Acceptance tests

ORB60 is the main test: in-sample Nov 2023 – Jun 2025, out-of-sample Jul 2025 onward. It must
pass all of these out-of-sample, the same tests as the swing strategies:

1. At least 60 trades.
2. Profit factor at least 1.3 after costs.
3. Maximum drawdown no worse than 20%.
4. CAGR after costs at least 15% and above the matching index (Nifty 50 for Nifty 100,
   Nifty Midcap 50 for Midcap 150) over the same period.
5. Out-of-sample profit factor at least 70% of in-sample.

ORB15 has only 60 sessions, which is too short to pass on its own. It is reported as a check:
profit factor below 1.0 counts against the setup.

These are research rule sets 7 (ORB15) and 8 (ORB60) in this project. Parameters above are
fixed; a change means a new rule set and a new entry in `trading/state.json`.
